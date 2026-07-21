from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import uuid4

from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database.postgresql import PostgreSQLConnectionPool

from .store import (
    SCRIPT_RUNTIMES,
    SOURCE_CATEGORIES,
    _json_object,
    _required_code,
    _required_text,
)


class PostgreSQLAcquisitionStore:
    """Production acquisition definitions, runs, artifacts, quality and repair facts."""

    def __init__(self, pool: PostgreSQLConnectionPool, *, owns_pool: bool = False) -> None:
        self.pool = pool
        self.owns_pool = owns_pool

    def close(self) -> None:
        if self.owns_pool:
            self.pool.close()

    def ensure_connection_reference(self, tenant_id: str, connection_id: str) -> None:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            self._connection_id(connection, tenant_key, connection_id)

    def create_source(self, tenant_id: str, payload: dict[str, Any], created_by: str) -> dict[str, Any]:
        source_code = _required_code(payload.get("source_code", payload.get("sourceCode")), "source_code")
        source_name = _required_text(payload.get("source_name", payload.get("sourceName")), "source_name", 300)
        category = str(payload.get("source_category", payload.get("sourceCategory")) or "other").strip()
        if category not in SOURCE_CATEGORIES:
            raise ValueError("invalid_source_category")
        source_key = str(payload.get("source_system_id", payload.get("sourceSystemId")) or f"src_{uuid4().hex}")
        license_metadata = _json_object(payload.get("license_metadata", payload.get("licenseMetadata", {})))
        if category == "market" and not any(license_metadata.get(key) for key in ("license_type", "terms_url", "contract_ref")):
            raise ValueError("market_source_license_metadata_required")
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, created_by)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_source_systems(
                        tenant_id, source_system_key, source_code, source_name,
                        source_category, license_metadata, status, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, 'active', %s)
                    """,
                    (tenant_key, source_key, source_code, source_name, category, _json(license_metadata), actor_key),
                )
        return self.get_source(tenant_id, source_key)

    def get_source(self, tenant_id: str, source_system_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._source_select() + " WHERE s.tenant_id = %s AND s.source_system_key = %s", (tenant_key, source_system_id))
                row = cursor.fetchone()
        if not row:
            raise KeyError("source_system_not_found")
        return self._source_from_row(row)

    def list_sources(self, tenant_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._source_select() + " WHERE s.tenant_id = %s ORDER BY s.source_name, s.source_system_key", (tenant_key,))
                rows = cursor.fetchall()
        return [self._source_from_row(row) for row in rows]

    def create_script_version(self, tenant_id: str, payload: dict[str, Any], created_by: str) -> dict[str, Any]:
        script_code = _required_code(payload.get("script_code", payload.get("scriptCode")), "script_code")
        script_name = _required_text(payload.get("script_name", payload.get("scriptName")), "script_name", 300)
        runtime = str(payload.get("runtime") or "http").strip().lower()
        if runtime not in SCRIPT_RUNTIMES:
            raise ValueError("invalid_script_runtime")
        if runtime == "shell_restricted":
            raise ValueError("shell_restricted_runtime_requires_external_worker")
        source_code = _required_text(payload.get("source_code", payload.get("sourceCode")), "source_code", 200_000)
        dependency_lock = _json_object(payload.get("dependency_lock", payload.get("dependencyLock", {})))
        input_schema = _json_object(payload.get("input_schema", payload.get("inputSchema", {})))
        output_schema = _json_object(payload.get("output_schema", payload.get("outputSchema", {})))
        version_key = f"asv_{uuid4().hex}"
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, created_by)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT acquisition_script_id, script_key, runtime, owner_user_id,
                           COALESCE((SELECT MAX(version_no) FROM platform_acquisition_script_versions v
                                     WHERE v.acquisition_script_id = s.acquisition_script_id), 0) AS max_version
                    FROM platform_acquisition_scripts s
                    WHERE tenant_id = %s AND script_code = %s FOR UPDATE
                    """,
                    (tenant_key, script_code),
                )
                existing = cursor.fetchone()
                if existing:
                    if _value(existing, "owner_user_id", 3) != actor_key:
                        raise PermissionError("script_owner_required")
                    if str(_value(existing, "runtime", 2)) != runtime:
                        raise ValueError("script_runtime_is_immutable")
                    script_id = _value(existing, "acquisition_script_id", 0)
                    version_no = int(_value(existing, "max_version", 4)) + 1
                    cursor.execute(
                        "UPDATE platform_acquisition_scripts SET script_name = %s, status = 'review', updated_at = now(), lock_version = lock_version + 1 WHERE acquisition_script_id = %s",
                        (script_name, script_id),
                    )
                else:
                    script_key = str(payload.get("acquisition_script_id", payload.get("acquisitionScriptId")) or f"as_{uuid4().hex}")
                    version_no = 1
                    cursor.execute(
                        """
                        INSERT INTO platform_acquisition_scripts(
                            tenant_id, script_key, script_code, script_name, runtime,
                            current_version_no, owner_user_id, status, created_by
                        ) VALUES (%s, %s, %s, %s, %s, 0, %s, 'review', %s)
                        RETURNING acquisition_script_id
                        """,
                        (tenant_key, script_key, script_code, script_name, runtime, actor_key, actor_key),
                    )
                    script_id = _value(cursor.fetchone(), "acquisition_script_id", 0)
                cursor.execute(
                    """
                    INSERT INTO platform_acquisition_script_versions(
                        tenant_id, script_version_key, acquisition_script_id, version_no,
                        source_code, source_hash, dependency_lock, input_schema,
                        output_schema, review_status, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, 'pending', %s)
                    """,
                    (
                        tenant_key, version_key, script_id, version_no, source_code,
                        hashlib.sha256(source_code.encode("utf-8")).hexdigest(),
                        _json(dependency_lock), _json(input_schema), _json(output_schema), actor_key,
                    ),
                )
        return self.get_script_version(tenant_id, version_key, reveal_source=True)

    def get_script_version(self, tenant_id: str, script_version_id: str, reveal_source: bool = False) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._script_select() + " WHERE v.tenant_id = %s AND v.script_version_key = %s", (tenant_key, script_version_id))
                row = cursor.fetchone()
        if not row:
            raise KeyError("script_version_not_found")
        return self._script_from_row(row, reveal_source)

    def list_scripts(self, tenant_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._script_select() + " WHERE v.tenant_id = %s ORDER BY s.script_code, v.version_no DESC", (tenant_key,))
                rows = cursor.fetchall()
        return [self._script_from_row(row, False) for row in rows]

    def review_script_version(self, tenant_id: str, script_version_id: str, decision: str, reviewer: str) -> dict[str, Any]:
        normalized = str(decision or "").strip().lower()
        if normalized not in {"approved", "rejected", "revoked"}:
            raise ValueError("invalid_script_review_decision")
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            reviewer_key = PostgreSQLIdentityResolver.user_id(connection, reviewer)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT v.script_version_id, v.review_status, v.created_by, v.version_no,
                           v.acquisition_script_id
                    FROM platform_acquisition_script_versions v
                    WHERE v.tenant_id = %s AND v.script_version_key = %s FOR UPDATE
                    """,
                    (tenant_key, script_version_id),
                )
                row = cursor.fetchone()
                if not row:
                    raise KeyError("script_version_not_found")
                if str(_value(row, "review_status", 1)) != "pending":
                    raise ValueError("script_version_is_not_pending")
                if _value(row, "created_by", 2) == reviewer_key:
                    raise PermissionError("four_eyes_script_review_required")
                cursor.execute(
                    """
                    UPDATE platform_acquisition_script_versions
                    SET review_status = %s, reviewed_by = %s, reviewed_at = now(),
                        updated_at = now(), lock_version = lock_version + 1
                    WHERE script_version_id = %s
                    """,
                    (normalized, reviewer_key, _value(row, "script_version_id", 0)),
                )
                if normalized == "approved":
                    cursor.execute(
                        """
                        UPDATE platform_acquisition_scripts
                        SET current_version_no = %s, status = 'active', updated_at = now(),
                            lock_version = lock_version + 1
                        WHERE acquisition_script_id = %s
                        """,
                        (_value(row, "version_no", 3), _value(row, "acquisition_script_id", 4)),
                    )
        return self.get_script_version(tenant_id, script_version_id, reveal_source=False)

    def create_job(self, tenant_id: str, payload: dict[str, Any], created_by: str) -> dict[str, Any]:
        script_version_key = _required_text(payload.get("script_version_id", payload.get("scriptVersionId")), "script_version_id", 160)
        version = self.get_script_version(tenant_id, script_version_key, reveal_source=False)
        if version["review_status"] != "approved":
            raise ValueError("approved_script_version_required")
        source_key = _required_text(payload.get("source_system_id", payload.get("sourceSystemId")), "source_system_id", 160)
        connection_code = _required_text(payload.get("connection_id", payload.get("connectionId")), "connection_id", 160)
        job_code = _required_code(payload.get("job_code", payload.get("jobCode")), "job_code")
        job_name = _required_text(payload.get("job_name", payload.get("jobName")), "job_name", 300)
        dataset_code = _required_text(payload.get("target_dataset_id", payload.get("targetDatasetId")), "target_dataset_id", 200)
        topic_code = str(payload.get("topic_table_id", payload.get("topicTableId")) or "").strip() or None
        trigger_type = str(payload.get("trigger_type", payload.get("triggerType")) or "manual").strip()
        if trigger_type not in {"manual", "schedule", "event"}:
            raise ValueError("invalid_acquisition_trigger_type")
        execution_mode = str(payload.get("execution_mode", payload.get("executionMode")) or "offline").strip()
        if execution_mode not in {"realtime", "offline"}:
            raise ValueError("invalid_acquisition_execution_mode")
        schedule_expression = str(payload.get("schedule_expression", payload.get("scheduleExpression")) or "").strip() or None
        if trigger_type == "schedule" and not schedule_expression:
            raise ValueError("schedule_expression_required")
        job_key = str(payload.get("acquisition_job_id", payload.get("acquisitionJobId")) or f"aj_{uuid4().hex}")
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, created_by)
            source_id = self._source_id(connection, tenant_key, source_key)
            script_version_id = self._script_version_id(connection, tenant_key, script_version_key)
            connection_id = self._connection_id(connection, tenant_key, connection_code)
            dataset_id = self._dataset_id(connection, tenant_key, dataset_code)
            topic_id = self._topic_id(connection, tenant_key, topic_code, required=False) if topic_code else None
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_acquisition_jobs(
                        tenant_id, job_key, job_code, job_name, source_system_id,
                        script_version_id, connection_id, target_dataset_id, topic_table_id,
                        trigger_type, schedule_expression, execution_mode, job_config,
                        status, owner_user_id, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, 'active', %s, %s)
                    """,
                    (
                        tenant_key, job_key, job_code, job_name, source_id, script_version_id,
                        connection_id, dataset_id, topic_id, trigger_type, schedule_expression,
                        execution_mode, _json(_json_object(payload.get("job_config", payload.get("jobConfig", {})))), actor_key, actor_key,
                    ),
                )
        return self.get_job(tenant_id, job_key)

    def get_job(self, tenant_id: str, acquisition_job_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._job_select() + " WHERE j.tenant_id = %s AND j.job_key = %s", (tenant_key, acquisition_job_id))
                row = cursor.fetchone()
        if not row:
            raise KeyError("acquisition_job_not_found")
        return self._job_from_row(row)

    def list_jobs(self, tenant_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._job_select() + " WHERE j.tenant_id = %s ORDER BY j.job_name, j.job_key", (tenant_key,))
                rows = cursor.fetchall()
        return [self._job_from_row(row) for row in rows]

    def queue_run(
        self,
        tenant_id: str,
        acquisition_job_id: str,
        idempotency_key: str,
        trigger_type: str,
        created_by: str,
        input_cursor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        key = _required_text(idempotency_key, "idempotency_key", 200)
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, created_by)
            job_id = self._job_id(connection, tenant_key, acquisition_job_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT run_key FROM platform_acquisition_job_runs WHERE tenant_id = %s AND acquisition_job_id = %s AND idempotency_key = %s",
                    (tenant_key, job_id, key),
                )
                existing = cursor.fetchone()
                if existing:
                    run_key = str(_value(existing, "run_key", 0))
                else:
                    run_key = f"ar_{uuid4().hex}"
                    cursor.execute(
                        """
                        INSERT INTO platform_acquisition_job_runs(
                            tenant_id, run_key, acquisition_job_id, trigger_type,
                            idempotency_key, status, input_cursor, created_by
                        ) VALUES (%s, %s, %s, %s, %s, 'queued', %s::jsonb, %s)
                        """,
                        (tenant_key, run_key, job_id, trigger_type, key, _json(input_cursor or {}), actor_key),
                    )
        return self.get_run(tenant_id, run_key)

    def get_run(self, tenant_id: str, acquisition_run_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._run_select() + " WHERE r.tenant_id = %s AND r.run_key = %s", (tenant_key, acquisition_run_id))
                row = cursor.fetchone()
        if not row:
            raise KeyError("acquisition_run_not_found")
        return self._run_from_row(row)

    def list_runs(self, tenant_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    self._run_select() + " WHERE r.tenant_id = %s ORDER BY r.created_at DESC LIMIT %s",
                    (tenant_key, max(1, min(int(limit), 500))),
                )
                rows = cursor.fetchall()
        return [self._run_from_row(row) for row in rows]

    def update_run(self, tenant_id: str, acquisition_run_id: str, **changes: Any) -> dict[str, Any]:
        allowed = {
            "status", "output_cursor", "rows_read", "rows_written", "source_snapshot",
            "quality_summary", "output_artifact_id", "partition_id", "started_at",
            "finished_at", "error_code", "error_summary",
        }
        unexpected = set(changes) - allowed
        if unexpected:
            raise ValueError(f"unsupported_run_fields:{','.join(sorted(unexpected))}")
        if not changes:
            return self.get_run(tenant_id, acquisition_run_id)
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            assignments: list[str] = []
            values: list[Any] = []
            for key, value in changes.items():
                if key in {"output_cursor", "source_snapshot", "quality_summary"}:
                    assignments.append(f"{key} = %s::jsonb")
                    values.append(_json(value))
                elif key == "output_artifact_id":
                    assignments.append("output_artifact_id = %s")
                    values.append(self._artifact_id(connection, tenant_key, str(value)) if value else None)
                elif key == "partition_id":
                    assignments.append("partition_id = %s")
                    values.append(self._partition_id(connection, tenant_key, str(value)) if value else None)
                elif key in {"started_at", "finished_at"}:
                    assignments.append(f"{key} = %s::timestamptz")
                    values.append(value)
                else:
                    assignments.append(f"{key} = %s")
                    values.append(value)
            assignments.extend(["updated_at = now()", "lock_version = lock_version + 1"])
            values.extend([tenant_key, acquisition_run_id])
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE platform_acquisition_job_runs SET {', '.join(assignments)} WHERE tenant_id = %s AND run_key = %s",
                    tuple(values),
                )
                if cursor.rowcount != 1:
                    raise KeyError("acquisition_run_not_found")
        return self.get_run(tenant_id, acquisition_run_id)

    def create_artifact(
        self,
        tenant_id: str,
        *,
        object_uri: str,
        content_hash: str,
        content_type: str,
        size_bytes: int,
        status: str,
        created_by: str,
        artifact_type: str = "csv",
    ) -> dict[str, Any]:
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, created_by)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT artifact_key FROM platform_data_artifacts WHERE tenant_id = %s AND content_hash = %s AND object_uri = %s",
                    (tenant_key, content_hash, object_uri),
                )
                existing = cursor.fetchone()
                if existing:
                    artifact_key = str(_value(existing, "artifact_key", 0))
                else:
                    artifact_key = f"da_{uuid4().hex}"
                    cursor.execute(
                        """
                        INSERT INTO platform_data_artifacts(
                            tenant_id, artifact_key, artifact_type, object_uri, content_hash,
                            content_type, size_bytes, status, created_by
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (tenant_key, artifact_key, artifact_type, object_uri, content_hash, content_type, int(size_bytes), status, actor_key),
                    )
        return self.get_artifact(tenant_id, artifact_key)

    def get_artifact(self, tenant_id: str, artifact_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT a.artifact_key, t.tenant_code, a.artifact_type, a.object_uri,
                           a.content_hash, a.content_type, a.size_bytes, a.status,
                           u.external_subject AS created_by, a.created_at, a.updated_at
                    FROM platform_data_artifacts a
                    JOIN platform_tenants t ON t.tenant_id = a.tenant_id
                    LEFT JOIN platform_user_profiles u ON u.user_id = a.created_by
                    WHERE a.tenant_id = %s AND a.artifact_key = %s
                    """,
                    (tenant_key, artifact_id),
                )
                row = cursor.fetchone()
        if not row:
            raise KeyError("data_artifact_not_found")
        keys = ("artifact_id", "tenant_id", "artifact_type", "object_uri", "content_hash", "content_type", "size_bytes", "status", "created_by", "created_at", "updated_at")
        db_keys = ("artifact_key", "tenant_code", "artifact_type", "object_uri", "content_hash", "content_type", "size_bytes", "status", "created_by", "created_at", "updated_at")
        return _row_dict(row, keys, db_keys)

    def create_partition(
        self,
        tenant_id: str,
        *,
        dataset_id: str,
        topic_table_id: str | None,
        org_unit_id: str | None,
        partition_key: dict[str, Any],
        artifact_id: str,
        source_version: str,
        snapshot_at: str,
        watermark_at: str | None,
        row_count: int,
        data_hash: str,
        freshness_status: str,
        acquisition_run_id: str,
        created_by: str,
    ) -> dict[str, Any]:
        partition_code = f"dp_{uuid4().hex}"
        normalized_key = _json(partition_key)
        partition_hash = hashlib.sha256(normalized_key.encode("utf-8")).hexdigest()
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, created_by)
            dataset_key = self._dataset_id(connection, tenant_key, dataset_id)
            topic_key = self._topic_id(connection, tenant_key, topic_table_id, required=False) if topic_table_id else None
            org_key = self._org_id(connection, tenant_key, org_unit_id) if org_unit_id else None
            artifact_key = self._artifact_id(connection, tenant_key, artifact_id)
            run_key = self._run_id(connection, tenant_key, acquisition_run_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_dataset_partitions(
                        tenant_id, partition_code, dataset_id, topic_table_id, org_unit_id,
                        partition_key, partition_hash, artifact_id, source_version,
                        snapshot_at, watermark_at, row_count, data_hash, freshness_status,
                        acquisition_run_id, created_by
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s,
                        %s::timestamptz, %s::timestamptz, %s, %s, %s, %s, %s
                    ) RETURNING partition_id
                    """,
                    (
                        tenant_key, partition_code, dataset_key, topic_key, org_key, normalized_key,
                        partition_hash, artifact_key, source_version, snapshot_at, watermark_at,
                        int(row_count), data_hash, freshness_status, run_key, actor_key,
                    ),
                )
                partition_id = _value(cursor.fetchone(), "partition_id", 0)
                cursor.execute(
                    "UPDATE platform_acquisition_job_runs SET partition_id = %s, updated_at = now(), lock_version = lock_version + 1 WHERE acquisition_run_id = %s",
                    (partition_id, run_key),
                )
        return self._partition_by_code(tenant_id, partition_code)

    def save_quality_results(
        self,
        tenant_id: str,
        acquisition_run_id: str,
        results: list[dict[str, Any]],
        created_by: str,
        partition_id: str | None = None,
    ) -> None:
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, created_by)
            run_key = self._run_id(connection, tenant_key, acquisition_run_id)
            partition_key = self._partition_id(connection, tenant_key, partition_id) if partition_id else None
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT j.target_dataset_id FROM platform_acquisition_job_runs r
                    JOIN platform_acquisition_jobs j ON j.acquisition_job_id = r.acquisition_job_id
                    WHERE r.acquisition_run_id = %s
                    """,
                    (run_key,),
                )
                dataset_id = _value(cursor.fetchone(), "target_dataset_id", 0)
                for result in results:
                    rule_code = str(result["rule_code"])
                    blocking = bool(result.get("blocking"))
                    cursor.execute(
                        """
                        INSERT INTO platform_data_quality_rules(
                            tenant_id, dataset_id, rule_code, rule_name, rule_type,
                            rule_expression, severity, blocking, status, created_by
                        ) VALUES (%s, %s, %s, %s, 'custom', %s::jsonb, %s, %s, 'active', %s)
                        ON CONFLICT (tenant_id, dataset_id, rule_code) DO UPDATE SET
                            rule_expression = EXCLUDED.rule_expression,
                            severity = EXCLUDED.severity, blocking = EXCLUDED.blocking,
                            updated_at = now(), lock_version = platform_data_quality_rules.lock_version + 1
                        RETURNING quality_rule_id
                        """,
                        (
                            tenant_key, dataset_id, rule_code, rule_code,
                            _json({"threshold": result.get("threshold", {})}),
                            "error" if blocking else "warning", blocking, actor_key,
                        ),
                    )
                    rule_id = _value(cursor.fetchone(), "quality_rule_id", 0)
                    quality_key = f"qr_{uuid4().hex}"
                    cursor.execute(
                        """
                        INSERT INTO platform_data_quality_results(
                            tenant_id, quality_result_key, quality_rule_id, partition_id,
                            acquisition_run_id, status, score, observed_value, threshold,
                            evaluated_at, created_by
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, now(), %s)
                        """,
                        (
                            tenant_key, quality_key, rule_id, partition_key, run_key,
                            str(result["status"]), float(result.get("score", 0)),
                            _json(result.get("observed_value", {})), _json(result.get("threshold", {})), actor_key,
                        ),
                    )

    def list_quality_results(self, tenant_id: str, limit: int = 500) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT q.quality_result_key, t.tenant_code, rule.rule_code, q.status,
                           q.score, q.observed_value, q.threshold, rule.blocking, q.evaluated_at,
                           r.run_key AS acquisition_run_id, j.job_key AS acquisition_job_id,
                           d.dataset_code AS target_dataset_id, topic.topic_code AS topic_table_id,
                           r.source_snapshot, r.quality_summary, r.status AS run_status
                    FROM platform_data_quality_results q
                    JOIN platform_tenants t ON t.tenant_id = q.tenant_id
                    JOIN platform_data_quality_rules rule ON rule.quality_rule_id = q.quality_rule_id
                    JOIN platform_acquisition_job_runs r ON r.acquisition_run_id = q.acquisition_run_id
                    JOIN platform_acquisition_jobs j ON j.acquisition_job_id = r.acquisition_job_id
                    LEFT JOIN platform_datasets d ON d.dataset_id = j.target_dataset_id
                    LEFT JOIN platform_topic_tables topic ON topic.topic_table_id = j.topic_table_id
                    WHERE q.tenant_id = %s
                    ORDER BY q.evaluated_at DESC, q.quality_result_id DESC LIMIT %s
                    """,
                    (tenant_key, max(1, min(int(limit), 2_000))),
                )
                rows = cursor.fetchall()
        return [self._quality_from_row(row) for row in rows]

    def create_repair_proposal(
        self,
        tenant_id: str,
        *,
        acquisition_run_id: str,
        failed_script_version_id: str,
        diagnosis: dict[str, Any],
        generation_method: str,
        candidate_source_code: str | None,
        created_by: str,
    ) -> dict[str, Any]:
        if generation_method not in {"deterministic", "llm", "manual"}:
            raise ValueError("invalid_repair_generation_method")
        candidate = str(candidate_source_code or "").strip() or None
        proposal_key = f"rp_{uuid4().hex}"
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, created_by)
            run_id = self._run_id(connection, tenant_key, acquisition_run_id)
            version_id = self._script_version_id(connection, tenant_key, failed_script_version_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_acquisition_repair_proposals(
                        tenant_id, repair_proposal_key, acquisition_run_id,
                        failed_script_version_id, diagnosis, generation_method,
                        candidate_source_code, candidate_hash, review_status, created_by
                    ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, 'pending', %s)
                    """,
                    (
                        tenant_key, proposal_key, run_id, version_id, _json(diagnosis),
                        generation_method, candidate,
                        hashlib.sha256(candidate.encode("utf-8")).hexdigest() if candidate else None,
                        actor_key,
                    ),
                )
                cursor.execute(
                    "UPDATE platform_acquisition_job_runs SET status = 'repair_review', updated_at = now(), lock_version = lock_version + 1 WHERE acquisition_run_id = %s",
                    (run_id,),
                )
        return self.get_repair_proposal(tenant_id, proposal_key, reveal_candidate=False)

    def get_repair_proposal(self, tenant_id: str, proposal_id: str, reveal_candidate: bool = False) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._repair_select() + " WHERE p.tenant_id = %s AND p.repair_proposal_key = %s", (tenant_key, proposal_id))
                row = cursor.fetchone()
        if not row:
            raise KeyError("repair_proposal_not_found")
        return self._repair_from_row(row, reveal_candidate)

    def list_repair_proposals(self, tenant_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._repair_select() + " WHERE p.tenant_id = %s ORDER BY p.created_at DESC", (tenant_key,))
                rows = cursor.fetchall()
        return [self._repair_from_row(row, False) for row in rows]

    def review_repair_proposal(self, tenant_id: str, proposal_id: str, decision: str, reviewer: str) -> dict[str, Any]:
        normalized = str(decision or "").strip().lower()
        if normalized not in {"approved", "rejected"}:
            raise ValueError("invalid_repair_review_decision")
        proposal = self.get_repair_proposal(tenant_id, proposal_id, reveal_candidate=True)
        if proposal["review_status"] != "pending":
            raise ValueError("repair_proposal_is_not_pending")
        failed = self.get_script_version(tenant_id, proposal["failed_script_version_id"], reveal_source=True)
        if failed["created_by"] == reviewer:
            raise PermissionError("four_eyes_repair_review_required")
        if normalized == "approved" and not proposal.get("candidate_source_code"):
            raise ValueError("repair_candidate_source_required")
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            reviewer_key = PostgreSQLIdentityResolver.user_id(connection, reviewer)
            applied_id = None
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT repair_proposal_id, acquisition_run_id, failed_script_version_id FROM platform_acquisition_repair_proposals WHERE tenant_id = %s AND repair_proposal_key = %s FOR UPDATE",
                    (tenant_key, proposal_id),
                )
                row = cursor.fetchone()
                if normalized == "approved":
                    script_id = self._script_id_for_version(connection, _value(row, "failed_script_version_id", 2))
                    cursor.execute(
                        "SELECT COALESCE(MAX(version_no), 0) + 1 AS next_version "
                        "FROM platform_acquisition_script_versions WHERE acquisition_script_id = %s",
                        (script_id,),
                    )
                    version_no = int(_value(cursor.fetchone(), "next_version", 0))
                    applied_key = f"asv_{uuid4().hex}"
                    source_code = str(proposal["candidate_source_code"])
                    cursor.execute(
                        """
                        INSERT INTO platform_acquisition_script_versions(
                            tenant_id, script_version_key, acquisition_script_id, version_no,
                            source_code, source_hash, dependency_lock, input_schema, output_schema,
                            review_status, reviewed_by, reviewed_at, created_by
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
                                  'approved', %s, now(), %s)
                        RETURNING script_version_id
                        """,
                        (
                            tenant_key, applied_key, script_id, version_no, source_code,
                            hashlib.sha256(source_code.encode("utf-8")).hexdigest(),
                            _json(failed.get("dependency_lock", {})), _json(failed.get("input_schema", {})),
                            _json(failed.get("output_schema", {})), reviewer_key, reviewer_key,
                        ),
                    )
                    applied_id = _value(cursor.fetchone(), "script_version_id", 0)
                    cursor.execute("UPDATE platform_acquisition_scripts SET current_version_no = %s, status = 'active', updated_at = now(), lock_version = lock_version + 1 WHERE acquisition_script_id = %s", (version_no, script_id))
                    cursor.execute(
                        """
                        UPDATE platform_acquisition_jobs j SET script_version_id = %s, updated_at = now(), lock_version = lock_version + 1
                        FROM platform_acquisition_job_runs r
                        WHERE r.acquisition_job_id = j.acquisition_job_id AND r.acquisition_run_id = %s
                        """,
                        (applied_id, _value(row, "acquisition_run_id", 1)),
                    )
                cursor.execute(
                    """
                    UPDATE platform_acquisition_repair_proposals
                    SET review_status = %s, reviewed_by = %s, reviewed_at = now(),
                        applied_script_version_id = %s, updated_at = now(), lock_version = lock_version + 1
                    WHERE repair_proposal_id = %s
                    """,
                    ("applied" if normalized == "approved" else "rejected", reviewer_key, applied_id, _value(row, "repair_proposal_id", 0)),
                )
        return self.get_repair_proposal(tenant_id, proposal_id, reveal_candidate=False)

    def enqueue_outbox_event(
        self,
        tenant_id: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        event_key = f"oe_{uuid4().hex}"
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_outbox_events(
                        tenant_id, outbox_event_key, aggregate_type, aggregate_id,
                        event_type, payload, status, available_at
                    ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, 'pending', now())
                    """,
                    (tenant_key, event_key, aggregate_type, aggregate_id, event_type, _json(payload)),
                )
        return {"outbox_event_id": event_key, "event_type": event_type, "status": "pending"}

    def enqueue_outbox_event_once(
        self,
        tenant_id: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT outbox_event_key, event_type, status FROM platform_outbox_events
                    WHERE tenant_id = %s AND aggregate_type = %s AND aggregate_id = %s AND event_type = %s
                    ORDER BY created_at LIMIT 1
                    """,
                    (tenant_key, aggregate_type, aggregate_id, event_type),
                )
                row = cursor.fetchone()
        if row:
            return {
                "outbox_event_id": str(_value(row, "outbox_event_key", 0)),
                "event_type": str(_value(row, "event_type", 1)),
                "status": str(_value(row, "status", 2)),
            }
        return self.enqueue_outbox_event(tenant_id, aggregate_type, aggregate_id, event_type, payload)

    def latest_artifact(self, tenant_id: str, topic_table_id: str, org_unit_id: str | None) -> dict[str, Any]:
        if not topic_table_id:
            raise ValueError("topic_table_id_required")
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            topic_id = self._topic_id(connection, tenant_key, topic_table_id)
            org_id = self._org_id(connection, tenant_key, org_unit_id) if org_unit_id else None
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT p.partition_code, d.dataset_code, topic.topic_code,
                           org.org_code, p.partition_key, p.partition_hash,
                           a.artifact_key, p.source_version, p.snapshot_at, p.watermark_at,
                           p.row_count, p.data_hash, p.freshness_status,
                           a.object_uri, a.content_hash, a.content_type, a.size_bytes,
                           a.status AS artifact_status
                    FROM platform_dataset_partitions p
                    JOIN platform_datasets d ON d.dataset_id = p.dataset_id
                    JOIN platform_topic_tables topic ON topic.topic_table_id = p.topic_table_id
                    LEFT JOIN platform_org_units org ON org.org_unit_id = p.org_unit_id
                    JOIN platform_data_artifacts a ON a.artifact_id = p.artifact_id
                    WHERE p.tenant_id = %s AND p.topic_table_id = %s
                      AND p.org_unit_id IS NOT DISTINCT FROM %s
                      AND p.freshness_status = 'fresh' AND a.status = 'active'
                    ORDER BY p.snapshot_at DESC, p.created_at DESC LIMIT 1
                    """,
                    (tenant_key, topic_id, org_id),
                )
                row = cursor.fetchone()
        if not row:
            raise KeyError("latest_topic_table_artifact_not_found")
        return self._partition_result(row)

    def get_topic_definition(self, tenant_id: str, topic_table_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT topic_table_id, topic_code, topic_name, description,
                           current_version_no, query_template, query_hash, status,
                           validated_at, updated_at
                    FROM platform_topic_tables
                    WHERE tenant_id = %s AND (topic_table_id::text = %s OR topic_code = %s)
                    LIMIT 1
                    """,
                    (tenant_key, topic_table_id, topic_table_id),
                )
                row = cursor.fetchone()
        if not row:
            raise KeyError("topic_table_not_found")
        return {
            "id": str(_value(row, "topic_table_id", 0)),
            "code": str(_value(row, "topic_code", 1)),
            "name": str(_value(row, "topic_name", 2)),
            "description": str(_value(row, "description", 3) or ""),
            "version": int(_value(row, "current_version_no", 4)),
            "sql": str(_value(row, "query_template", 5)),
            "query_hash": str(_value(row, "query_hash", 6)),
            "status": str(_value(row, "status", 7)),
            "validated_at": _iso(_value(row, "validated_at", 8)),
            "updated_at": _iso(_value(row, "updated_at", 9)),
        }

    def upsert_topic_metadata(
        self,
        tenant_id: str,
        *,
        topic: dict[str, Any],
        connection_id: str,
        decomposition: dict[str, Any],
        tables: list[dict[str, Any]],
        actor_user_id: str,
    ) -> dict[str, Any]:
        changed: list[str] = []
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, actor_user_id, required=False)
            connection_key = self._connection_id(connection, tenant_key, connection_id)
            topic_key = self._topic_id(connection, tenant_key, str(topic.get("code") or topic.get("id") or ""))
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM platform_topic_table_sources WHERE topic_table_id = %s", (topic_key,))
                for position, table in enumerate(tables):
                    dataset_code = str(table.get("qualified_name") or table.get("table") or "").strip()
                    schema_hash = str(table.get("schema_hash") or hashlib.sha256(_json(table.get("fields", [])).encode()).hexdigest())
                    cursor.execute(
                        "SELECT dataset_id, schema_hash FROM platform_datasets WHERE tenant_id = %s AND dataset_code = %s",
                        (tenant_key, dataset_code),
                    )
                    existing = cursor.fetchone()
                    if existing and str(_value(existing, "schema_hash", 1) or "") not in {"", schema_hash}:
                        changed.append(dataset_code)
                    cursor.execute(
                        """
                        INSERT INTO platform_datasets(
                            tenant_id, connection_id, dataset_code, dataset_name,
                            physical_locator, dataset_type, status, schema_hash, created_by
                        ) VALUES (%s, %s, %s, %s, %s::jsonb, 'table', 'active', %s, %s)
                        ON CONFLICT (tenant_id, dataset_code) DO UPDATE SET
                            connection_id = EXCLUDED.connection_id,
                            dataset_name = EXCLUDED.dataset_name,
                            physical_locator = EXCLUDED.physical_locator,
                            status = 'active', schema_hash = EXCLUDED.schema_hash,
                            updated_at = now(), lock_version = platform_datasets.lock_version + 1
                        RETURNING dataset_id
                        """,
                        (
                            tenant_key, connection_key, dataset_code,
                            str(table.get("table") or dataset_code),
                            _json({key: table.get(key) for key in ("catalog", "schema", "table", "qualified_name")}),
                            schema_hash, actor_key,
                        ),
                    )
                    dataset_key = _value(cursor.fetchone(), "dataset_id", 0)
                    cursor.execute("DELETE FROM platform_dataset_fields WHERE dataset_id = %s", (dataset_key,))
                    for field_position, field in enumerate(table.get("fields") or (), start=1):
                        field_code = str(field.get("field_code") or field.get("name") or "").strip()
                        if not field_code:
                            continue
                        metadata = {
                            "comment": field.get("comment") or "",
                            "business_description": field.get("business_description") or "",
                            "length": field.get("length"),
                            "sample_value_masked": field.get("sample_value_masked") or "",
                            "metadata_source": field.get("metadata_source") or "sql_inferred",
                            "metadata_version": decomposition.get("query_hash"),
                        }
                        cursor.execute(
                            """
                            INSERT INTO platform_dataset_fields(
                                tenant_id, dataset_id, field_code, field_name,
                                ordinal_position, physical_type, semantic_type, is_nullable,
                                is_dimension, is_measure, metadata, created_by
                            ) VALUES (%s, %s, %s, %s, %s, %s, NULLIF(%s, ''), %s, %s, %s, %s::jsonb, %s)
                            """,
                            (
                                tenant_key, dataset_key, field_code,
                                str(field.get("field_name") or field_code), field_position,
                                str(field.get("physical_type") or "unknown"),
                                str(field.get("semantic_type") or ""),
                                bool(field.get("is_nullable", True)),
                                bool(field.get("is_dimension", True)),
                                bool(field.get("is_measure", False)),
                                _json(metadata), actor_key,
                            ),
                        )
                    cursor.execute(
                        """
                        INSERT INTO platform_topic_table_sources(topic_table_id, dataset_id, source_alias, join_role)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (
                            topic_key, dataset_key,
                            str(table.get("alias") or table.get("table") or dataset_code),
                            "primary" if position == 0 else "lookup",
                        ),
                    )
                cursor.execute(
                    "UPDATE platform_topic_tables SET validated_at = now(), updated_at = now(), lock_version = lock_version + 1 WHERE topic_table_id = %s",
                    (topic_key,),
                )
        return {"topic_table_id": str(topic_key), "schema_changed_tables": changed, "table_count": len(tables), "synced_at": _utcnow()}

    def metadata_status(self, tenant_id: str, topic_table_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            try:
                topic_key = self._topic_id(connection, tenant_key, topic_table_id)
            except KeyError:
                return {"topic_table_id": topic_table_id, "status": "not_fetched", "last_synced_at": None, "raw_tables": [], "schema_changed": False}
            with connection.cursor() as cursor:
                cursor.execute("SELECT validated_at FROM platform_topic_tables WHERE topic_table_id = %s", (topic_key,))
                topic_row = cursor.fetchone()
                cursor.execute(
                    """
                    SELECT d.dataset_code, d.dataset_name, d.schema_hash, d.updated_at,
                           s.source_alias, s.join_role, COUNT(f.field_id) AS field_count,
                           SUM(CASE WHEN f.physical_type = 'unknown' THEN 1 ELSE 0 END) AS unknown_field_count
                    FROM platform_topic_table_sources s
                    JOIN platform_datasets d ON d.dataset_id = s.dataset_id
                    LEFT JOIN platform_dataset_fields f ON f.dataset_id = d.dataset_id
                    WHERE s.topic_table_id = %s
                    GROUP BY d.dataset_id, d.dataset_code, d.dataset_name, d.schema_hash,
                             d.updated_at, s.source_alias, s.join_role
                    ORDER BY s.join_role, d.dataset_code
                    """,
                    (topic_key,),
                )
                rows = cursor.fetchall()
        raw_tables = [
            {
                "dataset_code": str(_value(row, "dataset_code", 0)),
                "dataset_name": str(_value(row, "dataset_name", 1)),
                "schema_hash": str(_value(row, "schema_hash", 2) or ""),
                "updated_at": _iso(_value(row, "updated_at", 3)),
                "source_alias": str(_value(row, "source_alias", 4)),
                "join_role": str(_value(row, "join_role", 5)),
                "field_count": int(_value(row, "field_count", 6)),
                "unknown_field_count": int(_value(row, "unknown_field_count", 7) or 0),
            }
            for row in rows
        ]
        status = "complete" if raw_tables and all(item["field_count"] > 0 and item["unknown_field_count"] == 0 for item in raw_tables) else "partial" if raw_tables else "not_fetched"
        return {
            "topic_table_id": topic_table_id,
            "status": status,
            "last_synced_at": _iso(_value(topic_row, "validated_at", 0)) if topic_row else None,
            "raw_tables": raw_tables,
            "schema_changed": False,
        }

    def list_execution_logs(self, tenant_id: str, topic_table_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            topic_key = self._topic_id(connection, tenant_key, topic_table_id) if topic_table_id else None
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT r.run_key, j.job_key, topic.topic_code, r.status,
                           r.started_at, r.finished_at, r.rows_read,
                           r.error_code, r.error_summary, r.source_snapshot
                    FROM platform_acquisition_job_runs r
                    JOIN platform_acquisition_jobs j ON j.acquisition_job_id = r.acquisition_job_id
                    LEFT JOIN platform_topic_tables topic ON topic.topic_table_id = j.topic_table_id
                    WHERE r.tenant_id = %s AND (%s::uuid IS NULL OR j.topic_table_id = %s::uuid)
                    ORDER BY r.created_at DESC LIMIT %s
                    """,
                    (tenant_key, topic_key, topic_key, max(1, min(int(limit), 200))),
                )
                rows = cursor.fetchall()
        return [
            {
                "acquisition_run_id": str(_value(row, "run_key", 0)),
                "acquisition_job_id": str(_value(row, "job_key", 1)),
                "topic_table_id": str(_value(row, "topic_code", 2) or ""),
                "status": str(_value(row, "status", 3)),
                "started_at": _iso(_value(row, "started_at", 4)),
                "finished_at": _iso(_value(row, "finished_at", 5)),
                "rows_read": int(_value(row, "rows_read", 6)),
                "error_code": str(_value(row, "error_code", 7) or ""),
                "error_summary": str(_value(row, "error_summary", 8) or ""),
                "source_snapshot": _json_value(_value(row, "source_snapshot", 9), {}),
            }
            for row in rows
        ]

    def expire_old_partitions(
        self,
        tenant_id: str,
        *,
        topic_table_id: str,
        org_unit_id: str | None,
        keep_latest_n: int,
    ) -> dict[str, Any]:
        limit = max(1, min(int(keep_latest_n), 30))
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            topic_id = self._topic_id(connection, tenant_key, topic_table_id)
            org_id = self._org_id(connection, tenant_key, org_unit_id) if org_unit_id else None
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    WITH ranked AS (
                        SELECT partition_id,
                               row_number() OVER (ORDER BY snapshot_at DESC, created_at DESC) AS position
                        FROM platform_dataset_partitions
                        WHERE tenant_id = %s AND topic_table_id = %s
                          AND org_unit_id IS NOT DISTINCT FROM %s
                          AND freshness_status = 'fresh'
                    )
                    UPDATE platform_dataset_partitions p
                    SET freshness_status = 'stale', updated_at = now(), lock_version = lock_version + 1
                    FROM ranked r
                    WHERE p.partition_id = r.partition_id AND r.position > %s
                    """,
                    (tenant_key, topic_id, org_id, limit),
                )
                expired = cursor.rowcount
        return {"keep_latest_n": limit, "expired_partitions": expired, "retained_object_artifacts": True}

    def bundle(self, tenant_id: str) -> dict[str, Any]:
        return {
            "sources": self.list_sources(tenant_id),
            "script_versions": self.list_scripts(tenant_id),
            "jobs": self.list_jobs(tenant_id),
            "runs": self.list_runs(tenant_id),
            "repair_proposals": self.list_repair_proposals(tenant_id),
            "quality_results": self.list_quality_results(tenant_id),
        }

    @staticmethod
    def _source_select() -> str:
        return """
            SELECT s.source_system_key, t.tenant_code, s.source_code, s.source_name,
                   s.source_category, s.license_metadata, s.status,
                   u.external_subject AS created_by, s.created_at, s.updated_at
            FROM platform_source_systems s JOIN platform_tenants t ON t.tenant_id = s.tenant_id
            LEFT JOIN platform_user_profiles u ON u.user_id = s.created_by
        """

    @staticmethod
    def _source_from_row(row: Any) -> dict[str, Any]:
        keys = ("source_system_id", "tenant_id", "source_code", "source_name", "source_category", "license_metadata", "status", "created_by", "created_at", "updated_at")
        db_keys = ("source_system_key", "tenant_code", "source_code", "source_name", "source_category", "license_metadata", "status", "created_by", "created_at", "updated_at")
        result = _row_dict(row, keys, db_keys)
        result["license_metadata"] = _json_value(result["license_metadata"], {})
        return result

    @staticmethod
    def _script_select() -> str:
        return """
            SELECT v.script_version_key, t.tenant_code, s.script_key AS acquisition_script_id,
                   v.version_no, v.source_code, v.source_hash, v.dependency_lock,
                   v.input_schema, v.output_schema, v.review_status,
                   reviewer.external_subject AS reviewed_by, v.reviewed_at,
                   creator.external_subject AS created_by, v.created_at,
                   s.script_code, s.script_name, s.runtime,
                   owner.external_subject AS owner_user_id, s.status AS script_status
            FROM platform_acquisition_script_versions v
            JOIN platform_acquisition_scripts s ON s.acquisition_script_id = v.acquisition_script_id
            JOIN platform_tenants t ON t.tenant_id = v.tenant_id
            LEFT JOIN platform_user_profiles reviewer ON reviewer.user_id = v.reviewed_by
            LEFT JOIN platform_user_profiles creator ON creator.user_id = v.created_by
            LEFT JOIN platform_user_profiles owner ON owner.user_id = s.owner_user_id
        """

    @staticmethod
    def _script_from_row(row: Any, reveal_source: bool) -> dict[str, Any]:
        keys = (
            "script_version_id", "tenant_id", "acquisition_script_id", "version_no",
            "source_code", "source_hash", "dependency_lock", "input_schema", "output_schema",
            "review_status", "reviewed_by", "reviewed_at", "created_by", "created_at",
            "script_code", "script_name", "runtime", "owner_user_id", "script_status",
        )
        db_keys = (
            "script_version_key", "tenant_code", "acquisition_script_id", "version_no",
            "source_code", "source_hash", "dependency_lock", "input_schema", "output_schema",
            "review_status", "reviewed_by", "reviewed_at", "created_by", "created_at",
            "script_code", "script_name", "runtime", "owner_user_id", "script_status",
        )
        result = _row_dict(row, keys, db_keys)
        for key in ("dependency_lock", "input_schema", "output_schema"):
            result[key] = _json_value(result[key], {})
        if not reveal_source:
            result.pop("source_code", None)
        return result

    @staticmethod
    def _job_select() -> str:
        return """
            SELECT j.job_key, t.tenant_code, j.job_code, j.job_name,
                   source.source_system_key AS source_system_id,
                   version.script_version_key AS script_version_id,
                   connection.connection_code AS connection_id,
                   dataset.dataset_code AS target_dataset_id,
                   topic.topic_code AS topic_table_id,
                   j.trigger_type, j.schedule_expression, j.execution_mode,
                   j.job_config, j.status, owner.external_subject AS owner_user_id,
                   creator.external_subject AS created_by, j.created_at, j.updated_at
            FROM platform_acquisition_jobs j
            JOIN platform_tenants t ON t.tenant_id = j.tenant_id
            JOIN platform_source_systems source ON source.source_system_id = j.source_system_id
            JOIN platform_acquisition_script_versions version ON version.script_version_id = j.script_version_id
            JOIN platform_data_connections connection ON connection.connection_id = j.connection_id
            LEFT JOIN platform_datasets dataset ON dataset.dataset_id = j.target_dataset_id
            LEFT JOIN platform_topic_tables topic ON topic.topic_table_id = j.topic_table_id
            JOIN platform_user_profiles owner ON owner.user_id = j.owner_user_id
            LEFT JOIN platform_user_profiles creator ON creator.user_id = j.created_by
        """

    @staticmethod
    def _job_from_row(row: Any) -> dict[str, Any]:
        keys = ("acquisition_job_id", "tenant_id", "job_code", "job_name", "source_system_id", "script_version_id", "connection_id", "target_dataset_id", "topic_table_id", "trigger_type", "schedule_expression", "execution_mode", "job_config", "status", "owner_user_id", "created_by", "created_at", "updated_at")
        db_keys = ("job_key", "tenant_code", "job_code", "job_name", "source_system_id", "script_version_id", "connection_id", "target_dataset_id", "topic_table_id", "trigger_type", "schedule_expression", "execution_mode", "job_config", "status", "owner_user_id", "created_by", "created_at", "updated_at")
        result = _row_dict(row, keys, db_keys)
        result["job_config"] = _json_value(result["job_config"], {})
        return result

    @staticmethod
    def _run_select() -> str:
        return """
            SELECT r.run_key, t.tenant_code, j.job_key AS acquisition_job_id,
                   r.trigger_type, r.idempotency_key, r.status, r.attempt_no,
                   r.lease_owner, r.lease_expires_at, r.input_cursor, r.output_cursor,
                   r.rows_read, r.rows_written, r.source_snapshot, r.quality_summary,
                   artifact.artifact_key AS output_artifact_id,
                   partition.partition_code AS partition_id,
                   r.started_at, r.finished_at, r.error_code, r.error_summary,
                   creator.external_subject AS created_by, r.created_at, r.updated_at
            FROM platform_acquisition_job_runs r
            JOIN platform_tenants t ON t.tenant_id = r.tenant_id
            JOIN platform_acquisition_jobs j ON j.acquisition_job_id = r.acquisition_job_id
            LEFT JOIN platform_data_artifacts artifact ON artifact.artifact_id = r.output_artifact_id
            LEFT JOIN platform_dataset_partitions partition ON partition.partition_id = r.partition_id
            LEFT JOIN platform_user_profiles creator ON creator.user_id = r.created_by
        """

    @staticmethod
    def _run_from_row(row: Any) -> dict[str, Any]:
        keys = ("acquisition_run_id", "tenant_id", "acquisition_job_id", "trigger_type", "idempotency_key", "status", "attempt_no", "lease_owner", "lease_expires_at", "input_cursor", "output_cursor", "rows_read", "rows_written", "source_snapshot", "quality_summary", "output_artifact_id", "partition_id", "started_at", "finished_at", "error_code", "error_summary", "created_by", "created_at", "updated_at")
        db_keys = ("run_key", "tenant_code", "acquisition_job_id", "trigger_type", "idempotency_key", "status", "attempt_no", "lease_owner", "lease_expires_at", "input_cursor", "output_cursor", "rows_read", "rows_written", "source_snapshot", "quality_summary", "output_artifact_id", "partition_id", "started_at", "finished_at", "error_code", "error_summary", "created_by", "created_at", "updated_at")
        result = _row_dict(row, keys, db_keys)
        for key in ("input_cursor", "output_cursor", "source_snapshot", "quality_summary"):
            result[key] = _json_value(result[key], {})
        return result

    @staticmethod
    def _repair_select() -> str:
        return """
            SELECT p.repair_proposal_key, t.tenant_code, r.run_key AS acquisition_run_id,
                   failed.script_version_key AS failed_script_version_id,
                   p.diagnosis, p.generation_method, p.candidate_source_code,
                   p.candidate_hash, p.review_status,
                   reviewer.external_subject AS reviewed_by, p.reviewed_at,
                   applied.script_version_key AS applied_script_version_id,
                   creator.external_subject AS created_by, p.created_at, p.updated_at
            FROM platform_acquisition_repair_proposals p
            JOIN platform_tenants t ON t.tenant_id = p.tenant_id
            JOIN platform_acquisition_job_runs r ON r.acquisition_run_id = p.acquisition_run_id
            JOIN platform_acquisition_script_versions failed ON failed.script_version_id = p.failed_script_version_id
            LEFT JOIN platform_acquisition_script_versions applied ON applied.script_version_id = p.applied_script_version_id
            LEFT JOIN platform_user_profiles reviewer ON reviewer.user_id = p.reviewed_by
            LEFT JOIN platform_user_profiles creator ON creator.user_id = p.created_by
        """

    @staticmethod
    def _repair_from_row(row: Any, reveal_candidate: bool) -> dict[str, Any]:
        keys = ("repair_proposal_id", "tenant_id", "acquisition_run_id", "failed_script_version_id", "diagnosis", "generation_method", "candidate_source_code", "candidate_hash", "review_status", "reviewed_by", "reviewed_at", "applied_script_version_id", "created_by", "created_at", "updated_at")
        db_keys = ("repair_proposal_key", "tenant_code", "acquisition_run_id", "failed_script_version_id", "diagnosis", "generation_method", "candidate_source_code", "candidate_hash", "review_status", "reviewed_by", "reviewed_at", "applied_script_version_id", "created_by", "created_at", "updated_at")
        result = _row_dict(row, keys, db_keys)
        result["diagnosis"] = _json_value(result["diagnosis"], {})
        if not reveal_candidate:
            result.pop("candidate_source_code", None)
        return result

    @staticmethod
    def _quality_from_row(row: Any) -> dict[str, Any]:
        keys = ("quality_result_id", "tenant_id", "rule_code", "status", "score", "observed_value", "threshold_value", "blocking", "evaluated_at", "acquisition_run_id", "acquisition_job_id", "target_dataset_id", "topic_table_id", "source_snapshot", "quality_summary", "run_status")
        db_keys = ("quality_result_key", "tenant_code", "rule_code", "status", "score", "observed_value", "threshold", "blocking", "evaluated_at", "acquisition_run_id", "acquisition_job_id", "target_dataset_id", "topic_table_id", "source_snapshot", "quality_summary", "run_status")
        result = _row_dict(row, keys, db_keys)
        for key in ("observed_value", "threshold_value", "source_snapshot", "quality_summary"):
            result[key] = _json_value(result[key], {})
        result["blocking"] = bool(result["blocking"])
        return result

    def _partition_by_code(self, tenant_id: str, code: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT p.partition_code, d.dataset_code, topic.topic_code,
                           org.org_code, p.partition_key, p.partition_hash,
                           a.artifact_key, p.source_version, p.snapshot_at, p.watermark_at,
                           p.row_count, p.data_hash, p.freshness_status,
                           a.object_uri, a.content_hash, a.content_type, a.size_bytes,
                           a.status AS artifact_status
                    FROM platform_dataset_partitions p
                    JOIN platform_datasets d ON d.dataset_id = p.dataset_id
                    LEFT JOIN platform_topic_tables topic ON topic.topic_table_id = p.topic_table_id
                    LEFT JOIN platform_org_units org ON org.org_unit_id = p.org_unit_id
                    JOIN platform_data_artifacts a ON a.artifact_id = p.artifact_id
                    WHERE p.tenant_id = %s AND p.partition_code = %s
                    """,
                    (tenant_key, code),
                )
                row = cursor.fetchone()
        if not row:
            raise KeyError("dataset_partition_not_found")
        return self._partition_result(row)

    @staticmethod
    def _partition_result(row: Any) -> dict[str, Any]:
        keys = ("partition_id", "dataset_id", "topic_table_id", "org_unit_id", "partition_key", "partition_hash", "artifact_id", "source_version", "snapshot_at", "watermark_at", "row_count", "data_hash", "freshness_status", "object_uri", "content_hash", "content_type", "size_bytes", "artifact_status")
        db_keys = ("partition_code", "dataset_code", "topic_code", "org_code", "partition_key", "partition_hash", "artifact_key", "source_version", "snapshot_at", "watermark_at", "row_count", "data_hash", "freshness_status", "object_uri", "content_hash", "content_type", "size_bytes", "artifact_status")
        result = _row_dict(row, keys, db_keys)
        result["partition_key"] = _json_value(result["partition_key"], {})
        return result

    @staticmethod
    def _source_id(connection: Any, tenant_id: Any, key: str) -> Any:
        return _lookup(connection, "platform_source_systems", "source_system_id", "source_system_key", tenant_id, key, "source_system_not_found")

    @staticmethod
    def _script_version_id(connection: Any, tenant_id: Any, key: str) -> Any:
        return _lookup(connection, "platform_acquisition_script_versions", "script_version_id", "script_version_key", tenant_id, key, "script_version_not_found")

    @staticmethod
    def _connection_id(connection: Any, tenant_id: Any, key: str) -> Any:
        return _lookup(connection, "platform_data_connections", "connection_id", "connection_code", tenant_id, key, "data_connection_not_found")

    @staticmethod
    def _dataset_id(connection: Any, tenant_id: Any, key: str) -> Any:
        return _lookup(connection, "platform_datasets", "dataset_id", "dataset_code", tenant_id, key, "dataset_not_found")

    @staticmethod
    def _job_id(connection: Any, tenant_id: Any, key: str) -> Any:
        return _lookup(connection, "platform_acquisition_jobs", "acquisition_job_id", "job_key", tenant_id, key, "acquisition_job_not_found")

    @staticmethod
    def _run_id(connection: Any, tenant_id: Any, key: str) -> Any:
        return _lookup(connection, "platform_acquisition_job_runs", "acquisition_run_id", "run_key", tenant_id, key, "acquisition_run_not_found")

    @staticmethod
    def _artifact_id(connection: Any, tenant_id: Any, key: str) -> Any:
        return _lookup(connection, "platform_data_artifacts", "artifact_id", "artifact_key", tenant_id, key, "data_artifact_not_found")

    @staticmethod
    def _partition_id(connection: Any, tenant_id: Any, key: str) -> Any:
        return _lookup(connection, "platform_dataset_partitions", "partition_id", "partition_code", tenant_id, key, "dataset_partition_not_found")

    @staticmethod
    def _topic_id(connection: Any, tenant_id: Any, key: str | None, required: bool = True) -> Any | None:
        if not key:
            return None
        try:
            return _lookup(connection, "platform_topic_tables", "topic_table_id", "topic_code", tenant_id, key, "topic_table_not_found")
        except KeyError:
            if required:
                raise
            return None

    @staticmethod
    def _org_id(connection: Any, tenant_id: Any, key: str) -> Any:
        return _lookup(connection, "platform_org_units", "org_unit_id", "org_code", tenant_id, key, "org_unit_not_found")

    @staticmethod
    def _script_id_for_version(connection: Any, version_id: Any) -> Any:
        with connection.cursor() as cursor:
            cursor.execute("SELECT acquisition_script_id FROM platform_acquisition_script_versions WHERE script_version_id = %s", (version_id,))
            row = cursor.fetchone()
        if not row:
            raise KeyError("script_version_not_found")
        return _value(row, "acquisition_script_id", 0)

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with self.pool.connection() as connection:
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise


