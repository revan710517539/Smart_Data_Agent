from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

from backend.platform.api.router import API_ROUTE_REGISTRY
from backend.platform.api.routes import DELETE_ROUTE_HANDLERS, GET_ROUTE_HANDLERS, POST_ROUTE_HANDLERS, PUT_ROUTE_HANDLERS
from backend.platform.api.support import APIRequestContext, MAX_JSON_BODY_BYTES, RequestBodyTooLarge, format_prometheus_metrics
from backend.platform.automation import AutomationWorker
from backend.platform.bootstrap import (
    LEGACY_TENANT_ID,
    LOCAL_ANALYSIS_USER_ID,
    PlatformServices,
    build_local_platform,
    build_production_platform,
)
from backend.platform.runtime_config import cors_origin_for_request
from backend.platform.security import request_limits, resolve_request_context


class AnalysisAPIServer(ThreadingHTTPServer):
    services: PlatformServices
    automation_worker: AutomationWorker | None = None

    def server_close(self) -> None:
        try:
            try:
                if self.automation_worker is not None:
                    self.automation_worker.close()
                self.services.close()
            finally:
                super().server_close()
        except BaseException:
            pass


class AnalysisAPIHandler(BaseHTTPRequestHandler):
    services: PlatformServices

    def do_OPTIONS(self) -> None:
        self._send_empty(HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:
        parsed_path = urlparse(self.path)
        if not self._enforce_ip_rate_limit(parsed_path.path):
            return
        if parsed_path.path == "/api/live":
            self._send_json({"status": "ok", "service": "smart-data-agent-api"})
            return
        if parsed_path.path == "/api/ready":
            health = _runtime_health(self)
            self._send_json(health, HTTPStatus.OK if health["ready"] else HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if parsed_path.path == "/api/health":
            health = _runtime_health(self)
            self._send_json(
                {
                    **health,
                    "service": "smart-data-agent-api",
                    "semantic_client_mode": self.services.semantic_client_mode,
                    "semantic_routing_mode": self.services.semantic_routing_mode,
                    "semantic_fallback_mode": self.services.semantic_fallback_mode,
                    "data_source_mode": self.services.data_source_mode,
                    "environment": self.services.runtime_config.environment,
                    "auth_mode": self.services.runtime_config.auth_mode,
                    "route_count": len(API_ROUTE_REGISTRY.list_routes()),
                    "runtime": self.services.task_repository.runtime_summary(),
                },
                HTTPStatus.OK if health["ready"] or not self.services.runtime_config.is_production else HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        if parsed_path.path == "/api/metrics":
            self._send_text(format_prometheus_metrics(self.services.task_repository.runtime_summary()))
            return
        if parsed_path.path == "/api/routes":
            self._send_json(API_ROUTE_REGISTRY.openapi_summary())
            return
        if parsed_path.path == "/api/openapi.json":
            self._send_json(API_ROUTE_REGISTRY.openapi_document())
            return
        route_handler = GET_ROUTE_HANDLERS.get(parsed_path.path)
        if route_handler:
            route_handler(self, parsed_path.query)
            return
        self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed_path = urlparse(self.path)
        if not self._enforce_ip_rate_limit(parsed_path.path):
            return
        route_handler = POST_ROUTE_HANDLERS.get(parsed_path.path)
        if not route_handler:
            self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
            return
        route_handler(self)

    def do_PUT(self) -> None:
        parsed_path = urlparse(self.path)
        if not self._enforce_ip_rate_limit(parsed_path.path):
            return
        route_handler = PUT_ROUTE_HANDLERS.get(parsed_path.path)
        if not route_handler:
            self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
            return
        route_handler(self)

    def do_DELETE(self) -> None:
        parsed_path = urlparse(self.path)
        if not self._enforce_ip_rate_limit(parsed_path.path):
            return
        route_handler = DELETE_ROUTE_HANDLERS.get(parsed_path.path)
        if not route_handler:
            self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
            return
        route_handler(self, parsed_path.query)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _request_context(
        self,
        payload: dict[str, Any] | None = None,
        params: dict[str, list[str]] | None = None,
    ) -> APIRequestContext:
        payload = payload or {}
        params = params or {}
        websocket_token = _websocket_session_token(self.headers.get("Sec-WebSocket-Protocol"))
        token = websocket_token
        authorization = self.headers.get("Authorization") or (f"Bearer {token}" if token else None)
        session = resolve_request_context(
            headers={
                "authorization": authorization,
                "cookie": self.headers.get("Cookie"),
                "x-user-id": self.headers.get("X-User-Id"),
                "x-tenant-id": self.headers.get("X-Tenant-Id"),
            },
            payload=payload,
            params=params,
            default_user_id=LOCAL_ANALYSIS_USER_ID,
            default_tenant_id=LEGACY_TENANT_ID,
        )
        if session.device_session_id:
            self.services.session_store.validate_access(
                session.session_id,
                session.device_session_id,
                session.user_id,
                session.tenant_id,
            )
        elif self.services.runtime_config.auth_mode == "strict":
            from backend.platform.security import AuthenticationError

            raise AuthenticationError("stateful_device_session_required")
        if not getattr(self, "_identity_rate_checked", False):
            self._enforce_identity_rate_limit(session.user_id, session.tenant_id)
            self._identity_rate_checked = True
        return APIRequestContext(user_id=session.user_id, tenant_id=session.tenant_id)

    def _enforce_ip_rate_limit(self, path: str) -> bool:
        ip_limit, _, _ = request_limits(path)
        ip_address = self.client_address[0] if self.client_address else "unknown"
        decision = self.services.rate_limiter.check(f"ip:{ip_address}:{path}", ip_limit, 60)
        if decision.allowed:
            return True
        self._send_json(
            {
                "error": "rate_limit_exceeded",
                "message": "Too many requests. Retry after the indicated delay.",
                "retry_after_seconds": decision.retry_after_seconds,
            },
            HTTPStatus.TOO_MANY_REQUESTS,
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )
        return False

    def _enforce_identity_rate_limit(self, user_id: str, tenant_id: str) -> None:
        path = urlparse(self.path).path
        _, user_limit, tenant_limit = request_limits(path)
        decisions = []
        if user_limit:
            decisions.append(self.services.rate_limiter.check(f"user:{user_id}:{path}", user_limit, 60))
        if tenant_limit:
            decisions.append(self.services.rate_limiter.check(f"tenant:{tenant_id}:{path}", tenant_limit, 60))
        denied = next((decision for decision in decisions if not decision.allowed), None)
        if denied:
            from backend.platform.security import RateLimitExceeded

            raise RateLimitExceeded(denied.retry_after_seconds)

    def _require_metric_permission(self, context: APIRequestContext, action: str) -> None:
        self.services.permission_broker.require_resource(
            context.to_execution_context(),
            "metric:*",
            action,
        )

    def _require_system_config_permission(self, context: APIRequestContext, action: str) -> None:
        self.services.permission_broker.require_resource(
            context.to_execution_context(),
            "system_config:*",
            action,
        )

    def _require_asset_permission(self, context: APIRequestContext, action: str) -> None:
        self.services.permission_broker.require_resource(
            context.to_execution_context(),
            "asset:*",
            action,
        )

    def _require_knowledge_permission(self, context: APIRequestContext, action: str) -> None:
        self.services.permission_broker.require_resource(
            context.to_execution_context(),
            "knowledge:*",
            action,
        )

    def _require_memory_permission(self, context: APIRequestContext, action: str) -> None:
        self.services.permission_broker.require_resource(
            context.to_execution_context(),
            "memory:*",
            action,
        )

    def _require_automation_permission(self, context: APIRequestContext, action: str) -> None:
        self.services.permission_broker.require_resource(
            context.to_execution_context(),
            "automation:*",
            action,
        )

    def _require_notification_permission(self, context: APIRequestContext, action: str) -> None:
        self.services.permission_broker.require_resource(
            context.to_execution_context(),
            "notification:*",
            action,
        )

    def _require_market_permission(self, context: APIRequestContext, action: str) -> None:
        self.services.permission_broker.require_resource(
            context.to_execution_context(),
            "market:*",
            action,
        )

    def _require_report_permission(self, context: APIRequestContext, action: str) -> None:
        self.services.permission_broker.require_resource(
            context.to_execution_context(),
            "report:*",
            action,
        )

    def _require_application_permission(self, context: APIRequestContext, action: str) -> None:
        self.services.permission_broker.require_resource(
            context.to_execution_context(),
            "application:*",
            action,
        )

    def _require_message_board_permission(self, context: APIRequestContext, action: str) -> None:
        # The authenticated user is the resource owner. All product accounts
        # may create/read their own messages; service methods enforce tenant
        # and owner scope on every row. The admin aggregate remains separately
        # guarded by _require_message_board_admin.
        if not context.user_id or not context.tenant_id or action not in {"read", "create", "manage"}:
            raise PermissionError("message_board_authenticated_user_required")

    def _require_message_board_admin(self, context: APIRequestContext) -> None:
        if not self.services.permission_broker.enforcer.has_super_admin_role(context.user_id, context.tenant_id):
            raise PermissionError("global_super_admin_required")
        self.services.permission_broker.require_resource(
            context.to_execution_context(),
            "message_board:admin",
            "read",
        )

    def _write_audit(
        self,
        context: APIRequestContext,
        action: str,
        target_type: str,
        target_id: str = "",
        detail: dict[str, Any] | None = None,
    ) -> None:
        try:
            event = self.services.audit_store.write(
                tenant_id=context.tenant_id,
                actor_user_id=context.user_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                detail=detail or {},
                ip_address=self.client_address[0] if self.client_address else "",
            )
        except Exception as exc:
            self.services.trace_recorder.add_span(
                "audit.write",
                inputs={"action": action, "target_type": target_type},
                status="error",
                error_code=type(exc).__name__,
            )
            return
        try:
            self.services.learning_service.observe_operation(event)
        except Exception as exc:
            # Learning is an additive background concern. A malformed candidate
            # or temporary learning failure must never roll back the user action.
            self.services.trace_recorder.add_span(
                "learning.operation.observe",
                inputs={"action": action, "target_type": target_type},
                status="error",
                error_code=type(exc).__name__,
            )

    def _read_json(self, max_bytes: int = MAX_JSON_BODY_BYTES) -> dict[str, Any]:
        content_length = int(self.headers.get("content-length") or "0")
        if content_length <= 0:
            return {}
        if content_length > max_bytes:
            raise RequestBodyTooLarge(f"Request body exceeds {max_bytes} bytes.")
        raw = self.rfile.read(content_length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object.")
        return payload

    def _send_empty(self, status: HTTPStatus) -> None:
        self.send_response(status)
        self._send_common_headers()
        self.end_headers()

    def _send_json(
        self,
        payload: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
        headers: dict[str, str | list[str] | tuple[str, ...]] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._send_common_headers()
        for header_name, header_value in (headers or {}).items():
            if isinstance(header_value, (list, tuple)):
                for item in header_value:
                    self.send_header(header_name, item)
            else:
                self.send_header(header_name, header_value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self._send_common_headers()
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(
        self,
        body: bytes,
        *,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self._send_common_headers()
        for header_name, header_value in (headers or {}).items():
            self.send_header(header_name, header_value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_common_headers(self) -> None:
        allowed_origin = cors_origin_for_request(self.headers.get("Origin"), self.services.runtime_config)
        if allowed_origin:
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        allowed_headers = "content-type,authorization,x-request-id,x-trace-id,x-idempotency-key,x-tenant-id"
        if self.services.runtime_config.auth_mode == "development":
            allowed_headers += ",x-user-id"
        self.send_header("Access-Control-Allow-Headers", allowed_headers)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), geolocation=(), payment=()")


def _websocket_session_token(protocol_header: str | None) -> str:
    if not protocol_header:
        return ""
    protocols = [item.strip() for item in protocol_header.split(",") if item.strip()]
    try:
        marker_index = protocols.index("sda-session")
    except ValueError:
        return ""
    if marker_index + 1 >= len(protocols):
        return ""
    return protocols[marker_index + 1]


def _runtime_health(handler: AnalysisAPIHandler) -> dict[str, Any]:
    services = handler.services
    checks: dict[str, dict[str, Any]] = {}
    try:
        services.task_repository.runtime_summary()
        roles = services.permission_broker.enforcer.repository.list_roles()
        profiles = services.access_service.user_store.list_profiles()
        pool_health = (
            services.primary_database_pool.health()
            if services.primary_database_pool is not None
            else {"ready": True, "adapter": type(services.task_repository).__name__}
        )
        checks["database"] = {
            **pool_health,
            "ready": bool(pool_health.get("ready")) and (not services.runtime_config.is_production or bool(roles and profiles)),
            "role_count": len(roles),
            "user_count": len(profiles),
        }
        if services.runtime_config.is_production and not roles:
            checks["database"]["error"] = "production_rbac_not_provisioned"
        elif services.runtime_config.is_production and not profiles:
            checks["database"]["error"] = "production_users_not_provisioned"
    except Exception as exc:
        checks["database"] = {"ready": False, "error": type(exc).__name__}
    worker = getattr(handler.server, "automation_worker", None)
    checks["automation_worker"] = (
        worker.health()
        if worker is not None and callable(getattr(worker, "health", None))
        else _external_worker_health(services.runtime_config.is_production)
    )
    limiter_health = getattr(services.rate_limiter, "health", None)
    checks["rate_limiter"] = limiter_health() if callable(limiter_health) else {"ready": False}
    object_store = services.data_acquisition_service.object_store
    object_health = getattr(object_store, "health", None)
    checks["object_store"] = (
        dict(object_health())
        if callable(object_health)
        else {
            "ready": True,
            "adapter": type(object_store).__name__,
            "durable": getattr(object_store, "_temporary", None) is None,
        }
    )
    semantic_mock = "mock" in str(services.data_source_mode).lower() or services.semantic_fallback_mode == "explicit_local"
    checks["semantic_runtime"] = {
        "ready": not services.runtime_config.is_production or not semantic_mock,
        "mode": services.semantic_client_mode,
        "data_source_mode": services.data_source_mode,
        "fallback_mode": services.semantic_fallback_mode,
    }
    kernel = getattr(services, "runtime_kernel", None)
    hermes_status = kernel.hermes_status() if kernel is not None and callable(getattr(kernel, "hermes_status", None)) else {"ready": True, "mode": "off", "configured": False}
    checks["hermes_draft"] = hermes_status
    if services.runtime_config.is_production:
        if type(services.task_repository).__name__.startswith(("SQLite", "InMemory")):
            checks["database"].update(
                {"ready": False, "error": "production_mysql_adapter_required"}
            )
        if not bool(checks["rate_limiter"].get("distributed")):
            checks["rate_limiter"].update(
                {"ready": False, "error": "production_distributed_rate_limiter_required"}
            )
        if type(object_store).__name__ == "LocalArtifactObjectStore":
            checks["object_store"].update(
                {"ready": False, "error": "production_object_store_adapter_required"}
            )
    ready = all(bool(check.get("ready")) for check in checks.values())
    degraded = semantic_mock or not bool(checks["object_store"].get("durable"))
    return {
        "status": "ok" if ready and not degraded else "degraded" if ready else "unavailable",
        "ready": ready,
        "build": {"commit_sha": os.getenv("SMART_DATA_AGENT_COMMIT_SHA", "").strip()},
        "checks": checks,
    }


def _external_worker_health(production: bool) -> dict[str, Any]:
    from datetime import datetime, timezone
    import json
    import os

    configured = os.getenv("SMART_DATA_AGENT_WORKER_HEALTH_FILE", "").strip()
    if not configured:
        return {
            "ready": not production,
            "mode": "external",
            "embedded": False,
            **({"error": "external_worker_health_file_required"} if production else {}),
        }
    try:
        payload = json.loads(Path(configured).read_text(encoding="utf-8"))
        if payload.get("schema_version") != "smart-data-agent-worker-health/v1":
            raise ValueError("external_worker_health_schema_incompatible")
        worker_id = str(payload.get("worker_id") or "").strip()
        if not worker_id:
            raise ValueError("external_worker_id_required")
        heartbeat = datetime.fromisoformat(str(payload.get("heartbeat_at") or "").replace("Z", "+00:00"))
        age_seconds = (datetime.now(timezone.utc) - heartbeat.astimezone(timezone.utc)).total_seconds()
        timestamp_valid = -5 <= age_seconds <= 30
        declared_ready = bool(payload.get("ready"))
        ready = declared_ready and timestamp_valid
        error = ""
        if not declared_ready:
            error = "external_worker_not_ready"
        elif not timestamp_valid:
            error = "external_worker_heartbeat_stale"
        return {
            "ready": ready,
            "mode": "external",
            "embedded": False,
            "worker_id": worker_id,
            "heartbeat_age_seconds": round(max(0.0, age_seconds), 3),
            "last_error_code": payload.get("last_error_code"),
            **({"error": error} if error else {}),
        }
    except Exception:
        return {
            "ready": False,
            "mode": "external",
            "embedded": False,
            "error": "external_worker_heartbeat_unavailable",
        }


def create_server(host: str, port: int, test_sqlite_db: str | Path | None = None) -> ThreadingHTTPServer:
    # SQLite remains an explicit isolated-test adapter. Every normal process,
    # including local development, must be backed by the configured MySQL URL.
    services = (
        build_local_platform(db_path=test_sqlite_db)
        if test_sqlite_db is not None
        else build_production_platform()
    )

    class BoundAnalysisAPIHandler(AnalysisAPIHandler):
        pass

    BoundAnalysisAPIHandler.services = services
    server = AnalysisAPIServer((host, port), BoundAnalysisAPIHandler)
    server.services = services
    server.automation_worker = AutomationWorker(services.automation_runtime)
    server.automation_worker.start()
    return server


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)
    parser = argparse.ArgumentParser(description="Run the Smart Data Agent local API server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--test-sqlite-db", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    os.environ.setdefault(
        "SMART_DATA_AGENT_OBJECT_ROOT",
        str(Path(__file__).resolve().parents[3] / "Topic_Data" / "artifacts"),
    )

    server = create_server(args.host, args.port, args.test_sqlite_db)
    print(f"Smart Data Agent API listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
