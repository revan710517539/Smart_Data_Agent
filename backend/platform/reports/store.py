from __future__ import annotations

import json
import hashlib
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from backend.platform.storage import connect_sqlite
from typing import Any
from uuid import uuid4


ANALYSIS_RESULT_FIELDS = (
    "id", "title", "query", "plan", "summary", "visualTypes", "savedAt",
    "analysisTaskId", "ownerUserId", "visibility", "topicData", "source",
    "weeklyReportEligible", "weeklyReportSavedAt", "analysisInstitution",
    "currentInstitution", "uploadedDataInstitutions", "visualizations",
)

SAVED_ANALYSIS_VISUALIZATION_TYPES = frozenset({
    "kpi", "line", "area", "column", "bar", "stacked_bar", "combo", "donut",
    "scatter", "funnel", "treemap", "radar", "table", "pivot", "text",
})
SAVED_ANALYSIS_VISUALIZATION_TYPE_ALIASES = {
    "stackedbar": "stacked_bar",
    "pie": "donut",
    "crosstab": "pivot",
    "note": "text",
    "textbox": "text",
}
SAVED_ANALYSIS_FILTER_OPERATORS = frozenset({"in", "not_in", "contains", "not_contains"})


class CommentRevisionConflict(ValueError):
    def __init__(self, current_revision: int) -> None:
        super().__init__("comment_revision_conflict")
        self.current_revision = current_revision


