from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.platform.storage import connect_sqlite


SOURCE_CATEGORIES = {
    "internal_operation",
    "yushu",
    "smart_operation",
    "market",
    "warehouse",
    "file_exchange",
    "other",
}
SCRIPT_RUNTIMES = {"python", "sql", "http", "shell_restricted"}


class SQLiteAcquisitionStore:
    """Tenant-scoped persistence for acquisition definitions and execution facts."""

    def __init__(self, db_path: str | Path, initialize: bool = False) -> None:
        self.db_path = str(db_path)
        self._conn = connect_sqlite(self.db_path)
        self._conn.row_factory = sqlite3.Row
        if initialize:
            self.init_schema()

    def close(self) -> None:
        self._conn.close()

    def init_schema(self) -> None:
        migration_dir = Path(__file__).resolve().parents[1] / "database" / "sql"
        acquisition_sql = (migration_dir / "0006_data_acquisition_runtime.sql").read_text(encoding="utf-8")
        self._conn.executescript(acquisition_sql)
        self._conn.executescript((migration_dir / "0021_lineage_runtime.sql").read_text(encoding="utf-8"))
        self._conn.commit()

    def ensure_connection_reference(self, tenant_id: str, connection_id: str) -> None:
        row = self._conn.execute(
            "SELECT 1 FROM platform_data_connections WHERE tenant_id = ? AND connection_id = ?",
            (tenant_id, connection_id),
        ).fetchone()
        if not row:
            raise KeyError("data_connection_not_found")

    def create_source(self, tenant_id: str, payload: dict[str, Any], created_by: str) -> dict[str, Any]:
        source_code = _required_code(payload.get("source_code", payload.get("sourceCode")), "source_code")
        source_name = _required_text(payload.get("source_name", payload.get("sourceName")), "source_name", 300)
        category = str(payload.get("source_category", payload.get("sourceCategory")) or "other").strip()
        if category not in SOURCE_CATEGORIES:
            raise ValueError("invalid_source_category")
        source_id = str(payload.get("source_system_id", payload.get("sourceSystemId")) or f"src_{uuid4().hex}")
        license_metadata = _json_object(payload.get("license_metadata", payload.get("licenseMetadata", {})))
        if category == "market" and not any(license_metadata.get(key) for key in ("license_type", "terms_url", "contract_ref")):
            raise ValueError("market_source_license_metadata_required")
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_source_systems(
                    tenant_id, source_system_id, source_code, source_name, source_category,
                    license_metadata, status, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (tenant_id, source_id, source_code, source_name, category, _json(license_metadata), created_by, now, now),
            )
        return self.get_source(tenant_id, source_id)

    def get_source(self, tenant_id: str, source_system_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM platform_source_systems WHERE tenant_id = ? AND source_system_id = ?",
            (tenant_id, source_system_id),
        ).fetchone()
        if not row:
            raise KeyError("source_system_not_found")
        return _source_row(row)

    def list_sources(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM platform_source_systems WHERE tenant_id = ? ORDER BY source_name, source_system_id",
            (tenant_id,),
        ).fetchall()
        return [_source_row(row) for row in rows]

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
        now = _utcnow()
        with self._conn:
            existing = self._conn.execute(
                "SELECT * FROM platform_acquisition_scripts WHERE tenant_id = ? AND script_code = ?",
                (tenant_id, script_code),
            ).fetchone()
            if existing:
                if str(existing["owner_user_id"]) != created_by:
                    raise PermissionError("script_owner_required")
                if str(existing["runtime"]) != runtime:
                    raise ValueError("script_runtime_is_immutable")
                script_id = str(existing["acquisition_script_id"])
                version_no = int(
                    self._conn.execute(
                        "SELECT COALESCE(MAX(version_no), 0) FROM platform_acquisition_script_versions WHERE tenant_id = ? AND acquisition_script_id = ?",
                        (tenant_id, script_id),
                    ).fetchone()[0]
                ) + 1
                self._conn.execute(
                    "UPDATE platform_acquisition_scripts SET script_name = ?, status = 'review', updated_at = ? WHERE tenant_id = ? AND acquisition_script_id = ?",
                    (script_name, now, tenant_id, script_id),
                )
            else:
                script_id = str(payload.get("acquisition_script_id", payload.get("acquisitionScriptId")) or f"as_{uuid4().hex}")
                version_no = 1
                self._conn.execute(
                    """
                    INSERT INTO platform_acquisition_scripts(
                        tenant_id, acquisition_script_id, script_code, script_name, runtime,
                        current_version_no, owner_user_id, status, created_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 0, ?, 'review', ?, ?, ?)
                    """,
                    (tenant_id, script_id, script_code, script_name, runtime, created_by, created_by, now, now),
                )
            version_id = f"asv_{uuid4().hex}"
            source_hash = hashlib.sha256(source_code.encode("utf-8")).hexdigest()
            self._conn.execute(
                """
                INSERT INTO platform_acquisition_script_versions(
                    tenant_id, script_version_id, acquisition_script_id, version_no,
                    source_code, source_hash, dependency_lock, input_schema, output_schema,
                    review_status, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    tenant_id,
                    version_id,
                    script_id,
                    version_no,
                    source_code,
                    source_hash,
                    _json(dependency_lock),
                    _json(input_schema),
                    _json(output_schema),
                    created_by,
                    now,
                ),
            )
        return self.get_script_version(tenant_id, version_id, reveal_source=True)

    def get_script_version(self, tenant_id: str, script_version_id: str, reveal_source: bool = False) -> dict[str, Any]:
        row = self._conn.execute(
            """
            SELECT v.*, s.script_code, s.script_name, s.runtime, s.owner_user_id, s.status AS script_status
            FROM platform_acquisition_script_versions v
            JOIN platform_acquisition_scripts s
              ON s.tenant_id = v.tenant_id AND s.acquisition_script_id = v.acquisition_script_id
            WHERE v.tenant_id = ? AND v.script_version_id = ?
            """,
            (tenant_id, script_version_id),
        ).fetchone()
        if not row:
            raise KeyError("script_version_not_found")
        return _script_version_row(row, reveal_source=reveal_source)

    def list_scripts(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT v.*, s.script_code, s.script_name, s.runtime, s.owner_user_id, s.status AS script_status
            FROM platform_acquisition_script_versions v
            JOIN platform_acquisition_scripts s
              ON s.tenant_id = v.tenant_id AND s.acquisition_script_id = v.acquisition_script_id
            WHERE v.tenant_id = ?
            ORDER BY s.script_code, v.version_no DESC
            """,
            (tenant_id,),
        ).fetchall()
        return [_script_version_row(row, reveal_source=False) for row in rows]

    def review_script_version(self, tenant_id: str, script_version_id: str, decision: str, reviewer: str) -> dict[str, Any]:
        normalized = str(decision or "").strip().lower()
        if normalized not in {"approved", "rejected", "revoked"}:
            raise ValueError("invalid_script_review_decision")
        version = self.get_script_version(tenant_id, script_version_id, reveal_source=True)
        if version["review_status"] != "pending":
            raise ValueError("script_version_is_not_pending")
        if version["created_by"] == reviewer:
            raise PermissionError("four_eyes_script_review_required")
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                UPDATE platform_acquisition_script_versions
                SET review_status = ?, reviewed_by = ?, reviewed_at = ?
                WHERE tenant_id = ? AND script_version_id = ?
                """,
                (normalized, reviewer, now, tenant_id, script_version_id),
            )
            if normalized == "approved":
                self._conn.execute(
                    """
                    UPDATE platform_acquisition_scripts
                    SET current_version_no = ?, status = 'active', updated_at = ?
                    WHERE tenant_id = ? AND acquisition_script_id = ?
                    """,
                    (version["version_no"], now, tenant_id, version["acquisition_script_id"]),
                )
        return self.get_script_version(tenant_id, script_version_id, reveal_source=False)

    def create_job(self, tenant_id: str, payload: dict[str, Any], created_by: str) -> dict[str, Any]:
        script_version_id = _required_text(payload.get("script_version_id", payload.get("scriptVersionId")), "script_version_id", 160)
        version = self.get_script_version(tenant_id, script_version_id, reveal_source=False)
        if version["review_status"] != "approved":
            raise ValueError("approved_script_version_required")
        source_system_id = _required_text(payload.get("source_system_id", payload.get("sourceSystemId")), "source_system_id", 160)
        self.get_source(tenant_id, source_system_id)
        connection_id = _required_text(payload.get("connection_id", payload.get("connectionId")), "connection_id", 160)
        self.ensure_connection_reference(tenant_id, connection_id)
        job_code = _required_code(payload.get("job_code", payload.get("jobCode")), "job_code")
        job_name = _required_text(payload.get("job_name", payload.get("jobName")), "job_name", 300)
        target_dataset_id = _required_text(payload.get("target_dataset_id", payload.get("targetDatasetId")), "target_dataset_id", 200)
        topic_table_id = str(payload.get("topic_table_id", payload.get("topicTableId")) or "").strip() or None
        trigger_type = str(payload.get("trigger_type", payload.get("triggerType")) or "manual").strip()
        if trigger_type not in {"manual", "schedule", "event"}:
            raise ValueError("invalid_acquisition_trigger_type")
        execution_mode = str(payload.get("execution_mode", payload.get("executionMode")) or "offline").strip()
        if execution_mode not in {"realtime", "offline"}:
            raise ValueError("invalid_acquisition_execution_mode")
        schedule_expression = str(payload.get("schedule_expression", payload.get("scheduleExpression")) or "").strip() or None
        if trigger_type == "schedule" and not schedule_expression:
            raise ValueError("schedule_expression_required")
        job_config = _json_object(payload.get("job_config", payload.get("jobConfig", {})))
        job_id = str(payload.get("acquisition_job_id", payload.get("acquisitionJobId")) or f"aj_{uuid4().hex}")
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_acquisition_jobs(
                    tenant_id, acquisition_job_id, job_code, job_name, source_system_id,
                    script_version_id, connection_id, target_dataset_id, topic_table_id,
                    trigger_type, schedule_expression, execution_mode, job_config, status,
                    owner_user_id, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    job_id,
                    job_code,
                    job_name,
                    source_system_id,
                    script_version_id,
                    connection_id,
                    target_dataset_id,
                    topic_table_id,
                    trigger_type,
                    schedule_expression,
                    execution_mode,
                    _json(job_config),
                    created_by,
                    created_by,
                    now,
                    now,
                ),
            )
        return self.get_job(tenant_id, job_id)

    def get_job(self, tenant_id: str, acquisition_job_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM platform_acquisition_jobs WHERE tenant_id = ? AND acquisition_job_id = ?",
            (tenant_id, acquisition_job_id),
        ).fetchone()
        if not row:
            raise KeyError("acquisition_job_not_found")
        return _job_row(row)

    def list_jobs(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM platform_acquisition_jobs WHERE tenant_id = ? ORDER BY job_name, acquisition_job_id",
            (tenant_id,),
        ).fetchall()
        return [_job_row(row) for row in rows]

    def queue_run(
        self,
        tenant_id: str,
        acquisition_job_id: str,
        idempotency_key: str,
        trigger_type: str,
        created_by: str,
        input_cursor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.get_job(tenant_id, acquisition_job_id)
        key = _required_text(idempotency_key, "idempotency_key", 200)
        existing = self._conn.execute(
            """
            SELECT * FROM platform_acquisition_job_runs
            WHERE tenant_id = ? AND acquisition_job_id = ? AND idempotency_key = ?
            """,
            (tenant_id, acquisition_job_id, key),
        ).fetchone()
        if existing:
            return _run_row(existing)
        run_id = f"ar_{uuid4().hex}"
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_acquisition_job_runs(
                    tenant_id, acquisition_run_id, acquisition_job_id, trigger_type,
                    idempotency_key, status, input_cursor, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?)
                """,
                (tenant_id, run_id, acquisition_job_id, trigger_type, key, _json(input_cursor or {}), created_by, now, now),
            )
        return self.get_run(tenant_id, run_id)

    def get_run(self, tenant_id: str, acquisition_run_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM platform_acquisition_job_runs WHERE tenant_id = ? AND acquisition_run_id = ?",
            (tenant_id, acquisition_run_id),
        ).fetchone()
        if not row:
            raise KeyError("acquisition_run_not_found")
        return _run_row(row)

    def list_runs(self, tenant_id: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT * FROM platform_acquisition_job_runs
            WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?
            """,
            (tenant_id, max(1, min(int(limit), 500))),
        ).fetchall()
        return [_run_row(row) for row in rows]

    def update_run(self, tenant_id: str, acquisition_run_id: str, **changes: Any) -> dict[str, Any]:
        allowed = {
            "status",
            "output_cursor",
            "rows_read",
            "rows_written",
            "source_snapshot",
            "quality_summary",
            "output_artifact_id",
            "partition_id",
            "started_at",
            "finished_at",
            "error_code",
            "error_summary",
        }
        unexpected = set(changes) - allowed
        if unexpected:
            raise ValueError(f"unsupported_run_fields:{','.join(sorted(unexpected))}")
        if not changes:
            return self.get_run(tenant_id, acquisition_run_id)
        self.get_run(tenant_id, acquisition_run_id)
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in changes.items():
            assignments.append(f"{key} = ?")
            values.append(_json(value) if key in {"output_cursor", "source_snapshot", "quality_summary"} else value)
        assignments.append("updated_at = ?")
        values.append(_utcnow())
        values.extend([tenant_id, acquisition_run_id])
        with self._conn:
            self._conn.execute(
                f"UPDATE platform_acquisition_job_runs SET {', '.join(assignments)} WHERE tenant_id = ? AND acquisition_run_id = ?",
                tuple(values),
            )
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
        existing = self._conn.execute(
            """
            SELECT artifact_id FROM platform_data_artifacts
            WHERE tenant_id = ? AND content_hash = ? AND object_uri = ?
            """,
            (tenant_id, content_hash, object_uri),
        ).fetchone()
        if existing:
            return self.get_artifact(tenant_id, str(existing["artifact_id"]))
        artifact_id = f"da_{uuid4().hex}"
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_data_artifacts(
                    tenant_id, artifact_id, artifact_type, object_uri, content_hash,
                    content_type, size_bytes, status, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (tenant_id, artifact_id, artifact_type, object_uri, content_hash, content_type, size_bytes, status, created_by, now, now),
            )
        return self.get_artifact(tenant_id, artifact_id)

    def get_artifact(self, tenant_id: str, artifact_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM platform_data_artifacts WHERE tenant_id = ? AND artifact_id = ?",
            (tenant_id, artifact_id),
        ).fetchone()
        if not row:
            raise KeyError("data_artifact_not_found")
        return dict(row)

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
        partition_id = f"dp_{uuid4().hex}"
        normalized_key = _json(partition_key)
        partition_hash = hashlib.sha256(normalized_key.encode("utf-8")).hexdigest()
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_dataset_partitions(
                    tenant_id, partition_id, dataset_id, topic_table_id, org_unit_id,
                    partition_key, partition_hash, artifact_id, source_version,
                    snapshot_at, watermark_at, row_count, data_hash, freshness_status,
                    acquisition_run_id, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    partition_id,
                    dataset_id,
                    topic_table_id,
                    org_unit_id,
                    normalized_key,
                    partition_hash,
                    artifact_id,
                    source_version,
                    snapshot_at,
                    watermark_at,
                    row_count,
                    data_hash,
                    freshness_status,
                    acquisition_run_id,
                    created_by,
                    now,
                ),
            )
            self._conn.execute(
                "UPDATE platform_acquisition_job_runs SET partition_id = ?, updated_at = ? WHERE tenant_id = ? AND acquisition_run_id = ?",
                (partition_id, now, tenant_id, acquisition_run_id),
            )
        row = self._conn.execute(
            "SELECT * FROM platform_dataset_partitions WHERE tenant_id = ? AND partition_id = ?",
            (tenant_id, partition_id),
        ).fetchone()
        assert row is not None
        result = dict(row)
        result["partition_key"] = _load_json(result["partition_key"], {})
        return result

    def save_quality_results(
        self,
        tenant_id: str,
        acquisition_run_id: str,
        results: list[dict[str, Any]],
        created_by: str,
        partition_id: str | None = None,
    ) -> None:
        with self._conn:
            for result in results:
                self._conn.execute(
                    """
                    INSERT INTO platform_data_quality_results(
                        tenant_id, quality_result_id, acquisition_run_id, partition_id,
                        rule_code, status, score, observed_value, threshold_value,
                        blocking, evaluated_at, created_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tenant_id,
                        f"qr_{uuid4().hex}",
                        acquisition_run_id,
                        partition_id,
                        str(result["rule_code"]),
                        str(result["status"]),
                        float(result.get("score", 0)),
                        _json(result.get("observed_value", {})),
                        _json(result.get("threshold", {})),
                        1 if result.get("blocking") else 0,
                        _utcnow(),
                        created_by,
                    ),
                )

    def list_quality_results(self, tenant_id: str, limit: int = 500) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT q.*, r.acquisition_job_id, j.target_dataset_id, j.topic_table_id,
                   r.source_snapshot, r.quality_summary, r.status AS run_status
            FROM platform_data_quality_results q
            JOIN platform_acquisition_job_runs r
              ON r.tenant_id = q.tenant_id AND r.acquisition_run_id = q.acquisition_run_id
            JOIN platform_acquisition_jobs j
              ON j.tenant_id = r.tenant_id AND j.acquisition_job_id = r.acquisition_job_id
            WHERE q.tenant_id = ?
            ORDER BY q.evaluated_at DESC, q.quality_result_id DESC
            LIMIT ?
            """,
            (tenant_id, max(1, min(int(limit), 2_000))),
        ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for key in ("observed_value", "threshold_value", "source_snapshot", "quality_summary"):
                item[key] = _load_json(item.get(key), {})
            item["blocking"] = bool(item.get("blocking"))
            results.append(item)
        return results

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
        candidate_hash = hashlib.sha256(candidate.encode("utf-8")).hexdigest() if candidate else None
        proposal_id = f"rp_{uuid4().hex}"
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_acquisition_repair_proposals(
                    tenant_id, repair_proposal_id, acquisition_run_id, failed_script_version_id,
                    diagnosis, generation_method, candidate_source_code, candidate_hash,
                    review_status, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    tenant_id,
                    proposal_id,
                    acquisition_run_id,
                    failed_script_version_id,
                    _json(diagnosis),
                    generation_method,
                    candidate,
                    candidate_hash,
                    created_by,
                    now,
                    now,
                ),
            )
            self._conn.execute(
                "UPDATE platform_acquisition_job_runs SET status = 'repair_review', updated_at = ? WHERE tenant_id = ? AND acquisition_run_id = ?",
                (now, tenant_id, acquisition_run_id),
            )
        return self.get_repair_proposal(tenant_id, proposal_id, reveal_candidate=False)

    def get_repair_proposal(self, tenant_id: str, proposal_id: str, reveal_candidate: bool = False) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM platform_acquisition_repair_proposals WHERE tenant_id = ? AND repair_proposal_id = ?",
            (tenant_id, proposal_id),
        ).fetchone()
        if not row:
            raise KeyError("repair_proposal_not_found")
        return _repair_row(row, reveal_candidate)

    def list_repair_proposals(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM platform_acquisition_repair_proposals WHERE tenant_id = ? ORDER BY created_at DESC",
            (tenant_id,),
        ).fetchall()
        return [_repair_row(row, False) for row in rows]

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
        now = _utcnow()
        applied_version_id: str | None = None
        with self._conn:
            if normalized == "approved":
                version_no = max(
                    int(failed["version_no"]) + 1,
                    int(
                        self._conn.execute(
                            "SELECT COALESCE(MAX(version_no), 0) FROM platform_acquisition_script_versions WHERE tenant_id = ? AND acquisition_script_id = ?",
                            (tenant_id, failed["acquisition_script_id"]),
                        ).fetchone()[0]
                    )
                    + 1,
                )
                applied_version_id = f"asv_{uuid4().hex}"
                source_code = str(proposal["candidate_source_code"])
                self._conn.execute(
                    """
                    INSERT INTO platform_acquisition_script_versions(
                        tenant_id, script_version_id, acquisition_script_id, version_no,
                        source_code, source_hash, dependency_lock, input_schema, output_schema,
                        review_status, reviewed_by, reviewed_at, created_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?, ?, ?)
                    """,
                    (
                        tenant_id,
                        applied_version_id,
                        failed["acquisition_script_id"],
                        version_no,
                        source_code,
                        hashlib.sha256(source_code.encode("utf-8")).hexdigest(),
                        _json(failed.get("dependency_lock", {})),
                        _json(failed.get("input_schema", {})),
                        _json(failed.get("output_schema", {})),
                        reviewer,
                        now,
                        reviewer,
                        now,
                    ),
                )
                self._conn.execute(
                    """
                    UPDATE platform_acquisition_scripts
                    SET current_version_no = ?, status = 'active', updated_at = ?
                    WHERE tenant_id = ? AND acquisition_script_id = ?
                    """,
                    (version_no, now, tenant_id, failed["acquisition_script_id"]),
                )
                self._conn.execute(
                    """
                    UPDATE platform_acquisition_jobs
                    SET script_version_id = ?, updated_at = ?
                    WHERE tenant_id = ? AND acquisition_job_id = (
                        SELECT acquisition_job_id
                        FROM platform_acquisition_job_runs
                        WHERE tenant_id = ? AND acquisition_run_id = ?
                    )
                    """,
                    (applied_version_id, now, tenant_id, tenant_id, proposal["acquisition_run_id"]),
                )
            self._conn.execute(
                """
                UPDATE platform_acquisition_repair_proposals
                SET review_status = ?, reviewed_by = ?, reviewed_at = ?,
                    applied_script_version_id = ?, updated_at = ?
                WHERE tenant_id = ? AND repair_proposal_id = ?
                """,
                ("applied" if normalized == "approved" else "rejected", reviewer, now, applied_version_id, now, tenant_id, proposal_id),
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
        event_id = f"oe_{uuid4().hex}"
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_outbox_events(
                    tenant_id, outbox_event_id, aggregate_type, aggregate_id,
                    event_type, payload, status, available_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (tenant_id, event_id, aggregate_type, aggregate_id, event_type, _json(payload), now, now, now),
            )
        return {"outbox_event_id": event_id, "event_type": event_type, "status": "pending"}

    def enqueue_outbox_event_once(
        self,
        tenant_id: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        row = self._conn.execute(
            """
            SELECT outbox_event_id, event_type, status
            FROM platform_outbox_events
            WHERE tenant_id = ? AND aggregate_type = ? AND aggregate_id = ? AND event_type = ?
            ORDER BY created_at LIMIT 1
            """,
            (tenant_id, aggregate_type, aggregate_id, event_type),
        ).fetchone()
        if row:
            return dict(row)
        return self.enqueue_outbox_event(tenant_id, aggregate_type, aggregate_id, event_type, payload)

    def latest_artifact(self, tenant_id: str, topic_table_id: str, org_unit_id: str | None) -> dict[str, Any]:
        if not topic_table_id:
            raise ValueError("topic_table_id_required")
        if org_unit_id:
            row = self._conn.execute(
                """
                SELECT p.*, a.object_uri, a.content_hash, a.content_type, a.size_bytes, a.status AS artifact_status
                FROM platform_dataset_partitions p
                JOIN platform_data_artifacts a
                  ON a.tenant_id = p.tenant_id AND a.artifact_id = p.artifact_id
                WHERE p.tenant_id = ? AND p.topic_table_id = ? AND p.org_unit_id = ?
                  AND p.freshness_status = 'fresh' AND a.status = 'active'
                ORDER BY p.snapshot_at DESC, p.created_at DESC LIMIT 1
                """,
                (tenant_id, topic_table_id, org_unit_id),
            ).fetchone()
        else:
            row = self._conn.execute(
                """
                SELECT p.*, a.object_uri, a.content_hash, a.content_type, a.size_bytes, a.status AS artifact_status
                FROM platform_dataset_partitions p
                JOIN platform_data_artifacts a
                  ON a.tenant_id = p.tenant_id AND a.artifact_id = p.artifact_id
                WHERE p.tenant_id = ? AND p.topic_table_id = ? AND p.org_unit_id IS NULL
                  AND p.freshness_status = 'fresh' AND a.status = 'active'
                ORDER BY p.snapshot_at DESC, p.created_at DESC LIMIT 1
                """,
                (tenant_id, topic_table_id),
            ).fetchone()
        if not row:
            raise KeyError("latest_topic_table_artifact_not_found")
        result = dict(row)
        result["partition_key"] = _load_json(result["partition_key"], {})
        return result

    def get_topic_definition(self, tenant_id: str, topic_table_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            """
            SELECT payload, lifecycle_status, current_version, updated_at
            FROM platform_data_asset_items
            WHERE tenant_id = ? AND item_type = 'topic_table'
              AND (item_id = ? OR json_extract(payload, '$.code') = ?)
            LIMIT 1
            """,
            (tenant_id, topic_table_id, topic_table_id),
        ).fetchone()
        if not row:
            normalized = self._conn.execute(
                "SELECT * FROM platform_topic_tables WHERE tenant_id = ? AND (topic_table_id = ? OR topic_code = ?) LIMIT 1",
                (tenant_id, topic_table_id, topic_table_id),
            ).fetchone()
            if not normalized:
                raise KeyError("topic_table_not_found")
            return {
                "id": str(normalized["topic_table_id"]),
                "code": str(normalized["topic_code"]),
                "name": str(normalized["topic_name"]),
                "description": str(normalized["description"]),
                "sql": str(normalized["query_template"]),
                "status": str(normalized["status"]),
                "version": int(normalized["current_version_no"]),
            }
        payload = _load_json(row["payload"], {})
        return {
            **payload,
            "id": str(payload.get("id") or topic_table_id),
            "code": str(payload.get("code") or payload.get("id") or topic_table_id),
            "name": str(payload.get("name") or payload.get("code") or topic_table_id),
            "sql": str(payload.get("sql") or ""),
            "status": str(row["lifecycle_status"]),
            "version": int(row["current_version"]),
            "updated_at": str(row["updated_at"]),
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
        self.ensure_connection_reference(tenant_id, connection_id)
        topic_code = str(topic.get("code") or topic.get("id") or "").strip()
        topic_id = f"tt_{hashlib.sha256(f'{tenant_id}:{topic_code}'.encode()).hexdigest()[:24]}"
        now = _utcnow()
        query = str(topic.get("sql") or "")
        query_hash = str(decomposition.get("query_hash") or hashlib.sha256(query.encode()).hexdigest())
        changed: list[str] = []
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_topic_tables(
                    tenant_id, topic_table_id, topic_code, topic_name, description,
                    current_version_no, query_template, query_hash, status, validated_at,
                    created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'published', ?, ?, ?, ?)
                ON CONFLICT(tenant_id, topic_code) DO UPDATE SET
                    topic_name = excluded.topic_name, description = excluded.description,
                    current_version_no = excluded.current_version_no,
                    query_template = excluded.query_template, query_hash = excluded.query_hash,
                    status = 'published', validated_at = excluded.validated_at, updated_at = excluded.updated_at
                """,
                (
                    tenant_id, topic_id, topic_code, str(topic.get("name") or topic_code),
                    str(topic.get("description") or ""), int(topic.get("version") or 1),
                    query, query_hash, now, actor_user_id, now, now,
                ),
            )
            topic_row = self._conn.execute(
                "SELECT topic_table_id FROM platform_topic_tables WHERE tenant_id = ? AND topic_code = ?",
                (tenant_id, topic_code),
            ).fetchone()
            topic_id = str(topic_row["topic_table_id"])
            self._conn.execute(
                "DELETE FROM platform_topic_table_sources WHERE tenant_id = ? AND topic_table_id = ?",
                (tenant_id, topic_id),
            )
            for position, table in enumerate(tables):
                dataset_code = str(table.get("qualified_name") or table.get("table") or "").strip()
                dataset_id = f"ds_{hashlib.sha256(f'{tenant_id}:{connection_id}:{dataset_code}'.encode()).hexdigest()[:24]}"
                schema_hash = str(table.get("schema_hash") or hashlib.sha256(_json(table.get("fields", [])).encode()).hexdigest())
                existing = self._conn.execute(
                    "SELECT schema_hash FROM platform_datasets WHERE tenant_id = ? AND dataset_code = ?",
                    (tenant_id, dataset_code),
                ).fetchone()
                if existing and str(existing["schema_hash"] or "") not in {"", schema_hash}:
                    changed.append(dataset_code)
                self._conn.execute(
                    """
                    INSERT INTO platform_datasets(
                        tenant_id, dataset_id, connection_id, dataset_code, dataset_name,
                        physical_locator, dataset_type, status, schema_hash, created_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'table', 'active', ?, ?, ?, ?)
                    ON CONFLICT(tenant_id, dataset_code) DO UPDATE SET
                        connection_id = excluded.connection_id, dataset_name = excluded.dataset_name,
                        physical_locator = excluded.physical_locator, status = 'active',
                        schema_hash = excluded.schema_hash, updated_at = excluded.updated_at
                    """,
                    (
                        tenant_id, dataset_id, connection_id, dataset_code,
                        str(table.get("table") or dataset_code),
                        _json({key: table.get(key) for key in ("catalog", "schema", "table", "qualified_name")}),
                        schema_hash, actor_user_id, now, now,
                    ),
                )
                dataset_row = self._conn.execute(
                    "SELECT dataset_id FROM platform_datasets WHERE tenant_id = ? AND dataset_code = ?",
                    (tenant_id, dataset_code),
                ).fetchone()
                dataset_id = str(dataset_row["dataset_id"])
                self._conn.execute(
                    "DELETE FROM platform_dataset_fields WHERE tenant_id = ? AND dataset_id = ?",
                    (tenant_id, dataset_id),
                )
                for field_position, field in enumerate(table.get("fields") or (), start=1):
                    field_code = str(field.get("field_code") or field.get("name") or "").strip()
                    if not field_code:
                        continue
                    field_id = f"df_{hashlib.sha256(f'{dataset_id}:{field_code}'.encode()).hexdigest()[:24]}"
                    metadata = {
                        "comment": field.get("comment") or "",
                        "business_description": field.get("business_description") or "",
                        "length": field.get("length"),
                        "sample_value_masked": field.get("sample_value_masked") or "",
                        "metadata_source": field.get("metadata_source") or "sql_inferred",
                        "metadata_version": decomposition.get("query_hash"),
                    }
                    self._conn.execute(
                        """
                        INSERT INTO platform_dataset_fields(
                            tenant_id, field_id, dataset_id, field_code, field_name,
                            ordinal_position, physical_type, semantic_type, is_nullable,
                            is_dimension, is_measure, metadata, created_by, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            tenant_id, field_id, dataset_id, field_code,
                            str(field.get("field_name") or field_code), field_position,
                            str(field.get("physical_type") or "unknown"),
                            str(field.get("semantic_type") or "") or None,
                            1 if field.get("is_nullable", True) else 0,
                            1 if field.get("is_dimension", True) else 0,
                            1 if field.get("is_measure", False) else 0,
                            _json(metadata), actor_user_id, now, now,
                        ),
                    )
                self._conn.execute(
                    """
                    INSERT INTO platform_topic_table_sources(
                        tenant_id, topic_table_id, dataset_id, source_alias, join_role, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tenant_id, topic_id, dataset_id,
                        str(table.get("alias") or table.get("table") or dataset_code),
                        "primary" if position == 0 else "lookup", now,
                    ),
                )
        return {"topic_table_id": topic_id, "schema_changed_tables": changed, "table_count": len(tables), "synced_at": now}

    def metadata_status(self, tenant_id: str, topic_table_id: str) -> dict[str, Any]:
        topic = self.get_topic_definition(tenant_id, topic_table_id)
        code = str(topic.get("code") or topic_table_id)
        row = self._conn.execute(
            "SELECT topic_table_id, validated_at FROM platform_topic_tables WHERE tenant_id = ? AND topic_code = ?",
            (tenant_id, code),
        ).fetchone()
        if not row:
            return {"topic_table_id": topic_table_id, "status": "not_fetched", "last_synced_at": None, "raw_tables": [], "schema_changed": False}
        sources = self._conn.execute(
            """
            SELECT d.dataset_code, d.dataset_name, d.schema_hash, d.updated_at,
                   s.source_alias, s.join_role, COUNT(f.field_id) AS field_count,
                   SUM(CASE WHEN f.physical_type = 'unknown' THEN 1 ELSE 0 END) AS unknown_field_count
            FROM platform_topic_table_sources s
            JOIN platform_datasets d ON d.tenant_id = s.tenant_id AND d.dataset_id = s.dataset_id
            LEFT JOIN platform_dataset_fields f ON f.tenant_id = d.tenant_id AND f.dataset_id = d.dataset_id
            WHERE s.tenant_id = ? AND s.topic_table_id = ?
            GROUP BY d.dataset_id, d.dataset_code, d.dataset_name, d.schema_hash, d.updated_at, s.source_alias, s.join_role
            ORDER BY s.join_role, d.dataset_code
            """,
            (tenant_id, str(row["topic_table_id"])),
        ).fetchall()
        raw_tables = [dict(item) for item in sources]
        status = "complete" if raw_tables and all(int(item["field_count"]) > 0 and int(item["unknown_field_count"] or 0) == 0 for item in raw_tables) else "partial" if raw_tables else "not_fetched"
        return {
            "topic_table_id": topic_table_id,
            "status": status,
            "last_synced_at": str(row["validated_at"] or "") or None,
            "raw_tables": raw_tables,
            "schema_changed": False,
        }

    def list_execution_logs(self, tenant_id: str, topic_table_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        params: list[Any] = [tenant_id]
        where = "r.tenant_id = ?"
        if topic_table_id:
            where += " AND j.topic_table_id = ?"
            params.append(topic_table_id)
        params.append(max(1, min(int(limit), 200)))
        rows = self._conn.execute(
            f"""
            SELECT r.acquisition_run_id, r.acquisition_job_id, j.topic_table_id,
                   r.status, r.started_at, r.finished_at, r.rows_read,
                   r.error_code, r.error_summary, r.source_snapshot
            FROM platform_acquisition_job_runs r
            JOIN platform_acquisition_jobs j
              ON j.tenant_id = r.tenant_id AND j.acquisition_job_id = r.acquisition_job_id
            WHERE {where} ORDER BY r.created_at DESC LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        return [{**dict(row), "source_snapshot": _load_json(row["source_snapshot"], {})} for row in rows]

    def expire_old_partitions(
        self,
        tenant_id: str,
        *,
        topic_table_id: str,
        org_unit_id: str | None,
        keep_latest_n: int,
    ) -> dict[str, Any]:
        limit = max(1, min(int(keep_latest_n), 30))
        rows = self._conn.execute(
            """
            SELECT partition_id FROM platform_dataset_partitions
            WHERE tenant_id = ? AND topic_table_id = ?
              AND org_unit_id IS ? AND freshness_status = 'fresh'
            ORDER BY snapshot_at DESC, created_at DESC
            """,
            (tenant_id, topic_table_id, org_unit_id),
        ).fetchall()
        expired = [str(row["partition_id"]) for row in rows[limit:]]
        if expired:
            with self._conn:
                self._conn.executemany(
                    "UPDATE platform_dataset_partitions SET freshness_status = 'stale' WHERE tenant_id = ? AND partition_id = ?",
                    [(tenant_id, partition_id) for partition_id in expired],
                )
        return {"keep_latest_n": limit, "expired_partitions": len(expired), "retained_object_artifacts": True}

    def bundle(self, tenant_id: str) -> dict[str, Any]:
        return {
            "sources": self.list_sources(tenant_id),
            "script_versions": self.list_scripts(tenant_id),
            "jobs": self.list_jobs(tenant_id),
            "runs": self.list_runs(tenant_id),
            "repair_proposals": self.list_repair_proposals(tenant_id),
            "quality_results": self.list_quality_results(tenant_id),
        }


class InMemoryAcquisitionStore(SQLiteAcquisitionStore):
    """Ephemeral SQLite implementation with the same invariants as persistence."""

    def __init__(self) -> None:
        self.db_path = ":memory:"
        self._conn = connect_sqlite(":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(
            """
            CREATE TABLE platform_data_connections (
                tenant_id TEXT NOT NULL,
                connection_id TEXT NOT NULL,
                PRIMARY KEY (tenant_id, connection_id)
            );
            """
        )
        self.init_schema()

    def ensure_connection_reference(self, tenant_id: str, connection_id: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO platform_data_connections(tenant_id, connection_id) VALUES (?, ?)",
                (tenant_id, connection_id),
            )


def _source_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["license_metadata"] = _load_json(result.get("license_metadata"), {})
    return result


def _script_version_row(row: sqlite3.Row, reveal_source: bool) -> dict[str, Any]:
    result = dict(row)
    result["dependency_lock"] = _load_json(result.get("dependency_lock"), {})
    result["input_schema"] = _load_json(result.get("input_schema"), {})
    result["output_schema"] = _load_json(result.get("output_schema"), {})
    if not reveal_source:
        result.pop("source_code", None)
    return result


def _job_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["job_config"] = _load_json(result.get("job_config"), {})
    return result


def _run_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for key in ("input_cursor", "output_cursor", "source_snapshot", "quality_summary"):
        result[key] = _load_json(result.get(key), {})
    return result


def _repair_row(row: sqlite3.Row, reveal_candidate: bool) -> dict[str, Any]:
    result = dict(row)
    result["diagnosis"] = _load_json(result.get("diagnosis"), {})
    if not reveal_candidate:
        result.pop("candidate_source_code", None)
    return result


def _required_text(value: Any, field: str, max_length: int) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > max_length:
        raise ValueError(f"invalid_{field}")
    return normalized


def _required_code(value: Any, field: str) -> str:
    normalized = _required_text(value, field, 160)
    if not all(character.isalnum() or character in {"_", "-", "."} for character in normalized):
        raise ValueError(f"invalid_{field}")
    return normalized


def _json_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("json_object_required")
    return json.loads(json.dumps(value, ensure_ascii=False))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return default


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
