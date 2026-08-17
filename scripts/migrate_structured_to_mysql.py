#!/usr/bin/env python3
"""One-time, fail-closed migration from the legacy SQLite Store to MySQL."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from backend.authz import PostgreSQLPolicyRepository
from backend.authz.models import PermissionPolicy, Role, RoleAssignment
from backend.authz.sqlite_repository import SQLitePolicyRepository
from backend.platform.assets import PostgreSQLDataAssetStore
from backend.platform.audit import PostgreSQLAuditEventStore
from backend.platform.audit.store import sanitize_audit_detail
from backend.platform.automation import PostgreSQLAutomationStore
from backend.platform.database import MySQLConnectionPool, MySQLStoreConnectionPool, apply_mysql_schema
from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.lineage import PostgreSQLLineageStore
from backend.platform.knowledge import KnowledgeDocument, PostgreSQLKnowledgeStore
from backend.platform.memory import MemoryRecord, PostgreSQLMemoryStore
from backend.platform.metrics import PostgreSQLMetricDictionaryStore
from backend.platform.orchestration import AgentStep, AnalysisTask
from backend.platform.postgresql_repository import PostgreSQLAnalysisTaskRepository
from backend.platform.reports import PostgreSQLReportStore
from backend.platform.security.secrets import decrypt_secret
from backend.platform.settings import PostgreSQLSystemConfigStore


@dataclass
class DomainResult:
    domain: str
    source_count: int = 0
    migrated_count: int = 0
    id_hash: str = ""
    errors: list[dict[str, str]] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.source_count == self.migrated_count and not self.errors


class StructuredMySQLMigrator:
    def __init__(self, sqlite_path: str | Path, mysql_url: str) -> None:
        self.source_path = Path(sqlite_path).resolve()
        self.source = sqlite3.connect(f"file:{self.source_path}?mode=ro", uri=True)
        self.source.row_factory = sqlite3.Row
        self.raw_pool = MySQLConnectionPool(mysql_url, min_size=1, max_size=6)
        self.pool = MySQLStoreConnectionPool(self.raw_pool)
        self.mysql_url = mysql_url
        self.scope_map: dict[str, str] = {}
        self.source_users: set[str] = set()
        self.historical_users: set[str] = set()
        self.disabled_users: set[str] = set()
        self.results: list[DomainResult] = []

    def close(self) -> None:
        self.source.close()
        self.pool.close()

    def migrate(self) -> dict[str, Any]:
        with self.raw_pool.connection() as connection:
            apply_mysql_schema(self.mysql_url, connection=connection)
        with self.pool.connection() as connection:
            try:
                PostgreSQLIdentityResolver.ensure_tenant(connection, "__global__", "Global knowledge scope")
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        replay = self._begin_or_replay()
        if replay is not None:
            return replay
        self._migrate_identity_roots()
        self._migrate_rbac()
        self._migrate_system_config()
        self._create_historical_model_tombstones()
        self._migrate_analysis_tasks()
        self._migrate_metrics()
        self._migrate_assets()
        self._migrate_lineage()
        self._migrate_reports()
        self._migrate_knowledge()
        self._migrate_memory()
        self._migrate_audit()
        self._migrate_automation_definitions()
        self._disable_non_login_users()
        coverage = self._source_table_coverage()
        report = {
            "source": str(self.source_path),
            "source_sha256": _file_hash(self.source_path),
            "target_adapter": "mysql_primary",
            "scope_map": dict(sorted(self.scope_map.items())),
            "historical_users_disabled": sorted(self.historical_users),
            "source_users_preserved_disabled": sorted(self.disabled_users),
            "domains": [asdict(item) | {"complete": item.complete} for item in self.results],
            "source_table_coverage": coverage,
        }
        report["ready_for_cutover"] = all(item.complete for item in self.results) and not coverage["uncovered_nonempty_tables"]
        self._complete_migration(report)
        return report

    def _begin_or_replay(self) -> dict[str, Any] | None:
        source_hash = _file_hash(self.source_path)
        key = f"sqlite-to-mysql:{source_hash}"
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, "__global__")
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT state,response_body FROM platform_idempotency_keys WHERE tenant_id=%s AND request_scope='structured_migration' AND idempotency_key=%s",
                    (tenant_key, key),
                )
                row = cursor.fetchone()
                if row and str(_row_value(row, "state", 0)) == "completed":
                    body = _row_value(row, "response_body", 1)
                    return json.loads(body) if isinstance(body, str) else dict(body)
                cursor.execute(
                    """
                    INSERT INTO platform_idempotency_keys(
                        tenant_id,idempotency_key,request_scope,request_hash,state,expires_at
                    ) VALUES(%s,%s,'structured_migration',%s,'processing',DATE_ADD(UTC_TIMESTAMP(6),INTERVAL 100 YEAR))
                    ON CONFLICT (tenant_id,request_scope,idempotency_key) DO UPDATE SET
                        request_hash=EXCLUDED.request_hash,state='processing',response_body=NULL,updated_at=now()
                    """,
                    (tenant_key, key, source_hash),
                )
            connection.commit()
        return None

    def _complete_migration(self, report: dict[str, Any]) -> None:
        source_hash = _file_hash(self.source_path)
        key = f"sqlite-to-mysql:{source_hash}"
        with self.pool.connection() as connection, connection.cursor() as cursor:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, "__global__")
            cursor.execute(
                "UPDATE platform_idempotency_keys SET state=%s,response_status=%s,response_body=%s,updated_at=now() "
                "WHERE tenant_id=%s AND request_scope='structured_migration' AND idempotency_key=%s",
                ("completed" if report["ready_for_cutover"] else "failed", 200 if report["ready_for_cutover"] else 409, json.dumps(report, ensure_ascii=False, sort_keys=True), tenant_key, key),
            )
            connection.commit()

    def _migrate_identity_roots(self) -> None:
        result = DomainResult("identity_roots")
        scopes = self._source_scopes()
        profiles = list(self.source.execute(
            "SELECT user_id,name,department,email,status,last_login FROM platform_user_profiles ORDER BY user_id"
        ))
        self.source_users = {str(row["user_id"]) for row in profiles}
        referenced = self._referenced_users()
        historical = sorted(
            subject for subject in referenced - self.source_users
            if not subject.startswith("role:") and subject != "development_seed"
        )
        result.source_count = len(scopes) + len(profiles) + len(historical)
        with self.pool.connection() as connection:
            try:
                for raw_scope in scopes:
                    scope = _normalize_scope(raw_scope)
                    self.scope_map[raw_scope] = scope
                    PostgreSQLIdentityResolver.ensure_tenant(connection, scope, _scope_name(scope))
                    result.migrated_count += 1
                PostgreSQLIdentityResolver.ensure_tenant(connection, "__global__", "Global knowledge scope")
                for row in profiles:
                    status = str(row["status"] or "active")
                    if status != "active":
                        self.disabled_users.add(str(row["user_id"]))
                    PostgreSQLIdentityResolver.ensure_user(
                        connection,
                        str(row["user_id"]),
                        email=str(row["email"] or f"{row['user_id']}@invalid.local"),
                        display_name=str(row["name"] or row["user_id"]),
                        status="active",
                    )
                    result.migrated_count += 1
                for subject in historical:
                    PostgreSQLIdentityResolver.ensure_user(
                        connection,
                        subject,
                        email=f"history-{hashlib.sha256(subject.encode()).hexdigest()[:12]}@invalid.local",
                        display_name=f"Historical identity ({subject})",
                        status="active",
                    )
                    self.historical_users.add(subject)
                    result.migrated_count += 1
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        result.id_hash = _id_hash([*scopes, *self.source_users, *historical])
        self.results.append(result)

    def _create_historical_model_tombstones(self) -> None:
        references: set[tuple[str, str]] = set()
        for row in self.source.execute("SELECT tenant_id,skill_results FROM platform_analysis_tasks"):
            tenant = self._scope(str(row["tenant_id"])) or str(row["tenant_id"])
            for result in _json(row["skill_results"], []):
                intelligent = result.get("intelligent_analysis", {}) if isinstance(result, dict) else {}
                for key in ("planning_invocation", "model_invocation"):
                    invocation = intelligent.get(key, {}) if isinstance(intelligent, dict) else {}
                    raw_model_id = str(invocation.get("model_id") or "").strip()
                    model_id = raw_model_id.partition("::")[0]
                    if model_id:
                        references.add((tenant, model_id))
        if not references:
            return
        with self.pool.connection() as connection:
            try:
                with connection.cursor() as cursor:
                    for tenant, model_id in sorted(references):
                        tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant)
                        cursor.execute(
                            "SELECT 1 FROM platform_model_integrations WHERE tenant_id=%s AND integration_code=%s",
                            (tenant_key, model_id),
                        )
                        if cursor.fetchone():
                            continue
                        cursor.execute(
                            """
                            INSERT INTO platform_model_integrations(
                                tenant_id,integration_code,display_name,provider,model_name,
                                base_url,capabilities,test_result,status
                            ) VALUES (%s,%s,%s,'historical','historical','',%s,%s,'disabled')
                            """,
                            (
                                tenant_key,
                                model_id,
                                f"Historical model ({model_id})"[:200],
                                json.dumps({"historicalOnly": True}, sort_keys=True),
                                json.dumps({"migrationReason": "referenced_by_legacy_analysis"}, sort_keys=True),
                            ),
                        )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def _migrate_system_config(self) -> None:
        groups = (
            ("model", "platform_model_integrations", "model_id", "payload"),
            ("speech", "platform_speech_integrations", "integration_id", "payload"),
            ("connection", "platform_data_connections", "connection_id", "payload"),
            ("parameter", "platform_system_data_params", "param_id", "payload"),
        )
        rows: list[tuple[str, sqlite3.Row, str, str]] = []
        for kind, table, key_column, payload_column in groups:
            if table not in _table_names(self.source):
                continue
            rows.extend(
                (kind, row, key_column, payload_column)
                for row in self.source.execute(f"SELECT * FROM {table} ORDER BY tenant_id,{key_column}")
            )
        store = PostgreSQLSystemConfigStore(self.pool)
        result = DomainResult("system_config", source_count=len(rows))
        migrated_ids: list[str] = []
        for kind, row, key_column, payload_column in rows:
            key = f"{kind}:{row['tenant_id']}:{row[key_column]}"
            try:
                tenant = self._scope(str(row["tenant_id"])) or str(row["tenant_id"])
                payload = _json(row[payload_column], {})
                actor = self._actor(row["updated_by"] if "updated_by" in row.keys() else row["created_by"])
                if kind == "model":
                    payload["value"] = decrypt_secret(str(payload.get("value") or ""))
                    store.upsert_model(tenant, payload, updated_by=actor)
                elif kind == "speech":
                    payload["apiKey"] = decrypt_secret(str(payload.get("apiKey") or ""))
                    store.upsert_speech_integration(tenant, payload, updated_by=actor)
                elif kind == "connection":
                    secret = decrypt_secret(str(row["secret_value"] or ""))
                    if str(payload.get("token") or ""):
                        payload["token"] = decrypt_secret(str(payload["token"]))
                    elif secret:
                        payload["password"] = secret
                    store.upsert_data_connection(tenant, payload, updated_by=actor)
                else:
                    store.upsert_system_param(tenant, payload, updated_by=actor)
                result.migrated_count += 1
                migrated_ids.append(key)
            except Exception as exc:
                result.errors.append({"id": key, "error": f"{type(exc).__name__}:{exc}"})
        result.id_hash = _id_hash(migrated_ids)
        self.results.append(result)

    def _migrate_rbac(self) -> None:
        result = DomainResult("rbac")
        source = SQLitePolicyRepository(self.source_path, initialize=False)
        try:
            roles = [replace(role, tenant_id=self._scope(role.tenant_id)) for role in source.list_roles()]
            assignments = [
                replace(item, tenant_id=self._scope(item.tenant_id) or "*")
                for item in source.list_user_assignments()
                if item.user_id in self.source_users
            ]
            policies: list[PermissionPolicy] = []
            manageable: dict[str, set[str]] = {}
            for role in roles:
                policies.extend(
                    replace(policy, tenant_id=self._scope(policy.tenant_id))
                    for policy in source.get_role_policies(role.role_id)
                )
                manageable[role.role_id] = source.get_manageable_role_ids(role.role_id)
            result.source_count = len(roles) + len(assignments) + len(policies) + sum(map(len, manageable.values()))
            PostgreSQLPolicyRepository(self.pool).seed(roles, assignments, policies, manageable)
            result.migrated_count = result.source_count
            result.id_hash = _id_hash(
                [role.role_id for role in roles]
                + [f"{item.user_id}:{item.tenant_id}:{item.role_id}" for item in assignments]
                + [f"{item.role_id}:{item.tenant_id}:{item.obj}:{item.act}:{item.priority}" for item in policies]
            )
        finally:
            source.close()
        self.results.append(result)

    def _migrate_analysis_tasks(self) -> None:
        rows = list(self.source.execute("SELECT * FROM platform_analysis_tasks ORDER BY created_at,task_id"))
        store = PostgreSQLAnalysisTaskRepository(self.pool)
        result = DomainResult("analysis_tasks", source_count=len(rows))
        migrated_ids: list[str] = []
        for row in rows:
            task_id = str(row["task_id"])
            try:
                task = AnalysisTask(
                    question=str(row["question"]),
                    task_type=str(row["task_type"]),  # type: ignore[arg-type]
                    tenant_id=self._scope(str(row["tenant_id"])) or str(row["tenant_id"]),
                    user_id=str(row["user_id"]),
                    task_id=task_id,
                    request_id=str(row["request_id"] or task_id),
                    execution_id=str(row["execution_id"] or task_id),
                    revision=max(1, int(row["revision"] or 1)),
                    parent_execution_id=row["parent_execution_id"],
                    execution_mode=str(row["execution_mode"] or "degraded"),
                    status=str(row["status"] or "failed"),
                    plan=[AgentStep(**item) for item in _json(row["plan"], []) if isinstance(item, dict)],
                    analysis_plan=_json(row["analysis_plan"], {}),
                    skill_results=_json(row["skill_results"], []),
                    knowledge_refs=_json(row["knowledge_refs"], []),
                    conclusions=_json(row["conclusions"], []),
                    review=_json(row["review"], {}),
                    trace_id=str(row["trace_id"] or task_id),
                    manual_edits=_json(row["manual_edits"], {}),
                    agent_group_state=_json(row["agent_group_state"], {}),
                )
                store.save_task(task)
                result.migrated_count += 1
                migrated_ids.append(task_id)
            except Exception as exc:
                result.errors.append({"id": task_id, "error": f"{type(exc).__name__}:{exc}"})
        result.id_hash = _id_hash(migrated_ids)
        self.results.append(result)

    def _migrate_metrics(self) -> None:
        rows = list(self.source.execute("SELECT tenant_id,metric_id,payload,updated_by FROM platform_metric_dictionary ORDER BY tenant_id,metric_id"))
        store = PostgreSQLMetricDictionaryStore(self.pool)
        result = DomainResult("metrics", source_count=len(rows))
        migrated_ids: list[str] = []
        for row in rows:
            key = f"{row['tenant_id']}:{row['metric_id']}"
            try:
                tenant = self._scope(str(row["tenant_id"])) or str(row["tenant_id"])
                payload = _json(row["payload"], {})
                store.upsert(tenant, payload, updated_by=self._actor(row["updated_by"]))
                result.migrated_count += 1
                migrated_ids.append(key)
            except Exception as exc:
                result.errors.append({"id": key, "error": f"{type(exc).__name__}:{exc}"})
        result.id_hash = _id_hash(migrated_ids)
        self.results.append(result)

    def _migrate_assets(self) -> None:
        rows = list(self.source.execute(
            "SELECT tenant_id,item_type,item_id,version_number,lifecycle_status,payload,submitted_by "
            "FROM platform_data_asset_versions ORDER BY tenant_id,item_type,item_id,version_number"
        ))
        store = PostgreSQLDataAssetStore(self.pool)
        result = DomainResult("data_asset_versions", source_count=len(rows))
        migrated_ids: list[str] = []
        for row in rows:
            key = f"{row['tenant_id']}:{row['item_type']}:{row['item_id']}:{row['version_number']}"
            try:
                tenant = self._scope(str(row["tenant_id"])) or str(row["tenant_id"])
                store.upsert_item(
                    tenant,
                    str(row["item_type"]),
                    _json(row["payload"], {}),
                    updated_by=self._actor(row["submitted_by"]),
                    lifecycle_status=str(row["lifecycle_status"] or "draft"),
                )
                result.migrated_count += 1
                migrated_ids.append(key)
            except Exception as exc:
                result.errors.append({"id": key, "error": f"{type(exc).__name__}:{exc}"})
        result.id_hash = _id_hash(migrated_ids)
        self.results.append(result)

    def _migrate_lineage(self) -> None:
        rows = list(self.source.execute("SELECT * FROM platform_lineage_edges ORDER BY created_at,lineage_edge_id"))
        store = PostgreSQLLineageStore(self.pool)
        result = DomainResult("lineage", source_count=len(rows))
        migrated_ids: list[str] = []
        for row in rows:
            key = str(row["lineage_edge_id"])
            try:
                tenant = self._scope(str(row["tenant_id"])) or str(row["tenant_id"])
                store.record_edge(tenant, {**dict(row), "metadata": _json(row["metadata"], {})}, self._actor(row["created_by"]))
                result.migrated_count += 1
                migrated_ids.append(key)
            except Exception as exc:
                result.errors.append({"id": key, "error": f"{type(exc).__name__}:{exc}"})
        result.id_hash = _id_hash(migrated_ids)
        self.results.append(result)

    def _migrate_reports(self) -> None:
        store = PostgreSQLReportStore(self.pool)
        saved_rows = list(self.source.execute(
            "SELECT tenant_id,result_id,payload,created_by FROM platform_saved_analysis_results ORDER BY created_at,result_id"
        ))
        version_rows = list(self.source.execute(
            "SELECT tenant_id,version_id,payload,updated_by FROM platform_weekly_report_versions ORDER BY created_at,version_id"
        ))
        comment_rows = list(self.source.execute(
            "SELECT tenant_id,report_id,comments,updated_by FROM platform_report_comments ORDER BY tenant_id,report_id"
        ))
        ai_rows = list(self.source.execute(
            "SELECT * FROM weekly_report_ai_analysis_task ORDER BY created_at,task_id"
        ))
        result = DomainResult(
            "reports",
            source_count=len(saved_rows) + len(version_rows) + len(comment_rows) + len(ai_rows),
        )
        migrated_ids: list[str] = []
        task_store = PostgreSQLAnalysisTaskRepository(self.pool)
        for row in saved_rows:
            key = f"saved:{row['tenant_id']}:{row['result_id']}"
            try:
                tenant = self._scope(str(row["tenant_id"])) or str(row["tenant_id"])
                payload = _json(row["payload"], {})
                actor = self._actor(row["created_by"])
                if not str(payload.get("analysisTaskId") or "").strip():
                    placeholder_id = f"historical_saved_{hashlib.sha256(key.encode()).hexdigest()[:24]}"
                    task_store.save_task(AnalysisTask(
                        question=str(payload.get("query") or payload.get("title") or "Historical saved report"),
                        task_type="report_generation",
                        tenant_id=tenant,
                        user_id=actor,
                        task_id=placeholder_id,
                        request_id=placeholder_id,
                        execution_id=placeholder_id,
                        execution_mode="degraded",
                        status="completed",
                        analysis_plan={"source": "historical_import", "saved_result_id": str(row["result_id"])},
                        conclusions=[str(payload.get("summary") or "Historical report imported without an original task reference.")],
                    ))
                    payload["analysisTaskId"] = placeholder_id
                store.upsert_analysis_result(tenant, payload, updated_by=actor)
                result.migrated_count += 1
                migrated_ids.append(key)
            except Exception as exc:
                result.errors.append({"id": key, "error": f"{type(exc).__name__}:{exc}"})
        for row in version_rows:
            key = f"version:{row['tenant_id']}:{row['version_id']}"
            try:
                tenant = self._scope(str(row["tenant_id"])) or str(row["tenant_id"])
                store.save_weekly_report_version(tenant, _json(row["payload"], {}), updated_by=self._actor(row["updated_by"]))
                result.migrated_count += 1
                migrated_ids.append(key)
            except Exception as exc:
                result.errors.append({"id": key, "error": f"{type(exc).__name__}:{exc}"})
        for row in comment_rows:
            key = f"comments:{row['tenant_id']}:{row['report_id']}"
            try:
                tenant = self._scope(str(row["tenant_id"])) or str(row["tenant_id"])
                store.replace_report_comments(
                    tenant,
                    str(row["report_id"]),
                    _json(row["comments"], []),
                    updated_by=self._actor(row["updated_by"]),
                )
                result.migrated_count += 1
                migrated_ids.append(key)
            except Exception as exc:
                result.errors.append({"id": key, "error": f"{type(exc).__name__}:{exc}"})
        for row in ai_rows:
            key = f"weekly-ai:{row['tenant_id']}:{row['task_id']}"
            try:
                tenant = self._scope(str(row["tenant_id"])) or str(row["tenant_id"])
                store.upsert_weekly_ai_task(
                    tenant,
                    {
                        "id": str(row["task_id"]),
                        "version_id": str(row["version_id"]),
                        "status": str(row["status"]),
                        "input_snapshot": _json(row["input_snapshot"], {}),
                        "debate_result": _json(row["debate_result"], {}),
                        "final_result": _json(row["final_result"], {}),
                        "error_message": str(row["error_message"] or ""),
                    },
                    updated_by=self._actor(row["updated_by"]),
                )
                result.migrated_count += 1
                migrated_ids.append(key)
            except Exception as exc:
                result.errors.append({"id": key, "error": f"{type(exc).__name__}:{exc}"})
        result.id_hash = _id_hash(migrated_ids)
        self.results.append(result)

    def _migrate_knowledge(self) -> None:
        rows = list(self.source.execute(
            """
            SELECT d.tenant_id,d.document_id,d.title,d.document_type,d.domains,d.tags,
                   d.status,d.owner_user_id,c.content
            FROM platform_knowledge_documents d
            JOIN platform_knowledge_versions v
              ON v.tenant_id=d.tenant_id AND v.document_id=d.document_id AND v.version_no=d.current_version_no
            JOIN platform_knowledge_chunks c
              ON c.tenant_id=v.tenant_id AND c.knowledge_version_id=v.knowledge_version_id
            ORDER BY d.tenant_id,d.document_id,c.chunk_no
            """
        ))
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (str(row["tenant_id"]), str(row["document_id"]))
            item = grouped.setdefault(key, {**dict(row), "content_parts": []})
            item["content_parts"].append(str(row["content"] or ""))
        store = PostgreSQLKnowledgeStore(self.pool)
        result = DomainResult("knowledge", source_count=len(grouped))
        migrated_ids: list[str] = []
        for (raw_tenant, document_id), item in grouped.items():
            key = f"{raw_tenant}:{document_id}"
            try:
                tenant = self._scope(raw_tenant) or raw_tenant
                store.add(KnowledgeDocument(
                    doc_id=document_id,
                    title=str(item["title"]),
                    content="\n".join(item["content_parts"]),
                    tenant_id=None if tenant == "__global__" else tenant,
                    domains=tuple(_json(item["domains"], [])),
                    source_type=str(item["document_type"] or "other"),
                    tags=tuple(_json(item["tags"], [])),
                    status=str(item["status"] or "active"),
                    owner_user_id=self._actor(item["owner_user_id"]),
                ))
                result.migrated_count += 1
                migrated_ids.append(key)
            except Exception as exc:
                result.errors.append({"id": key, "error": f"{type(exc).__name__}:{exc}"})
        result.id_hash = _id_hash(migrated_ids)
        self.results.append(result)

    def _migrate_memory(self) -> None:
        rows = list(self.source.execute("SELECT * FROM platform_memory_records ORDER BY created_at,memory_id"))
        evidence = {
            str(row["memory_id"]): row
            for row in self.source.execute("SELECT * FROM platform_memory_evidence WHERE support_type='supports'")
        }
        store = PostgreSQLMemoryStore(self.pool)
        result = DomainResult("memory", source_count=len(rows))
        migrated_ids: list[str] = []
        for row in rows:
            key = str(row["memory_id"])
            try:
                tenant = self._scope(str(row["tenant_id"])) or str(row["tenant_id"])
                support = evidence.get(key)
                record = MemoryRecord(
                    memory_id=key,
                    memory_type=str(row["memory_type"]),
                    tenant_id=tenant,
                    subject=str(row["title"] or row["subject_id"] or key),
                    content=_json(row["content"], {}),
                    source_trace_id=row["source_trace_id"],
                    confidence=float(row["confidence"] or 0),
                    verified_status=str(row["status"] or "candidate"),
                    subject_type=str(row["subject_type"] or "tenant"),
                    subject_id=str(row["subject_id"] or tenant),
                    title=str(row["title"] or key),
                    weight=float(row["weight"] or 1),
                    expires_at=row["expires_at"],
                    supersedes_memory_id=row["supersedes_memory_id"],
                    evidence_type=str(support["evidence_type"]) if support else None,
                    evidence_id=str(support["evidence_id"]) if support else None,
                    evidence_hash=str(support["evidence_hash"]) if support else None,
                    created_by=self._actor(row["created_by"]),
                    created_at=str(row["created_at"]),
                )
                if not store.write(record, force=True):
                    existing = store.get(tenant, key)
                    if existing["memory_id"] != key:
                        raise RuntimeError("memory_id_mismatch")
                result.migrated_count += 1
                migrated_ids.append(key)
            except Exception as exc:
                result.errors.append({"id": key, "error": f"{type(exc).__name__}:{exc}"})
        result.id_hash = _id_hash(migrated_ids)
        self.results.append(result)

    def _migrate_audit(self) -> None:
        rows = list(self.source.execute("SELECT * FROM platform_audit_events ORDER BY created_at,event_id"))
        result = DomainResult("audit", source_count=len(rows))
        migrated_ids: list[str] = []
        with self.pool.connection() as connection:
            try:
                with connection.cursor() as cursor:
                    for row in rows:
                        key = str(row["event_id"])
                        try:
                            tenant = self._scope(str(row["tenant_id"])) or str(row["tenant_id"])
                            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant)
                            actor = self._actor(row["actor_user_id"])
                            actor_key = PostgreSQLIdentityResolver.user_id(connection, actor, required=False)
                            detail = sanitize_audit_detail(_json(row["detail"], {}))
                            detail["legacy_event_id"] = key
                            if row["ip_address"]:
                                detail["ip_address"] = str(row["ip_address"])
                            event_hash = hashlib.sha256(json.dumps(detail, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                            cursor.execute(
                                """
                                INSERT INTO platform_audit_events(
                                    tenant_id,actor_user_id,event_type,resource_type,resource_id,
                                    action,outcome,metadata,event_hash,occurred_at,created_by
                                ) VALUES(%s,%s,%s,%s,%s,%s,'success',%s,%s,%s,%s)
                                """,
                                (tenant_key, actor_key, f"{row['target_type']}.{row['action']}"[:120], str(row["target_type"])[:120], str(row["target_id"] or "")[:200] or None, str(row["action"])[:64], json.dumps(detail, ensure_ascii=False, sort_keys=True), event_hash, row["created_at"], actor_key),
                            )
                            result.migrated_count += 1
                            migrated_ids.append(key)
                        except Exception as exc:
                            result.errors.append({"id": key, "error": f"{type(exc).__name__}:{exc}"})
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        result.id_hash = _id_hash(migrated_ids)
        self.results.append(result)

    def _migrate_automation_definitions(self) -> None:
        rows = list(self.source.execute("SELECT * FROM platform_automation_tasks ORDER BY created_at,automation_task_id"))
        store = PostgreSQLAutomationStore(self.pool)
        result = DomainResult("automation_definitions", source_count=len(rows))
        migrated_ids: list[str] = []
        task_codes: set[tuple[str, str]] = set()
        for row in rows:
            key = str(row["automation_task_id"])
            try:
                tenant = self._scope(str(row["tenant_id"])) or str(row["tenant_id"])
                original_task_code = str(row["task_code"])
                task_code = original_task_code
                if (tenant, task_code) in task_codes:
                    task_code = f"{task_code[:143]}.legacy.{hashlib.sha256(key.encode()).hexdigest()[:8]}"
                task_codes.add((tenant, task_code))
                task_config = _json(row["task_config"], {})
                if task_code != original_task_code:
                    task_config = {**task_config, "legacyTaskCode": original_task_code}
                created = store.create_task(tenant, {
                    "automation_task_id": key,
                    "task_code": task_code,
                    "task_name": str(row["task_name"]),
                    "task_type": str(row["task_type"]),
                    "trigger_type": str(row["trigger_type"]),
                    "schedule_expression": row["schedule_expression"],
                    "event_type": row["event_type"],
                    "handler_ref": str(row["handler_ref"]),
                    "task_config": task_config,
                    "retry_policy": _json(row["retry_policy"], {}),
                    "timeout_seconds": int(row["timeout_seconds"] or 900),
                    "max_concurrency": int(row["max_concurrency"] or 1),
                }, self._actor(row["owner_user_id"]))
                store.update_task(
                    tenant,
                    key,
                    {"status": "paused"},
                    self._actor(row["owner_user_id"]),
                    int(created["lock_version"]),
                )
                result.migrated_count += 1
                migrated_ids.append(key)
            except Exception as exc:
                result.errors.append({"id": key, "error": f"{type(exc).__name__}:{exc}"})
        result.id_hash = _id_hash(migrated_ids)
        self.results.append(result)

    def _source_table_coverage(self) -> dict[str, Any]:
        migrated = {
            "auth_manageable_roles", "auth_permission_policies", "auth_role_assignments", "auth_roles",
            "platform_analysis_tasks", "platform_data_asset_items", "platform_data_asset_versions",
            "platform_data_connections", "platform_knowledge_chunks", "platform_knowledge_documents",
            "platform_knowledge_versions", "platform_lineage_edges", "platform_memory_evidence",
            "platform_memory_records", "platform_metric_dictionary", "platform_metric_visibility",
            "platform_model_integrations", "platform_saved_analysis_results", "platform_speech_integrations",
            "platform_system_data_params", "platform_user_profiles", "platform_weekly_report_versions",
            "weekly_report_ai_analysis_task", "platform_report_comments", "platform_audit_events",
            "platform_automation_tasks",
        }
        rebuilt = {
            "platform_analysis_artifacts", "platform_analysis_evidence", "platform_analysis_queries",
            "platform_evaluations", "platform_job_steps", "platform_model_calls",
        }
        archived_only = {
            "platform_application_actions", "platform_application_module_state", "platform_auth_sessions",
            "platform_automation_task_runs", "platform_bootstrap_state", "platform_bridge_bindings",
            "platform_bridge_enrollments", "platform_data_artifacts", "platform_file_attachments",
            "platform_knowledge_citations", "platform_knowledge_documents_legacy", "platform_memory_records_legacy",
            "platform_outbox_events", "platform_report_comment_items", "platform_report_comment_replies",
            "platform_report_comment_revisions", "platform_runtime_events", "platform_schema_migrations",
            "platform_subscriptions", "platform_trace_spans",
        }
        nonempty: dict[str, int] = {}
        for table in _table_names(self.source):
            quoted = table.replace('"', '""')
            count = int(self.source.execute(f'SELECT COUNT(*) FROM "{quoted}"').fetchone()[0])
            if count:
                nonempty[table] = count
        covered = migrated | rebuilt | archived_only
        return {
            "nonempty_table_count": len(nonempty),
            "normalized_migration_tables": sorted(set(nonempty) & migrated),
            "deterministically_rebuilt_tables": sorted(set(nonempty) & rebuilt),
            "snapshot_only_not_reactivated_tables": sorted(set(nonempty) & archived_only),
            "uncovered_nonempty_tables": sorted(set(nonempty) - covered),
        }

    def _disable_non_login_users(self) -> None:
        subjects = self.historical_users | self.disabled_users
        if not subjects:
            return
        with self.pool.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE platform_user_profiles SET status='disabled',updated_at=now(),lock_version=lock_version+1 "
                "WHERE external_subject=ANY(%s)",
                (sorted(subjects),),
            )
            connection.commit()

    def _source_scopes(self) -> list[str]:
        values: set[str] = {"__global__"}
        for table in _table_names(self.source):
            columns = _columns(self.source, table)
            if "tenant_id" not in columns:
                continue
            quoted = table.replace('"', '""')
            values.update(
                str(row[0]) for row in self.source.execute(
                    f'SELECT DISTINCT tenant_id FROM "{quoted}" WHERE tenant_id IS NOT NULL AND tenant_id NOT IN (\'\',\'*\')'
                )
            )
        return sorted(values)

    def _referenced_users(self) -> set[str]:
        values: set[str] = set()
        user_columns = {
            "user_id", "created_by", "updated_by", "owner_user_id", "requested_by",
            "reviewed_by", "submitted_by", "granted_by", "actor_user_id", "resolved_by",
        }
        for table in _table_names(self.source):
            quoted_table = table.replace('"', '""')
            for column in user_columns.intersection(_columns(self.source, table)):
                quoted_column = column.replace('"', '""')
                values.update(
                    str(row[0]) for row in self.source.execute(
                        f'SELECT DISTINCT "{quoted_column}" FROM "{quoted_table}" '
                        f'WHERE "{quoted_column}" IS NOT NULL AND "{quoted_column}" <> \'\''
                    )
                )
        return values

    def _scope(self, value: str | None) -> str | None:
        if value in (None, "*"):
            return value
        text = str(value)
        return self.scope_map.get(text, _normalize_scope(text))

    def _actor(self, value: Any) -> str:
        actor = str(value or "system")
        if actor.startswith("role:") or actor == "development_seed":
            return "system"
        return actor


def _normalize_scope(value: str) -> str:
    decoded = unquote(str(value))
    try:
        repaired = decoded.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        repaired = decoded
    return repaired


def _scope_name(value: str) -> str:
    return value.removeprefix("tenant:").removeprefix("account:") or value


def _json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    return json.loads(value) if isinstance(value, str) else value


def _table_names(connection: sqlite3.Connection) -> list[str]:
    return [str(row[0]) for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    quoted = table.replace('"', '""')
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{quoted}")')}


def _id_hash(values: list[str] | set[str]) -> str:
    return hashlib.sha256("\n".join(sorted(map(str, values))).encode("utf-8")).hexdigest()


def _row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        for candidate, value in row.items():
            if str(candidate).lower() == key.lower():
                return value
        raise KeyError(key)
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy SDA SQLite structured data to MySQL.")
    parser.add_argument("--sqlite", required=True)
    parser.add_argument("--mysql-url", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--allow-partial", action="store_true", help="Return success for an incomplete rehearsal only.")
    args = parser.parse_args()
    migrator = StructuredMySQLMigrator(args.sqlite, args.mysql_url)
    try:
        report = migrator.migrate()
    finally:
        migrator.close()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "ready_for_cutover": report["ready_for_cutover"]}, ensure_ascii=False))
    return 0 if report["ready_for_cutover"] or args.allow_partial else 2


if __name__ == "__main__":
    raise SystemExit(main())