class InMemoryReportStore:
    def __init__(self) -> None:
        self._analysis_results_by_tenant: dict[str, dict[str, dict[str, Any]]] = {}
        self._comments_by_tenant_report: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._weekly_versions_by_tenant: dict[str, dict[str, dict[str, Any]]] = {}
        self._weekly_ai_tasks_by_tenant_version: dict[tuple[str, str], dict[str, Any]] = {}
        self._comment_revision_by_tenant_report: dict[tuple[str, str], int] = {}
        self._learning_candidates_by_tenant: dict[str, dict[str, dict[str, Any]]] = {}
        self._daily_report_runs_by_tenant: dict[str, dict[str, dict[str, Any]]] = {}
        self._lock = threading.RLock()
        self._archived_analysis_results: set[tuple[str, str]] = set()
        self._archived_weekly_versions: set[tuple[str, str]] = set()

    def list_analysis_results(self, tenant_id: str, actor_user_id: str | None = None) -> list[dict[str, Any]]:
        results = self._analysis_results_by_tenant.get(tenant_id, {})
        visible = [
            item for item in results.values()
            if (tenant_id, str(item.get("id") or "")) not in self._archived_analysis_results
            and _report_object_visible(item, actor_user_id)
        ]
        return sorted(visible, key=lambda item: str(item.get("savedAt", "")), reverse=True)

    def get_analysis_result(self, tenant_id: str, result_id: str, actor_user_id: str | None = None) -> dict[str, Any] | None:
        item = self._analysis_results_by_tenant.get(tenant_id, {}).get(result_id)
        if not item or (tenant_id, result_id) in self._archived_analysis_results or not _report_object_visible(item, actor_user_id):
            return None
        return dict(item)

    def upsert_analysis_result(
        self,
        tenant_id: str,
        result: dict[str, Any],
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        normalized = _normalize_analysis_result(result)
        existing = self._analysis_results_by_tenant.get(tenant_id, {}).get(normalized["id"])
        if existing and updated_by and existing.get("ownerUserId") != updated_by:
            if existing.get("weeklyReportEligible") and not normalized.get("weeklyReportEligible"):
                normalized["ownerUserId"] = str(existing.get("ownerUserId") or "")
            else:
                raise PermissionError("saved_analysis_owner_required")
        normalized["ownerUserId"] = str(existing.get("ownerUserId") if existing else updated_by or "")
        normalized["updatedBy"] = updated_by or normalized.get("updatedBy") or ""
        self._analysis_results_by_tenant.setdefault(tenant_id, {})[normalized["id"]] = normalized
        return dict(normalized)

    def delete_analysis_result(self, tenant_id: str, result_id: str, actor_user_id: str | None = None) -> bool:
        existing = self._analysis_results_by_tenant.setdefault(tenant_id, {}).get(result_id)
        if existing and actor_user_id and existing.get("ownerUserId") != actor_user_id:
            raise PermissionError("saved_analysis_owner_required")
        return self._analysis_results_by_tenant.setdefault(tenant_id, {}).pop(result_id, None) is not None

    def get_report_comments(self, tenant_id: str, report_id: str) -> list[dict[str, Any]]:
        return [
            json.loads(json.dumps(comment, ensure_ascii=False))
            for comment in self._comments_by_tenant_report.get((tenant_id, report_id), [])
            if comment.get("status") != "deleted"
        ]

    def list_weekly_report_versions(self, tenant_id: str, actor_user_id: str | None = None) -> list[dict[str, Any]]:
        versions = self._weekly_versions_by_tenant.get(tenant_id, {})
        visible = [
            item for item in versions.values()
            if (tenant_id, str(item.get("id") or "")) not in self._archived_weekly_versions
            and (not actor_user_id or item.get("ownerUserId") == actor_user_id or item.get("visibility") == "tenant")
        ]
        return sorted(visible, key=lambda item: str(item.get("savedAt", "")), reverse=True)

    def get_weekly_report_version(self, tenant_id: str, version_id: str) -> dict[str, Any] | None:
        if (tenant_id, version_id) in self._archived_weekly_versions:
            return None
        version = self._weekly_versions_by_tenant.get(tenant_id, {}).get(version_id)
        return dict(version) if version else None

    def archive_expired(self, tenant_id: str, cutoff: datetime) -> dict[str, int]:
        archived_results = 0
        archived_versions = 0
        for result_id, item in self._analysis_results_by_tenant.get(tenant_id, {}).items():
            if (tenant_id, result_id) not in self._archived_analysis_results and _older_than(item.get("savedAt"), cutoff):
                self._archived_analysis_results.add((tenant_id, result_id))
                archived_results += 1
        for version_id, item in self._weekly_versions_by_tenant.get(tenant_id, {}).items():
            if (tenant_id, version_id) not in self._archived_weekly_versions and _older_than(item.get("savedAt"), cutoff):
                self._archived_weekly_versions.add((tenant_id, version_id))
                archived_versions += 1
        return {"analysis_results": archived_results, "weekly_versions": archived_versions}

    def create_daily_report_run(self, tenant_id: str, payload: dict[str, Any], created_by: str) -> dict[str, Any]:
        normalized = _normalize_daily_report_run(tenant_id, payload, created_by)
        bucket = self._daily_report_runs_by_tenant.setdefault(tenant_id, {})
        existing = next(
            (
                item for item in bucket.values()
                if item["owner_user_id"] == created_by
                and item["report_date"] == normalized["report_date"]
                and item["content_hash"] == normalized["content_hash"]
            ),
            None,
        )
        if existing:
            return dict(existing)
        bucket[normalized["daily_report_run_id"]] = normalized
        return dict(normalized)

    def list_daily_report_runs(self, tenant_id: str, owner_user_id: str) -> list[dict[str, Any]]:
        runs = [
            dict(item) for item in self._daily_report_runs_by_tenant.get(tenant_id, {}).values()
            if item["owner_user_id"] == owner_user_id
        ]
        return sorted(runs, key=lambda item: item["created_at"], reverse=True)

    def get_daily_report_run(self, tenant_id: str, run_id: str, owner_user_id: str) -> dict[str, Any]:
        run = self._daily_report_runs_by_tenant.get(tenant_id, {}).get(run_id)
        if not run:
            raise KeyError("daily_report_run_not_found")
        if run["owner_user_id"] != owner_user_id:
            raise PermissionError("daily_report_owner_required")
        return dict(run)

    def update_daily_report_run(
        self, tenant_id: str, run_id: str, owner_user_id: str, *, status: str, outbox_event_id: str | None = None
    ) -> dict[str, Any]:
        run = self.get_daily_report_run(tenant_id, run_id, owner_user_id)
        if status not in {"generated", "queued", "sending", "delivered", "failed"}:
            raise ValueError("invalid_daily_report_status")
        stored = self._daily_report_runs_by_tenant[tenant_id][run_id]
        stored.update({"status": status, "updated_at": _utcnow()})
        if outbox_event_id:
            stored["outbox_event_id"] = outbox_event_id
        return dict(stored)

    def save_weekly_report_version(
        self,
        tenant_id: str,
        version: dict[str, Any],
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        normalized = _prepare_weekly_report_version(tenant_id, version, updated_by)
        with self._lock:
            versions = self._weekly_versions_by_tenant.setdefault(tenant_id, {})
            existing = versions.get(normalized["id"])
            if existing:
                if existing.get("contentHash") != normalized["contentHash"]:
                    raise ValueError("immutable_weekly_report_version_conflict")
                return dict(existing)
            duplicate = next(
                (
                    item for item in versions.values()
                    if item.get("reportId") == normalized["reportId"]
                    and item.get("contentHash") == normalized["contentHash"]
                ),
                None,
            )
            if duplicate:
                return {**duplicate, "deduplicated": True}
            normalized["revisionNo"] = 1 + max(
                (int(item.get("revisionNo") or 0) for item in versions.values() if item.get("reportId") == normalized["reportId"]),
                default=0,
            )
            versions[normalized["id"]] = normalized
            return dict(normalized)

    def get_comment_revision(self, tenant_id: str, report_id: str) -> int:
        return self._comment_revision_by_tenant_report.get((tenant_id, report_id), 0)

    def replace_report_comments(
        self,
        tenant_id: str,
        report_id: str,
        comments: list[dict[str, Any]],
        updated_by: str | None = None,
        expected_revision: int | None = None,
    ) -> list[dict[str, Any]]:
        normalized = _normalize_comments(comments)
        key = (tenant_id, report_id)
        with self._lock:
            current_revision = self._comment_revision_by_tenant_report.get(key, 0)
            if expected_revision is not None and expected_revision != current_revision:
                raise CommentRevisionConflict(current_revision)
            self._comments_by_tenant_report[key] = normalized
            self._comment_revision_by_tenant_report[key] = current_revision + 1
        return [dict(comment) for comment in normalized]

    def create_report_comment(
        self,
        tenant_id: str,
        report_id: str,
        draft: dict[str, Any],
        actor_user_id: str,
        expected_revision: int,
        client_request_id: str,
    ) -> dict[str, Any]:
        key = (tenant_id, report_id)
        with self._lock:
            current_revision = self._comment_revision_by_tenant_report.get(key, 0)
            if expected_revision != current_revision:
                raise CommentRevisionConflict(current_revision)
            current = self._comments_by_tenant_report.setdefault(key, [])
            replay = next((item for item in current if item.get("clientRequestId") == client_request_id), None)
            if replay:
                return _comment_mutation_result(replay, current, current_revision, idempotent_replay=True)
            comment = _server_comment_from_draft(draft, actor_user_id, client_request_id)
            current.insert(0, comment)
            current_revision += 1
            self._comment_revision_by_tenant_report[key] = current_revision
            return _comment_mutation_result(comment, current, current_revision)

    def mutate_report_comment(
        self,
        tenant_id: str,
        report_id: str,
        comment_id: str,
        action: str,
        payload: dict[str, Any],
        actor_user_id: str,
        expected_revision: int,
        client_request_id: str = "",
    ) -> dict[str, Any]:
        key = (tenant_id, report_id)
        with self._lock:
            current_revision = self._comment_revision_by_tenant_report.get(key, 0)
            if expected_revision != current_revision:
                raise CommentRevisionConflict(current_revision)
            current = self._comments_by_tenant_report.setdefault(key, [])
            comment = next((item for item in current if item.get("id") == comment_id), None)
            if not comment or comment.get("status") == "deleted":
                raise KeyError("report_comment_not_found")
            changed = _apply_comment_mutation(comment, action, payload, actor_user_id, client_request_id)
            if changed:
                current_revision += 1
                self._comment_revision_by_tenant_report[key] = current_revision
            return _comment_mutation_result(comment, current, current_revision, idempotent_replay=not changed)

    def list_weekly_ai_tasks(self, tenant_id: str) -> list[dict[str, Any]]:
        tasks = [
            dict(task)
            for (stored_tenant_id, _), task in self._weekly_ai_tasks_by_tenant_version.items()
            if stored_tenant_id == tenant_id
        ]
        return sorted(tasks, key=lambda item: str(item.get("updated_at", "")), reverse=True)

    def get_weekly_ai_task(self, tenant_id: str, version_id: str) -> dict[str, Any] | None:
        task = self._weekly_ai_tasks_by_tenant_version.get((tenant_id, version_id))
        return dict(task) if task else None

    def upsert_weekly_ai_task(
        self,
        tenant_id: str,
        task: dict[str, Any],
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        normalized = _normalize_weekly_ai_task(task)
        normalized["tenant_id"] = tenant_id
        normalized["updated_by"] = updated_by or normalized.get("updated_by") or ""
        self._weekly_ai_tasks_by_tenant_version[(tenant_id, normalized["version_id"])] = normalized
        return dict(normalized)

    def create_learning_candidate(
        self,
        tenant_id: str,
        version_id: str,
        candidate_type: str,
        content: dict[str, Any],
        evidence_summary: dict[str, Any],
        confidence: float,
        created_by: str,
    ) -> dict[str, Any]:
        candidate = _learning_candidate(
            tenant_id, version_id, candidate_type, content, evidence_summary, confidence, created_by
        )
        bucket = self._learning_candidates_by_tenant.setdefault(tenant_id, {})
        existing = next(
            (
                item for item in bucket.values()
                if item["version_id"] == version_id
                and item["candidate_type"] == candidate_type
                and item["content_hash"] == candidate["content_hash"]
            ),
            None,
        )
        if existing:
            return dict(existing)
        bucket[candidate["learning_candidate_id"]] = candidate
        return dict(candidate)

    def list_learning_candidates(self, tenant_id: str, status: str | None = None) -> list[dict[str, Any]]:
        items = list(self._learning_candidates_by_tenant.get(tenant_id, {}).values())
        if status:
            items = [item for item in items if item["status"] == status]
        return sorted((dict(item) for item in items), key=lambda item: item["created_at"], reverse=True)

    def review_learning_candidate(
        self, tenant_id: str, candidate_id: str, decision: str, reviewer: str
    ) -> dict[str, Any]:
        candidate = self._learning_candidates_by_tenant.get(tenant_id, {}).get(candidate_id)
        if not candidate:
            raise KeyError("report_learning_candidate_not_found")
        if candidate["status"] not in {"candidate", "review"}:
            raise ValueError("report_learning_candidate_is_not_pending")
        if candidate["created_by"] == reviewer:
            raise PermissionError("four_eyes_report_learning_review_required")
        if decision not in {"approve", "reject"}:
            raise ValueError("invalid_report_learning_review_decision")
        candidate.update(
            {
                "status": "approved" if decision == "approve" else "rejected",
                "reviewed_by": reviewer,
                "reviewed_at": _utcnow(),
                "updated_at": _utcnow(),
            }
        )
        return dict(candidate)

    def mark_learning_candidate_applied(self, tenant_id: str, candidate_id: str) -> dict[str, Any]:
        candidate = self._learning_candidates_by_tenant.get(tenant_id, {}).get(candidate_id)
        if not candidate or candidate["status"] != "approved":
            raise ValueError("approved_report_learning_candidate_required")
        candidate["status"] = "applied"
        candidate["updated_at"] = _utcnow()
        return dict(candidate)


class SQLiteReportStore:
    def __init__(self, db_path: str | Path, initialize: bool = True) -> None:
        self.db_path = str(db_path)
        self._conn = connect_sqlite(self.db_path)
        self._conn.row_factory = sqlite3.Row
        if initialize:
            self.init_schema()

    def close(self) -> None:
        self._conn.close()

    def init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS platform_saved_analysis_results (
                tenant_id TEXT NOT NULL,
                result_id TEXT NOT NULL,
                title TEXT NOT NULL,
                query_text TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                created_by TEXT,
                updated_by TEXT,
                saved_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, result_id)
            );

            CREATE INDEX IF NOT EXISTS idx_platform_saved_analysis_results_tenant
                ON platform_saved_analysis_results(tenant_id, saved_at DESC);

            CREATE TABLE IF NOT EXISTS platform_report_comments (
                tenant_id TEXT NOT NULL,
                report_id TEXT NOT NULL,
                comments TEXT NOT NULL DEFAULT '[]',
                updated_by TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, report_id)
            );

            CREATE INDEX IF NOT EXISTS idx_platform_report_comments_tenant
                ON platform_report_comments(tenant_id, report_id);

            CREATE TABLE IF NOT EXISTS platform_weekly_report_versions (
                tenant_id TEXT NOT NULL,
                version_id TEXT NOT NULL,
                report_id TEXT NOT NULL,
                name TEXT NOT NULL,
                saved_at TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                created_by TEXT,
                updated_by TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, version_id)
            );

            CREATE INDEX IF NOT EXISTS idx_platform_weekly_report_versions_tenant
                ON platform_weekly_report_versions(tenant_id, saved_at DESC);

            CREATE TABLE IF NOT EXISTS weekly_report_ai_analysis_task (
                tenant_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                version_id TEXT NOT NULL,
                status TEXT NOT NULL,
                input_snapshot TEXT NOT NULL DEFAULT '{}',
                debate_result TEXT NOT NULL DEFAULT '{}',
                final_result TEXT NOT NULL DEFAULT '{}',
                error_message TEXT,
                created_by TEXT,
                updated_by TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, version_id)
            );

            CREATE INDEX IF NOT EXISTS idx_weekly_report_ai_analysis_task_tenant
                ON weekly_report_ai_analysis_task(tenant_id, updated_at DESC);
            """
        )
        self._conn.commit()

    def list_analysis_results(self, tenant_id: str, actor_user_id: str | None = None) -> list[dict[str, Any]]:
        owner_clause = "" if not actor_user_id else "AND (created_by = ? OR json_extract(payload, '$.visibility') = 'tenant')"
        parameters: tuple[str, ...] = (tenant_id,) if not actor_user_id else (tenant_id, actor_user_id)
        rows = self._conn.execute(
            f"""
            SELECT payload
            FROM platform_saved_analysis_results
            WHERE tenant_id = ?
              AND archived_at IS NULL
              {owner_clause}
            ORDER BY saved_at DESC, updated_at DESC
            LIMIT 50
            """,
            parameters,
        ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def get_analysis_result(self, tenant_id: str, result_id: str, actor_user_id: str | None = None) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT payload, created_by FROM platform_saved_analysis_results WHERE tenant_id = ? AND result_id = ? AND archived_at IS NULL",
            (tenant_id, result_id),
        ).fetchone()
        if not row:
            return None
        item = json.loads(row["payload"])
        return item if _report_object_visible(item, actor_user_id) else None

    def upsert_analysis_result(
        self,
        tenant_id: str,
        result: dict[str, Any],
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        normalized = _normalize_analysis_result(result)
        existing = self._conn.execute(
            "SELECT created_by FROM platform_saved_analysis_results WHERE tenant_id = ? AND result_id = ?",
            (tenant_id, normalized["id"]),
        ).fetchone()
        if existing and updated_by and existing["created_by"] != updated_by:
            previous = self.get_analysis_result(tenant_id, normalized["id"])
            if not (previous and previous.get("weeklyReportEligible") and not normalized.get("weeklyReportEligible")):
                raise PermissionError("saved_analysis_owner_required")
        normalized["ownerUserId"] = str(existing["created_by"] if existing else updated_by or "")
        normalized["updatedBy"] = updated_by or normalized.get("updatedBy") or ""
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_saved_analysis_results(
                    tenant_id, result_id, title, query_text, payload, created_by, updated_by, saved_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(tenant_id, result_id) DO UPDATE SET
                    title = excluded.title,
                    query_text = excluded.query_text,
                    payload = excluded.payload,
                    updated_by = excluded.updated_by,
                    saved_at = excluded.saved_at,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    tenant_id,
                    normalized["id"],
                    normalized["title"],
                    normalized["query"],
                    json.dumps(normalized, ensure_ascii=False, sort_keys=True),
                    updated_by,
                    updated_by,
                    normalized["savedAt"],
                ),
            )
        return normalized

    def create_learning_candidate(
        self,
        tenant_id: str,
        version_id: str,
        candidate_type: str,
        content: dict[str, Any],
        evidence_summary: dict[str, Any],
        confidence: float,
        created_by: str,
    ) -> dict[str, Any]:
        candidate = _learning_candidate(
            tenant_id, version_id, candidate_type, content, evidence_summary, confidence, created_by
        )
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO platform_report_learning_candidates(
                    tenant_id, learning_candidate_id, version_id, candidate_type,
                    candidate_content, content_hash, evidence_summary, confidence,
                    status, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'candidate', ?, ?, ?)
                """,
                (
                    tenant_id,
                    candidate["learning_candidate_id"],
                    version_id,
                    candidate_type,
                    json.dumps(content, ensure_ascii=False, sort_keys=True),
                    candidate["content_hash"],
                    json.dumps(evidence_summary, ensure_ascii=False, sort_keys=True),
                    candidate["confidence"],
                    created_by,
                    candidate["created_at"],
                    candidate["updated_at"],
                ),
            )
        row = self._conn.execute(
            """
            SELECT * FROM platform_report_learning_candidates
            WHERE tenant_id = ? AND version_id = ? AND candidate_type = ? AND content_hash = ?
            """,
            (tenant_id, version_id, candidate_type, candidate["content_hash"]),
        ).fetchone()
        assert row is not None
        return _learning_candidate_row(row)

    def list_learning_candidates(self, tenant_id: str, status: str | None = None) -> list[dict[str, Any]]:
        clause = "" if not status else "AND status = ?"
        params: tuple[Any, ...] = (tenant_id,) if not status else (tenant_id, status)
        rows = self._conn.execute(
            f"SELECT * FROM platform_report_learning_candidates WHERE tenant_id = ? {clause} ORDER BY created_at DESC",
            params,
        ).fetchall()
        return [_learning_candidate_row(row) for row in rows]

    def review_learning_candidate(
        self, tenant_id: str, candidate_id: str, decision: str, reviewer: str
    ) -> dict[str, Any]:
        if decision not in {"approve", "reject"}:
            raise ValueError("invalid_report_learning_review_decision")
        row = self._conn.execute(
            "SELECT * FROM platform_report_learning_candidates WHERE tenant_id = ? AND learning_candidate_id = ?",
            (tenant_id, candidate_id),
        ).fetchone()
        if not row:
            raise KeyError("report_learning_candidate_not_found")
        if str(row["status"]) not in {"candidate", "review"}:
            raise ValueError("report_learning_candidate_is_not_pending")
        if str(row["created_by"]) == reviewer:
            raise PermissionError("four_eyes_report_learning_review_required")
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                UPDATE platform_report_learning_candidates
                SET status = ?, reviewed_by = ?, reviewed_at = ?, updated_at = ?
                WHERE tenant_id = ? AND learning_candidate_id = ?
                """,
                ("approved" if decision == "approve" else "rejected", reviewer, now, now, tenant_id, candidate_id),
            )
        updated = self._conn.execute(
            "SELECT * FROM platform_report_learning_candidates WHERE tenant_id = ? AND learning_candidate_id = ?",
            (tenant_id, candidate_id),
        ).fetchone()
        assert updated is not None
        return _learning_candidate_row(updated)

    def mark_learning_candidate_applied(self, tenant_id: str, candidate_id: str) -> dict[str, Any]:
        now = _utcnow()
        with self._conn:
            cursor = self._conn.execute(
                """
                UPDATE platform_report_learning_candidates
                SET status = 'applied', updated_at = ?
                WHERE tenant_id = ? AND learning_candidate_id = ? AND status = 'approved'
                """,
                (now, tenant_id, candidate_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("approved_report_learning_candidate_required")
        row = self._conn.execute(
            "SELECT * FROM platform_report_learning_candidates WHERE tenant_id = ? AND learning_candidate_id = ?",
            (tenant_id, candidate_id),
        ).fetchone()
        assert row is not None
        return _learning_candidate_row(row)

    def list_weekly_report_versions(self, tenant_id: str, actor_user_id: str | None = None) -> list[dict[str, Any]]:
        owner_clause = "" if not actor_user_id else "AND (owner_user_id = ? OR json_extract(payload, '$.visibility') = 'tenant')"
        params: tuple[Any, ...] = (tenant_id,) if not actor_user_id else (tenant_id, actor_user_id)
        rows = self._conn.execute(
            f"""
            SELECT payload, owner_user_id, content_hash, parent_version_id, revision_no,
                   lifecycle_status, publication_status, evidence_summary
            FROM platform_weekly_report_versions
            WHERE tenant_id = ?
              AND archived_at IS NULL
              {owner_clause}
            ORDER BY saved_at DESC, updated_at DESC
            LIMIT 50
            """,
            params,
        ).fetchall()
        return [_weekly_version_from_row(row) for row in rows]

    def get_weekly_report_version(self, tenant_id: str, version_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT payload, owner_user_id, content_hash, parent_version_id, revision_no,
                   lifecycle_status, publication_status, evidence_summary
            FROM platform_weekly_report_versions
            WHERE tenant_id = ? AND version_id = ? AND archived_at IS NULL
            """,
            (tenant_id, version_id),
        ).fetchone()
        return _weekly_version_from_row(row) if row else None

    def archive_expired(self, tenant_id: str, cutoff: datetime) -> dict[str, int]:
        cutoff_utc = cutoff.astimezone(timezone.utc)
        archived_at = _utcnow()
        result_rows = self._conn.execute(
            "SELECT result_id, saved_at FROM platform_saved_analysis_results WHERE tenant_id = ? AND archived_at IS NULL",
            (tenant_id,),
        ).fetchall()
        version_rows = self._conn.execute(
            "SELECT version_id, saved_at FROM platform_weekly_report_versions WHERE tenant_id = ? AND archived_at IS NULL",
            (tenant_id,),
        ).fetchall()
        result_ids = [str(row["result_id"]) for row in result_rows if _older_than(row["saved_at"], cutoff_utc)]
        version_ids = [str(row["version_id"]) for row in version_rows if _older_than(row["saved_at"], cutoff_utc)]
        with self._conn:
            self._conn.executemany(
                "UPDATE platform_saved_analysis_results SET archived_at = ? WHERE tenant_id = ? AND result_id = ? AND archived_at IS NULL",
                [(archived_at, tenant_id, item_id) for item_id in result_ids],
            )
            self._conn.executemany(
                "UPDATE platform_weekly_report_versions SET archived_at = ?, lifecycle_status = 'archived' WHERE tenant_id = ? AND version_id = ? AND archived_at IS NULL",
                [(archived_at, tenant_id, item_id) for item_id in version_ids],
            )
        return {"analysis_results": len(result_ids), "weekly_versions": len(version_ids)}

    def create_daily_report_run(self, tenant_id: str, payload: dict[str, Any], created_by: str) -> dict[str, Any]:
        normalized = _normalize_daily_report_run(tenant_id, payload, created_by)
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO platform_daily_report_runs(
                    tenant_id, daily_report_run_id, owner_user_id, report_date,
                    source_report_version_id, subject, body_artifact_id, content_hash,
                    evidence_summary, preview_text, status, outbox_event_id,
                    created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'generated', NULL, ?, ?, ?)
                """,
                (
                    tenant_id, normalized["daily_report_run_id"], created_by,
                    normalized["report_date"], normalized["source_report_version_id"],
                    normalized["subject"], normalized["body_artifact_id"], normalized["content_hash"],
                    json.dumps(normalized["evidence_summary"], ensure_ascii=False, sort_keys=True),
                    normalized["preview_text"], created_by, normalized["created_at"], normalized["updated_at"],
                ),
            )
        row = self._conn.execute(
            """
            SELECT * FROM platform_daily_report_runs
            WHERE tenant_id = ? AND owner_user_id = ? AND report_date = ? AND content_hash = ?
            """,
            (tenant_id, created_by, normalized["report_date"], normalized["content_hash"]),
        ).fetchone()
        assert row is not None
        return _daily_report_run_row(row)

    def list_daily_report_runs(self, tenant_id: str, owner_user_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT * FROM platform_daily_report_runs
            WHERE tenant_id = ? AND owner_user_id = ?
            ORDER BY report_date DESC, created_at DESC LIMIT 100
            """,
            (tenant_id, owner_user_id),
        ).fetchall()
        return [_daily_report_run_row(row) for row in rows]

    def get_daily_report_run(self, tenant_id: str, run_id: str, owner_user_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            """
            SELECT * FROM platform_daily_report_runs
            WHERE tenant_id = ? AND daily_report_run_id = ? AND owner_user_id = ?
            """,
            (tenant_id, run_id, owner_user_id),
        ).fetchone()
        if not row:
            raise KeyError("daily_report_run_not_found")
        return _daily_report_run_row(row)

    def update_daily_report_run(
        self, tenant_id: str, run_id: str, owner_user_id: str, *, status: str, outbox_event_id: str | None = None
    ) -> dict[str, Any]:
        if status not in {"generated", "queued", "sending", "delivered", "failed"}:
            raise ValueError("invalid_daily_report_status")
        now = _utcnow()
        with self._conn:
            cursor = self._conn.execute(
                """
                UPDATE platform_daily_report_runs
                SET status = ?, outbox_event_id = COALESCE(?, outbox_event_id), updated_at = ?
                WHERE tenant_id = ? AND daily_report_run_id = ? AND owner_user_id = ?
                """,
                (status, outbox_event_id, now, tenant_id, run_id, owner_user_id),
            )
            if cursor.rowcount != 1:
                raise KeyError("daily_report_run_not_found")
        return self.get_daily_report_run(tenant_id, run_id, owner_user_id)

    def save_weekly_report_version(
        self,
        tenant_id: str,
        version: dict[str, Any],
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        normalized = _prepare_weekly_report_version(tenant_id, version, updated_by)
        existing = self._conn.execute(
            """
            SELECT payload, content_hash, owner_user_id, parent_version_id, revision_no,
                   lifecycle_status, publication_status, evidence_summary
            FROM platform_weekly_report_versions
            WHERE tenant_id = ? AND version_id = ?
            """,
            (tenant_id, normalized["id"]),
        ).fetchone()
        if existing:
            if str(existing["content_hash"] or "") != normalized["contentHash"]:
                raise ValueError("immutable_weekly_report_version_conflict")
            return _weekly_version_from_row(existing)
        duplicate = self._conn.execute(
            """
            SELECT payload, content_hash, owner_user_id, parent_version_id, revision_no,
                   lifecycle_status, publication_status, evidence_summary
            FROM platform_weekly_report_versions
            WHERE tenant_id = ? AND report_id = ? AND content_hash = ?
            """,
            (tenant_id, normalized["reportId"], normalized["contentHash"]),
        ).fetchone()
        if duplicate:
            return {**_weekly_version_from_row(duplicate), "deduplicated": True}
        revision_no = int(
            self._conn.execute(
                "SELECT COALESCE(MAX(revision_no), 0) FROM platform_weekly_report_versions WHERE tenant_id = ? AND report_id = ?",
                (tenant_id, normalized["reportId"]),
            ).fetchone()[0]
        ) + 1
        normalized["revisionNo"] = revision_no
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_weekly_report_versions(
                    tenant_id, version_id, report_id, name, saved_at, payload, created_by, updated_by,
                    owner_user_id, content_hash, parent_version_id, revision_no, lifecycle_status,
                    publication_status, evidence_summary, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    tenant_id,
                    normalized["id"],
                    normalized["reportId"],
                    normalized["name"],
                    normalized["savedAt"],
                    json.dumps(normalized, ensure_ascii=False, sort_keys=True),
                    updated_by,
                    updated_by,
                    normalized["ownerUserId"],
                    normalized["contentHash"],
                    normalized.get("parentVersionId"),
                    revision_no,
                    normalized["lifecycleStatus"],
                    normalized["publicationStatus"],
                    json.dumps(normalized["evidenceSummary"], ensure_ascii=False, sort_keys=True),
                ),
            )
        return normalized

    def list_weekly_ai_tasks(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT task_id, version_id, status, input_snapshot, debate_result, final_result,
                   error_message, created_by, updated_by, created_at, updated_at
            FROM weekly_report_ai_analysis_task
            WHERE tenant_id = ?
            ORDER BY updated_at DESC
            LIMIT 100
            """,
            (tenant_id,),
        ).fetchall()
        return [_weekly_ai_task_from_row(tenant_id, row) for row in rows]

    def get_weekly_ai_task(self, tenant_id: str, version_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT task_id, version_id, status, input_snapshot, debate_result, final_result,
                   error_message, created_by, updated_by, created_at, updated_at
            FROM weekly_report_ai_analysis_task
            WHERE tenant_id = ? AND version_id = ?
            """,
            (tenant_id, version_id),
        ).fetchone()
        return _weekly_ai_task_from_row(tenant_id, row) if row else None

    def upsert_weekly_ai_task(
        self,
        tenant_id: str,
        task: dict[str, Any],
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        normalized = _normalize_weekly_ai_task(task)
        normalized["tenant_id"] = tenant_id
        normalized["updated_by"] = updated_by or normalized.get("updated_by") or ""
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO weekly_report_ai_analysis_task(
                    tenant_id, task_id, version_id, status, input_snapshot, debate_result,
                    final_result, error_message, created_by, updated_by, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(tenant_id, version_id) DO UPDATE SET
                    task_id = excluded.task_id,
                    status = excluded.status,
                    input_snapshot = excluded.input_snapshot,
                    debate_result = excluded.debate_result,
                    final_result = excluded.final_result,
                    error_message = excluded.error_message,
                    updated_by = excluded.updated_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    tenant_id,
                    normalized["id"],
                    normalized["version_id"],
                    _weekly_status_to_db(normalized["status"]),
                    json.dumps(normalized["input_snapshot"], ensure_ascii=False, sort_keys=True),
                    json.dumps(normalized["debate_result"], ensure_ascii=False, sort_keys=True),
                    json.dumps(normalized["final_result"], ensure_ascii=False, sort_keys=True),
                    normalized["error_message"],
                    updated_by,
                    updated_by,
                    normalized["created_at"],
                ),
            )
        return normalized

    def delete_analysis_result(self, tenant_id: str, result_id: str, actor_user_id: str | None = None) -> bool:
        owner_clause = "" if not actor_user_id else " AND created_by = ?"
        parameters: tuple[str, ...] = (tenant_id, result_id) if not actor_user_id else (tenant_id, result_id, actor_user_id)
        with self._conn:
            cursor = self._conn.execute(
                f"""
                DELETE FROM platform_saved_analysis_results
                WHERE tenant_id = ? AND result_id = ?
                {owner_clause}
                """,
                parameters,
            )
        return cursor.rowcount > 0

    def get_report_comments(self, tenant_id: str, report_id: str) -> list[dict[str, Any]]:
        entity_comments = self._list_comment_entities(tenant_id, report_id)
        if entity_comments:
            return entity_comments
        row = self._conn.execute(
            """
            SELECT comments
            FROM platform_report_comments
            WHERE tenant_id = ? AND report_id = ?
            """,
            (tenant_id, report_id),
        ).fetchone()
        return json.loads(row["comments"]) if row else []

    def get_comment_revision(self, tenant_id: str, report_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(revision_no), 0) AS revision_no FROM platform_report_comment_revisions WHERE tenant_id = ? AND report_id = ?",
            (tenant_id, report_id),
        ).fetchone()
        return int(row["revision_no"] or 0)

    def replace_report_comments(
        self,
        tenant_id: str,
        report_id: str,
        comments: list[dict[str, Any]],
        updated_by: str | None = None,
        expected_revision: int | None = None,
    ) -> list[dict[str, Any]]:
        normalized = _normalize_comments(comments)
        snapshot_json = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
        with self._conn:
            current_revision = int(
                self._conn.execute(
                    "SELECT COALESCE(MAX(revision_no), 0) FROM platform_report_comment_revisions WHERE tenant_id = ? AND report_id = ?",
                    (tenant_id, report_id),
                ).fetchone()[0]
            )
            if expected_revision is not None and expected_revision != current_revision:
                raise CommentRevisionConflict(current_revision)
            next_revision = current_revision + 1
            self._conn.execute(
                """
                INSERT INTO platform_report_comment_revisions(
                    tenant_id, report_id, revision_no, comments_snapshot, snapshot_hash,
                    created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (tenant_id, report_id, next_revision, snapshot_json, snapshot_hash, updated_by or "", _utcnow()),
            )
            self._conn.execute(
                """
                INSERT INTO platform_report_comments(tenant_id, report_id, comments, updated_by, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(tenant_id, report_id) DO UPDATE SET
                    comments = excluded.comments,
                    updated_by = excluded.updated_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    tenant_id,
                    report_id,
                    snapshot_json,
                    updated_by,
                ),
            )
        return normalized

    def create_report_comment(
        self,
        tenant_id: str,
        report_id: str,
        draft: dict[str, Any],
        actor_user_id: str,
        expected_revision: int,
        client_request_id: str,
    ) -> dict[str, Any]:
        if not client_request_id:
            raise ValueError("comment_client_request_id_required")
        with self._conn:
            current_revision = self._comment_revision_tx(tenant_id, report_id)
            if expected_revision != current_revision:
                raise CommentRevisionConflict(current_revision)
            replay_row = self._conn.execute(
                """
                SELECT comment_id FROM platform_report_comment_items
                WHERE tenant_id = ? AND report_id = ? AND client_request_id = ?
                """,
                (tenant_id, report_id, client_request_id),
            ).fetchone()
            if replay_row:
                comments = self._list_comment_entities_tx(tenant_id, report_id)
                replay = next(item for item in comments if item["id"] == replay_row["comment_id"])
                return _comment_mutation_result(replay, comments, current_revision, idempotent_replay=True)
            comment = _server_comment_from_draft(draft, actor_user_id, client_request_id)
            self._conn.execute(
                """
                INSERT INTO platform_report_comment_items(
                    tenant_id, report_id, comment_id, client_request_id, target_id, target_label,
                    target_kind, selected_text, block_id, item_id, range_start, range_end,
                    anchor_top, author_user_id, comment_body, status, created_at, updated_at, lock_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, 0)
                """,
                (
                    tenant_id,
                    report_id,
                    comment["id"],
                    client_request_id,
                    comment["targetId"],
                    comment["targetLabel"],
                    comment.get("targetKind"),
                    comment.get("selectedText"),
                    comment.get("blockId"),
                    comment.get("itemId"),
                    comment.get("rangeStart"),
                    comment.get("rangeEnd"),
                    comment.get("anchorTop"),
                    actor_user_id,
                    comment["text"],
                    comment["time"],
                    comment["time"],
                ),
            )
            comments = self._list_comment_entities_tx(tenant_id, report_id)
            next_revision = self._write_comment_snapshot_tx(
                tenant_id, report_id, comments, actor_user_id, current_revision
            )
            created = next(item for item in comments if item["id"] == comment["id"])
            return _comment_mutation_result(created, comments, next_revision)

    def mutate_report_comment(
        self,
        tenant_id: str,
        report_id: str,
        comment_id: str,
        action: str,
        payload: dict[str, Any],
        actor_user_id: str,
        expected_revision: int,
        client_request_id: str = "",
    ) -> dict[str, Any]:
        with self._conn:
            current_revision = self._comment_revision_tx(tenant_id, report_id)
            if expected_revision != current_revision:
                raise CommentRevisionConflict(current_revision)
            row = self._conn.execute(
                """
                SELECT * FROM platform_report_comment_items
                WHERE tenant_id = ? AND report_id = ? AND comment_id = ? AND status <> 'deleted'
                """,
                (tenant_id, report_id, comment_id),
            ).fetchone()
            if not row:
                raise KeyError("report_comment_not_found")
            changed = True
            now = _utcnow()
            if action == "resolve":
                reason = _resolved_reason(payload.get("reason"))
                if row["status"] == "resolved" and row["resolved_reason"] == reason:
                    changed = False
                else:
                    self._conn.execute(
                        """
                        UPDATE platform_report_comment_items
                        SET status = 'resolved', resolved_by = ?, resolved_at = ?, resolved_reason = ?,
                            updated_at = ?, lock_version = lock_version + 1
                        WHERE tenant_id = ? AND report_id = ? AND comment_id = ?
                        """,
                        (actor_user_id, now, reason, now, tenant_id, report_id, comment_id),
                    )
            elif action == "reopen":
                if row["status"] in {"open", "reopened"}:
                    changed = False
                else:
                    self._conn.execute(
                        """
                        UPDATE platform_report_comment_items
                        SET status = 'reopened', resolved_by = NULL, resolved_at = NULL, resolved_reason = NULL,
                            updated_at = ?, lock_version = lock_version + 1
                        WHERE tenant_id = ? AND report_id = ? AND comment_id = ?
                        """,
                        (now, tenant_id, report_id, comment_id),
                    )
            elif action == "reply":
                reply_body = str(payload.get("text") or "").strip()
                if not reply_body:
                    raise ValueError("report_comment_reply_text_required")
                if not client_request_id:
                    raise ValueError("comment_client_request_id_required")
                replay = self._conn.execute(
                    """
                    SELECT reply_id FROM platform_report_comment_replies
                    WHERE tenant_id = ? AND report_id = ? AND client_request_id = ?
                    """,
                    (tenant_id, report_id, client_request_id),
                ).fetchone()
                if replay:
                    changed = False
                else:
                    self._conn.execute(
                        """
                        INSERT INTO platform_report_comment_replies(
                            tenant_id, report_id, comment_id, reply_id, client_request_id,
                            author_user_id, reply_body, status, created_at, updated_at, lock_version
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, 0)
                        """,
                        (
                            tenant_id,
                            report_id,
                            comment_id,
                            f"reply_{uuid4().hex}",
                            client_request_id,
                            actor_user_id,
                            reply_body,
                            now,
                            now,
                        ),
                    )
                    self._conn.execute(
                        """
                        UPDATE platform_report_comment_items
                        SET updated_at = ?, lock_version = lock_version + 1
                        WHERE tenant_id = ? AND report_id = ? AND comment_id = ?
                        """,
                        (now, tenant_id, report_id, comment_id),
                    )
            elif action == "delete":
                if row["author_user_id"] != actor_user_id:
                    raise PermissionError("report_comment_author_required")
                self._conn.execute(
                    """
                    UPDATE platform_report_comment_items
                    SET status = 'deleted', updated_at = ?, lock_version = lock_version + 1
                    WHERE tenant_id = ? AND report_id = ? AND comment_id = ?
                    """,
                    (now, tenant_id, report_id, comment_id),
                )
            else:
                raise ValueError("unsupported_report_comment_action")
            comments = self._list_comment_entities_tx(tenant_id, report_id)
            next_revision = current_revision
            if changed:
                next_revision = self._write_comment_snapshot_tx(
                    tenant_id, report_id, comments, actor_user_id, current_revision
                )
            updated = next((item for item in comments if item["id"] == comment_id), None)
            if action == "delete":
                updated = {"id": comment_id, "status": "deleted"}
            if updated is None:
                raise KeyError("report_comment_not_found")
            return _comment_mutation_result(updated, comments, next_revision, idempotent_replay=not changed)

    def _comment_revision_tx(self, tenant_id: str, report_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(revision_no), 0) FROM platform_report_comment_revisions WHERE tenant_id = ? AND report_id = ?",
            (tenant_id, report_id),
        ).fetchone()
        return int(row[0] or 0)

    def _list_comment_entities(self, tenant_id: str, report_id: str) -> list[dict[str, Any]]:
        return self._list_comment_entities_tx(tenant_id, report_id)

    def _list_comment_entities_tx(self, tenant_id: str, report_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT comment_item.*,
                   COALESCE(NULLIF(TRIM(author_profile.name), ''), comment_item.author_user_id) AS author_name
            FROM platform_report_comment_items AS comment_item
            LEFT JOIN platform_user_profiles AS author_profile
              ON author_profile.user_id = comment_item.author_user_id
            WHERE comment_item.tenant_id = ? AND comment_item.report_id = ? AND comment_item.status <> 'deleted'
            ORDER BY comment_item.created_at DESC, comment_item.comment_id DESC
            """,
            (tenant_id, report_id),
        ).fetchall()
        reply_rows = self._conn.execute(
            """
            SELECT reply_item.*,
                   COALESCE(NULLIF(TRIM(author_profile.name), ''), reply_item.author_user_id) AS author_name
            FROM platform_report_comment_replies AS reply_item
            LEFT JOIN platform_user_profiles AS author_profile
              ON author_profile.user_id = reply_item.author_user_id
            WHERE reply_item.tenant_id = ? AND reply_item.report_id = ? AND reply_item.status = 'active'
            ORDER BY reply_item.created_at, reply_item.reply_id
            """,
            (tenant_id, report_id),
        ).fetchall()
        replies_by_comment: dict[str, list[dict[str, Any]]] = {}
        for reply in reply_rows:
            replies_by_comment.setdefault(str(reply["comment_id"]), []).append(
                {
                    "id": str(reply["reply_id"]),
                    "author": str(reply["author_name"] or reply["author_user_id"]),
                    "time": str(reply["created_at"]),
                    "text": str(reply["reply_body"]),
                    "lockVersion": int(reply["lock_version"] or 0),
                }
            )
        return [_comment_entity_from_row(row, replies_by_comment.get(str(row["comment_id"]), [])) for row in rows]

    def _write_comment_snapshot_tx(
        self,
        tenant_id: str,
        report_id: str,
        comments: list[dict[str, Any]],
        actor_user_id: str,
        current_revision: int,
    ) -> int:
        next_revision = current_revision + 1
        snapshot_json = json.dumps(comments, ensure_ascii=False, sort_keys=True)
        snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
        now = _utcnow()
        self._conn.execute(
            """
            INSERT INTO platform_report_comment_revisions(
                tenant_id, report_id, revision_no, comments_snapshot, snapshot_hash, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (tenant_id, report_id, next_revision, snapshot_json, snapshot_hash, actor_user_id, now),
        )
        self._conn.execute(
            """
            INSERT INTO platform_report_comments(tenant_id, report_id, comments, updated_by, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(tenant_id, report_id) DO UPDATE SET
                comments = excluded.comments, updated_by = excluded.updated_by, updated_at = CURRENT_TIMESTAMP
            """,
            (tenant_id, report_id, snapshot_json, actor_user_id),
        )
        return next_revision


def _server_comment_from_draft(
    draft: dict[str, Any], actor_user_id: str, client_request_id: str
) -> dict[str, Any]:
    target_id = str(draft.get("targetId") or "").strip()
    target_label = str(draft.get("targetLabel") or "").strip()
    text = str(draft.get("text") or "").strip()
    if not target_id or not target_label:
        raise ValueError("report_comment_target_required")
    if not text:
        raise ValueError("report_comment_text_required")
    if len(text) > 10_000:
        raise ValueError("report_comment_text_too_long")
    target_kind = str(draft.get("targetKind") or "").strip()
    if target_kind and target_kind not in {"paragraph", "analysis", "table", "chart"}:
        raise ValueError("invalid_report_comment_target_kind")
    now = _utcnow()
    comment = {
        "id": f"comment_{uuid4().hex}",
        "clientRequestId": client_request_id,
        "targetId": target_id,
        "targetLabel": target_label,
        "status": "open",
        "author": actor_user_id,
        "time": now,
        "text": text,
        "replies": [],
        "lockVersion": 0,
    }
    optional_strings = {
        "selectedText": draft.get("selectedText"),
        "blockId": draft.get("blockId"),
        "itemId": draft.get("itemId"),
        "targetKind": target_kind or None,
    }
    for key, value in optional_strings.items():
        if value is not None and str(value).strip():
            comment[key] = str(value)
    for key in ("rangeStart", "rangeEnd"):
        value = draft.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            comment[key] = value
    anchor_top = draft.get("anchorTop")
    if isinstance(anchor_top, (int, float)) and not isinstance(anchor_top, bool):
        comment["anchorTop"] = float(anchor_top)
    return comment


def _resolved_reason(value: Any) -> str:
    reason = str(value or "manual").strip()
    if reason not in {"manual", "source_text_deleted", "source_text_replaced"}:
        raise ValueError("invalid_report_comment_resolved_reason")
    return reason


def _apply_comment_mutation(
    comment: dict[str, Any],
    action: str,
    payload: dict[str, Any],
    actor_user_id: str,
    client_request_id: str,
) -> bool:
    now = _utcnow()
    if action == "resolve":
        reason = _resolved_reason(payload.get("reason"))
        if comment.get("status") == "resolved" and comment.get("resolvedReason") == reason:
            return False
        comment.update(
            {
                "status": "resolved",
                "resolvedAt": now,
                "resolvedBy": actor_user_id,
                "resolvedReason": reason,
                "lockVersion": int(comment.get("lockVersion") or 0) + 1,
            }
        )
        return True
    if action == "reopen":
        if comment.get("status") in {"open", "reopened"}:
            return False
        comment.update(
            {
                "status": "reopened",
                "lockVersion": int(comment.get("lockVersion") or 0) + 1,
            }
        )
        comment.pop("resolvedAt", None)
        comment.pop("resolvedBy", None)
        comment.pop("resolvedReason", None)
        return True
    if action == "reply":
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError("report_comment_reply_text_required")
        if len(text) > 10_000:
            raise ValueError("report_comment_reply_text_too_long")
        if not client_request_id:
            raise ValueError("comment_client_request_id_required")
        replies = comment.setdefault("replies", [])
        if any(reply.get("clientRequestId") == client_request_id for reply in replies):
            return False
        replies.append(
            {
                "id": f"reply_{uuid4().hex}",
                "clientRequestId": client_request_id,
                "author": actor_user_id,
                "time": now,
                "text": text,
                "lockVersion": 0,
            }
        )
        comment["lockVersion"] = int(comment.get("lockVersion") or 0) + 1
        return True
    if action == "delete":
        if comment.get("author") != actor_user_id:
            raise PermissionError("report_comment_author_required")
        comment["status"] = "deleted"
        comment["lockVersion"] = int(comment.get("lockVersion") or 0) + 1
        return True
    raise ValueError("unsupported_report_comment_action")


def _comment_mutation_result(
    comment: dict[str, Any],
    comments: list[dict[str, Any]],
    revision: int,
    *,
    idempotent_replay: bool = False,
) -> dict[str, Any]:
    visible = [item for item in comments if item.get("status") != "deleted"]
    return {
        "comment": json.loads(json.dumps(comment, ensure_ascii=False)),
        "comments": json.loads(json.dumps(visible, ensure_ascii=False)),
        "revision": revision,
        "idempotent_replay": idempotent_replay,
    }


def _comment_entity_from_row(row: sqlite3.Row, replies: list[dict[str, Any]]) -> dict[str, Any]:
    comment: dict[str, Any] = {
        "id": str(row["comment_id"]),
        "clientRequestId": str(row["client_request_id"] or ""),
        "targetId": str(row["target_id"]),
        "targetLabel": str(row["target_label"]),
        "status": str(row["status"]),
        "author": str(row["author_name"] or row["author_user_id"]) if "author_name" in row.keys() else str(row["author_user_id"]),
        "time": str(row["created_at"]),
        "text": str(row["comment_body"]),
        "replies": replies,
        "lockVersion": int(row["lock_version"] or 0),
    }
    optional = {
        "targetKind": row["target_kind"],
        "selectedText": row["selected_text"],
        "blockId": row["block_id"],
        "itemId": row["item_id"],
        "rangeStart": row["range_start"],
        "rangeEnd": row["range_end"],
        "anchorTop": row["anchor_top"],
        "resolvedBy": row["resolved_by"],
        "resolvedAt": row["resolved_at"],
        "resolvedReason": row["resolved_reason"],
    }
    for key, value in optional.items():
        if value is not None and value != "":
            comment[key] = value
    return comment


def _normalize_analysis_result(result: dict[str, Any]) -> dict[str, Any]:
    normalized = {field: result.get(field) for field in ANALYSIS_RESULT_FIELDS}
    normalized["id"] = str(normalized.get("id") or "").strip()
    normalized["title"] = str(normalized.get("title") or normalized["id"] or "").strip()
    normalized["query"] = str(normalized.get("query") or normalized["title"] or "").strip()
    normalized["plan"] = str(normalized.get("plan") or "").strip()
    normalized["summary"] = str(normalized.get("summary") or "").strip()
    normalized["savedAt"] = str(normalized.get("savedAt") or "").strip()
    visual_types = normalized.get("visualTypes")
    if not normalized["id"] or not normalized["title"]:
        raise ValueError("analysis result id and title are required.")
    if not isinstance(visual_types, dict):
        normalized["visualTypes"] = {"primary": "bar", "secondary": "table"}
    normalized["analysisTaskId"] = str(normalized.get("analysisTaskId") or "").strip()
    normalized["analysisInstitution"] = str(normalized.get("analysisInstitution") or "").strip()[:120]
    normalized["currentInstitution"] = str(normalized.get("currentInstitution") or "").strip()[:120]
    uploaded_institutions = normalized.get("uploadedDataInstitutions")
    normalized["uploadedDataInstitutions"] = [
        str(item).strip()[:120]
        for item in uploaded_institutions if str(item).strip()
    ][:20] if isinstance(uploaded_institutions, list) else []
    normalized["visualizations"] = _normalize_saved_analysis_visualizations(normalized.get("visualizations"))
    topic_data = normalized.get("topicData")
    is_topic_data_report = isinstance(topic_data, dict) and str(topic_data.get("reference_type") or "") == "report"
    if not normalized["analysisTaskId"] and not is_topic_data_report:
        raise ValueError("analysisTaskId is required unless the report has a Topic_Data snapshot.")
    normalized["ownerUserId"] = str(normalized.get("ownerUserId") or "").strip()
    normalized["weeklyReportEligible"] = bool(normalized.get("weeklyReportEligible"))
    normalized["weeklyReportSavedAt"] = (
        str(normalized.get("weeklyReportSavedAt") or "").strip()
        if normalized["weeklyReportEligible"]
        else ""
    )
    visibility = str(normalized.get("visibility") or "private").strip()
    normalized["visibility"] = visibility if visibility in {"private", "tenant"} else "private"
    source = normalized.get("source")
    if isinstance(source, dict) and str(source.get("channel") or "").strip():
        normalized["source"] = {
            "channel": str(source.get("channel") or "").strip()[:64],
            "label": str(source.get("label") or source.get("channel") or "").strip()[:120],
            "bindingId": str(source.get("bindingId") or "").strip()[:120],
            "runId": str(source.get("runId") or "").strip()[:500],
            "reportId": str(source.get("reportId") or "").strip()[:500],
            "url": str(source.get("url") or "").strip()[:2000],
        }
    else:
        normalized["source"] = None
    normalized["rows"] = []
    if not normalized["savedAt"]:
        normalized["savedAt"] = "未记录"
    return normalized


def _normalize_saved_analysis_visualizations(value: Any) -> list[dict[str, Any]]:
    """Bound user-authored presentation metadata without copying analysis facts."""

    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("saved_analysis_visualizations_invalid")
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_card in enumerate(value[:40]):
        if not isinstance(raw_card, dict):
            raise ValueError("saved_analysis_visualizations_invalid")
        card_id = str(raw_card.get("id") or f"visual-{index + 1}").strip()[:160]
        card_type = str(raw_card.get("type") or "table").strip()
        card_type = SAVED_ANALYSIS_VISUALIZATION_TYPE_ALIASES.get(card_type.lower(), card_type.lower())
        if not card_id or card_id in seen_ids or card_type not in SAVED_ANALYSIS_VISUALIZATION_TYPES:
            raise ValueError("saved_analysis_visualizations_invalid")
        seen_ids.add(card_id)
        key = str(raw_card.get("key") or "").strip()
        card: dict[str, Any] = {
            "id": card_id,
            "title": str(raw_card.get("title") or "未命名可视化").strip()[:500] or "未命名可视化",
            "type": card_type,
        }
        if key in {"primary", "secondary"}:
            card["key"] = key
        raw_config = raw_card.get("config")
        if raw_config is not None:
            if not isinstance(raw_config, dict):
                raise ValueError("saved_analysis_visualizations_invalid")
            card["config"] = _normalize_saved_analysis_visualization_config(raw_config)
        normalized.append(card)
    return normalized


def _normalize_saved_analysis_visualization_config(value: dict[str, Any]) -> dict[str, Any]:
    def string_list(raw: Any, *, limit: int = 100, width: int = 300) -> list[str]:
        if not isinstance(raw, list):
            return []
        result: list[str] = []
        for item in raw[:limit]:
            text = str(item or "").strip()[:width]
            if text and text not in result:
                result.append(text)
        return result

    filters: dict[str, list[str]] = {}
    raw_filters = value.get("filters")
    if isinstance(raw_filters, dict):
        for raw_field, raw_values in list(raw_filters.items())[:100]:
            field = str(raw_field or "").strip()[:300]
            values = string_list(raw_values, limit=200, width=500)
            if field and values:
                filters[field] = values

    filter_groups: list[dict[str, Any]] = []
    raw_groups = value.get("filterGroups")
    if isinstance(raw_groups, list):
        for group_index, raw_group in enumerate(raw_groups[:20]):
            if not isinstance(raw_group, dict):
                continue
            rules: list[dict[str, Any]] = []
            for rule_index, raw_rule in enumerate((raw_group.get("rules") or [])[:50] if isinstance(raw_group.get("rules"), list) else []):
                if not isinstance(raw_rule, dict):
                    continue
                field = str(raw_rule.get("field") or "").strip()[:300]
                values = string_list(raw_rule.get("values"), limit=200, width=500)
                operator = str(raw_rule.get("operator") or "in").strip()
                if not field or not values:
                    continue
                rules.append({
                    "id": str(raw_rule.get("id") or f"filter-rule-{group_index}-{rule_index}").strip()[:160],
                    "field": field,
                    "operator": operator if operator in SAVED_ANALYSIS_FILTER_OPERATORS else "in",
                    "values": values,
                })
            if rules:
                filter_groups.append({
                    "id": str(raw_group.get("id") or f"filter-group-{group_index}").strip()[:160],
                    "rules": rules,
                })

    config: dict[str, Any] = {
        "metricFields": string_list(value.get("metricFields")),
        "dimensionFields": string_list(value.get("dimensionFields")),
        "filters": filters,
        "filterGroups": filter_groups,
        "sumFilteredRows": bool(value.get("sumFilteredRows")),
        "comboLineFields": string_list(value.get("comboLineFields")),
    }
    if "noteTitle" in value:
        config["noteTitle"] = str(value.get("noteTitle") or "").strip()[:500]
    if "noteBody" in value:
        config["noteBody"] = str(value.get("noteBody") or "")[:8000]
    if "noteTitleHidden" in value:
        config["noteTitleHidden"] = bool(value.get("noteTitleHidden"))
    if "noteItems" in value:
        config["noteItems"] = _normalize_saved_note_items(value.get("noteItems"))
    for key in ("layoutSpan", "layoutHeight", "maxLayoutSpan", "maxLayoutHeight"):
        raw = value.get(key)
        if raw is None:
            continue
        try:
            number = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= number <= 24:
            config[key] = number
    return config


def _normalize_saved_note_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for raw in value[:80]:
        if not isinstance(raw, dict):
            continue
        item_id = str(raw.get("id") or "").strip()[:160]
        item_type = str(raw.get("type") or "").strip()
        if not item_id:
            continue
        if item_type == "paragraph":
            item: dict[str, Any] = {
                "id": item_id,
                "type": "paragraph",
                "text": str(raw.get("text") or "")[:8000],
            }
            html = str(raw.get("html") or "").strip()
            if html:
                item["html"] = html[:16000]
            items.append(item)
        elif item_type == "image":
            src = str(raw.get("src") or "").strip()[:4000]
            if not src:
                continue
            items.append({
                "id": item_id,
                "type": "image",
                "src": src,
                "name": str(raw.get("name") or "image").strip()[:300] or "image",
            })
    return items


def _report_object_visible(item: dict[str, Any], actor_user_id: str | None) -> bool:
    if not actor_user_id:
        return True
    return item.get("ownerUserId") == actor_user_id or item.get("visibility") == "tenant"


def _normalize_weekly_report_version(version: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(version, dict):
        raise ValueError("weekly report version must be an object.")
    report = version.get("report") if isinstance(version.get("report"), dict) else {}
    version_id = str(version.get("id") or "").strip()
    report_id = str(version.get("reportId") or report.get("id") or "").strip()
    if not version_id:
        raise ValueError("weekly report version id is required.")
    if not report_id:
        raise ValueError("weekly report version reportId is required.")
    name = str(version.get("name") or "").strip()
    if not name:
        institution = str(report.get("institutionName") or "某机构").strip()
        period = str(report.get("period") or "未记录周期").strip()
        name = f"{institution}经营周报：{period}"
    comments = version.get("comments") if isinstance(version.get("comments"), list) else []
    return {
        **version,
        "id": version_id,
        "name": name,
        "savedAt": str(version.get("savedAt") or "").strip() or "未记录",
        "tenantId": str(version.get("tenantId") or "").strip(),
        "reportId": report_id,
        "report": report,
        "comments": [comment for comment in comments if isinstance(comment, dict)][:500],
    }


def _prepare_weekly_report_version(
    tenant_id: str,
    version: dict[str, Any],
    updated_by: str | None,
) -> dict[str, Any]:
    normalized = _normalize_weekly_report_version(version)
    evidence_summary = _report_evidence_summary(normalized["report"])
    content_material = {
        "reportId": normalized["reportId"],
        "report": normalized["report"],
        "comments": normalized["comments"],
        "analysisTaskRefs": normalized.get("analysisTaskRefs") if isinstance(normalized.get("analysisTaskRefs"), list) else [],
        "analysisEvidenceRefs": normalized.get("analysisEvidenceRefs") if isinstance(normalized.get("analysisEvidenceRefs"), list) else [],
    }
    content_hash = hashlib.sha256(
        json.dumps(content_material, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return {
        **normalized,
        "tenantId": tenant_id,
        "updatedBy": updated_by or normalized.get("updatedBy") or "",
        "ownerUserId": str(normalized.get("ownerUserId") or updated_by or ""),
        "visibility": "tenant",
        "contentHash": content_hash,
        "parentVersionId": str(normalized.get("parentVersionId") or "") or None,
        "revisionNo": int(normalized.get("revisionNo") or 0),
        "lifecycleStatus": "saved",
        "publicationStatus": "ready" if evidence_summary["publishable"] else "review_required",
        "evidenceSummary": evidence_summary,
    }


def _report_evidence_summary(report: dict[str, Any]) -> dict[str, Any]:
    table_blocks: list[dict[str, Any]] = []
    for section in report.get("sections", []) if isinstance(report.get("sections"), list) else []:
        if not isinstance(section, dict):
            continue
        for block in section.get("blocks", []) if isinstance(section.get("blocks"), list) else []:
            if isinstance(block, dict) and block.get("type") == "table":
                table_blocks.append(block)
    verified = []
    unverified = []
    for block in table_blocks:
        evidence = block.get("evidenceRef") if isinstance(block.get("evidenceRef"), dict) else {}
        complete = bool(
            evidence.get("verified") is True
            and evidence.get("evidence_id")
            and evidence.get("evidence_hash")
            and evidence.get("source_snapshot")
        )
        (verified if complete else unverified).append(str(block.get("id") or "unknown_block"))
    return {
        "table_block_count": len(table_blocks),
        "verified_block_ids": verified,
        "unverified_block_ids": unverified,
        "publishable": bool(table_blocks) and not unverified,
        "checked_at": _utcnow(),
    }


def _weekly_version_from_row(row: sqlite3.Row) -> dict[str, Any]:
    normalized = _normalize_weekly_report_version(json.loads(row["payload"]))
    return {
        **normalized,
        "ownerUserId": str(row["owner_user_id"] or ""),
        "contentHash": str(row["content_hash"] or ""),
        "parentVersionId": str(row["parent_version_id"] or "") or None,
        "revisionNo": int(row["revision_no"] or 1),
        "lifecycleStatus": str(row["lifecycle_status"] or "saved"),
        "publicationStatus": str(row["publication_status"] or "review_required"),
        "evidenceSummary": json.loads(row["evidence_summary"] or "{}"),
        "visibility": str(normalized.get("visibility") or "tenant"),
    }


def _learning_candidate(
    tenant_id: str,
    version_id: str,
    candidate_type: str,
    content: dict[str, Any],
    evidence_summary: dict[str, Any],
    confidence: float,
    created_by: str,
) -> dict[str, Any]:
    if candidate_type not in {"analysis_method", "behavior_habit", "todo", "business_fact"}:
        raise ValueError("invalid_report_learning_candidate_type")
    content_json = json.dumps(content, ensure_ascii=False, sort_keys=True)
    now = _utcnow()
    return {
        "tenant_id": tenant_id,
        "learning_candidate_id": f"rlc_{uuid4().hex}",
        "version_id": version_id,
        "candidate_type": candidate_type,
        "candidate_content": json.loads(content_json),
        "content_hash": hashlib.sha256(content_json.encode("utf-8")).hexdigest(),
        "evidence_summary": json.loads(json.dumps(evidence_summary, ensure_ascii=False)),
        "confidence": max(0, min(float(confidence), 1)),
        "status": "candidate",
        "reviewed_by": None,
        "reviewed_at": None,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }


def _learning_candidate_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["candidate_content"] = json.loads(result["candidate_content"] or "{}")
    result["evidence_summary"] = json.loads(result["evidence_summary"] or "{}")
    return result


def _normalize_weekly_ai_task(task: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(task, dict):
        raise ValueError("weekly AI analysis task must be an object.")
    version_id = str(task.get("version_id") or task.get("versionId") or "").strip()
    if not version_id:
        raise ValueError("weekly AI analysis task version_id is required.")
    task_id = str(task.get("id") or task.get("task_id") or f"weekly_ai_task_{version_id}").strip()
    status = str(task.get("status") or "待分析").strip()
    if status not in {"待分析", "分析中", "已完成", "分析失败"}:
        status = "待分析"
    created_at = str(task.get("created_at") or task.get("createdAt") or "").strip()
    updated_at = str(task.get("updated_at") or task.get("updatedAt") or created_at).strip()
    return {
        "id": task_id,
        "tenant_id": str(task.get("tenant_id") or task.get("tenantId") or "").strip(),
        "version_id": version_id,
        "status": status,
        "input_snapshot": _dict_or_empty(task.get("input_snapshot") or task.get("inputSnapshot")),
        "debate_result": _dict_or_empty(task.get("debate_result") or task.get("debateResult")),
        "final_result": _dict_or_empty(task.get("final_result") or task.get("finalResult")),
        "error_message": str(task.get("error_message") or task.get("errorMessage") or "").strip(),
        "created_by": str(task.get("created_by") or task.get("createdBy") or "").strip(),
        "updated_by": str(task.get("updated_by") or task.get("updatedBy") or "").strip(),
        "created_at": created_at,
        "updated_at": updated_at or created_at,
    }


def _weekly_ai_task_from_row(tenant_id: str, row: sqlite3.Row) -> dict[str, Any]:
    return _normalize_weekly_ai_task(
        {
            "id": row["task_id"],
            "tenant_id": tenant_id,
            "version_id": row["version_id"],
            "status": _weekly_status_from_db(str(row["status"])),
            "input_snapshot": json.loads(row["input_snapshot"] or "{}"),
            "debate_result": json.loads(row["debate_result"] or "{}"),
            "final_result": json.loads(row["final_result"] or "{}"),
            "error_message": row["error_message"] or "",
            "created_by": row["created_by"] or "",
            "updated_by": row["updated_by"] or "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    )


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _weekly_status_to_db(value: str) -> str:
    return {
        "待分析": "queued",
        "分析中": "running",
        "已完成": "completed",
        "分析失败": "failed",
    }.get(value, "queued")


def _weekly_status_from_db(value: str) -> str:
    return {
        "queued": "待分析",
        "running": "分析中",
        "completed": "已完成",
        "failed": "分析失败",
    }.get(value, value)


def _normalize_daily_report_run(tenant_id: str, payload: dict[str, Any], created_by: str) -> dict[str, Any]:
    report_date = str(payload.get("report_date") or "").strip()
    try:
        datetime.fromisoformat(report_date)
    except ValueError as exc:
        raise ValueError("invalid_daily_report_date") from exc
    subject = " ".join(str(payload.get("subject") or "").replace("\r", " ").replace("\n", " ").split())
    if not subject or len(subject) > 998:
        raise ValueError("invalid_daily_report_subject")
    source_version_id = str(payload.get("source_report_version_id") or "").strip()
    body_artifact_id = str(payload.get("body_artifact_id") or "").strip()
    content_hash = str(payload.get("content_hash") or "").strip().lower()
    if not source_version_id or not body_artifact_id or len(content_hash) != 64:
        raise ValueError("invalid_daily_report_evidence")
    now = _utcnow()
    return {
        "tenant_id": tenant_id,
        "daily_report_run_id": f"drr_{uuid4().hex}",
        "owner_user_id": created_by,
        "report_date": report_date[:10],
        "source_report_version_id": source_version_id,
        "subject": subject,
        "body_artifact_id": body_artifact_id,
        "content_hash": content_hash,
        "evidence_summary": _dict_or_empty(payload.get("evidence_summary")),
        "preview_text": str(payload.get("preview_text") or "").strip()[:4000],
        "status": "generated",
        "outbox_event_id": None,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }


def _daily_report_run_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["evidence_summary"] = json.loads(result.get("evidence_summary") or "{}")
    return result


def _normalize_comments(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(comments, list):
        raise ValueError("comments must be a list.")
    normalized: list[dict[str, Any]] = []
    for item in comments[:500]:
        if not isinstance(item, dict):
            continue
        comment = {
            "id": str(item.get("id") or "").strip(),
            "targetId": str(item.get("targetId") or "").strip(),
            "targetLabel": str(item.get("targetLabel") or "").strip(),
            "selectedText": str(item.get("selectedText") or "").strip(),
            "blockId": str(item.get("blockId") or "").strip(),
            "itemId": str(item.get("itemId") or "").strip(),
            "rangeStart": _optional_int(item.get("rangeStart")),
            "rangeEnd": _optional_int(item.get("rangeEnd")),
            "anchorTop": _optional_number(item.get("anchorTop")),
            "status": _normalize_comment_status(item.get("status")),
            "resolvedAt": str(item.get("resolvedAt") or "").strip(),
            "resolvedBy": str(item.get("resolvedBy") or "").strip(),
            "resolvedReason": _normalize_resolved_reason(item.get("resolvedReason")),
            "targetKind": _normalize_target_kind(item),
            "author": str(item.get("author") or "").strip() or "当前用户",
            "time": str(item.get("time") or "").strip(),
            "text": str(item.get("text") or "").strip(),
            "replies": _normalize_replies(item.get("replies")),
        }
        if comment["id"] and comment["targetId"] and comment["text"]:
            normalized.append({key: value for key, value in comment.items() if value not in ("", None)})
    return normalized


def _normalize_comment_status(value: Any) -> str:
    return "resolved" if value == "resolved" else "open"


def _normalize_resolved_reason(value: Any) -> str:
    return value if value in {"manual", "source_text_deleted", "source_text_replaced"} else ""


def _normalize_target_kind(item: dict[str, Any]) -> str:
    value = item.get("targetKind")
    if value in {"paragraph", "analysis", "table", "chart"}:
        return str(value)
    target_id = str(item.get("targetId") or "")
    item_id = str(item.get("itemId") or "")
    if "_analysis_text" in target_id or "_analysis_conclusion" in item_id:
        return "analysis"
    if target_id.endswith("_trend"):
        return "chart"
    if target_id.endswith("_data"):
        return "table"
    if item_id or "_selection" in target_id or target_id.endswith("_text"):
        return "paragraph"
    return ""


def _normalize_replies(replies: Any) -> list[dict[str, Any]]:
    if not isinstance(replies, list):
        return []
    normalized = []
    for item in replies[:200]:
        if not isinstance(item, dict):
            continue
        reply = {
            "id": str(item.get("id") or "").strip(),
            "author": str(item.get("author") or "").strip() or "当前用户",
            "time": str(item.get("time") or "").strip(),
            "text": str(item.get("text") or "").strip(),
        }
        if reply["id"] and reply["text"]:
            normalized.append(reply)
    return normalized


def _optional_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _older_than(value: Any, cutoff: datetime) -> bool:
    text = str(value or "").strip()
    if not text or text == "未记录":
        return False
    normalized = text.replace("Z", "+00:00")
    try:
        observed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return observed.astimezone(timezone.utc) < cutoff.astimezone(timezone.utc)
