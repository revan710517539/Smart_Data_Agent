from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator
from uuid import uuid4

from backend.platform.database.identity import PostgreSQLIdentityResolver
from backend.platform.database.postgresql import PostgreSQLConnectionPool
from backend.platform.security.secrets import decrypt_secret, encrypt_secret

from .store import TEAMS_CONNECTION_EVENT_TYPE, TASK_TYPES, _next_run, _object, _required, _schedule_timezone, _subscription_fields


class PostgreSQLAutomationStore:
    """Concurrent production queue, scheduler, outbox and notification store."""

    def __init__(self, pool: PostgreSQLConnectionPool, *, owns_pool: bool = False) -> None:
        self.pool = pool
        self.owns_pool = owns_pool

    def close(self) -> None:
        if self.owns_pool:
            self.pool.close()

    def create_task(self, tenant_id: str, payload: dict[str, Any], created_by: str) -> dict[str, Any]:
        task_code = _required(payload.get("task_code", payload.get("taskCode")), "task_code", 160)
        task_name = _required(payload.get("task_name", payload.get("taskName")), "task_name", 300)
        task_type = str(payload.get("task_type", payload.get("taskType")) or "custom").strip()
        if task_type not in TASK_TYPES:
            raise ValueError("invalid_automation_task_type")
        fields = _task_fields(payload)
        task_key = str(payload.get("automation_task_id") or f"at_{uuid4().hex}")
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, created_by)
            next_run = _next_run(fields["schedule"], _now(), _schedule_timezone(fields["task_config"])) if fields["schedule"] else None
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_automation_tasks(
                        tenant_id, automation_task_key, task_code, task_name, task_type,
                        trigger_type, schedule_expression, event_type, handler_ref,
                        task_config, retry_policy, timeout_seconds, max_concurrency,
                        status, next_run_at, owner_user_id, created_by
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,'active',%s,%s,%s)
                    """,
                    (
                        tenant_key, task_key, task_code, task_name, task_type,
                        fields["trigger_type"], fields["schedule"], fields["event_type"], fields["handler_ref"],
                        _json(fields["task_config"]), _json(fields["retry_policy"]),
                        fields["timeout_seconds"], fields["max_concurrency"], next_run, actor_key, actor_key,
                    ),
                )
        return self.get_task(tenant_id, task_key)

    def get_task(self, tenant_id: str, task_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._task_select() + " WHERE t.tenant_id = %s AND t.automation_task_key = %s", (tenant_key, task_id))
                row = cursor.fetchone()
        if not row:
            raise KeyError("automation_task_not_found")
        return self._task_row(row)

    def list_tasks(self, tenant_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._task_select() + " WHERE t.tenant_id = %s ORDER BY t.updated_at DESC LIMIT 500", (tenant_key,))
                rows = cursor.fetchall()
        return [self._task_row(row) for row in rows]

    def pause_tasks_by_handler_refs(self, handler_refs: set[str]) -> int:
        refs = sorted({str(item).strip() for item in handler_refs if str(item).strip()})
        if not refs:
            return 0
        placeholders = ",".join("%s" for _ in refs)
        with self._transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE platform_automation_tasks
                    SET status = 'paused', next_run_at = NULL, updated_at = now(),
                        lock_version = lock_version + 1
                    WHERE handler_ref IN ({placeholders}) AND status = 'active'
                    """,
                    tuple(refs),
                )
                return int(cursor.rowcount)

    def get_task_by_code(self, tenant_id: str, task_code: str) -> dict[str, Any] | None:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._task_select() + " WHERE t.tenant_id = %s AND t.task_code = %s", (tenant_key, task_code))
                row = cursor.fetchone()
        return self._task_row(row) if row else None

    def update_task(
        self,
        tenant_id: str,
        task_id: str,
        payload: dict[str, Any],
        actor_user_id: str,
        expected_lock_version: int,
    ) -> dict[str, Any]:
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, actor_user_id)
            with connection.cursor() as cursor:
                cursor.execute(self._task_select() + " WHERE t.tenant_id = %s AND t.automation_task_key = %s FOR UPDATE OF t", (tenant_key, task_id))
                row = cursor.fetchone()
                if not row:
                    raise KeyError("automation_task_not_found")
                current = self._task_row(row)
                if _value(row, "owner_user_key", 21) != actor_key:
                    raise PermissionError("automation_task_owner_required")
                if int(current["lock_version"]) != int(expected_lock_version):
                    raise ValueError("automation_task_revision_conflict")
                merged = dict(payload)
                for snake, camel, value in (
                    ("trigger_type", "triggerType", current["trigger_type"]),
                    ("schedule_expression", "scheduleExpression", current.get("schedule_expression")),
                    ("event_type", "eventType", current.get("event_type")),
                    ("handler_ref", "handlerRef", current["handler_ref"]),
                    ("task_config", "taskConfig", current["task_config"]),
                    ("retry_policy", "retryPolicy", current["retry_policy"]),
                    ("timeout_seconds", "timeoutSeconds", current["timeout_seconds"]),
                    ("max_concurrency", "maxConcurrency", current["max_concurrency"]),
                ):
                    if snake not in merged and camel not in merged:
                        merged[snake] = value
                fields = _task_fields(merged)
                task_name = _required(payload.get("task_name", payload.get("taskName", current["task_name"])), "task_name", 300)
                status = str(payload.get("status") or current["status"]).strip()
                if status not in {"active", "paused", "disabled"}:
                    raise ValueError("invalid_automation_task_status")
                next_run = _next_run(fields["schedule"], _now(), _schedule_timezone(fields["task_config"])) if status == "active" and fields["trigger_type"] == "schedule" else None
                cursor.execute(
                    """
                    UPDATE platform_automation_tasks SET
                        task_name=%s, trigger_type=%s, schedule_expression=%s, event_type=%s,
                        handler_ref=%s, task_config=%s::jsonb, retry_policy=%s::jsonb,
                        timeout_seconds=%s, max_concurrency=%s, status=%s, next_run_at=%s,
                        updated_at=now(), lock_version=lock_version+1
                    WHERE tenant_id=%s AND automation_task_key=%s AND owner_user_id=%s AND lock_version=%s
                    """,
                    (
                        task_name, fields["trigger_type"], fields["schedule"], fields["event_type"], fields["handler_ref"],
                        _json(fields["task_config"]), _json(fields["retry_policy"]), fields["timeout_seconds"],
                        fields["max_concurrency"], status, next_run, tenant_key, task_id, actor_key, int(expected_lock_version),
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
        key = _required(idempotency_key, "idempotency_key", 200)
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, created_by)
            task_key = self._task_uuid(connection, tenant_key, task_id, active=True)
            run_key = f"atr_{uuid4().hex}"
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_automation_task_runs(
                        tenant_id, automation_run_key, automation_task_id, idempotency_key,
                        trigger_type, trigger_payload, status, created_by
                    ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,'queued',%s)
                    ON CONFLICT (tenant_id, automation_task_id, idempotency_key) DO NOTHING
                    """,
                    (tenant_key, run_key, task_key, key, trigger_type, _json(_object(trigger_payload)), actor_key),
                )
                cursor.execute(
                    """
                    SELECT automation_run_key FROM platform_automation_task_runs
                    WHERE tenant_id=%s AND automation_task_id=%s AND idempotency_key=%s
                    """,
                    (tenant_key, task_key, key),
                )
                run_key = str(_value(cursor.fetchone(), "automation_run_key", 0))
        return self.get_run(tenant_id, run_key)

    def enqueue_due_tasks(self, now: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        current = now or _now()
        queued_keys: list[tuple[str, str]] = []
        with self._transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT t.tenant_id, tenant.tenant_code, t.automation_task_id, t.automation_task_key,
                           t.schedule_expression, t.next_run_at, t.owner_user_id, t.task_config
                    FROM platform_automation_tasks t
                    JOIN platform_tenants tenant ON tenant.tenant_id=t.tenant_id
                    WHERE t.status='active' AND t.trigger_type='schedule'
                      AND t.next_run_at IS NOT NULL AND t.next_run_at <= %s::timestamptz
                    ORDER BY t.next_run_at
                    FOR UPDATE OF t SKIP LOCKED LIMIT %s
                    """,
                    (current, max(1, min(int(limit), 500))),
                )
                tasks = list(cursor.fetchall())
                for row in tasks:
                    due_at = _iso(_value(row, "next_run_at", 5))
                    run_key = f"atr_{uuid4().hex}"
                    cursor.execute(
                        """
                        INSERT INTO platform_automation_task_runs(
                            tenant_id, automation_run_key, automation_task_id, idempotency_key,
                            trigger_type, trigger_payload, status, created_by
                        ) VALUES (%s,%s,%s,%s,'schedule',%s::jsonb,'queued',%s)
                        ON CONFLICT (tenant_id, automation_task_id, idempotency_key) DO NOTHING
                        RETURNING automation_run_key
                        """,
                        (
                            _value(row, "tenant_id", 0), run_key, _value(row, "automation_task_id", 2),
                            f"schedule:{due_at}", _json({"scheduled_for": due_at}), _value(row, "owner_user_id", 6),
                        ),
                    )
                    inserted = cursor.fetchone()
                    if inserted:
                        queued_keys.append((str(_value(row, "tenant_code", 1)), str(_value(inserted, "automation_run_key", 0))))
                    cursor.execute(
                        "UPDATE platform_automation_tasks SET next_run_at=%s, updated_at=now(), lock_version=lock_version+1 WHERE automation_task_id=%s",
                        (_next_run(str(_value(row, "schedule_expression", 4)), current, _schedule_timezone(_convert(_value(row, "task_config", 7)) or {})), _value(row, "automation_task_id", 2)),
                    )
        return [self.get_run(tenant, run) for tenant, run in queued_keys]

    def claim_run(self, worker_id: str, lease_seconds: int = 60) -> tuple[dict[str, Any], dict[str, Any]] | None:
        lease_until = datetime.now(timezone.utc) + timedelta(seconds=max(10, int(lease_seconds)))
        selected: tuple[str, str, str] | None = None
        with self._transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT r.automation_run_id, r.automation_run_key, r.tenant_id,
                           tenant.tenant_code, t.automation_task_key, t.max_concurrency,
                           r.status, r.attempt_no, r.automation_task_id
                    FROM platform_automation_task_runs r
                    JOIN platform_automation_tasks t ON t.automation_task_id=r.automation_task_id
                    JOIN platform_tenants tenant ON tenant.tenant_id=r.tenant_id
                    WHERE t.status='active' AND (
                        r.status='queued'
                        OR (r.status='retry_wait' AND r.next_retry_at <= now())
                        OR (r.status='running' AND r.lease_expires_at < now())
                    )
                    ORDER BY r.created_at
                    FOR UPDATE OF r SKIP LOCKED LIMIT 50
                    """
                )
                for row in cursor.fetchall():
                    cursor.execute(
                        """
                        SELECT COUNT(*) AS running_count FROM platform_automation_task_runs
                        WHERE tenant_id=%s AND automation_task_id=%s AND status='running'
                          AND automation_run_id <> %s
                          AND (lease_expires_at IS NULL OR lease_expires_at >= now())
                        """,
                        (_value(row, "tenant_id", 2), _value(row, "automation_task_id", 8), _value(row, "automation_run_id", 0)),
                    )
                    if int(_value(cursor.fetchone(), "running_count", 0)) >= int(_value(row, "max_concurrency", 5)):
                        continue
                    prior_status = str(_value(row, "status", 6))
                    attempt = int(_value(row, "attempt_no", 7) or 1) + (1 if prior_status in {"retry_wait", "running"} else 0)
                    cursor.execute(
                        """
                        UPDATE platform_automation_task_runs SET
                            status='running', attempt_no=%s, lease_owner=%s, lease_expires_at=%s,
                            started_at=COALESCE(started_at,now()), next_retry_at=NULL,
                            updated_at=now(), lock_version=lock_version+1
                        WHERE automation_run_id=%s
                        """,
                        (attempt, worker_id[:200], lease_until, _value(row, "automation_run_id", 0)),
                    )
                    selected = (
                        str(_value(row, "tenant_code", 3)),
                        str(_value(row, "automation_run_key", 1)),
                        str(_value(row, "automation_task_key", 4)),
                    )
                    break
        if selected is None:
            return None
        return self.get_run(selected[0], selected[1]), self.get_task(selected[0], selected[2])

    def get_run(self, tenant_id: str, run_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._run_select() + " WHERE r.tenant_id=%s AND r.automation_run_key=%s", (tenant_key, run_id))
                row = cursor.fetchone()
        if not row:
            raise KeyError("automation_run_not_found")
        return self._run_row(row)

    def list_runs(self, tenant_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._run_select() + " WHERE r.tenant_id=%s ORDER BY r.created_at DESC LIMIT %s", (tenant_key, max(1, min(int(limit), 500))))
                rows = cursor.fetchall()
        return [self._run_row(row) for row in rows]

    def cancel_run(self, tenant_id: str, run_id: str, actor_user_id: str) -> dict[str, Any]:
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, actor_user_id)
            run_key = self._run_uuid(connection, tenant_key, run_id)
            with connection.cursor() as cursor:
                cursor.execute("SELECT created_by,status FROM platform_automation_task_runs WHERE automation_run_id=%s FOR UPDATE", (run_key,))
                row = cursor.fetchone()
                if _value(row, "created_by", 0) != actor_key:
                    raise PermissionError("Only the run owner may cancel this execution.")
                if str(_value(row, "status", 1)) not in {"succeeded", "failed", "cancelled"}:
                    cursor.execute(
                        """
                        UPDATE platform_automation_task_runs SET status='cancelled', error_code='cancelled_by_user',
                            error_summary='Execution cancelled by its owner.', finished_at=now(), next_retry_at=NULL,
                            lease_owner=NULL, lease_expires_at=NULL, updated_at=now(), lock_version=lock_version+1
                        WHERE automation_run_id=%s AND status IN ('queued','running','retry_wait')
                        """,
                        (run_key,),
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
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            run_key = self._run_uuid(connection, tenant_key, run_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_automation_task_runs SET status=%s, result_refs=%s::jsonb,
                        error_code=%s, error_summary=%s, next_retry_at=%s,
                        finished_at=CASE WHEN %s='retry_wait' THEN NULL ELSE now() END,
                        lease_owner=NULL, lease_expires_at=NULL, updated_at=now(), lock_version=lock_version+1
                    WHERE automation_run_id=%s AND status NOT IN ('succeeded','failed','cancelled')
                    """,
                    (status, _json(result_refs or []), error_code, str(error_summary or "")[:2000] or None, next_retry_at, status, run_key),
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
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            run_key = self._run_uuid(connection, tenant_key, run_id)
            with connection.cursor() as cursor:
                cursor.execute("SELECT created_by FROM platform_automation_task_runs WHERE automation_run_id=%s", (run_key,))
                actor_key = _value(cursor.fetchone(), "created_by", 0)
                cursor.execute(
                    """
                    INSERT INTO platform_job_steps(
                        tenant_id,job_step_key,automation_run_id,step_code,sequence_no,status,
                        input_refs,output_refs,started_at,finished_at,error_code,created_by
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,now(),
                        CASE WHEN %s IN ('succeeded','failed','skipped','compensated') THEN now() END,%s,%s)
                    ON CONFLICT (automation_run_id,step_code) DO UPDATE SET
                        status=EXCLUDED.status, output_refs=EXCLUDED.output_refs,
                        finished_at=EXCLUDED.finished_at, error_code=EXCLUDED.error_code,
                        updated_at=now(), lock_version=platform_job_steps.lock_version+1
                    """,
                    (
                        tenant_key, f"js_{uuid4().hex}", run_key, step_code[:120], int(sequence_no), status,
                        _json(input_refs or []), _json(output_refs or []), status, error_code, actor_key,
                    ),
                )

    def list_steps(self, tenant_id: str, run_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            run_key = self._run_uuid(connection, tenant_key, run_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT step_code, sequence_no, status, output_refs, error_code,
                           started_at, finished_at, updated_at
                    FROM platform_job_steps
                    WHERE tenant_id=%s AND automation_run_id=%s
                    ORDER BY sequence_no, started_at
                    """,
                    (tenant_key, run_key),
                )
                rows = cursor.fetchall()
        return [
            _mapped(
                row,
                ("step_code", "sequence_no", "status", "output_refs", "error_code", "started_at", "finished_at", "updated_at"),
            )
            for row in rows
        ]

    def create_subscription(self, tenant_id: str, payload: dict[str, Any], owner_user_id: str) -> dict[str, Any]:
        fields = _subscription_fields(payload)
        key = f"sub_{uuid4().hex}"
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            owner_key = PostgreSQLIdentityResolver.user_id(connection, owner_user_id)
            cipher = encrypt_secret(_json(fields["channel_config"])).encode("utf-8")
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_subscriptions(
                        tenant_id,subscription_key,subscriber_user_id,subscription_name,event_types,
                        channel_type,channel_config_cipher,filter_expression,quiet_hours,
                        filter_config,channels,schedule_config,status,created_by
                    ) VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,'active',%s)
                    """,
                    (
                        tenant_key,key,owner_key,fields["subscription_name"],_json(fields["event_types"]),
                        fields["channel_type"],cipher,_json(fields["filter_expression"]),_json(fields["quiet_hours"]),
                        _json(fields["filter_expression"]),_json([fields["channel_type"]]),_json(fields["quiet_hours"]),owner_key,
                    ),
                )
        return self.get_subscription(tenant_id, key)

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
        merged = {
            "subscription_name": payload.get("subscription_name", payload.get("subscriptionName", current["subscription_name"])),
            "event_types": payload.get("event_types", payload.get("eventTypes", current["event_types"])),
            "channel_type": payload.get("channel_type", payload.get("channelType", current["channel_type"])),
            "channel_config": payload.get("channel_config", payload.get("channelConfig", current["channel_config"])),
            "filter_expression": payload.get("filter_expression", payload.get("filterExpression", current["filter_expression"])),
            "quiet_hours": payload.get("quiet_hours", payload.get("quietHours", current["quiet_hours"])),
        }
        fields = _subscription_fields(merged)
        status = str(payload.get("status") or current["status"])
        if status not in {"active", "paused", "disabled"}:
            raise ValueError("invalid_subscription_status")
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            owner_key = PostgreSQLIdentityResolver.user_id(connection, owner_user_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_subscriptions SET subscription_name=%s,event_types=%s::jsonb,
                        channel_type=%s,channel_config_cipher=%s,filter_expression=%s::jsonb,
                        quiet_hours=%s::jsonb,filter_config=%s::jsonb,channels=%s::jsonb,
                        schedule_config=%s::jsonb,status=%s,
                        disabled_at=CASE WHEN %s='disabled' THEN now() ELSE NULL END,
                        updated_at=now(),lock_version=lock_version+1
                    WHERE tenant_id=%s AND subscription_key=%s AND subscriber_user_id=%s AND lock_version=%s
                    """,
                    (
                        fields["subscription_name"],_json(fields["event_types"]),fields["channel_type"],
                        encrypt_secret(_json(fields["channel_config"])).encode("utf-8"),_json(fields["filter_expression"]),
                        _json(fields["quiet_hours"]),_json(fields["filter_expression"]),_json([fields["channel_type"]]),
                        _json(fields["quiet_hours"]),status,status,tenant_key,subscription_id,owner_key,int(expected_lock_version),
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError("subscription_revision_conflict")
        return self.get_subscription(tenant_id, subscription_id)

    def disable_subscription(self, tenant_id: str, subscription_id: str, owner_user_id: str, expected_lock_version: int) -> dict[str, Any]:
        return self.update_subscription(tenant_id, subscription_id, {"status": "disabled"}, owner_user_id, expected_lock_version)

    def get_subscription(self, tenant_id: str, subscription_id: str, reveal_config: bool = False) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(self._subscription_select() + " WHERE s.tenant_id=%s AND s.subscription_key=%s", (tenant_key, subscription_id))
                row = cursor.fetchone()
        if not row:
            raise KeyError("subscription_not_found")
        return self._subscription_row(row, reveal_config)

    def list_subscriptions(self, tenant_id: str, owner_user_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            owner_key = PostgreSQLIdentityResolver.user_id(connection, owner_user_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    self._subscription_select()
                    + " WHERE s.tenant_id=%s AND s.subscriber_user_id=%s AND s.status<>'disabled' AND s.event_types <> %s::jsonb ORDER BY s.updated_at DESC",
                    (tenant_key, owner_key, _json([TEAMS_CONNECTION_EVENT_TYPE])),
                )
                rows = cursor.fetchall()
        return [self._subscription_row(row, False) for row in rows]

    def get_teams_connection(
        self,
        tenant_id: str,
        owner_user_id: str,
        *,
        reveal_config: bool = False,
    ) -> dict[str, Any] | None:
        with self.pool.connection() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            owner_key = PostgreSQLIdentityResolver.user_id(connection, owner_user_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    self._subscription_select()
                    + " WHERE s.tenant_id=%s AND s.subscriber_user_id=%s AND s.status<>'disabled' AND s.event_types = %s::jsonb ORDER BY s.updated_at DESC LIMIT 1",
                    (tenant_key, owner_key, _json([TEAMS_CONNECTION_EVENT_TYPE])),
                )
                row = cursor.fetchone()
        return self._subscription_row(row, reveal_config) if row else None

    def upsert_teams_connection(self, tenant_id: str, owner_user_id: str, access_token: str) -> dict[str, Any]:
        token = _required(access_token, "teams_access_token", 8_192)
        current = self.get_teams_connection(tenant_id, owner_user_id, reveal_config=True)
        payload = {
            "subscription_name": "360Teams 连接",
            "event_types": [TEAMS_CONNECTION_EVENT_TYPE],
            "channel_type": "webhook",
            "channel_config": {"provider": "360teams_self", "access_token": token},
        }
        if current is None:
            return self.create_subscription(tenant_id, payload, owner_user_id)
        return self.update_subscription(
            tenant_id,
            str(current["subscription_id"]),
            payload,
            owner_user_id,
            int(current["lock_version"]),
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
        key = event_key or f"oe_{uuid4().hex}"
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            actor_key = PostgreSQLIdentityResolver.user_id(connection, created_by, required=False) if created_by else None
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO platform_outbox_events(
                        tenant_id,outbox_event_key,aggregate_type,aggregate_id,event_type,payload,status,created_by
                    ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,'pending',%s)
                    ON CONFLICT (tenant_id,outbox_event_key) DO NOTHING
                    """,
                    (tenant_key,key,aggregate_type[:120],aggregate_id[:200],event_type[:160],_json(_object(payload)),actor_key),
                )
        return key

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
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute("SELECT payload_hash,callback_key FROM platform_provider_callbacks WHERE provider=%s AND provider_event_id=%s FOR UPDATE", (provider, provider_event_id))
                existing = cursor.fetchone()
                if existing:
                    if str(_value(existing, "payload_hash", 0)) != payload_hash:
                        raise ValueError("provider_callback_idempotency_conflict")
                    callback_key = str(_value(existing, "callback_key", 1))
                else:
                    cursor.execute(
                        "SELECT delivery_id FROM platform_notification_deliveries WHERE tenant_id=%s AND provider_message_id=%s ORDER BY created_at DESC LIMIT 1",
                        (tenant_key, provider_message_id),
                    )
                    delivery = cursor.fetchone()
                    callback_key = f"pcb_{uuid4().hex}"
                    cursor.execute(
                        """
                        INSERT INTO platform_provider_callbacks(
                            tenant_id,callback_key,provider,provider_event_id,provider_message_id,event_type,
                            signature_valid,payload_hash,safe_payload,processed_at,processing_status
                        ) VALUES (%s,%s,%s,%s,%s,%s,true,%s,%s::jsonb,now(),%s)
                        """,
                        (tenant_key,callback_key,provider,provider_event_id,provider_message_id,event_type,payload_hash,_json(_object(safe_payload)),"processed" if delivery else "ignored"),
                    )
                    mapped = {"accepted":"sending","delivered":"delivered","read":"delivered","opened":"delivered","bounced":"dead_letter","rejected":"dead_letter","failed":"failed"}.get(event_type)
                    if delivery and mapped:
                        cursor.execute(
                            """
                            UPDATE platform_notification_deliveries SET status=%s,
                                delivered_at=CASE WHEN %s='delivered' THEN COALESCE(delivered_at,now()) ELSE delivered_at END,
                                error_code=CASE WHEN %s IN ('failed','dead_letter') THEN %s END,
                                next_attempt_at=NULL,updated_at=now(),lock_version=lock_version+1
                            WHERE delivery_id=%s
                            """,
                            (mapped,mapped,mapped,f"provider_{event_type}",_value(delivery,"delivery_id",0)),
                        )
        return self._provider_callback(tenant_id, callback_key)

    def expand_outbox_once(self) -> int:
        created = 0
        with self._transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM platform_outbox_events
                    WHERE status='pending' AND available_at<=now()
                    ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
                    """
                )
                event = cursor.fetchone()
                if not event:
                    return 0
                event_id = _value(event,"outbox_event_id",0)
                tenant_key = _value(event,"tenant_id",1)
                event_type = str(_value(event,"event_type",5))
                cursor.execute("UPDATE platform_outbox_events SET status='publishing',attempt_count=attempt_count+1,updated_at=now() WHERE outbox_event_id=%s", (event_id,))
                cursor.execute("SELECT subscription_id,subscription_key,subscriber_user_id,channel_type,event_types,created_by FROM platform_subscriptions WHERE tenant_id=%s AND status='active'", (tenant_key,))
                for sub in cursor.fetchall():
                    if event_type not in _json_value(_value(sub,"event_types",4), []):
                        continue
                    delivery_key = f"nd_{uuid4().hex}"
                    idempotency_key = f"{_value(sub,'subscription_key',1)}:{_value(event,'outbox_event_key',2)}"
                    cursor.execute(
                        """
                        INSERT INTO platform_notification_deliveries(
                            tenant_id,delivery_key,subscription_id,outbox_event_id,recipient_user_id,
                            channel,template_code,payload_ref,idempotency_key,status,next_attempt_at,created_by
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,'queued',now(),%s)
                        ON CONFLICT (tenant_id,channel,idempotency_key) DO NOTHING
                        """,
                        (tenant_key,delivery_key,_value(sub,"subscription_id",0),event_id,_value(sub,"subscriber_user_id",2),_value(sub,"channel_type",3),event_type,_json({"outbox_event_id":str(_value(event,"outbox_event_key",2))}),idempotency_key,_value(sub,"created_by",5)),
                    )
                    created += int(cursor.rowcount or 0)
                cursor.execute("UPDATE platform_outbox_events SET status='published',published_at=now(),updated_at=now(),lock_version=lock_version+1 WHERE outbox_event_id=%s", (event_id,))
        return created

    def claim_delivery(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
        selected: tuple[str, str, str] | None = None
        with self._transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT d.delivery_id,d.delivery_key,d.tenant_id,tenant.tenant_code,s.subscription_key,e.outbox_event_key
                    FROM platform_notification_deliveries d
                    JOIN platform_tenants tenant ON tenant.tenant_id=d.tenant_id
                    JOIN platform_subscriptions s ON s.subscription_id=d.subscription_id
                    JOIN platform_outbox_events e ON e.outbox_event_id=d.outbox_event_id
                    WHERE d.status IN ('queued','failed') AND (d.next_attempt_at IS NULL OR d.next_attempt_at<=now())
                      AND d.attempt_count<5
                    ORDER BY d.created_at FOR UPDATE OF d SKIP LOCKED LIMIT 1
                    """
                )
                row = cursor.fetchone()
                if not row:
                    return None
                cursor.execute("UPDATE platform_notification_deliveries SET status='sending',attempt_count=attempt_count+1,updated_at=now(),lock_version=lock_version+1 WHERE delivery_id=%s", (_value(row,"delivery_id",0),))
                selected = (str(_value(row,"tenant_code",3)),str(_value(row,"delivery_key",1)),str(_value(row,"subscription_key",4)))
        tenant, delivery_key, subscription_key = selected
        return self._delivery(tenant, delivery_key), self.get_subscription(tenant, subscription_key, reveal_config=True), self._outbox_event(tenant, self._delivery(tenant, delivery_key)["outbox_event_id"])

    def finish_delivery(self, tenant_id: str, delivery_id: str, *, status: str, provider_message_id: str | None = None, error_code: str | None = None, next_attempt_at: str | None = None) -> None:
        if status not in {"queued","sending","accepted","delivered","failed","bounced","cancelled","suppressed","dead_letter"}:
            raise ValueError("invalid_notification_delivery_status")
        with self._transaction() as connection:
            tenant_key = PostgreSQLIdentityResolver.tenant_id(connection, tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE platform_notification_deliveries SET status=%s,provider_message_id=%s,error_code=%s,
                        next_attempt_at=%s,delivered_at=CASE WHEN %s='delivered' THEN now() ELSE delivered_at END,
                        updated_at=now(),lock_version=lock_version+1
                    WHERE tenant_id=%s AND delivery_key=%s
                    """,
                    (status,provider_message_id,error_code,next_attempt_at,status,tenant_key,delivery_id),
                )

    def list_in_app_deliveries(self, tenant_id: str, owner_user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            owner_key=PostgreSQLIdentityResolver.user_id(connection,owner_user_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT d.delivery_key AS delivery_id,s.subscription_key AS subscription_id,
                           e.outbox_event_key AS outbox_event_id,d.channel AS channel_type,d.status,
                           d.attempt_count AS attempt_no,d.provider_message_id,d.error_code,d.delivered_at,
                           d.created_at,d.updated_at,e.event_type,e.payload
                    FROM platform_notification_deliveries d
                    JOIN platform_subscriptions s ON s.subscription_id=d.subscription_id
                    JOIN platform_outbox_events e ON e.outbox_event_id=d.outbox_event_id
                    WHERE d.tenant_id=%s AND s.subscriber_user_id=%s
                    ORDER BY d.created_at DESC LIMIT %s
                    """,
                    (tenant_key,owner_key,max(1,min(int(limit),500))),
                )
                rows=cursor.fetchall()
        return [_row(row) for row in rows]

    def list_deliveries_for_outbox(self, tenant_id: str, outbox_event_id: str) -> list[dict[str, Any]]:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT d.delivery_key AS delivery_id,s.subscription_key AS subscription_id,
                           e.outbox_event_key AS outbox_event_id,d.channel AS channel_type,d.status,
                           d.attempt_count AS attempt_no,d.provider_message_id,d.error_code,d.delivered_at,d.created_at,d.updated_at
                    FROM platform_notification_deliveries d
                    LEFT JOIN platform_subscriptions s ON s.subscription_id=d.subscription_id
                    JOIN platform_outbox_events e ON e.outbox_event_id=d.outbox_event_id
                    WHERE d.tenant_id=%s AND e.outbox_event_key=%s ORDER BY d.created_at
                    """,
                    (tenant_key,outbox_event_id),
                )
                rows=cursor.fetchall()
        return [_row(row) for row in rows]

    def record_email_message(self, tenant_id: str, delivery_id: str, *, subject: str, body_artifact_id: str, from_address: str, to_address: str, provider_message_id: str) -> None:
        with self._transaction() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            with connection.cursor() as cursor:
                cursor.execute("SELECT delivery_id,created_by FROM platform_notification_deliveries WHERE tenant_id=%s AND delivery_key=%s",(tenant_key,delivery_id))
                delivery=cursor.fetchone()
                if not delivery: raise KeyError("notification_delivery_not_found")
                cursor.execute("SELECT artifact_id FROM platform_data_artifacts WHERE tenant_id=%s AND artifact_key=%s",(tenant_key,body_artifact_id))
                artifact=cursor.fetchone()
                if not artifact: raise KeyError("data_artifact_not_found")
                cursor.execute(
                    """
                    INSERT INTO platform_email_messages(
                        tenant_id,email_message_key,delivery_id,subject,body_artifact_id,from_address,
                        to_addresses,cc_addresses,attachment_ids,provider_response,created_by
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,'[]'::jsonb,'[]'::jsonb,%s::jsonb,%s)
                    ON CONFLICT (delivery_id) DO NOTHING
                    """,
                    (tenant_key,f"em_{uuid4().hex}",_value(delivery,"delivery_id",0),subject[:998],_value(artifact,"artifact_id",0),from_address[:320],_json([to_address]),_json({"provider_message_id":provider_message_id}),_value(delivery,"created_by",1)),
                )

    @staticmethod
    def _task_select() -> str:
        return """SELECT t.automation_task_key AS automation_task_id,tenant.tenant_code AS tenant_id,t.task_code,t.task_name,t.task_type,t.trigger_type,
            t.schedule_expression,t.event_type,t.handler_ref,t.task_config,t.retry_policy,t.timeout_seconds,
            t.max_concurrency,t.status,t.next_run_at,owner.external_subject AS owner_user_id,
            creator.external_subject AS created_by,t.created_at,t.updated_at,t.lock_version,t.automation_task_id AS automation_task_uuid,t.owner_user_id AS owner_user_key
            FROM platform_automation_tasks t JOIN platform_tenants tenant ON tenant.tenant_id=t.tenant_id
            JOIN platform_user_profiles owner ON owner.user_id=t.owner_user_id
            LEFT JOIN platform_user_profiles creator ON creator.user_id=t.created_by"""

    @staticmethod
    def _task_row(row: Any) -> dict[str, Any]:
        keys=("automation_task_id","tenant_id","task_code","task_name","task_type","trigger_type","schedule_expression","event_type","handler_ref","task_config","retry_policy","timeout_seconds","max_concurrency","status","next_run_at","owner_user_id","created_by","created_at","updated_at","lock_version")
        result = _mapped(row,keys)
        result["task_config"] = _json_value(result.get("task_config"), {})
        result["retry_policy"] = _json_value(result.get("retry_policy"), {})
        return result

    @staticmethod
    def _run_select() -> str:
        return """SELECT r.automation_run_key AS automation_run_id,tenant.tenant_code AS tenant_id,t.automation_task_key AS automation_task_id,r.idempotency_key,r.trigger_type,
            r.trigger_payload,r.status,r.attempt_no,r.lease_owner,r.lease_expires_at,r.started_at,r.finished_at,
            r.next_retry_at,r.result_refs,r.error_code,r.error_summary,creator.external_subject AS created_by,
            r.created_at,r.updated_at,r.lock_version FROM platform_automation_task_runs r
            JOIN platform_tenants tenant ON tenant.tenant_id=r.tenant_id
            JOIN platform_automation_tasks t ON t.automation_task_id=r.automation_task_id
            LEFT JOIN platform_user_profiles creator ON creator.user_id=r.created_by"""

    @staticmethod
    def _run_row(row: Any) -> dict[str, Any]:
        keys=("automation_run_id","tenant_id","automation_task_id","idempotency_key","trigger_type","trigger_payload","status","attempt_no","lease_owner","lease_expires_at","started_at","finished_at","next_retry_at","result_refs","error_code","error_summary","created_by","created_at","updated_at","lock_version")
        result = _mapped(row,keys)
        result["trigger_payload"] = _json_value(result.get("trigger_payload"), {})
        result["result_refs"] = _json_value(result.get("result_refs"), [])
        return result

    @staticmethod
    def _subscription_select() -> str:
        return """SELECT s.subscription_key AS subscription_id,tenant.tenant_code AS tenant_id,owner.external_subject AS owner_user_id,
            s.subscription_name,s.event_types,s.channel_type,s.channel_config_cipher,s.filter_expression,
            s.quiet_hours,s.status,s.disabled_at,s.created_at,s.updated_at,s.lock_version
            FROM platform_subscriptions s JOIN platform_tenants tenant ON tenant.tenant_id=s.tenant_id
            JOIN platform_user_profiles owner ON owner.user_id=s.subscriber_user_id"""

    @staticmethod
    def _subscription_row(row: Any, reveal: bool) -> dict[str, Any]:
        result=_mapped(row,("subscription_id","tenant_id","owner_user_id","subscription_name","event_types","channel_type","channel_config_cipher","filter_expression","quiet_hours","status","disabled_at","created_at","updated_at","lock_version"))
        cipher=result.pop("channel_config_cipher")
        if reveal:
            raw=bytes(cipher).decode("utf-8") if isinstance(cipher,(bytes,bytearray,memoryview)) else str(cipher)
            result["channel_config"]=_json_value(decrypt_secret(raw),{})
        else:
            result["channel_config"]={"configured":True}
            raw=bytes(cipher).decode("utf-8") if isinstance(cipher,(bytes,bytearray,memoryview)) else str(cipher)
            provider=str(_json_value(decrypt_secret(raw),{}).get("provider") or "").strip()
            if provider:
                result["channel_provider"]=provider
        return result

    def _delivery(self, tenant_id: str, delivery_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT d.delivery_key AS delivery_id,tenant.tenant_code AS tenant_id,s.subscription_key AS subscription_id,
                        e.outbox_event_key AS outbox_event_id,d.channel AS channel_type,d.status,d.attempt_count AS attempt_no,
                        d.provider_message_id,d.error_code,d.next_attempt_at,d.delivered_at,d.created_at,d.updated_at
                        FROM platform_notification_deliveries d JOIN platform_tenants tenant ON tenant.tenant_id=d.tenant_id
                        LEFT JOIN platform_subscriptions s ON s.subscription_id=d.subscription_id
                        JOIN platform_outbox_events e ON e.outbox_event_id=d.outbox_event_id
                        WHERE d.tenant_id=%s AND d.delivery_key=%s""",
                    (tenant_key,delivery_id),
                )
                row=cursor.fetchone()
        if not row: raise KeyError("notification_delivery_not_found")
        return _row(row)

    def _outbox_event(self, tenant_id: str, outbox_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            with connection.cursor() as cursor:
                cursor.execute("""SELECT e.outbox_event_key AS outbox_event_id,tenant.tenant_code AS tenant_id,e.aggregate_type,e.aggregate_id,e.event_type,e.payload,e.status,e.available_at,e.published_at,e.attempt_count,e.created_at,e.updated_at FROM platform_outbox_events e JOIN platform_tenants tenant ON tenant.tenant_id=e.tenant_id WHERE e.tenant_id=%s AND e.outbox_event_key=%s""",(tenant_key,outbox_id))
                row=cursor.fetchone()
        if not row: raise KeyError("outbox_event_not_found")
        return _row(row)

    def _provider_callback(self, tenant_id: str, callback_id: str) -> dict[str, Any]:
        with self.pool.connection() as connection:
            tenant_key=PostgreSQLIdentityResolver.tenant_id(connection,tenant_id)
            with connection.cursor() as cursor:
                cursor.execute("SELECT callback_key AS callback_id,provider,provider_event_id,provider_message_id,event_type,signature_valid,payload_hash,safe_payload,processing_status,processed_at,created_at FROM platform_provider_callbacks WHERE tenant_id=%s AND callback_key=%s",(tenant_key,callback_id))
                row=cursor.fetchone()
        if not row: raise KeyError("provider_callback_not_found")
        return _row(row)

    @staticmethod
    def _task_uuid(connection: Any, tenant_key: Any, task_id: str, *, active: bool=False) -> Any:
        with connection.cursor() as cursor:
            cursor.execute("SELECT automation_task_id,status FROM platform_automation_tasks WHERE tenant_id=%s AND automation_task_key=%s",(tenant_key,task_id))
            row=cursor.fetchone()
        if not row: raise KeyError("automation_task_not_found")
        if active and str(_value(row,"status",1))!="active": raise ValueError("automation_task_is_not_active")
        return _value(row,"automation_task_id",0)

    @staticmethod
    def _run_uuid(connection: Any, tenant_key: Any, run_id: str) -> Any:
        with connection.cursor() as cursor:
            cursor.execute("SELECT automation_run_id FROM platform_automation_task_runs WHERE tenant_id=%s AND automation_run_key=%s",(tenant_key,run_id))
            row=cursor.fetchone()
        if not row: raise KeyError("automation_run_not_found")
        return _value(row,"automation_run_id",0)

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with self.pool.connection() as connection:
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise


def _task_fields(payload: dict[str, Any]) -> dict[str, Any]:
    trigger_type=str(payload.get("trigger_type",payload.get("triggerType")) or "manual").strip()
    if trigger_type not in {"manual","schedule","event"}: raise ValueError("invalid_automation_trigger_type")
    schedule=str(payload.get("schedule_expression",payload.get("scheduleExpression")) or "").strip() or None
    event_type=str(payload.get("event_type",payload.get("eventType")) or "").strip() or None
    if trigger_type=="schedule" and not schedule: raise ValueError("schedule_expression_required")
    if trigger_type=="event" and not event_type: raise ValueError("event_type_required")
    handler_ref=_required(payload.get("handler_ref",payload.get("handlerRef")),"handler_ref",300)
    return {"trigger_type":trigger_type,"schedule":schedule,"event_type":event_type,"handler_ref":handler_ref,
        "task_config":_object(payload.get("task_config",payload.get("taskConfig",{}))),
        "retry_policy":_object(payload.get("retry_policy",payload.get("retryPolicy",{}))),
        "timeout_seconds":max(1,min(int(payload.get("timeout_seconds",payload.get("timeoutSeconds",900))),86400)),
        "max_concurrency":max(1,min(int(payload.get("max_concurrency",payload.get("maxConcurrency",1))),100))}


def _mapped(row: Any, keys: tuple[str,...]) -> dict[str,Any]:
    if isinstance(row,dict):
        result={key:row.get(key) for key in keys}
    else:
        result={key:row[index] for index,key in enumerate(keys)}
    return {key:_convert(value) for key,value in result.items()}


def _row(row: Any) -> dict[str,Any]:
    return {str(key):_convert(value) for key,value in dict(row).items()} if isinstance(row,dict) else {}


def _convert(value: Any) -> Any:
    if isinstance(value,datetime): return value.isoformat()
    if isinstance(value,(dict,list,bool,int,float)) or value is None: return value
    return value


def _json_value(value: Any, default: Any) -> Any:
    if value is None: return default
    if isinstance(value,(dict,list)): return value
    try: return json.loads(value)
    except (TypeError,json.JSONDecodeError): return default


def _value(row: Any,key: str,index: int) -> Any:
    if isinstance(row,dict): return row[key]
    try: return row[key]
    except (TypeError,KeyError,IndexError): return row[index]


def _json(value: Any) -> str:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,default=str,separators=(",",":"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value,datetime) else str(value)
