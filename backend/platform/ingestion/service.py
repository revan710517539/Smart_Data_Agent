from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.platform.data_access import HTTPJSONSourceClient
from backend.platform.crawler_engine import (
    CrawlerEngine,
    CrawlerExecutionError,
    CrawlerOperation,
    CrawlerRequest,
    build_crawler_url_identity,
    infer_crawler_mode,
)
from backend.platform.security.sql_validation import validate_read_only_sql_candidate

from .artifacts import LocalArtifactObjectStore
from .sandbox import RestrictedRowTransformSandbox
from .repair import ModelAcquisitionRepairGenerator


class DataAcquisitionService:
    """Governed source -> version -> job -> run -> quality -> artifact pipeline."""

    max_rows = 50_000
    max_raw_file_bytes = 8 * 1024 * 1024

    def __init__(
        self,
        store: Any,
        object_store: LocalArtifactObjectStore,
        system_config_store: Any,
        model_call_repository: Any | None = None,
        crawler_engine: CrawlerEngine | None = None,
        data_asset_store: Any | None = None,
    ) -> None:
        self.store = store
        self.object_store = object_store
        self.system_config_store = system_config_store
        self.model_call_repository = model_call_repository
        self.transform_sandbox = RestrictedRowTransformSandbox()
        self.repair_generator = ModelAcquisitionRepairGenerator(system_config_store, self.transform_sandbox)
        self.crawler_engine = crawler_engine or CrawlerEngine()
        self.data_asset_store = data_asset_store
        self.automation_runtime: Any | None = None

    def close(self) -> None:
        self.object_store.close()

    def _integer_param(self, tenant_id: str, param_id: str, default: int, minimum: int, maximum: int) -> int:
        getter = getattr(self.system_config_store, "get_system_param_value", None)
        if not callable(getter):
            return default
        try:
            return max(minimum, min(int(getter(tenant_id, param_id)), maximum))
        except (KeyError, TypeError, ValueError):
            return default

    def create_source(self, tenant_id: str, payload: dict[str, Any], actor_user_id: str) -> dict[str, Any]:
        return self.store.create_source(tenant_id, payload, actor_user_id)

    def create_script_version(self, tenant_id: str, payload: dict[str, Any], actor_user_id: str) -> dict[str, Any]:
        return self.store.create_script_version(tenant_id, payload, actor_user_id)

    def review_script_version(
        self,
        tenant_id: str,
        script_version_id: str,
        decision: str,
        actor_user_id: str,
    ) -> dict[str, Any]:
        return self.store.review_script_version(tenant_id, script_version_id, decision, actor_user_id)

    def create_job(self, tenant_id: str, payload: dict[str, Any], actor_user_id: str) -> dict[str, Any]:
        connection_id = str(payload.get("connection_id", payload.get("connectionId")) or "").strip()
        connection = self._verified_connection(tenant_id, connection_id)
        target_dataset = str(payload.get("target_dataset_id", payload.get("targetDatasetId")) or "").strip()
        configured_dataset = str(connection.get("dataset") or "").strip()
        if configured_dataset and target_dataset != configured_dataset:
            raise ValueError("job_dataset_does_not_match_verified_connection")
        return self.store.create_job(tenant_id, payload, actor_user_id)

    def validate_scheduled_task(
        self,
        tenant_id: str,
        acquisition_job_id: str,
        *,
        topic_table_id: str | None = None,
        connection_id: str | None = None,
    ) -> dict[str, Any]:
        job = self.store.get_job(tenant_id, acquisition_job_id)
        if job.get("status") != "active" or job.get("execution_mode") != "offline":
            raise ValueError("active_offline_acquisition_job_required")
        if topic_table_id and str(job.get("topic_table_id") or "") != topic_table_id:
            raise ValueError("scheduled_task_topic_table_mismatch")
        if connection_id and str(job.get("connection_id") or "") != connection_id:
            raise ValueError("scheduled_task_connection_mismatch")
        self._verified_connection(tenant_id, str(job.get("connection_id") or ""))
        version = self.store.get_script_version(tenant_id, str(job.get("script_version_id") or ""), reveal_source=False)
        if version.get("review_status") != "approved":
            raise ValueError("approved_script_version_required")
        return job

    def run_job(
        self,
        tenant_id: str,
        acquisition_job_id: str,
        actor_user_id: str,
        idempotency_key: str,
        *,
        org_unit_id: str | None = None,
        input_cursor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job = self.store.get_job(tenant_id, acquisition_job_id)
        if job["status"] != "active":
            raise ValueError("acquisition_job_is_not_active")
        run = self.store.queue_run(
            tenant_id,
            acquisition_job_id,
            idempotency_key,
            "manual",
            actor_user_id,
            input_cursor,
        )
        if run["status"] in {"succeeded", "repair_review", "failed", "cancelled"}:
            return run
        run_id = str(run["acquisition_run_id"])
        version = self.store.get_script_version(tenant_id, job["script_version_id"], reveal_source=True)
        self.store.update_run(tenant_id, run_id, status="running", started_at=_utcnow())
        try:
            connection = self._verified_connection(tenant_id, job["connection_id"])
            rows, source_snapshot, provider_cursor = self._execute(
                tenant_id,
                actor_user_id,
                org_unit_id,
                job,
                version,
                connection,
                input_cursor or {},
            )
            quality_config = dict(job["job_config"])
            quality_config.setdefault(
                "freshness_sla_seconds",
                self._integer_param(
                    tenant_id,
                    "acquisition_freshness_sla_seconds",
                    86_400,
                    60,
                    31_536_000,
                ),
            )
            quality_results, quality_summary = _evaluate_quality(rows, source_snapshot, quality_config)
            blocked = bool(quality_summary["blocked"])
            csv_bytes = _rows_to_csv(rows)
            stored_object = self.object_store.put(tenant_id, csv_bytes, ".csv")
            artifact = self.store.create_artifact(
                tenant_id,
                object_uri=stored_object.object_uri,
                content_hash=stored_object.content_hash,
                content_type="text/csv; charset=utf-8",
                size_bytes=stored_object.size_bytes,
                status="quarantined" if blocked else "active",
                created_by=actor_user_id,
            )
            self.store.save_quality_results(tenant_id, run_id, quality_results, actor_user_id)
            if blocked:
                raise AcquisitionQualityGateError(quality_summary, str(artifact["artifact_id"]), len(rows), source_snapshot)
            partition_key = {
                "topic_table_id": job.get("topic_table_id"),
                "org_unit_id": org_unit_id,
                "source_snapshot_id": source_snapshot["snapshot_id"],
            }
            partition = self.store.create_partition(
                tenant_id,
                dataset_id=job["target_dataset_id"],
                topic_table_id=job.get("topic_table_id"),
                org_unit_id=org_unit_id,
                partition_key=partition_key,
                artifact_id=artifact["artifact_id"],
                source_version=str(source_snapshot.get("source_version") or source_snapshot["snapshot_id"]),
                snapshot_at=str(source_snapshot["observed_at"]),
                watermark_at=str(source_snapshot.get("watermark_at") or "") or None,
                row_count=len(rows),
                data_hash=stored_object.content_hash,
                freshness_status="fresh",
                acquisition_run_id=run_id,
                created_by=actor_user_id,
            )
            raw_table_asset = None
            if str(version.get("runtime") or "") == "browser":
                raw_table_asset = self._register_crawler_csv_raw_table(
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    artifact=artifact,
                    object_uri=stored_object.object_uri,
                    rows=rows,
                    source_snapshot=source_snapshot,
                    connection=connection,
                    dataset_id=str(job.get("target_dataset_id") or ""),
                    topic_table_id=str(job.get("topic_table_id") or ""),
                    context={
                        "job_name": str(job.get("job_name") or job.get("job_code") or ""),
                        **(dict(job.get("job_config") or {})),
                    },
                )
            completed = self.store.update_run(
                tenant_id,
                run_id,
                status="succeeded",
                rows_read=len(rows),
                rows_written=len(rows),
                output_cursor=provider_cursor,
                source_snapshot=source_snapshot,
                quality_summary=quality_summary,
                output_artifact_id=artifact["artifact_id"],
                partition_id=partition["partition_id"],
                finished_at=_utcnow(),
                error_code=None,
                error_summary=None,
            )
            run_cursor = input_cursor or {}
            keep_latest_n = _bounded_keep_latest_n(run_cursor.get("keep_latest_n", job["job_config"].get("keep_latest_n", 3)))
            expire_partitions = getattr(self.store, "expire_old_partitions", None)
            retention_summary = (
                expire_partitions(
                    tenant_id,
                    topic_table_id=job.get("topic_table_id"),
                    org_unit_id=org_unit_id,
                    keep_latest_n=keep_latest_n,
                )
                if callable(expire_partitions) and job.get("topic_table_id")
                else {"keep_latest_n": keep_latest_n, "expired_partitions": 0}
            )
            self.store.enqueue_outbox_event(
                tenant_id,
                "acquisition_run",
                run_id,
                "data.acquisition.succeeded",
                {
                    "run_id": run_id,
                    "job_id": acquisition_job_id,
                    "artifact_id": artifact["artifact_id"],
                    "partition_id": partition["partition_id"],
                    "row_count": len(rows),
                    "raw_table_asset_id": str((raw_table_asset or {}).get("id") or ""),
                    "retention": retention_summary,
                },
            )
            return {**completed, "retention": retention_summary, "raw_table_asset": raw_table_asset}
        except Exception as exc:
            error_code, error_summary, failure_facts = _safe_failure(exc)
            failed = self.store.update_run(
                tenant_id,
                run_id,
                status="failed",
                rows_read=int(failure_facts.get("rows_read") or 0),
                rows_written=0,
                source_snapshot=failure_facts.get("source_snapshot", {}),
                quality_summary=failure_facts.get("quality_summary", {}),
                output_artifact_id=failure_facts.get("artifact_id"),
                finished_at=_utcnow(),
                error_code=error_code,
                error_summary=error_summary,
            )
            diagnosis = {
                "error_code": error_code,
                "error_summary": error_summary,
                "automatic_application_allowed": False,
                "recommended_action": _recommended_action(error_code),
                "quality_summary": failure_facts.get("quality_summary", {}),
                "diagnostics": failure_facts.get("diagnostics", {}),
            }
            generation_method = "deterministic"
            candidate_source_code = None
            try:
                generated = self.repair_generator.generate(tenant_id, version, diagnosis)
                if generated:
                    diagnosis["model_call"] = generated.get("model_call") or {}
                    candidate_source_code = generated.get("candidate_source_code")
                    if candidate_source_code:
                        generation_method = "llm"
            except Exception:
                diagnosis["llm_repair_status"] = "failed_validation_or_provider"
            proposal = self.store.create_repair_proposal(
                tenant_id,
                acquisition_run_id=run_id,
                failed_script_version_id=job["script_version_id"],
                diagnosis=diagnosis,
                generation_method=generation_method,
                candidate_source_code=candidate_source_code,
                created_by=actor_user_id,
            )
            model_call = diagnosis.get("model_call") if isinstance(diagnosis.get("model_call"), dict) else {}
            save_model_call = getattr(self.model_call_repository, "save_model_call_fact", None)
            if model_call and callable(save_model_call):
                save_model_call(
                    tenant_id,
                    "acquisition_repair_proposal",
                    proposal["repair_proposal_id"],
                    actor_user_id,
                    model_call,
                )
            self.store.enqueue_outbox_event(
                tenant_id,
                "acquisition_run",
                run_id,
                "data.acquisition.failed",
                {
                    "run_id": run_id,
                    "job_id": acquisition_job_id,
                    "error_code": error_code,
                    "repair_proposal_id": proposal["repair_proposal_id"],
                },
            )
            return {**failed, "status": "repair_review", "repair_proposal": proposal}

    def run_verified_crawler(
        self,
        tenant_id: str,
        connection_id: str,
        actor_user_id: str,
        idempotency_key: str,
        crawler_engine: CrawlerEngine | None = None,
    ) -> dict[str, Any]:
        """Execute one tested system crawler and persist its rows as an immutable CSV artifact."""

        connection = self._verified_connection(tenant_id, connection_id)
        return self._run_crawler_connection(
            tenant_id,
            connection,
            actor_user_id,
            idempotency_key,
            crawler_engine=crawler_engine,
        )

    def validate_and_run_crawler(
        self,
        tenant_id: str,
        connection_id: str,
        actor_user_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Run a draft real crawler once; mark it verified only after data succeeds."""

        connection = self._crawler_connection(tenant_id, connection_id)
        result = self._run_crawler_connection(
            tenant_id,
            connection,
            actor_user_id,
            idempotency_key,
        )
        verified = self.system_config_store.upsert_data_connection(
            tenant_id,
            {
                **connection,
                "status": "verified",
                "testStatus": "verified",
                "testMessage": f"真实数据采集成功，共 {result['row_count']} 行。",
                "lastTestedAt": _utcnow(),
            },
            updated_by=actor_user_id,
        )
        return {**result, "connection": verified}

    def ensure_crawler_connection(
        self,
        tenant_id: str,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        """Idempotently create or refresh one page-level crawler connection."""

        candidate = dict(payload)
        candidate_identity = build_crawler_url_identity(candidate)
        if candidate_identity is None:
            raise ValueError("crawler_page_url_required")
        for existing in self.system_config_store.list_data_connections(tenant_id, reveal_secret=True):
            identity = build_crawler_url_identity(existing)
            if identity and identity.page_url == candidate_identity.page_url:
                candidate = {
                    **existing,
                    **{key: value for key, value in candidate.items() if value not in (None, "")},
                    "id": existing["id"],
                }
                break
        return self.system_config_store.upsert_data_connection(
            tenant_id,
            candidate,
            updated_by=actor_user_id,
        )

    def _run_crawler_connection(
        self,
        tenant_id: str,
        connection: dict[str, Any],
        actor_user_id: str,
        idempotency_key: str,
        crawler_engine: CrawlerEngine | None = None,
    ) -> dict[str, Any]:
        identity = build_crawler_url_identity(connection)
        if identity is None or not identity.profile_id:
            raise ValueError("registered_crawler_profile_required")
        config = connection.get("crawlerConfig") if isinstance(connection.get("crawlerConfig"), dict) else {}
        steps = self._crawler_steps(identity.profile_id, config)
        result = (crawler_engine or self.crawler_engine).execute(
            CrawlerRequest(
                tenant_id=tenant_id,
                operation_type=CrawlerOperation.DATA_QUERY,
                idempotency_key=idempotency_key,
                connection=connection,
                connection_version_id=str(connection.get("currentVersionId") or connection.get("id") or ""),
                script_version_id=f"{identity.profile_id}:v1",
                script={"version": 1, "steps": steps, "metadata": {"profile": identity.profile_id}},
                timeout_seconds=900,
            )
        )
        if result.status != "succeeded" or not result.rows:
            raise CrawlerExecutionError(
                str(result.error_code or "EMPTY_RESULT"),
                str(result.diagnostics.get("message") or "crawler_data_collection_failed"),
            )
        rows = [dict(row) for row in result.rows]
        csv_bytes = _rows_to_csv(rows)
        stored_object = self.object_store.put(tenant_id, csv_bytes, ".csv")
        artifact = self.store.create_artifact(
            tenant_id,
            object_uri=stored_object.object_uri,
            content_hash=stored_object.content_hash,
            content_type="text/csv; charset=utf-8",
            size_bytes=stored_object.size_bytes,
            status="active",
            created_by=actor_user_id,
        )
        operational_csv = self._write_operational_crawler_csv(
            connection=connection,
            profile_id=identity.profile_id,
            source_snapshot=dict(result.source_snapshot),
            metadata=dict(result.metadata),
            content=csv_bytes,
            rows=rows,
        )
        raw_table_asset = self._register_crawler_csv_raw_table(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            artifact=artifact,
            object_uri=stored_object.object_uri,
            rows=rows,
            source_snapshot=dict(result.source_snapshot),
            connection=connection,
            dataset_id=str(connection.get("dataset") or identity.profile_id.split(".", 1)[0]),
            topic_table_id="",
            context={**dict(result.metadata), "operational_csv": operational_csv},
        )
        automation_task = self._ensure_crawler_automation_task(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            connection=connection,
            identity=identity,
        )
        return {
            "status": "succeeded",
            "connection_id": str(connection.get("id") or ""),
            "crawler_profile_id": identity.profile_id,
            "artifact_id": artifact["artifact_id"],
            "object_uri": stored_object.object_uri,
            "content_hash": stored_object.content_hash,
            "csv_path": operational_csv["path"],
            "csv_file_name": operational_csv["file_name"],
            "standard_report_paths": operational_csv.get("standard_report_paths", ""),
            "row_count": len(rows),
            "source_snapshot": dict(result.source_snapshot),
            "raw_table_asset": raw_table_asset,
            "automation_task": automation_task,
        }

    @staticmethod
    def _crawler_steps(profile_id: str, config: dict[str, Any]) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = [
            {"action": "goto", "url": "${login_url}", "timeout_ms": 20_000},
            {
                "action": "fill",
                "selector": str(
                    config.get("accountSelector")
                    or 'input[placeholder="请输入邮箱或手机号"], input[name="username"], input[name="account"], input[type="email"]'
                ),
                "value_key": "account",
                "optional": True,
                "timeout_ms": 10_000,
            },
            {
                "action": "fill",
                "selector": str(config.get("passwordSelector") or 'input[type="password"]'),
                "value_key": "password",
                "optional": True,
                "timeout_ms": 10_000,
            },
        ]
        if profile_id == "qifu_focuspro_sios.business_sandbox.v1":
            if bool(config.get("autoSubmitLogin", False)):
                steps.append(
                    {
                        "action": "click",
                        "selector": str(config.get("loginButtonSelector") or 'button[type="submit"]'),
                        "optional": True,
                        "timeout_ms": 10_000,
                    }
                )
            steps.extend(
                [
                    {
                        "action": "wait_for_url",
                        "url_contains": "#/sios/businessSandbox",
                        "match_query_page": True,
                        "manual": True,
                        "stability_ms": 5_000,
                        "timeout_ms": 840_000,
                    },
                    {"action": "wait", "timeout_ms": 3_000},
                    {
                        "action": "collect_system",
                        "profile_id": profile_id,
                        "api_base": str(config.get("apiBase") or "app-module:50826"),
                        "traversal_mode": str(config.get("traversalMode") or "current"),
                        "include_totals": bool(config.get("includeTotals", True)),
                        "include_current_date": bool(config.get("includeCurrentDate", True)),
                        "statistical_dates": config.get("statisticalDates") or [],
                        "collect_all_trends": bool(config.get("collectAllTrends", False)),
                        **(
                            {"request_delay_ms": int(config["requestDelayMs"])}
                            if config.get("requestDelayMs") is not None
                            else {
                                "request_delay_min_ms": int(config.get("requestDelayMinMs") or 250),
                                "request_delay_max_ms": int(config.get("requestDelayMaxMs") or 500),
                            }
                        ),
                        "max_rate_limit_retries": int(config.get("maxRateLimitRetries") or 3),
                        "max_combinations": int(config.get("maxCombinations") or 10_000),
                        "batch_size": int(config.get("batchSize") or 16),
                        "batch_concurrency": int(config.get("batchConcurrency") or 1),
                        "checkpoint_path": str(config.get("checkpointPath") or ""),
                        "timeout_ms": 840_000,
                    },
                ]
            )
        elif profile_id == "qifu_focuspro_sios.funnel_analysis.v1":
            steps.extend(
                [
                    {
                        "action": "wait_for_url",
                        "url_contains": "#/sios/funnelAnalysis",
                        "match_query_page": True,
                        "manual": True,
                        "stability_ms": 1_000,
                        "timeout_ms": 840_000,
                    },
                    {"action": "wait", "selector": ".funnel-analysis-page", "timeout_ms": 60_000},
                    {
                        "action": "collect_system",
                        "profile_id": profile_id,
                        # The FocusPro frontend API module applies the live
                        # encryption/signing contract for the /lost endpoints.
                        "api_base": str(config.get("apiBase") or "app-module:24915"),
                        "traversal_mode": str(config.get("traversalMode") or "current"),
                        "default_product_code": str(config.get("defaultProductCode") or ""),
                        "default_date_range": str(config.get("defaultDateRange") or ""),
                        "include_totals": bool(config.get("includeTotals", True)),
                        "staff_search_terms": config.get("staffSearchTerms") or [],
                        "statistical_dates": config.get("statisticalDates") or [],
                        # 250ms gives a stable 4 requests/sec; deployments
                        # may opt into a bounded random interval explicitly.
                        "request_delay_ms": int(config.get("requestDelayMs") or 250),
                        "request_delay_min_ms": int(config.get("requestDelayMinMs") or 250),
                        "request_delay_max_ms": int(config.get("requestDelayMaxMs") or 500),
                        "max_rate_limit_retries": int(config.get("maxRateLimitRetries") or 6),
                        "max_combinations": int(config.get("maxCombinations") or 2_000),
                        "lost_scenes": config.get("lostScenes") or ["COMPLETE", "APPROVAL", "PUTOUT"],
                        # The page exposes one trend chart per section by
                        # default.  Use all trends only when an operator asks
                        # for a deeper traversal, avoiding needless requests.
                        "trend_item_limit": 0 if bool(config.get("collectAllTrends", False)) else int(config.get("trendItemLimit") or 1),
                        "timeout_ms": 840_000,
                    },
                ]
            )
        else:
            steps.extend(
                [
                    {
                        "action": "click",
                        "selector": str(config.get("loginButtonSelector") or 'button[type="submit"]'),
                        "optional": True,
                        "timeout_ms": 10_000,
                    },
                    {"action": "wait", "timeout_ms": 1_000},
                    {"action": "goto", "url": "${query_page_url}", "timeout_ms": 20_000},
                    {
                        "action": "collect_system",
                        "profile_id": profile_id,
                        "timeout_ms": 840_000,
                    },
                ]
            )
        return steps

    def _write_operational_crawler_csv(
        self,
        *,
        connection: dict[str, Any],
        profile_id: str,
        source_snapshot: dict[str, Any],
        metadata: dict[str, Any],
        content: bytes,
        rows: list[dict[str, Any]],
    ) -> dict[str, str]:
        configured_root = os.getenv("SMART_DATA_AGENT_CRAWLER_EXPORT_ROOT", "").strip()
        export_root = (
            Path(configured_root).expanduser().resolve()
            if configured_root
            else Path(__file__).resolve().parents[3] / "data" / "智能运营"
        )
        export_root.mkdir(parents=True, exist_ok=True)
        page_name = str(metadata.get("page_name") or _crawler_page_name(profile_id)).strip()
        institution = str(connection.get("institution") or "未知机构").strip()
        observed_at = str(source_snapshot.get("observed_at") or _utcnow())
        timezone_name = os.getenv("SMART_DATA_AGENT_CRAWLER_EXPORT_TIMEZONE", "Asia/Shanghai").strip()
        try:
            export_timezone = ZoneInfo(timezone_name or "Asia/Shanghai")
        except ZoneInfoNotFoundError:
            export_timezone = timezone.utc
        try:
            file_date = _parse_timestamp(observed_at).astimezone(export_timezone).date().isoformat()
        except (TypeError, ValueError):
            file_date = datetime.now(export_timezone).date().isoformat()
        file_name = (
            f"{_safe_file_name_component(institution, '未知机构')}"
            f"{_safe_file_name_component(page_name, '数据页面')}"
            f"{file_date}.csv"
        )
        destination = export_root / file_name
        content_hash = hashlib.sha256(content).hexdigest()
        temporary = export_root / f".{file_name}.{content_hash[:12]}.tmp"
        temporary.write_bytes(content)
        temporary.replace(destination)
        output = {
            "path": str(destination),
            "file_name": file_name,
            "content_hash": content_hash,
        }
        if profile_id == "qifu_focuspro_sios.business_sandbox.v1":
            standard_paths = _write_business_sandbox_standard_csvs(
                export_root=export_root / "标准报表",
                institution=institution,
                file_date=file_date,
                rows=rows,
            )
            output["standard_report_paths"] = json.dumps(standard_paths, ensure_ascii=False)
        return output

    def _ensure_crawler_automation_task(
        self,
        *,
        tenant_id: str,
        actor_user_id: str,
        connection: dict[str, Any],
        identity: Any,
    ) -> dict[str, Any] | None:
        runtime = self.automation_runtime
        if runtime is None:
            return None
        task_code = f"crawler_{identity.crawler_key}"
        existing = runtime.store.get_task_by_code(tenant_id, task_code)
        if existing:
            return existing
        institution = str(connection.get("institution") or "机构").strip()
        page_name = _crawler_page_name(identity.profile_id)
        task_name = f"{institution}{page_name}数据获取"
        crawler_config = (
            connection.get("crawlerConfig") if isinstance(connection.get("crawlerConfig"), dict) else {}
        )
        traversal_mode = str(crawler_config.get("traversalMode") or "current").strip().lower()
        if traversal_mode == "cartesian":
            scope_description = "遍历全部机构、产品、时间维度和业务板块，采集指标及趋势"
            data_content = "全部筛选枚举、全量筛选组合、业务板块指标、同比/环比字段及绩效趋势明细"
        elif traversal_mode == "independent":
            scope_description = "按各筛选维度独立遍历业务板块，采集指标及趋势"
            data_content = "全部筛选枚举、独立维度筛选结果、业务板块指标、同比/环比字段及绩效趋势明细"
        else:
            scope_description = "按页面默认机构、默认产品和月数据口径，采集全部业务板块、指标及绩效趋势"
            data_content = "全部筛选枚举、当前页面五个业务板块指标、同比/环比字段及绩效趋势明细"
        description = (
            f"定时登录{institution}的奇富 FocusPro SIOS {page_name}页面，{scope_description}，"
            "生成按机构+页面+日期命名的 CSV，并更新原始表资产。"
        )
        return runtime.create_task(
            tenant_id,
            {
                "task_code": task_code,
                "task_name": task_name,
                "task_type": "acquisition",
                "trigger_type": "schedule",
                "schedule_expression": "0 8 * * *",
                "handler_ref": "crawler.connection.run",
                "task_config": {
                    "connection_id": str(connection.get("id") or ""),
                    "crawler_profile_id": identity.profile_id,
                    "page_url": identity.page_url,
                    "institution": institution,
                    "page_name": page_name,
                    "category": "automation",
                    "question": description,
                    "description": description,
                    "data_content": data_content,
                    "display_type": "数据获取",
                    "display_schedule": "每天 08:00",
                    "schedule_timezone": "Asia/Shanghai",
                },
                "retry_policy": {
                    "max_attempts": 3,
                    "base_delay_seconds": 1_800,
                    "retryable_error_codes": ["RATE_LIMITED", "TIMEOUT", "NETWORK_ERROR"],
                },
                "timeout_seconds": 14_400,
                "max_concurrency": 1,
            },
            actor_user_id,
        )

    def _register_crawler_csv_raw_table(
        self,
        *,
        tenant_id: str,
        actor_user_id: str,
        artifact: dict[str, Any],
        object_uri: str,
        rows: list[dict[str, Any]],
        source_snapshot: dict[str, Any],
        connection: dict[str, Any],
        dataset_id: str,
        topic_table_id: str,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Upsert one active raw-table asset per connection and page profile."""

        if self.data_asset_store is None:
            return None
        artifact_id = str(artifact.get("artifact_id") or "").strip()
        if not artifact_id:
            raise ValueError("crawler_csv_artifact_id_required")
        profile = context.get("crawler_profile") if isinstance(context.get("crawler_profile"), dict) else {}
        profile_id = str(
            profile.get("profile_id")
            or context.get("profile")
            or connection.get("crawlerProfileId")
            or ""
        ).strip()
        topic = None
        get_item = getattr(self.data_asset_store, "get_item", None)
        if topic_table_id and callable(get_item):
            try:
                topic = get_item(tenant_id, "topic_table", topic_table_id)
            except (KeyError, ValueError):
                topic = None
        usage_scenario = str(
            context.get("usageScenario")
            or context.get("usage_scenario")
            or (topic or {}).get("applicableScene")
            or profile.get("display_name")
            or connection.get("sourceName")
            or "智能分析、经营周报"
        ).strip()
        related_intent = str(
            context.get("relatedIntent")
            or context.get("related_intent")
            or (topic or {}).get("relatedIntent")
            or _default_crawler_intent(profile_id, dataset_id)
        ).strip()
        dataset_code = _safe_asset_identifier(dataset_id, "crawler_data")
        observed_at = str(source_snapshot.get("observed_at") or _utcnow())
        operational_csv = context.get("operational_csv") if isinstance(context.get("operational_csv"), dict) else {}
        file_name = str(operational_csv.get("file_name") or "").strip() or _crawler_csv_file_name(
            dataset_code, observed_at, artifact_id
        )
        object_file_name = str(object_uri).rstrip("/").rsplit("/", 1)[-1]
        fields = _crawler_csv_fields(rows, file_name, usage_scenario, related_intent)
        source_name = str(connection.get("sourceName") or profile.get("display_name") or dataset_id or "爬虫引擎").strip()
        institution = str(connection.get("institution") or "机构").strip()
        page_name = str(context.get("page_name") or _crawler_page_name(profile_id)).strip()
        asset_identity = "|".join(
            [
                str(connection.get("id") or ""),
                profile_id,
                dataset_code,
            ]
        )
        asset_key = hashlib.sha256(asset_identity.encode("utf-8")).hexdigest()[:24]
        table_name_en = _safe_asset_identifier(f"{dataset_code}_csv_{asset_key[:8]}", f"crawler_csv_{asset_key[:8]}")
        field_codes = {str(field["fieldNameCn"]): str(field["fieldNameEn"]) for field in fields}
        item = {
            "id": f"raw_crawler_{asset_key}",
            "tableNameEn": table_name_en,
            "tableNameCn": f"{institution}{page_name} CSV原始数据",
            "source": source_name,
            "tableType": "crawler_csv",
            "primaryKey": _first_matching_field(field_codes, ("id", "编号", "流水")),
            "dateField": _first_matching_field(field_codes, ("date", "time", "日期", "时间")),
            "orgField": _first_matching_field(field_codes, ("org", "branch", "机构", "分行")),
            "customerField": _first_matching_field(field_codes, ("customer", "客户")),
            "description": f"爬虫引擎获取的 CSV 文件 {file_name}，共 {len(rows)} 行、{len(fields)} 个字段。",
            "updateFrequency": "随爬虫任务更新",
            "restrictions": "沿用数据连接及租户、机构权限，不允许跨租户复用。",
            "exampleSql": "",
            "fields": fields,
            "updatedAt": _utcnow(),
            "fileName": file_name,
            "objectFileName": object_file_name,
            "artifactId": artifact_id,
            "artifactObjectUri": object_uri,
            "operationalCsvPath": str(operational_csv.get("path") or ""),
            "rowCount": len(rows),
            "usageScenario": usage_scenario,
            "relatedIntent": related_intent,
            "crawlerProfileId": profile_id,
            "connectionId": str(connection.get("id") or ""),
            "sourceSnapshotId": str(source_snapshot.get("snapshot_id") or ""),
            "sourcePlatform": "智能运营" if profile_id.startswith("qifu_focuspro_sios.") else "",
            "linkedToolId": (
                "tool_focuspro_funnel_analysis_crawler"
                if profile_id == "qifu_focuspro_sios.funnel_analysis.v1"
                else "tool_focuspro_business_sandbox_crawler"
                if profile_id == "qifu_focuspro_sios.business_sandbox.v1"
                else ""
            ),
        }
        return self.data_asset_store.upsert_item(
            tenant_id,
            "raw_table",
            item,
            updated_by=actor_user_id,
            lifecycle_status="active",
        )

    def review_repair_proposal(
        self,
        tenant_id: str,
        proposal_id: str,
        decision: str,
        actor_user_id: str,
    ) -> dict[str, Any]:
        return self.store.review_repair_proposal(tenant_id, proposal_id, decision, actor_user_id)

    def latest_csv(
        self,
        tenant_id: str,
        topic_table_id: str,
        org_unit_id: str | None = None,
        *,
        include_content: bool = False,
    ) -> dict[str, Any]:
        artifact = self.store.latest_artifact(tenant_id, topic_table_id, org_unit_id)
        result = dict(artifact)
        if include_content:
            content = self.object_store.read(tenant_id, artifact["object_uri"], artifact["content_hash"])
            if len(content) > 8_000_000:
                raise ValueError("artifact_inline_size_limit_exceeded")
            result["content"] = content.decode("utf-8")
        return result

    # Explicit camelCase compatibility for the acquisition design contract.
    def getLatestCsvByTopicTable(self, topic_table_id: str, org_id: str | None, tenant_id: str) -> dict[str, Any]:  # noqa: N802
        return self.latest_csv(tenant_id, topic_table_id, org_id, include_content=True)

    def get_artifact_content(self, tenant_id: str, artifact_id: str) -> tuple[dict[str, Any], bytes]:
        artifact = self.store.get_artifact(tenant_id, artifact_id)
        if artifact["status"] != "active":
            raise PermissionError("artifact_is_not_publishable")
        content = self.object_store.read(tenant_id, artifact["object_uri"], artifact["content_hash"])
        return artifact, content

    def upload_raw_asset_file(
        self,
        tenant_id: str,
        file_name: str,
        content: bytes,
        actor_user_id: str,
    ) -> dict[str, Any]:
        normalized_name = str(file_name or "").strip()
        if (
            not normalized_name
            or len(normalized_name) > 500
            or "/" in normalized_name
            or "\\" in normalized_name
        ):
            raise ValueError("invalid_raw_file_name")
        suffix = "." + normalized_name.rsplit(".", 1)[-1].lower() if "." in normalized_name else ""
        content_types = {
            ".csv": "text/csv; charset=utf-8",
            ".tsv": "text/tab-separated-values; charset=utf-8",
            ".json": "application/json; charset=utf-8",
        }
        if suffix not in content_types:
            raise ValueError("unsupported_raw_file_type")
        if not content or len(content) > self.max_raw_file_bytes:
            raise ValueError("invalid_raw_file_upload_size")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("raw_file_must_be_utf8") from exc
        if not text.strip():
            raise ValueError("raw_file_is_empty")
        if suffix == ".json":
            parsed = json.loads(text)
            if not isinstance(parsed, (dict, list)):
                raise ValueError("raw_json_requires_object_or_array")
        else:
            delimiter = "\t" if suffix == ".tsv" else ","
            header = next(csv.reader(io.StringIO(text), delimiter=delimiter), [])
            if not any(str(value).strip() for value in header):
                raise ValueError("raw_file_header_required")
        stored = self.object_store.put(tenant_id, content, suffix)
        artifact = self.store.create_artifact(
            tenant_id,
            object_uri=stored.object_uri,
            content_hash=stored.content_hash,
            content_type=content_types[suffix],
            size_bytes=stored.size_bytes,
            status="active",
            created_by=actor_user_id,
            artifact_type="other",
        )
        return {
            "file_name": normalized_name,
            "artifact_id": artifact["artifact_id"],
            "object_uri": artifact["object_uri"],
            "content_hash": artifact["content_hash"],
            "content_type": artifact["content_type"],
            "size_bytes": artifact["size_bytes"],
        }

    def bundle(self, tenant_id: str) -> dict[str, Any]:
        return self.store.bundle(tenant_id)

    def _verified_connection(self, tenant_id: str, connection_id: str) -> dict[str, Any]:
        if not connection_id:
            raise ValueError("connection_id_required")
        connection = self.system_config_store.get_data_connection(tenant_id, connection_id, reveal_secret=True)
        if not connection:
            raise KeyError("data_connection_not_found")
        if (
            not connection.get("enabled")
            or connection.get("mockEnabled")
            or str(connection.get("status") or "") != "verified"
            or str(connection.get("testStatus") or "") != "verified"
        ):
            raise ValueError("verified_real_data_connection_required")
        return connection

    def _crawler_connection(self, tenant_id: str, connection_id: str) -> dict[str, Any]:
        if not connection_id:
            raise ValueError("connection_id_required")
        connection = self.system_config_store.get_data_connection(tenant_id, connection_id, reveal_secret=True)
        if not connection:
            raise KeyError("data_connection_not_found")
        if not connection.get("enabled") or connection.get("mockEnabled"):
            raise ValueError("enabled_real_data_connection_required")
        identity = build_crawler_url_identity(connection)
        if identity is None or not identity.profile_id:
            raise ValueError("registered_crawler_profile_required")
        return connection

    def _execute(
        self,
        tenant_id: str,
        actor_user_id: str,
        org_unit_id: str | None,
        job: dict[str, Any],
        version: dict[str, Any],
        connection: dict[str, Any],
        input_cursor: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        if version["review_status"] != "approved":
            raise PermissionError("approved_script_version_required")
        runtime = str(version["runtime"])
        source_code = str(version["source_code"])
        if runtime == "browser":
            try:
                script_config = json.loads(source_code)
            except json.JSONDecodeError as exc:
                raise ValueError("browser_script_must_be_json") from exc
            job_config = dict(job.get("job_config") or {})
            readonly_sql = str(
                input_cursor.get("readonly_sql")
                or job_config.get("readonly_sql")
                or script_config.get("readonly_sql")
                or ""
            ).strip()
            if infer_crawler_mode(connection) == "sql" and not readonly_sql:
                raise ValueError("crawler_readonly_sql_required")
            result = self.crawler_engine.execute(
                CrawlerRequest(
                    tenant_id=tenant_id,
                    org_id=org_unit_id,
                    operation_type=CrawlerOperation.DATA_QUERY,
                    topic_table_id=str(job.get("topic_table_id") or "") or None,
                    connection_version_id=str(connection.get("currentVersionId") or connection.get("id") or "") or None,
                    script_version_id=str(version.get("script_version_id") or "") or None,
                    readonly_sql=readonly_sql,
                    parameters={"dialect": str(job_config.get("sql_dialect") or "postgres")},
                    idempotency_key=str(input_cursor.get("idempotency_key") or f"run:{job.get('acquisition_job_id') or job.get('job_key') or ''}"),
                    connection=connection,
                    script=script_config,
                    timeout_seconds=min(max(int(job_config.get("timeout_seconds") or 240), 1), 900),
                )
            )
            if result.status != "succeeded":
                message = str(result.diagnostics.get("message") or "crawler_transport_not_ready")
                raise CrawlerExecutionError(str(result.error_code or "UNKNOWN_ERROR"), message)
            return [dict(row) for row in result.rows], dict(result.source_snapshot), dict(result.output_cursor)
        if runtime == "sql":
            sql = validate_read_only_sql_candidate(source_code)
            query_config: dict[str, Any] = {"manual_sql_candidate": sql, "query_revision": version["version_no"]}
            transform_code = ""
        elif runtime in {"http", "python"}:
            try:
                script_config = json.loads(source_code)
            except json.JSONDecodeError as exc:
                raise ValueError("acquisition_script_must_be_json") from exc
            if not isinstance(script_config, dict):
                raise ValueError("acquisition_script_config_must_be_object")
            query_config = script_config.get("query", {})
            if not isinstance(query_config, dict):
                raise ValueError("acquisition_query_config_must_be_object")
            transform_code = str(script_config.get("transform_code") or "")
            if runtime == "python" and not transform_code:
                raise ValueError("python_transform_code_required")
        else:
            raise PermissionError("unsupported_acquisition_runtime")
        required_filters: dict[str, Any] = {"tenant_id": tenant_id}
        if org_unit_id:
            required_filters["org_unit_id"] = org_unit_id
        requested_filters = query_config.get("filters", {})
        if requested_filters and not isinstance(requested_filters, dict):
            raise ValueError("acquisition_filters_must_be_object")
        max_rows = self._integer_param(tenant_id, "acquisition_max_rows", self.max_rows, 1, 500_000)
        query_payload = {
            **query_config,
            "dataset_id": job["target_dataset_id"],
            "tenant_id": tenant_id,
            "user_id": actor_user_id,
            "filters": {**dict(requested_filters or {}), **required_filters},
            "authorization": {"row_filter": required_filters},
            "input_cursor": input_cursor,
            "limit": min(int(query_config.get("limit") or max_rows), max_rows),
        }
        response = HTTPJSONSourceClient(connection).query(query_payload)
        result = response.get("result") if isinstance(response.get("result"), dict) else response
        rows = result.get("rows", result.get("data", []))
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise RuntimeError("source_rows_invalid")
        if len(rows) > max_rows:
            raise RuntimeError("source_row_limit_exceeded")
        semantic_info = result.get("semantic_info", result.get("semanticInfo", {}))
        if not isinstance(semantic_info, dict):
            raise RuntimeError("source_semantic_info_invalid")
        applied = semantic_info.get("applied_filters")
        if not isinstance(applied, dict) or any(applied.get(key) != value for key, value in required_filters.items()):
            raise PermissionError("source_did_not_confirm_tenant_filters")
        if runtime == "sql" and (
            semantic_info.get("catalog_validated") is not True
            or semantic_info.get("tenant_policy_injected") is not True
        ):
            raise PermissionError("source_did_not_confirm_sql_governance")
        source_snapshot = semantic_info.get("source_snapshot")
        if not isinstance(source_snapshot, dict) or not source_snapshot.get("snapshot_id") or not source_snapshot.get("observed_at"):
            raise RuntimeError("source_snapshot_evidence_missing")
        _parse_timestamp(str(source_snapshot["observed_at"]))
        safe_rows = [dict(row) for row in rows]
        if runtime == "python":
            safe_rows = self.transform_sandbox.transform(
                transform_code,
                safe_rows,
                {
                    "tenant_id": tenant_id,
                    "org_unit_id": org_unit_id,
                    "dataset_id": job["target_dataset_id"],
                    "source_snapshot": dict(source_snapshot),
                },
            )
        output_cursor = result.get("output_cursor", semantic_info.get("output_cursor", {}))
        if not isinstance(output_cursor, dict):
            output_cursor = {}
        return safe_rows, dict(source_snapshot), dict(output_cursor)


class AcquisitionQualityGateError(RuntimeError):
    def __init__(
        self,
        quality_summary: dict[str, Any],
        artifact_id: str,
        rows_read: int,
        source_snapshot: dict[str, Any],
    ) -> None:
        super().__init__("quality_gate_failed")
        self.quality_summary = quality_summary
        self.artifact_id = artifact_id
        self.rows_read = rows_read
        self.source_snapshot = source_snapshot


def _evaluate_quality(
    rows: list[dict[str, Any]],
    source_snapshot: dict[str, Any],
    job_config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = job_config.get("quality_rules", {})
    if config and not isinstance(config, dict):
        raise ValueError("quality_rules_must_be_object")
    config = dict(config or {})
    results: list[dict[str, Any]] = []
    min_rows = max(0, int(config.get("min_rows", 1)))
    results.append(_quality_result("min_rows", len(rows) >= min_rows, len(rows), {"min_rows": min_rows}, True))
    required_columns = [str(item) for item in config.get("required_columns", []) if str(item).strip()]
    missing_columns = sorted({column for column in required_columns if any(column not in row for row in rows)})
    results.append(
        _quality_result(
            "required_columns",
            not missing_columns,
            {"missing_columns": missing_columns},
            {"required_columns": required_columns},
            bool(required_columns),
        )
    )
    unique_by = [str(item) for item in config.get("unique_by", []) if str(item).strip()]
    duplicates = 0
    if unique_by:
        keys = [tuple(_stable_cell(row.get(field)) for field in unique_by) for row in rows]
        duplicates = len(keys) - len(set(keys))
    results.append(
        _quality_result(
            "unique_by",
            duplicates == 0,
            {"duplicate_count": duplicates},
            {"fields": unique_by},
            bool(unique_by),
        )
    )
    max_null_ratio = float(config.get("max_null_ratio", 1.0))
    null_count = sum(1 for row in rows for value in row.values() if value in (None, ""))
    cell_count = sum(len(row) for row in rows)
    null_ratio = null_count / cell_count if cell_count else 0.0
    results.append(
        _quality_result(
            "max_null_ratio",
            null_ratio <= max_null_ratio,
            {"null_ratio": round(null_ratio, 6)},
            {"max_null_ratio": max_null_ratio},
            max_null_ratio < 1,
        )
    )
    freshness_sla = max(1, int(job_config.get("freshness_sla_seconds", 86_400)))
    observed = _parse_timestamp(str(source_snapshot["observed_at"]))
    age_seconds = max(0, int((datetime.now(timezone.utc) - observed).total_seconds()))
    freshness_ok = age_seconds <= freshness_sla
    results.append(
        _quality_result(
            "freshness_sla",
            freshness_ok,
            {"age_seconds": age_seconds},
            {"freshness_sla_seconds": freshness_sla},
            bool(job_config.get("block_on_stale", True)),
        )
    )
    blocking_failures = [item["rule_code"] for item in results if item["blocking"] and item["status"] == "failed"]
    score = sum(float(item["score"]) for item in results) / max(len(results), 1)
    return results, {
        "blocked": bool(blocking_failures),
        "blocking_failures": blocking_failures,
        "score": round(score, 4),
        "rule_count": len(results),
        "evaluated_at": _utcnow(),
    }


def _quality_result(
    rule_code: str,
    passed: bool,
    observed: Any,
    threshold: Any,
    blocking: bool,
) -> dict[str, Any]:
    return {
        "rule_code": rule_code,
        "status": "passed" if passed else "failed",
        "score": 1.0 if passed else 0.0,
        "observed_value": observed if isinstance(observed, dict) else {"value": observed},
        "threshold": threshold if isinstance(threshold, dict) else {"value": threshold},
        "blocking": blocking,
    }


_BUSINESS_REPORT_HEADERS = [
    "二级机构", "三级机构", "产品名称", "统计日期", "时间维度",
    "在贷余额", "新增余额", "在贷人数", "放款金额", "还款金额", "创建订单人数", "完件人数", "完件率",
    "授信人数", "授信通过率", "授信金额", "授信户均", "授信利率", "动支率", "动支户均金额",
    "注册人数", "活跃展业人数", "创建订单人数", "创建订单笔数", "人均创建订单客户数", "完件人数", "完件笔数", "完件率",
    "1段初审通过人数", "1段初审出额额度", "1段初审出额户均", "1段初审出额利率", "1段风控出额率",
    "1段授信成功人数", "1段授信成功金额", "1段授信户均", "1段授信利率", "1段授信通过率",
    "2段授信成功人数", "2段授信成功金额", "2段授信户均", "2段授信利率", "2段授信通过率",
    "动支申请人数", "动支申请金额", "动支风控通过人数", "动支风控拒绝人数", "动支风控通过率",
    "动支成功人数", "动支金额", "动支户均", "动支利率", "动支率",
    "申请还款人数", "申请还款金额", "申请还款借据数", "成功还款人数", "成功还款金额",
    "还款成功率-用户", "还款成功率-借据", "还款成功率-金额", "新增在贷人数", "新增余额",
    "新增余额（不含代偿、核销）", "余额利率",
]

_BUSINESS_SECTION_ORDER = (
    ("业绩追踪", 15),
    ("完件业务数据表现", 8),
    ("授信业务数据表现", 10),
    ("动支业务数据表现", 10),
    ("还款业务数据表现", 12),
)

_TIME_DIMENSION_LABELS = {
    "7DAY": "近7日",
    "30DAY": "近30日",
    "WEEK": "本周",
    "MONTH": "本月",
    "QUARTER": "本季",
    "YEAR": "本年",
    "ALL": "累计",
}


def _write_business_sandbox_standard_csvs(
    *,
    export_root: Path,
    institution: str,
    file_date: str,
    rows: list[dict[str, Any]],
) -> list[str]:
    export_root.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    dates_by_filter: dict[str, str] = {}
    for row in rows:
        filter_hash = str(row.get("filter_hash") or "")
        trend_date = str(row.get("trend_date") or "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", trend_date):
            dates_by_filter[filter_hash] = max(dates_by_filter.get(filter_hash, ""), trend_date)

    detail_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("record_type") != "detail_metric":
            continue
        key = (str(row.get("filter_hash") or ""), str(row.get("dimension_code") or ""))
        detail_groups.setdefault(key, []).append(row)

    business_groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("record_type") == "section_metric":
            business_groups.setdefault(str(row.get("filter_hash") or ""), []).append(row)
    business_records: list[list[Any]] = []
    for filter_hash, group in sorted(
        business_groups.items(),
        key=lambda item: int(item[1][0].get("combination_index") or 0),
    ):
        first = group[0]
        by_section: dict[str, list[Any]] = {}
        for row in group:
            by_section.setdefault(str(row.get("section_name") or ""), []).append(row.get("metric_value", ""))
        values: list[Any] = []
        for section_name, count in _BUSINESS_SECTION_ORDER:
            section_values = list(by_section.get(section_name, []))[:count]
            section_values.extend([""] * (count - len(section_values)))
            values.extend(section_values)
        values[33:33] = ["0", "0", "0", "0%", "0%"]
        selected_org = str(first.get("third_org_code") or first.get("second_org_code") or "")
        detail_rows = detail_groups.get((filter_hash, selected_org or "000"), [])
        registered = next(
            (row.get("metric_value", "") for row in detail_rows if row.get("metric_code") == "regist_num"),
            "",
        )
        if registered != "":
            values[15] = registered
        statistical_date = str(first.get("date_record") or "") or dates_by_filter.get(filter_hash, "") or file_date
        business_records.append(
            [
                str(first.get("second_org_name") or "") if first.get("second_org_code") else "",
                str(first.get("third_org_name") or "") if first.get("third_org_code") else "",
                str(first.get("product_name") or ""),
                statistical_date,
                _TIME_DIMENSION_LABELS.get(str(first.get("date_range") or ""), str(first.get("date_range_name") or "")),
                *values,
            ]
        )
    if business_records:
        destination = export_root / (
            f"{_safe_file_name_component(institution, '未知机构')}经营沙盘标准指标报表{file_date}.csv"
        )
        _write_csv_matrix(destination, _BUSINESS_REPORT_HEADERS, business_records)
        paths.append(str(destination))

    detail_report_groups: dict[tuple[str, str], list[tuple[tuple[str, str], list[dict[str, Any]]]]] = {}
    for group_key, group in detail_groups.items():
        first = group[0]
        report_key = (str(first.get("product_name") or "未知产品"), str(first.get("date_range") or "MONTH"))
        detail_report_groups.setdefault(report_key, []).append((group_key, group))
    for (product_name, date_range), groups in detail_report_groups.items():
        metric_schema: list[tuple[str, str, str, int, int]] = []
        seen_schema: set[tuple[str, str]] = set()
        section_order: dict[str, int] = {}
        for _group_key, group in groups:
            for row in group:
                section_code = str(row.get("section_code") or "")
                section_order.setdefault(section_code, len(section_order))
                schema_key = (section_code, str(row.get("metric_code") or ""))
                if not schema_key[1] or schema_key in seen_schema:
                    continue
                seen_schema.add(schema_key)
                metric_schema.append(
                    (
                        schema_key[0],
                        schema_key[1],
                        str(row.get("metric_name") or schema_key[1]),
                        section_order[schema_key[0]],
                        int(row.get("schema_order") or 0),
                    )
                )
        metric_schema.sort(key=lambda item: (item[3], item[4]))
        detail_headers = ["机构", "产品名称", "统计日期", "时间维度", *[item[2] for item in metric_schema]]
        detail_records: list[list[Any]] = []
        for (filter_hash, _dimension_code), group in sorted(
            groups,
            key=lambda item: (
                int(item[1][0].get("combination_index") or 0),
                str(item[1][0].get("dimension_name") or ""),
            ),
        ):
            first = group[0]
            metrics: dict[tuple[str, str], Any] = {}
            for row in group:
                metrics.setdefault(
                    (str(row.get("section_code") or ""), str(row.get("metric_code") or "")),
                    row.get("metric_value", ""),
                )
            statistical_date = str(first.get("date_record") or "") or dates_by_filter.get(filter_hash, "") or file_date
            detail_records.append(
                [
                    str(first.get("dimension_name") or ""),
                    product_name,
                    statistical_date,
                    str(first.get("date_range_name") or first.get("period_label") or _TIME_DIMENSION_LABELS.get(date_range, date_range)),
                    *[
                        metrics.get((section_code, metric_code), "")
                        for section_code, metric_code, _name, _section_order, _metric_order in metric_schema
                    ],
                ]
            )
        destination = export_root / (
            f"{_safe_file_name_component(institution, '未知机构')}经营明细标准报表_"
            f"{_safe_file_name_component(product_name, '未知产品')}_"
            f"{_safe_file_name_component(_TIME_DIMENSION_LABELS.get(date_range, date_range), '时间维度')}_"
            f"{file_date}.csv"
        )
        _write_csv_matrix(destination, detail_headers, detail_records)
        paths.append(str(destination))
    return paths


def _write_csv_matrix(destination: Path, headers: list[str], records: list[list[Any]]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows(records)
    content = stream.getvalue().encode("utf-8-sig")
    digest = hashlib.sha256(content).hexdigest()
    temporary = destination.parent / f".{destination.name}.{digest[:12]}.tmp"
    temporary.write_bytes(content)
    temporary.replace(destination)


def _rows_to_csv(rows: list[dict[str, Any]]) -> bytes:
    headers: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            field = str(key)
            if field not in seen:
                seen.add(field)
                headers.append(field)
    stream = io.StringIO(newline="")
    if headers:
        writer = csv.DictWriter(stream, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_cell(row.get(key)) for key in headers})
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def _crawler_csv_file_name(dataset_code: str, observed_at: str, artifact_id: str) -> str:
    try:
        stamp = _parse_timestamp(observed_at).strftime("%Y%m%d_%H%M%S")
    except (TypeError, ValueError):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{dataset_code}_{stamp}_{artifact_id[-8:]}.csv"


def _crawler_csv_fields(
    rows: list[dict[str, Any]],
    file_name: str,
    usage_scenario: str,
    related_intent: str,
) -> list[dict[str, Any]]:
    headers: list[str] = []
    seen_headers: set[str] = set()
    for row in rows:
        for raw_key in row:
            key = str(raw_key).strip()
            if key and key not in seen_headers:
                seen_headers.add(key)
                headers.append(key)
    fields: list[dict[str, Any]] = []
    used_codes: set[str] = set()
    for index, header in enumerate(headers, start=1):
        base_code = _safe_asset_identifier(header, f"field_{index:03d}")
        field_code = base_code
        suffix = 2
        while field_code in used_codes:
            field_code = f"{base_code[:190]}_{suffix}"
            suffix += 1
        used_codes.add(field_code)
        samples: list[Any] = []
        for row in rows:
            value = row.get(header)
            if value in (None, ""):
                continue
            samples.append(value)
            if len(samples) >= 200:
                break
        field_type = _infer_crawler_field_type(header, samples)
        fields.append(
            {
                "fieldNameEn": field_code,
                "fieldNameCn": header,
                "type": field_type,
                "explanation": f"由爬虫 CSV 文件 {file_name} 自动识别，原始列名为“{header}”。",
                "isTime": field_type in {"date", "datetime"},
                "isMetric": field_type in {"integer", "decimal"},
                "notes": "爬虫产物字段；修改字段语义不会改写原始 CSV。",
                "exampleUsage": f"使用场景：{usage_scenario}；关联意图：{related_intent}",
            }
        )
    if not fields:
        raise ValueError("crawler_csv_fields_required")
    return fields


def _safe_asset_identifier(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.]+", "_", str(value or "").strip()).strip("_.")
    if not normalized or not re.match(r"^[A-Za-z_]", normalized):
        normalized = str(fallback or "field").strip() or "field"
    normalized = re.sub(r"[^A-Za-z0-9_.]+", "_", normalized)
    if not re.match(r"^[A-Za-z_]", normalized):
        normalized = f"field_{normalized}"
    return normalized[:200]


def _safe_file_name_component(value: str, fallback: str) -> str:
    normalized = re.sub(r"[\\/:*?\"<>|\r\n]+", "_", str(value or "").strip()).strip(" ._")
    return (normalized or fallback)[:120]


def _infer_crawler_field_type(header: str, samples: list[Any]) -> str:
    lowered = header.lower()
    if any(token in lowered for token in ("datetime", "timestamp", "日期时间", "统计时间")):
        return "datetime"
    if any(token in lowered for token in ("date", "日期")):
        return "date"
    if samples and all(isinstance(value, bool) or str(value).strip().lower() in {"true", "false"} for value in samples):
        return "boolean"
    if samples and all(_is_integer_value(value) for value in samples):
        return "integer"
    if samples and all(_is_decimal_value(value) for value in samples):
        return "decimal"
    return "string"


def _is_integer_value(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return bool(re.fullmatch(r"[-+]?\d+", str(value).strip().replace(",", "")))


def _is_decimal_value(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    return bool(re.fullmatch(r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)", str(value).strip().replace(",", "")))


def _first_matching_field(field_codes: dict[str, str], tokens: tuple[str, ...]) -> str:
    for label, code in field_codes.items():
        haystack = f"{label} {code}".lower()
        if any(token.lower() in haystack for token in tokens):
            return code
    return ""


def _default_crawler_intent(profile_id: str, dataset_id: str) -> str:
    if "funnel" in profile_id.lower():
        return "经营分析 / 漏斗转化与流失归因"
    if "business_sandbox" in profile_id.lower():
        return "经营分析 / 经营沙盘指标与趋势"
    return f"数据获取 / {dataset_id or '爬虫数据分析'}"


def _crawler_page_name(profile_id: str) -> str:
    normalized = str(profile_id or "").lower()
    if "business_sandbox" in normalized:
        return "经营沙盘"
    if "funnel" in normalized:
        return "漏斗分析"
    return "数据页面"


def _csv_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("source_snapshot_timezone_required")
    return parsed.astimezone(timezone.utc)


def _safe_failure(exc: Exception) -> tuple[str, str, dict[str, Any]]:
    if isinstance(exc, CrawlerExecutionError):
        return (
            exc.error_code,
            exc.summary,
            {"source_snapshot": {}, "diagnostics": exc.diagnostic.to_dict()},
        )
    if isinstance(exc, AcquisitionQualityGateError):
        return (
            "quality_gate_failed",
            "采集结果未通过阻断型质量规则，产物已隔离并进入修复评审。",
            {
                "quality_summary": exc.quality_summary,
                "artifact_id": exc.artifact_id,
                "rows_read": exc.rows_read,
                "source_snapshot": exc.source_snapshot,
            },
        )
    if isinstance(exc, PermissionError):
        return "source_governance_rejected", "数据源未确认租户/机构过滤或脚本治理要求，运行已拒绝。", {}
    if str(exc) == "source_row_limit_exceeded":
        return "source_row_limit_exceeded", "数据源返回行数超过租户系统参数上限，运行已拒绝。", {}
    if isinstance(exc, ValueError):
        return "acquisition_validation_failed", "采集定义、脚本参数或数据质量配置无效。", {}
    return "source_execution_failed", "真实数据源执行失败；请使用运行 ID 查询受控服务端日志。", {}


def _recommended_action(error_code: str) -> str:
    return {
        "LOGIN_FAILED": "检查账号、密码、登录页和账号状态；不得绕过验证码或 MFA。",
        "ACCOUNT_EXPIRED": "更新账号凭证并重新执行全链路连通性测试。",
        "PAGE_CHANGED": "根据脱敏 DOM 和截图修复选择器 DSL，经沙箱验证和人工审批后发布新版本。",
        "SQL_PARSE_FAILED": "修正为单条只读查询；LLM 不得改写业务 SQL。",
        "METADATA_FETCH_FAILED": "检查原始表定位和元数据页面选择器后重试。",
        "SQL_EXECUTION_FAILED": "检查毓数查询页、只读 SQL 和上游执行状态。",
        "CSV_DOWNLOAD_FAILED": "检查下载按钮、等待条件和浏览器下载权限。",
        "CSV_SCHEMA_CHANGED": "比较主题表输出 Schema，人工确认后更新字段映射。",
        "EMPTY_RESULT": "确认数据分区、过滤条件和业务日期，不自动放宽业务查询条件。",
        "NETWORK_ERROR": "检查受控出口和外部系统状态，并按退避策略重试。",
        "MANUAL_INTERVENTION_REQUIRED": "需要人工完成验证码、MFA 或账号解锁。",
        "TRANSPORT_NOT_CONFIGURED": "部署独立 Playwright Crawler Worker 并显式启用真实传输。",
        "quality_gate_failed": "检查阻断型质量结果、上游分区和字段映射；修复后创建新脚本版本。",
        "source_governance_rejected": "确认上游返回 applied_filters，并对 SQL 返回 catalog_validated 与 tenant_policy_injected。",
        "acquisition_validation_failed": "修正脚本配置或任务质量规则，提交新版本并由另一位用户审批。",
        "source_row_limit_exceeded": "缩小分区或过滤范围，或由管理员在容量评估后调整单次采集最大行数。",
        "source_execution_failed": "检查已验证连接、上游健康状态和快照证据，再生成修复候选。",
    }.get(error_code, "人工复核后创建新版本。")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounded_keep_latest_n(value: Any) -> int:
    try:
        return max(1, min(int(value), 30))
    except (TypeError, ValueError):
        return 3