def _lookup(connection: Any, table: str, id_field: str, key_field: str, tenant_id: Any, key: str, error: str) -> Any:
    allowed = {
        ("platform_source_systems", "source_system_id", "source_system_key"),
        ("platform_acquisition_script_versions", "script_version_id", "script_version_key"),
        ("platform_data_connections", "connection_id", "connection_code"),
        ("platform_datasets", "dataset_id", "dataset_code"),
        ("platform_acquisition_jobs", "acquisition_job_id", "job_key"),
        ("platform_acquisition_job_runs", "acquisition_run_id", "run_key"),
        ("platform_data_artifacts", "artifact_id", "artifact_key"),
        ("platform_dataset_partitions", "partition_id", "partition_code"),
        ("platform_topic_tables", "topic_table_id", "topic_code"),
        ("platform_org_units", "org_unit_id", "org_code"),
    }
    if (table, id_field, key_field) not in allowed:
        raise ValueError("unsafe_lookup_target")
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {id_field} FROM {table} WHERE tenant_id = %s AND {key_field} = %s", (tenant_id, key))
        row = cursor.fetchone()
    if not row:
        raise KeyError(error)
    return _value(row, id_field, 0)


def _row_dict(row: Any, keys: tuple[str, ...], db_keys: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for index, (key, db_key) in enumerate(zip(keys, db_keys)):
        value = _value(row, db_key, index)
        result[key] = value.isoformat() if isinstance(value, datetime) else value
    return result


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value) if isinstance(value, str) else value


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value or "")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]
