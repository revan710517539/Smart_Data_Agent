from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:  # Optional at source checkout time; declared as a production dependency.
    from croniter import croniter as _croniter
except ImportError:  # pragma: no cover - exercised by the bundled fallback tests.
    _croniter = None

from backend.platform.security.secrets import decrypt_secret, encrypt_secret
from backend.platform.storage import connect_sqlite


TASK_TYPES = {"acquisition", "analysis", "report", "export", "notification", "quality", "market_monitoring", "custom"}


class SQLiteAutomationStore:
    def __init__(self, db_path: str | Path, initialize: bool = False) -> None:
        self.db_path = str(db_path)
        self._conn = connect_sqlite(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._owns_connection = True
        if initialize:
            self.init_schema()

    def close(self) -> None:
        if self._owns_connection:
            self._conn.close()

    def init_schema(self) -> None:
        migration_dir = Path(__file__).resolve().parents[1] / "database" / "sql"
        for migration_name in (
            "0009_automation_notifications.sql",
            "0012_daily_email_delivery.sql",
            "0014_automation_task_optimistic_lock.sql",
            "0018_notification_management_callbacks.sql",
        ):
            self._conn.executescript((migration_dir / migration_name).read_text(encoding="utf-8"))
        self._conn.commit()

    def create_task(self, tenant_id: str, payload: dict[str, Any], created_by: str) -> dict[str, Any]:
        task_code = _required(payload.get("task_code", payload.get("taskCode")), "task_code", 160)
        task_name = _required(payload.get("task_name", payload.get("taskName")), "task_name", 300)
        task_type = str(payload.get("task_type", payload.get("taskType")) or "custom").strip()
        if task_type not in TASK_TYPES:
            raise ValueError("invalid_automation_task_type")
        trigger_type = str(payload.get("trigger_type", payload.get("triggerType")) or "manual").strip()
        if trigger_type not in {"manual", "schedule", "event"}:
            raise ValueError("invalid_automation_trigger_type")
        schedule = str(payload.get("schedule_expression", payload.get("scheduleExpression")) or "").strip() or None
        event_type = str(payload.get("event_type", payload.get("eventType")) or "").strip() or None
        if trigger_type == "schedule" and not schedule:
            raise ValueError("schedule_expression_required")
        if trigger_type == "event" and not event_type:
            raise ValueError("event_type_required")
        handler_ref = _required(payload.get("handler_ref", payload.get("handlerRef")), "handler_ref", 300)
        task_config = _object(payload.get("task_config", payload.get("taskConfig", {})))
        retry_policy = _object(payload.get("retry_policy", payload.get("retryPolicy", {})))
        timeout_seconds = max(1, min(int(payload.get("timeout_seconds", payload.get("timeoutSeconds", 900))), 86_400))
        max_concurrency = max(1, min(int(payload.get("max_concurrency", payload.get("maxConcurrency", 1))), 100))
        now = _utcnow()
        next_run_at = _next_run(schedule, now, _schedule_timezone(task_config)) if schedule else None
        task_id = str(payload.get("automation_task_id") or f"at_{uuid4().hex}")
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_automation_tasks(
                    tenant_id, automation_task_id, task_code, task_name, task_type,
                    trigger_type, schedule_expression, event_type, handler_ref, task_config,
                    retry_policy, timeout_seconds, max_concurrency, status, next_run_at,
                    owner_user_id, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id, task_id, task_code, task_name, task_type, trigger_type,
                    schedule, event_type, handler_ref, _json(task_config), _json(retry_policy),
                    timeout_seconds, max_concurrency, next_run_at, created_by, created_by, now, now,
                ),
            )
        return self.get_task(tenant_id, task_id)

    def get_task(self, tenant_id: str, task_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM platform_automation_tasks WHERE tenant_id = ? AND automation_task_id = ?",
            (tenant_id, task_id),
        ).fetchone()
        if not row:
            raise KeyError("automation_task_not_found")
        return _task_row(row)

    def list_tasks(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM platform_automation_tasks WHERE tenant_id = ? ORDER BY updated_at DESC",
            (tenant_id,),
        ).fetchall()
        return [_task_row(row) for row in rows]

    def get_task_by_code(self, tenant_id: str, task_code: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM platform_automation_tasks WHERE tenant_id = ? AND task_code = ?",
            (tenant_id, task_code),
        ).fetchone()
        return _task_row(row) if row else None

    def update_task(
        self,
        tenant_id: str,
        task_id: str,
        payload: dict[str, Any],
        actor_user_id: str,
        expected_lock_version: int,
    ) -> dict[str, Any]:
        current = self.get_task(tenant_id, task_id)
        if current["owner_user_id"] != actor_user_id:
            raise PermissionError("automation_task_owner_required")
        if int(current.get("lock_version") or 0) != int(expected_lock_version):
            raise ValueError("automation_task_revision_conflict")
        task_name = _required(payload.get("task_name", payload.get("taskName", current["task_name"])), "task_name", 300)
        trigger_type = str(payload.get("trigger_type", payload.get("triggerType", current["trigger_type"]))).strip()
        if trigger_type not in {"manual", "schedule", "event"}:
            raise ValueError("invalid_automation_trigger_type")
        schedule = str(payload.get("schedule_expression", payload.get("scheduleExpression", current.get("schedule_expression") or ""))).strip() or None
        event_type = str(payload.get("event_type", payload.get("eventType", current.get("event_type") or ""))).strip() or None
        if trigger_type == "schedule" and not schedule:
            raise ValueError("schedule_expression_required")
        if trigger_type == "event" and not event_type:
            raise ValueError("event_type_required")
        task_config = _object(payload.get("task_config", payload.get("taskConfig", current["task_config"])))
        retry_policy = _object(payload.get("retry_policy", payload.get("retryPolicy", current["retry_policy"])))
        status = str(payload.get("status") or current["status"]).strip()
        if status not in {"active", "paused", "disabled"}:
            raise ValueError("invalid_automation_task_status")
        timeout_seconds = max(1, min(int(payload.get("timeout_seconds", payload.get("timeoutSeconds", current["timeout_seconds"]))), 86_400))
        max_concurrency = max(1, min(int(payload.get("max_concurrency", payload.get("maxConcurrency", current["max_concurrency"]))), 100))
        next_run_at = _next_run(schedule, _utcnow(), _schedule_timezone(task_config)) if status == "active" and trigger_type == "schedule" else None
        with self._conn:
            cursor = self._conn.execute(
                """
                UPDATE platform_automation_tasks
                SET task_name = ?, trigger_type = ?, schedule_expression = ?, event_type = ?,
                    task_config = ?, retry_policy = ?, timeout_seconds = ?, max_concurrency = ?,
                    status = ?, next_run_at = ?, updated_at = ?, lock_version = lock_version + 1
                WHERE tenant_id = ? AND automation_task_id = ? AND owner_user_id = ? AND lock_version = ?
                """,
                (
                    task_name, trigger_type, schedule, event_type, _json(task_config), _json(retry_policy),
                    timeout_seconds, max_concurrency, status, next_run_at, _utcnow(), tenant_id, task_id,
                    actor_user_id, int(expected_lock_version),
                ),
            )
        if cursor.rowcount != 1:
            raise ValueError("automation_task_revision_conflict")
        return self.get_task(tenant_id, task_id)

    def enqueue_run(
        self,
        tenant_id: str,
        task_id: str,
        idempotency_key: str,
        trigger_type: str,
        trigger_payload: dict[str, Any],
        created_by: str,
    ) -> dict[str, Any]:
        task = self.get_task(tenant_id, task_id)
        if task["status"] != "active":
            raise ValueError("automation_task_is_not_active")
        key = _required(idempotency_key, "idempotency_key", 200)
        existing = self._conn.execute(
            """
            SELECT * FROM platform_automation_task_runs
            WHERE tenant_id = ? AND automation_task_id = ? AND idempotency_key = ?
            """,
            (tenant_id, task_id, key),
        ).fetchone()
        if existing:
            return _run_row(existing)
        run_id = f"atr_{uuid4().hex}"
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_automation_task_runs(
                    tenant_id, automation_run_id, automation_task_id, idempotency_key,
                    trigger_type, trigger_payload, status, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)
                """,
                (tenant_id, run_id, task_id, key, trigger_type, _json(trigger_payload), created_by, now, now),
            )
        return self.get_run(tenant_id, run_id)

    def enqueue_due_tasks(self, now: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        current = now or _utcnow()
        rows = self._conn.execute(
            """
            SELECT * FROM platform_automation_tasks
            WHERE status = 'active' AND trigger_type = 'schedule'
              AND next_run_at IS NOT NULL AND next_run_at <= ?
            ORDER BY next_run_at LIMIT ?
            """,
            (current, max(1, min(int(limit), 500))),
        ).fetchall()
        queued: list[dict[str, Any]] = []
        for row in rows:
            task = _task_row(row)
            due_at = str(task["next_run_at"])
            run = self.enqueue_run(
                task["tenant_id"],
                task["automation_task_id"],
                f"schedule:{due_at}",
                "schedule",
                {"scheduled_for": due_at},
                "system_scheduler",
            )
            next_run = _next_run(task["schedule_expression"], current, _schedule_timezone(task["task_config"]))
            with self._conn:
                self._conn.execute(
                    "UPDATE platform_automation_tasks SET next_run_at = ?, updated_at = ? WHERE tenant_id = ? AND automation_task_id = ?",
                    (next_run, current, task["tenant_id"], task["automation_task_id"]),
                )
            queued.append(run)
        return queued

    def claim_run(self, worker_id: str, lease_seconds: int = 60) -> tuple[dict[str, Any], dict[str, Any]] | None:
        now = _utcnow()
        lease_expires = (datetime.now(timezone.utc) + timedelta(seconds=max(10, lease_seconds))).isoformat()
        with self._conn:
            candidates = self._conn.execute(
                """
                SELECT r.*, t.max_concurrency
                FROM platform_automation_task_runs r
                JOIN platform_automation_tasks t
                  ON t.tenant_id = r.tenant_id AND t.automation_task_id = r.automation_task_id
                WHERE t.status = 'active'
                  AND (
                    r.status = 'queued'
                    OR (r.status = 'retry_wait' AND r.next_retry_at <= ?)
                    OR (r.status = 'running' AND r.lease_expires_at < ?)
                  )
                ORDER BY r.created_at
                LIMIT 50
                """,
                (now, now),
            ).fetchall()
            selected: sqlite3.Row | None = None
            for candidate in candidates:
                running_count = int(
                    self._conn.execute(
                        """
                        SELECT COUNT(*) FROM platform_automation_task_runs
                        WHERE tenant_id = ? AND automation_task_id = ? AND status = 'running'
                          AND (lease_expires_at IS NULL OR lease_expires_at >= ?)
                        """,
                        (candidate["tenant_id"], candidate["automation_task_id"], now),
                    ).fetchone()[0]
                )
                if running_count < int(candidate["max_concurrency"]):
                    selected = candidate
                    break
            if selected is None:
                return None
            next_attempt = int(selected["attempt_no"] or 1)
            if str(selected["status"]) in {"retry_wait", "running"}:
                next_attempt += 1
            self._conn.execute(
                """
                UPDATE platform_automation_task_runs
                SET status = 'running', attempt_no = ?, lease_owner = ?, lease_expires_at = ?,
                    started_at = COALESCE(started_at, ?), next_retry_at = NULL, updated_at = ?
                WHERE tenant_id = ? AND automation_run_id = ?
                """,
                (next_attempt, worker_id, lease_expires, now, now, selected["tenant_id"], selected["automation_run_id"]),
            )
        run = self.get_run(str(selected["tenant_id"]), str(selected["automation_run_id"]))
        task = self.get_task(run["tenant_id"], run["automation_task_id"])
        return run, task

    def get_run(self, tenant_id: str, run_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM platform_automation_task_runs WHERE tenant_id = ? AND automation_run_id = ?",
            (tenant_id, run_id),
        ).fetchone()
        if not row:
            raise KeyError("automation_run_not_found")
        return _run_row(row)

    def list_runs(self, tenant_id: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM platform_automation_task_runs WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
            (tenant_id, max(1, min(int(limit), 500))),
        ).fetchall()
        return [_run_row(row) for row in rows]

    def cancel_run(self, tenant_id: str, run_id: str, actor_user_id: str) -> dict[str, Any]:
        current = self.get_run(tenant_id, run_id)
        if str(current["created_by"]) != actor_user_id:
            raise PermissionError("Only the run owner may cancel this execution.")
        if current["status"] in {"succeeded", "failed", "cancelled"}:
            return current
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                UPDATE platform_automation_task_runs
                SET status = 'cancelled', error_code = 'cancelled_by_user',
                    error_summary = 'Execution cancelled by its owner.',
                    finished_at = ?, next_retry_at = NULL, lease_owner = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE tenant_id = ? AND automation_run_id = ?
                  AND status IN ('queued','running','retry_wait')
                """,
                (now, now, tenant_id, run_id),
            )
        return self.get_run(tenant_id, run_id)

    def finish_run(
        self,
        tenant_id: str,
        run_id: str,
        *,
        status: str,
        result_refs: list[dict[str, Any]] | None = None,
        error_code: str | None = None,
        error_summary: str | None = None,
        next_retry_at: str | None = None,
    ) -> dict[str, Any]:
        if status not in {"succeeded", "failed", "retry_wait", "cancelled"}:
            raise ValueError("invalid_automation_run_terminal_status")
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                UPDATE platform_automation_task_runs
                SET status = ?, result_refs = ?, error_code = ?, error_summary = ?,
                    next_retry_at = ?, finished_at = CASE WHEN ? = 'retry_wait' THEN NULL ELSE ? END,
                    lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE tenant_id = ? AND automation_run_id = ?
                  AND status NOT IN ('succeeded','failed','cancelled')
                """,
                (
                    status, _json(result_refs or []), error_code, error_summary,
                    next_retry_at, status, now, now, tenant_id, run_id,
                ),
            )
        return self.get_run(tenant_id, run_id)

    def record_step(
        self,
        tenant_id: str,
        run_id: str,
        step_code: str,
        sequence_no: int,
        status: str,
        *,
        input_refs: list[Any] | None = None,
        output_refs: list[Any] | None = None,
        error_code: str | None = None,
    ) -> None:
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_job_steps(
                    tenant_id, job_step_id, automation_run_id, step_code, sequence_no,
                    status, input_refs, output_refs, started_at, finished_at,
                    error_code, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, automation_run_id, step_code) DO UPDATE SET
                    status = excluded.status,
                    output_refs = excluded.output_refs,
                    finished_at = excluded.finished_at,
                    error_code = excluded.error_code,
                    updated_at = excluded.updated_at
                """,
                (
                    tenant_id, f"js_{uuid4().hex}", run_id, step_code, sequence_no,
                    status, _json(input_refs or []), _json(output_refs or []), now,
                    now if status in {"succeeded", "failed", "skipped", "compensated"} else None,
                    error_code, now, now,
                ),
            )

    def list_steps(self, tenant_id: str, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT step_code, sequence_no, status, output_refs, error_code,
                   started_at, finished_at, updated_at
            FROM platform_job_steps
            WHERE tenant_id = ? AND automation_run_id = ?
            ORDER BY sequence_no, started_at
            """,
            (tenant_id, run_id),
        ).fetchall()
        return [
            {
                **dict(row),
                "output_refs": _load(row["output_refs"], []),
            }
            for row in rows
        ]

    def create_subscription(self, tenant_id: str, payload: dict[str, Any], owner_user_id: str) -> dict[str, Any]:
        fields = _subscription_fields(payload)
        subscription_id = f"sub_{uuid4().hex}"
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_subscriptions(
                    tenant_id, subscription_id, owner_user_id, subscription_name,
                    event_types, channel_type, channel_config_secret, filter_expression,
                    quiet_hours, status, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    tenant_id, subscription_id, owner_user_id, fields["subscription_name"], _json(fields["event_types"]),
                    fields["channel_type"], encrypt_secret(_json(fields["channel_config"])),
                    _json(fields["filter_expression"]),
                    _json(fields["quiet_hours"]),
                    owner_user_id, now, now,
                ),
            )
        return self.get_subscription(tenant_id, subscription_id, reveal_config=False)

    def update_subscription(
        self,
        tenant_id: str,
        subscription_id: str,
        payload: dict[str, Any],
        owner_user_id: str,
        expected_lock_version: int,
    ) -> dict[str, Any]:
        current = self.get_subscription(tenant_id, subscription_id, reveal_config=True)
        if current["owner_user_id"] != owner_user_id:
            raise PermissionError("subscription_owner_required")
        if int(current.get("lock_version") or 1) != int(expected_lock_version):
            raise ValueError("subscription_revision_conflict")
        merged = {
            "subscription_name": payload.get("subscription_name", payload.get("subscriptionName", current["subscription_name"])),
            "event_types": payload.get("event_types", payload.get("eventTypes", current["event_types"])),
            "channel_type": payload.get("channel_type", payload.get("channelType", current["channel_type"])),
            "channel_config": payload.get("channel_config", payload.get("channelConfig", current["channel_config"])),
            "filter_expression": payload.get("filter_expression", payload.get("filterExpression", current["filter_expression"])),
            "quiet_hours": payload.get("quiet_hours", payload.get("quietHours", current["quiet_hours"])),
        }
        fields = _subscription_fields(merged)
        status = str(payload.get("status") or current["status"]).strip()
        if status not in {"active", "paused", "disabled"}:
            raise ValueError("invalid_subscription_status")
        now = _utcnow()
        with self._conn:
            cursor = self._conn.execute(
                """
                UPDATE platform_subscriptions
                SET subscription_name = ?, event_types = ?, channel_type = ?,
                    channel_config_secret = ?, filter_expression = ?, quiet_hours = ?,
                    status = ?, disabled_at = CASE WHEN ? = 'disabled' THEN ? ELSE NULL END,
                    updated_at = ?, lock_version = lock_version + 1
                WHERE tenant_id = ? AND subscription_id = ? AND owner_user_id = ? AND lock_version = ?
                """,
                (
                    fields["subscription_name"], _json(fields["event_types"]), fields["channel_type"],
                    encrypt_secret(_json(fields["channel_config"])), _json(fields["filter_expression"]),
                    _json(fields["quiet_hours"]), status, status, now, now,
                    tenant_id, subscription_id, owner_user_id, int(expected_lock_version),
                ),
            )
        if cursor.rowcount != 1:
            raise ValueError("subscription_revision_conflict")
        return self.get_subscription(tenant_id, subscription_id, reveal_config=False)

    def disable_subscription(
        self,
        tenant_id: str,
        subscription_id: str,
        owner_user_id: str,
        expected_lock_version: int,
    ) -> dict[str, Any]:
        return self.update_subscription(
            tenant_id,
            subscription_id,
            {"status": "disabled"},
            owner_user_id,
            expected_lock_version,
        )

    def get_subscription(self, tenant_id: str, subscription_id: str, reveal_config: bool = False) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT * FROM platform_subscriptions WHERE tenant_id = ? AND subscription_id = ?",
            (tenant_id, subscription_id),
        ).fetchone()
        if not row:
            raise KeyError("subscription_not_found")
        return _subscription_row(row, reveal_config)

    def list_subscriptions(self, tenant_id: str, owner_user_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM platform_subscriptions WHERE tenant_id = ? AND owner_user_id = ? AND status <> 'disabled' ORDER BY updated_at DESC",
            (tenant_id, owner_user_id),
        ).fetchall()
        return [_subscription_row(row, False) for row in rows]

    def record_provider_callback(
        self,
        tenant_id: str,
        *,
        provider: str,
        provider_event_id: str,
        provider_message_id: str,
        event_type: str,
        payload_hash: str,
        safe_payload: dict[str, Any],
    ) -> dict[str, Any]:
        provider = _required(provider, "provider", 80).lower()
        provider_event_id = _required(provider_event_id, "provider_event_id", 300)
        provider_message_id = _required(provider_message_id, "provider_message_id", 300)
        event_type = _required(event_type, "provider_event_type", 100).lower()
        if len(payload_hash) != 64:
            raise ValueError("invalid_provider_callback_payload_hash")
        existing = self._conn.execute(
            "SELECT * FROM platform_provider_callbacks WHERE provider = ? AND provider_event_id = ?",
            (provider, provider_event_id),
        ).fetchone()
        if existing:
            if str(existing["payload_hash"]) != payload_hash:
                raise ValueError("provider_callback_idempotency_conflict")
            return dict(existing)
        delivery = self._conn.execute(
            """
            SELECT * FROM platform_notification_deliveries
            WHERE tenant_id = ? AND provider_message_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (tenant_id, provider_message_id),
        ).fetchone()
        processing_status = "processed" if delivery else "ignored"
        now = _utcnow()
        callback_id = f"pcb_{uuid4().hex}"
        delivery_status = {
            "accepted": "sending",
            "delivered": "delivered",
            "read": "delivered",
            "opened": "delivered",
            "bounced": "dead_letter",
            "rejected": "dead_letter",
            "failed": "failed",
        }.get(event_type)
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO platform_provider_callbacks(
                    tenant_id, callback_id, provider, provider_event_id,
                    provider_message_id, event_type, signature_valid, payload_hash,
                    safe_payload, processing_status, processed_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id, callback_id, provider, provider_event_id, provider_message_id,
                    event_type, payload_hash, _json(_object(safe_payload)), processing_status, now, now,
                ),
            )
            if delivery and delivery_status:
                self._conn.execute(
                    """
                    UPDATE platform_notification_deliveries
                    SET status = ?, delivered_at = CASE WHEN ? = 'delivered' THEN COALESCE(delivered_at, ?) ELSE delivered_at END,
                        error_code = CASE WHEN ? IN ('failed','dead_letter') THEN ? ELSE NULL END,
                        next_attempt_at = NULL, updated_at = ?
                    WHERE tenant_id = ? AND delivery_id = ?
                    """,
                    (
                        delivery_status, delivery_status, now, delivery_status,
                        f"provider_{event_type}", now, tenant_id, delivery["delivery_id"],
                    ),
                )
        return dict(
            self._conn.execute(
                "SELECT * FROM platform_provider_callbacks WHERE tenant_id = ? AND callback_id = ?",
                (tenant_id, callback_id),
            ).fetchone()
        )

    def enqueue_outbox_event(
        self,
        tenant_id: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        event_key: str | None = None,
        created_by: str | None = None,
    ) -> str:
        del created_by
        key = event_key or f"oe_{uuid4().hex}"
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO platform_outbox_events(
                    tenant_id, outbox_event_id, aggregate_type, aggregate_id,
                    event_type, payload, status, available_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (tenant_id, key, aggregate_type, aggregate_id, event_type, _json(payload), now, now, now),
            )
        return key

    def expand_outbox_once(self) -> int:
        event = self._conn.execute(
            "SELECT * FROM platform_outbox_events WHERE status = 'pending' AND available_at <= ? ORDER BY created_at LIMIT 1",
            (_utcnow(),),
        ).fetchone()
        if not event:
            return 0
        subscriptions = self._conn.execute(
            "SELECT * FROM platform_subscriptions WHERE tenant_id = ? AND status = 'active'",
            (event["tenant_id"],),
        ).fetchall()
        now = _utcnow()
        created = 0
        with self._conn:
            self._conn.execute(
                "UPDATE platform_outbox_events SET status = 'publishing', attempt_count = attempt_count + 1, updated_at = ? WHERE tenant_id = ? AND outbox_event_id = ?",
                (now, event["tenant_id"], event["outbox_event_id"]),
            )
            for subscription in subscriptions:
                if str(event["event_type"]) not in _load(subscription["event_types"], []):
                    continue
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO platform_notification_deliveries(
                        tenant_id, delivery_id, subscription_id, outbox_event_id,
                        channel_type, status, idempotency_key, next_attempt_at,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?)
                    """,
                    (
                        event["tenant_id"], f"nd_{uuid4().hex}", subscription["subscription_id"],
                        event["outbox_event_id"], subscription["channel_type"],
                        f"{subscription['subscription_id']}:{event['outbox_event_id']}", now, now, now,
                    ),
                )
                created += 1
            self._conn.execute(
                "UPDATE platform_outbox_events SET status = 'published', published_at = ?, updated_at = ? WHERE tenant_id = ? AND outbox_event_id = ?",
                (now, now, event["tenant_id"], event["outbox_event_id"]),
            )
        return created

    def claim_delivery(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
        now = _utcnow()
        with self._conn:
            row = self._conn.execute(
                """
                SELECT * FROM platform_notification_deliveries
                WHERE status IN ('queued','failed') AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                  AND attempt_no < 5
                ORDER BY created_at LIMIT 1
                """,
                (now,),
            ).fetchone()
            if not row:
                return None
            self._conn.execute(
                "UPDATE platform_notification_deliveries SET status = 'sending', attempt_no = attempt_no + 1, updated_at = ? WHERE tenant_id = ? AND delivery_id = ?",
                (now, row["tenant_id"], row["delivery_id"]),
            )
        delivery = dict(row)
        delivery["attempt_no"] = int(delivery["attempt_no"] or 0) + 1
        subscription = self.get_subscription(str(row["tenant_id"]), str(row["subscription_id"]), reveal_config=True)
        event_row = self._conn.execute(
            "SELECT * FROM platform_outbox_events WHERE tenant_id = ? AND outbox_event_id = ?",
            (row["tenant_id"], row["outbox_event_id"]),
        ).fetchone()
        if not event_row:
            raise KeyError("outbox_event_not_found")
        event = dict(event_row)
        event["payload"] = _load(event["payload"], {})
        return delivery, subscription, event

    def finish_delivery(
        self,
        tenant_id: str,
        delivery_id: str,
        *,
        status: str,
        provider_message_id: str | None = None,
        error_code: str | None = None,
        next_attempt_at: str | None = None,
    ) -> None:
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                UPDATE platform_notification_deliveries
                SET status = ?, provider_message_id = ?, error_code = ?, next_attempt_at = ?,
                    delivered_at = CASE WHEN ? = 'delivered' THEN ? ELSE delivered_at END,
                    updated_at = ?
                WHERE tenant_id = ? AND delivery_id = ?
                """,
                (status, provider_message_id, error_code, next_attempt_at, status, now, now, tenant_id, delivery_id),
            )

    def list_in_app_deliveries(self, tenant_id: str, owner_user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT d.*, e.event_type, e.payload
            FROM platform_notification_deliveries d
            JOIN platform_subscriptions s
              ON s.tenant_id = d.tenant_id AND s.subscription_id = d.subscription_id
            JOIN platform_outbox_events e
              ON e.tenant_id = d.tenant_id AND e.outbox_event_id = d.outbox_event_id
            WHERE d.tenant_id = ? AND s.owner_user_id = ? AND d.channel_type = 'in_app'
            ORDER BY d.created_at DESC LIMIT ?
            """,
            (tenant_id, owner_user_id, max(1, min(int(limit), 500))),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["payload"] = _load(item["payload"], {})
            result.append(item)
        return result

    def list_deliveries_for_outbox(self, tenant_id: str, outbox_event_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT delivery_id, subscription_id, outbox_event_id, channel_type, status,
                   attempt_no, provider_message_id, error_code, delivered_at, created_at, updated_at
            FROM platform_notification_deliveries
            WHERE tenant_id = ? AND outbox_event_id = ?
            ORDER BY created_at
            """,
            (tenant_id, outbox_event_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def record_email_message(
        self,
        tenant_id: str,
        delivery_id: str,
        *,
        subject: str,
        body_artifact_id: str,
        from_address: str,
        to_address: str,
        provider_message_id: str,
    ) -> None:
        now = _utcnow()
        with self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO platform_email_messages(
                    tenant_id, email_message_id, delivery_id, subject, body_artifact_id,
                    from_address, to_addresses, cc_addresses, attachment_ids,
                    provider_response, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '[]', '[]', ?, ?)
                """,
                (
                    tenant_id, f"em_{uuid4().hex}", delivery_id, subject[:998], body_artifact_id,
                    from_address[:320], _json([to_address]), _json({"provider_message_id": provider_message_id}), now,
                ),
            )


class InMemoryAutomationStore(SQLiteAutomationStore):
    def __init__(self, acquisition_store: Any) -> None:
        self.db_path = ":memory:shared-acquisition"
        self._conn = acquisition_store._conn
        self._owns_connection = False
        self.init_schema()


def _task_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["task_config"] = _load(result["task_config"], {})
    result["retry_policy"] = _load(result["retry_policy"], {})
    return result


def _run_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["trigger_payload"] = _load(result["trigger_payload"], {})
    result["result_refs"] = _load(result["result_refs"], [])
    return result


def _subscription_row(row: sqlite3.Row, reveal_config: bool) -> dict[str, Any]:
    result = dict(row)
    result["event_types"] = _load(result["event_types"], [])
    result["filter_expression"] = _load(result["filter_expression"], {})
    result["quiet_hours"] = _load(result["quiet_hours"], {})
    if reveal_config:
        result["channel_config"] = _load(decrypt_secret(str(result.pop("channel_config_secret"))), {})
    else:
        result.pop("channel_config_secret", None)
        result["channel_config"] = {"configured": True}
    return result


def _subscription_fields(payload: dict[str, Any]) -> dict[str, Any]:
    name = _required(payload.get("subscription_name", payload.get("subscriptionName")), "subscription_name", 300)
    event_types = payload.get("event_types", payload.get("eventTypes", []))
    if not isinstance(event_types, list) or not event_types:
        raise ValueError("event_types_required")
    normalized_events = list(dict.fromkeys(_required(item, "event_type", 160) for item in event_types))
    channel_type = str(payload.get("channel_type", payload.get("channelType")) or "in_app").strip()
    if channel_type not in {"in_app", "email", "webhook"}:
        raise ValueError("invalid_notification_channel")
    channel_config = _object(payload.get("channel_config", payload.get("channelConfig", {})))
    if channel_type == "email" and "@" not in str(channel_config.get("recipient") or ""):
        raise ValueError("notification_email_recipient_required")
    if channel_type == "webhook" and not str(channel_config.get("url") or "").startswith("https://"):
        raise ValueError("https_webhook_url_required")
    return {
        "subscription_name": name,
        "event_types": normalized_events,
        "channel_type": channel_type,
        "channel_config": channel_config,
        "filter_expression": _object(payload.get("filter_expression", payload.get("filterExpression", {}))),
        "quiet_hours": _object(payload.get("quiet_hours", payload.get("quietHours", {}))),
    }


def _next_run(expression: str, base_time: str, schedule_timezone: str = "UTC") -> str:
    try:
        base = datetime.fromisoformat(base_time.replace("Z", "+00:00"))
        zone = ZoneInfo(schedule_timezone)
        base = base.astimezone(zone)
        if _croniter is not None:
            return _croniter(expression, base).get_next(datetime).astimezone(timezone.utc).isoformat()
        fields = expression.split()
        if len(fields) != 5:
            raise ValueError("five_field_cron_required")
        candidate = base.astimezone(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(60 * 24 * 366):
            # Python Monday is 0; cron Sunday is 0.
            cron_weekday = (candidate.weekday() + 1) % 7
            values = (candidate.minute, candidate.hour, candidate.day, candidate.month, cron_weekday)
            ranges = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
            if all(_cron_field_matches(field, value, minimum, maximum) for field, value, (minimum, maximum) in zip(fields, values, ranges)):
                return candidate.isoformat()
            candidate += timedelta(minutes=1)
        raise ValueError("cron_next_run_not_found")
    except Exception as exc:
        raise ValueError("invalid_schedule_expression") from exc


def _schedule_timezone(task_config: dict[str, Any]) -> str:
    value = str(task_config.get("schedule_timezone") or "UTC").strip() or "UTC"
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("invalid_schedule_timezone") from exc
    return value


def _cron_field_matches(field: str, value: int, minimum: int, maximum: int) -> bool:
    for part in field.split(","):
        part = part.strip()
        if part == "*":
            return True
        if part.startswith("*/"):
            step = int(part[2:])
            if step > 0 and (value - minimum) % step == 0:
                return True
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text), int(end_text)
            if minimum <= start <= value <= end <= maximum:
                return True
            continue
        if int(part) == value and minimum <= value <= maximum:
            return True
    return False


def _required(value: Any, field: str, max_length: int) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > max_length:
        raise ValueError(f"invalid_{field}")
    return normalized


def _object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("json_object_required")
    return json.loads(json.dumps(value, ensure_ascii=False))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: Any, default: Any) -> Any:
    try:
        return json.loads(str(value)) if value not in (None, "") else default
    except (TypeError, json.JSONDecodeError):
        return default


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
