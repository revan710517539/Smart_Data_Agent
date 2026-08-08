from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from backend.platform.data_access import HTTPJSONSourceClient
from backend.platform.security.sql_validation import validate_read_only_sql_candidate

from .artifacts import LocalArtifactObjectStore
from .csv_folder import CSVFolderSource
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
        data_asset_store: Any | None = None,
    ) -> None:
        self.store = store
        self.object_store = object_store
        self.system_config_store = system_config_store
        self.model_call_repository = model_call_repository
        self.transform_sandbox = RestrictedRowTransformSandbox()
        self.repair_generator = ModelAcquisitionRepairGenerator(system_config_store, self.transform_sandbox)
        self.csv_source = CSVFolderSource.from_environment()
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
                    "retention": retention_summary,
                },
            )
            return {**completed, "retention": retention_summary}
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
        return {
            **self.store.bundle(tenant_id),
            "source_mode": "csv_folder",
            "source_read_only": True,
            # The acquisition overview must expose the same institution-bound
            # catalog as the raw-table tab. Never disclose the shared root or
            # another institution's delivery inventory.
            "csv_source": self.csv_source.for_tenant(tenant_id).snapshot(),
        }

    def read_csv_source_file(self, relative_path: str) -> bytes:
        return self.csv_source.read(relative_path)

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
            raise PermissionError("browser_acquisition_runtime_removed")
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


def _rows_to_csv(rows: list[dict[str, Any]]) -> bytes:
    """Serialize governed application output without involving source intake."""

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
