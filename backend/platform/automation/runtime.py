from __future__ import annotations

import json
import os
import sqlite3
import smtplib
import ssl
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request
from uuid import uuid4
from zoneinfo import ZoneInfo

import certifi

from backend.platform.security import safe_urlopen, validate_outbound_url


AutomationHandler = Callable[[str, dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]]

HANDLER_POOLS = {
    "analysis.run": "query",
    "acquisition.run": "query",
    "topic-data.refresh": "query",
    "analysis.monitor": "query",
    "metric.subscription.snapshot": "delivery",
    "market.evaluate": "query",
    "memory.extract": "llm",
    "report.weekly_learning": "llm",
    "learning.observe_episode": "llm",
    "learning.draft": "llm",
    "capability.promote": "llm",
    "eval.score": "llm",
    "delivery.fulfill": "delivery",
    "delivery.sync": "delivery",
}


class AutomationRuntime:
    def __init__(self, store: Any, artifact_content_resolver: Callable[[str, str], tuple[dict[str, Any], bytes]] | None = None) -> None:
        self.store = store
        self.artifact_content_resolver = artifact_content_resolver
        self._handlers: dict[str, AutomationHandler] = {}
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="smart-data-worker")
        self._pools = {
            "query": ThreadPoolExecutor(max_workers=5, thread_name_prefix="sda-query"),
            "sandbox": ThreadPoolExecutor(max_workers=3, thread_name_prefix="sda-sandbox"),
            "llm": ThreadPoolExecutor(max_workers=4, thread_name_prefix="sda-llm"),
            "delivery": ThreadPoolExecutor(max_workers=4, thread_name_prefix="sda-delivery"),
        }

    def close(self) -> None:
        for pool in self._pools.values():
            pool.shutdown(wait=False, cancel_futures=True)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _pool_for(self, handler_ref: str) -> ThreadPoolExecutor:
        name = HANDLER_POOLS.get(str(handler_ref or ""), "")
        return self._pools.get(name, self._executor)

    def register_handler(self, handler_ref: str, handler: AutomationHandler) -> None:
        normalized = str(handler_ref or "").strip()
        if not normalized or normalized in self._handlers:
            raise ValueError("invalid_or_duplicate_automation_handler")
        self._handlers[normalized] = handler

    def list_handlers(self) -> list[str]:
        return sorted(self._handlers)

    def create_task(self, tenant_id: str, payload: dict[str, Any], actor_user_id: str) -> dict[str, Any]:
        handler_ref = str(payload.get("handler_ref", payload.get("handlerRef")) or "").strip()
        if handler_ref not in self._handlers:
            raise ValueError("unregistered_automation_handler")
        return self.store.create_task(tenant_id, payload, actor_user_id)

    def update_task(
        self,
        tenant_id: str,
        task_id: str,
        payload: dict[str, Any],
        actor_user_id: str,
        expected_lock_version: int,
    ) -> dict[str, Any]:
        handler_ref = str(payload.get("handler_ref", payload.get("handlerRef")) or "").strip()
        if handler_ref and handler_ref not in self._handlers:
            raise ValueError("unregistered_automation_handler")
        return self.store.update_task(
            tenant_id,
            task_id,
            payload,
            actor_user_id,
            expected_lock_version,
        )

    def trigger(
        self,
        tenant_id: str,
        task_id: str,
        actor_user_id: str,
        idempotency_key: str,
        trigger_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.store.enqueue_run(
            tenant_id,
            task_id,
            idempotency_key,
            "manual",
            trigger_payload or {},
            actor_user_id,
        )

    def run_once(self, worker_id: str = "local-worker") -> dict[str, Any] | None:
        claimed = self.store.claim_run(worker_id)
        if claimed is None:
            return None
        run, task = claimed
        run_id = str(run["automation_run_id"])
        tenant_id = str(run["tenant_id"])
        handler = self._handlers.get(str(task["handler_ref"]))
        if handler is None:
            return self.store.finish_run(
                tenant_id,
                run_id,
                status="failed",
                error_code="handler_not_registered",
                error_summary="The configured automation handler is not registered in this worker deployment.",
            )
        self.store.record_step(tenant_id, run_id, "execute_handler", 0, "running")
        context = {
            "automation_run_id": run_id,
            "automation_task_id": task["automation_task_id"],
            "actor_user_id": run["created_by"],
            "attempt_no": run["attempt_no"],
            "worker_id": worker_id,
            "is_cancelled": lambda: self.store.get_run(tenant_id, run_id)["status"] == "cancelled",
        }
        future = self._pool_for(str(task.get("handler_ref") or "")).submit(
            handler,
            tenant_id,
            dict(task["task_config"]),
            dict(run["trigger_payload"]),
            context,
        )
        try:
            result = future.result(timeout=int(task["timeout_seconds"]))
            if self.store.get_run(tenant_id, run_id)["status"] == "cancelled":
                self.store.record_step(tenant_id, run_id, "execute_handler", 0, "skipped", error_code="cancelled_by_user")
                return self.store.get_run(tenant_id, run_id)
            if not isinstance(result, dict):
                raise RuntimeError("automation_handler_result_must_be_object")
            refs = _result_refs(result)
            self.store.record_step(tenant_id, run_id, "execute_handler", 0, "succeeded", output_refs=refs)
            finished = self.store.finish_run(tenant_id, run_id, status="succeeded", result_refs=refs)
            self._emit_run_event(tenant_id, run_id, task, finished, "automation.run.succeeded")
            return finished
        except FutureTimeoutError:
            future.cancel()
            return self._handle_failure(
                run,
                task,
                "automation_timeout",
                "分析执行超过时限，系统将按重试策略自动恢复。",
                retryable=True,
            )
        except Exception as exc:
            if self.store.get_run(tenant_id, run_id)["status"] == "cancelled":
                self.store.record_step(tenant_id, run_id, "execute_handler", 0, "skipped", error_code="cancelled_by_user")
                return self.store.get_run(tenant_id, run_id)
            error_code, error_summary, retryable = _public_handler_failure(exc)
            return self._handle_failure(run, task, error_code, error_summary, retryable=retryable)

    def process_notifications_once(self) -> int:
        expanded = self.store.expand_outbox_once()
        claimed = self.store.claim_delivery()
        if claimed is None:
            return expanded
        delivery, subscription, event = claimed
        tenant_id = str(delivery["tenant_id"])
        delivery_id = str(delivery["delivery_id"])
        if not _matches_filter(event.get("payload", {}), subscription.get("filter_expression", {})):
            self.store.finish_delivery(tenant_id, delivery_id, status="suppressed", error_code="filter_not_matched")
            return expanded + 1
        if _in_quiet_hours(subscription.get("quiet_hours", {})):
            next_attempt = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            self.store.finish_delivery(
                tenant_id,
                delivery_id,
                status="failed",
                error_code="quiet_hours",
                next_attempt_at=next_attempt,
            )
            return expanded + 1
        try:
            provider_id = _deliver(subscription, event, self.artifact_content_resolver)
            self.store.finish_delivery(
                tenant_id,
                delivery_id,
                status="delivered",
                provider_message_id=provider_id,
            )
            if str(subscription.get("channel_type")) == "email" and event.get("payload", {}).get("body_artifact_id"):
                config = dict(subscription.get("channel_config") or {})
                self.store.record_email_message(
                    tenant_id,
                    delivery_id,
                    subject=_safe_email_header(event.get("payload", {}).get("subject") or event["event_type"]),
                    body_artifact_id=str(event["payload"]["body_artifact_id"]),
                    from_address=os.getenv("SMART_DATA_AGENT_SMTP_FROM", "").strip(),
                    to_address=str(config.get("recipient") or "").strip(),
                    provider_message_id=provider_id,
                )
        except Exception:
            attempt = int(delivery.get("attempt_no") or 1)
            if attempt >= 5:
                self.store.finish_delivery(
                    tenant_id,
                    delivery_id,
                    status="dead_letter",
                    error_code="notification_delivery_failed",
                )
            else:
                self.store.finish_delivery(
                    tenant_id,
                    delivery_id,
                    status="failed",
                    error_code="notification_delivery_failed",
                    next_attempt_at=(datetime.now(timezone.utc) + timedelta(seconds=min(3600, 30 * (2 ** (attempt - 1))))).isoformat(),
                )
        return expanded + 1

    def _handle_failure(
        self,
        run: dict[str, Any],
        task: dict[str, Any],
        error_code: str,
        error_summary: str,
        *,
        retryable: bool = True,
    ) -> dict[str, Any]:
        tenant_id = str(run["tenant_id"])
        run_id = str(run["automation_run_id"])
        if self.store.get_run(tenant_id, run_id)["status"] == "cancelled":
            return self.store.get_run(tenant_id, run_id)
        self.store.record_step(tenant_id, run_id, "execute_handler", 0, "failed", error_code=error_code)
        policy = dict(task.get("retry_policy") or {})
        max_attempts = max(1, min(int(policy.get("max_attempts", 3)), 20))
        attempt_no = int(run.get("attempt_no") or 1)
        if retryable and attempt_no < max_attempts:
            base_seconds = max(1, min(int(policy.get("base_delay_seconds", 30)), 86_400))
            delay_seconds = base_seconds if bool(policy.get("fixed_delay")) else min(86_400, base_seconds * (2 ** (attempt_no - 1)))
            next_retry = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat()
            failed = self.store.finish_run(
                tenant_id,
                run_id,
                status="retry_wait",
                error_code=error_code,
                error_summary=error_summary,
                next_retry_at=next_retry,
            )
            self._emit_run_event(tenant_id, run_id, task, failed, "automation.run.retry_scheduled")
            return failed
        failed = self.store.finish_run(
            tenant_id,
            run_id,
            status="failed",
            error_code=error_code,
            error_summary=error_summary,
        )
        self._emit_run_event(tenant_id, run_id, task, failed, "automation.run.failed")
        return failed

    def _emit_run_event(
        self,
        tenant_id: str,
        run_id: str,
        task: dict[str, Any],
        run: dict[str, Any],
        event_type: str,
    ) -> None:
        self.store.enqueue_outbox_event(
            tenant_id,
            "automation_run",
            run_id,
            event_type,
            {
                "automation_run_id": run_id,
                "automation_task_id": task["automation_task_id"],
                "task_name": task["task_name"],
                "status": run["status"],
                "error_code": run.get("error_code"),
            },
            event_key=f"automation:{run_id}:{event_type}:{run.get('attempt_no', 1)}",
            created_by=run.get("created_by"),
        )


def _public_handler_failure(exc: Exception) -> tuple[str, str, bool]:
    message = str(exc)
    if isinstance(exc, PermissionError):
        if "selected_data_asset_not_published_or_not_authorized" in message:
            return (
                "analysis_selected_data_asset_unavailable",
                "所选数据表已更新、下线或不属于当前机构，请重新选择数据表后重试。",
                False,
            )
        if "selected_submodel_not_enabled_for_application_module" in message or "selected_model_not_registered_for_application_module" in message:
            return (
                "analysis_selected_model_unavailable",
                "所选模型或子模型已更新，请从默认模型重新选择后重试。",
                False,
            )
        if "skill:supersonic.query:execute" in message:
            return (
                "analysis_query_permission_denied",
                "当前角色缺少智能分析查询权限，请由机构管理员授予“执行智能分析”权限后重试。",
                False,
            )
        return "automation_permission_denied", "当前角色没有执行此任务所需的权限。", False
    if isinstance(exc, (ValueError, KeyError, TypeError, AttributeError, AssertionError)):
        if "analysis_selected_raw_table_requires_single_source" in message:
            return (
                "analysis_single_data_table_required",
                "一次分析只能使用一张数据表，请重新选择数据表后重试。",
                False,
            )
        if "analysis_production_data_table_required" in message:
            return (
                "analysis_production_data_table_required",
                "请先在智能分析输入框左侧点击“+”，选择当前机构的数据表后再开始分析。",
                False,
            )
        detail = " ".join(message.split())[:180]
        return (
            "automation_request_invalid",
            f"任务输入或执行配置无效：{type(exc).__name__}({detail or '无补充信息'})",
            False,
        )
    if isinstance(exc, (TimeoutError, ConnectionError, OSError, sqlite3.OperationalError)):
        lowered = message.lower()
        if any(token in lowered for token in ("name or service not known", "nodename nor servname", "getaddrinfo", "temporary failure in name resolution", "dns")):
            return (
                "dns_resolution_failed",
                "模型或数据服务地址无法解析。请检查左下角所选模型的 API 地址、企业 DNS/VPN 后重试。",
                False,
            )
        return "automation_transient_failure", "分析依赖服务暂时不可用，系统将按重试策略自动恢复。", True
    if isinstance(exc, RuntimeError):
        return "automation_handler_failed", "分析执行遇到可恢复异常，系统将按重试策略自动恢复。", True
    return "automation_handler_failed", "任务执行失败，请使用运行 ID 查看脱敏执行记录。", False


class AutomationWorker:
    def __init__(
        self,
        runtime: AutomationRuntime,
        poll_seconds: float = 0.5,
        worker_id: str | None = None,
        health_path: str | Path | None = None,
    ) -> None:
        self.runtime = runtime
        self.poll_seconds = max(0.1, min(float(poll_seconds), 10.0))
        self.worker_id = worker_id or f"worker-{uuid4().hex[:12]}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_heartbeat_at = datetime.now(timezone.utc).isoformat()
        self._last_error_at: str | None = None
        self._last_error_code: str | None = None
        configured_health_path = str(health_path or os.getenv("SMART_DATA_AGENT_WORKER_HEALTH_FILE", "")).strip()
        self._health_path = Path(configured_health_path) if configured_health_path else None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.run_forever, name=self.worker_id, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def run_forever(self) -> None:
        self._write_health_file()
        while not self._stop.is_set():
            did_work = False
            try:
                self._last_heartbeat_at = datetime.now(timezone.utc).isoformat()
                did_work = bool(self.runtime.store.enqueue_due_tasks(limit=50)) or did_work
                did_work = self.runtime.run_once(self.worker_id) is not None or did_work
                did_work = self.runtime.process_notifications_once() > 0 or did_work
                self._last_error_code = None
            except Exception as exc:
                did_work = False
                self._last_error_at = datetime.now(timezone.utc).isoformat()
                self._last_error_code = type(exc).__name__
            self._write_health_file()
            self._stop.wait(0.05 if did_work else self.poll_seconds)
        self._write_health_file(stopped=True)

    def health(self) -> dict[str, Any]:
        alive = bool(self._thread and self._thread.is_alive() and not self._stop.is_set())
        return {
            "ready": alive,
            "worker_id": self.worker_id,
            "alive": alive,
            "last_heartbeat_at": self._last_heartbeat_at,
            "last_error_at": self._last_error_at,
            "last_error_code": self._last_error_code,
        }

    def _write_health_file(self, *, stopped: bool = False) -> None:
        if self._health_path is None:
            return
        payload = {
            "schema_version": "smart-data-agent-worker-health/v1",
            "ready": not stopped,
            "worker_id": self.worker_id,
            "heartbeat_at": datetime.now(timezone.utc).isoformat(),
            "last_error_at": self._last_error_at,
            "last_error_code": self._last_error_code,
        }
        try:
            self._health_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._health_path.with_name(f".{self._health_path.name}.{os.getpid()}.tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            os.replace(temporary, self._health_path)
        except OSError:
            # Missing/stale heartbeat is interpreted as unavailable by the API
            # and container healthcheck. The worker keeps retrying safely.
            return


def _result_refs(result: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for key in (
        "task_id",
        "execution_id",
        "acquisition_run_id",
        "artifact_id",
        "partition_id",
        "report_id",
        "version_id",
    ):
        if result.get(key):
            refs.append({"type": key.removesuffix("_id"), "id": str(result[key])})
    if not refs:
        digest = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
        refs.append({"type": "result", "hash": __import__("hashlib").sha256(digest.encode()).hexdigest()})
    return refs


def _deliver(
    subscription: dict[str, Any],
    event: dict[str, Any],
    artifact_content_resolver: Callable[[str, str], tuple[dict[str, Any], bytes]] | None = None,
) -> str:
    channel = str(subscription["channel_type"])
    config = dict(subscription.get("channel_config") or {})
    if channel == "in_app":
        return f"inapp:{event['outbox_event_id']}"
    if channel == "webhook":
        if str(config.get("provider") or "").strip() == "360teams_self":
            from backend.platform.integrations.teams import send_markdown_to_self
            from backend.platform.automation.metric_subscription import render_teams_metric_markdown

            title, text = render_teams_metric_markdown(dict(event.get("payload") or {}))
            return send_markdown_to_self(str(config.get("access_token") or ""), title, text)
        url = validate_outbound_url(str(config.get("url") or ""))
        body = json.dumps(
            {
                "event_id": event["outbox_event_id"],
                "event_type": event["event_type"],
                "payload": event["payload"],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "SmartDataAgent/1.0 webhook"}
        if config.get("bearer_token"):
            headers["Authorization"] = f"Bearer {config['bearer_token']}"
        request = Request(url, data=body, headers=headers, method="POST")
        with safe_urlopen(
            request,
            timeout=10,
            context=ssl.create_default_context(cafile=certifi.where()),
        ) as response:
            if int(response.status) < 200 or int(response.status) >= 300:
                raise RuntimeError("webhook_provider_rejected")
            return str(response.headers.get("X-Request-Id") or f"webhook:{event['outbox_event_id']}")
    if channel == "email":
        host = os.getenv("SMART_DATA_AGENT_SMTP_HOST", "").strip()
        username = os.getenv("SMART_DATA_AGENT_SMTP_USERNAME", "").strip()
        password = os.getenv("SMART_DATA_AGENT_SMTP_PASSWORD", "")
        sender = os.getenv("SMART_DATA_AGENT_SMTP_FROM", "").strip()
        recipient = str(config.get("recipient") or "").strip()
        if not host or not sender or "@" not in recipient:
            raise RuntimeError("smtp_not_configured")
        validate_outbound_url(f"https://{host}")
        message = EmailMessage()
        message["From"] = sender
        message["To"] = recipient
        event_subject = event.get("payload", {}).get("subject") or event["event_type"]
        message["Subject"] = _safe_email_header(str(config.get("subject_prefix") or "[Smart Data Agent]") + " " + str(event_subject))
        body_artifact_id = str(event.get("payload", {}).get("body_artifact_id") or "").strip()
        if body_artifact_id:
            if artifact_content_resolver is None:
                raise RuntimeError("email_artifact_resolver_not_configured")
            metadata, content = artifact_content_resolver(str(event["tenant_id"]), body_artifact_id)
            if str(metadata.get("content_type") or "").split(";", 1)[0].strip().lower() != "text/html":
                raise RuntimeError("email_body_artifact_must_be_html")
            message.set_content("This report requires an HTML-capable email client.")
            message.add_alternative(content.decode("utf-8"), subtype="html")
        else:
            message.set_content(json.dumps(event["payload"], ensure_ascii=False, indent=2))
        message["Message-ID"] = make_msgid(domain=sender.split("@", 1)[-1])
        port = int(os.getenv("SMART_DATA_AGENT_SMTP_PORT", "465"))
        context = ssl.create_default_context(cafile=certifi.where())
        with smtplib.SMTP_SSL(host, port, timeout=15, context=context) as smtp:
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
        return str(message.get("Message-ID") or f"email:{event['outbox_event_id']}")
    raise RuntimeError("unsupported_notification_channel")


def _safe_email_header(value: Any) -> str:
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())[:998]


def _matches_filter(payload: dict[str, Any], expression: dict[str, Any]) -> bool:
    if not expression:
        return True
    return all(payload.get(key) == value for key, value in expression.items())


def _in_quiet_hours(config: dict[str, Any]) -> bool:
    if not config:
        return False
    try:
        timezone_name = str(config.get("timezone") or "Asia/Shanghai")
        hour = datetime.now(ZoneInfo(timezone_name)).hour
        start = int(config["start_hour"])
        end = int(config["end_hour"])
    except (KeyError, ValueError, TypeError):
        return False
    return start <= hour < end if start < end else hour >= start or hour < end
