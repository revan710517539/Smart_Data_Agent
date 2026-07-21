from __future__ import annotations

import os
from dataclasses import replace
from typing import Any
from uuid import uuid4

from backend.platform.security import validate_outbound_url

from .contracts import CrawlerOperation, CrawlerRequest, CrawlerResult
from .playwright_transport import PlaywrightCrawlerTransport
from .policy import validate_browser_script
from .profile_registry import CrawlerProfileRegistry, get_default_crawler_profile_registry
from .sql_parser import SQLDecomposer
from .stub_transport import StubCrawlerTransport
from .url_identity import build_crawler_url_identity


class CrawlerEngine:
    def __init__(
        self,
        transport: Any | None = None,
        sql_decomposer: SQLDecomposer | None = None,
        profile_registry: CrawlerProfileRegistry | None = None,
    ) -> None:
        self.profile_registry = (
            profile_registry
            or getattr(transport, "profile_registry", None)
            or get_default_crawler_profile_registry()
        )
        self.transport = transport or self._transport_from_environment(self.profile_registry)
        self.sql_decomposer = sql_decomposer or SQLDecomposer()

    @staticmethod
    def _transport_from_environment(profile_registry: CrawlerProfileRegistry) -> Any:
        mode = os.getenv("SMART_DATA_AGENT_CRAWLER_TRANSPORT", "stub").strip().lower()
        if mode == "playwright":
            return PlaywrightCrawlerTransport(profile_registry=profile_registry)
        if mode != "stub":
            raise ValueError(f"unsupported_crawler_transport:{mode}")
        return StubCrawlerTransport()

    def execute(self, request: CrawlerRequest) -> CrawlerResult:
        if request.timeout_seconds < 1 or request.timeout_seconds > 900:
            raise ValueError("crawler_timeout_out_of_range")
        for key in ("loginUrl", "queryPageUrl", "apiUrl"):
            value = str(request.connection.get(key) or "").strip()
            if value:
                validate_outbound_url(value)
        if request.readonly_sql:
            self.sql_decomposer.parse(request.readonly_sql, str(request.parameters.get("dialect") or "postgres"))
        script = validate_browser_script(request.script)
        crawler_url = build_crawler_url_identity(request.connection)
        if crawler_url and crawler_url.mode == "sql" and request.operation_type == CrawlerOperation.DATA_QUERY:
            if not request.readonly_sql:
                raise ValueError("sql_crawler_readonly_sql_required")
        if crawler_url and crawler_url.profile_id:
            for step in script.get("steps", []):
                if str(step.get("action") or "") not in {"collect_system", "collect_funnel_analysis"}:
                    continue
                requested_profile = str(step.get("profile_id") or step.get("action") or "").strip()
                resolved_profile = self.profile_registry.get(requested_profile).descriptor.profile_id
                if resolved_profile != crawler_url.profile_id:
                    raise ValueError(
                        f"crawler_url_profile_mismatch:{crawler_url.crawler_key}:{resolved_profile}"
                    )
        result = self.transport.execute(CrawlerRequest(**{**request.__dict__, "script": script}))
        if not crawler_url:
            return result
        return replace(
            result,
            metadata={**result.metadata, "crawler_url": crawler_url.to_dict()},
        )

    def list_crawler_profiles(self, *, system_id: str | None = None) -> tuple[dict[str, Any], ...]:
        return tuple(item.to_dict() for item in self.profile_registry.list_profiles(system_id=system_id))

    @staticmethod
    def describe_connection_crawler(connection: dict[str, Any]) -> dict[str, str] | None:
        identity = build_crawler_url_identity(connection)
        return identity.to_dict() if identity else None

    def connectivity_test(self, connection: dict[str, Any], tenant_id: str) -> CrawlerResult:
        script = _connection_test_script(connection)
        request = CrawlerRequest(
            tenant_id=tenant_id,
            operation_type=CrawlerOperation.CONNECTIVITY_TEST,
            idempotency_key=f"connection-test:{uuid4().hex}",
            connection=connection,
            script=script,
            timeout_seconds=60,
        )
        return self.execute(request)


def _connection_test_script(connection: dict[str, Any]) -> dict[str, Any]:
    config = connection.get("crawlerConfig") if isinstance(connection.get("crawlerConfig"), dict) else {}
    steps: list[dict[str, Any]] = [
        {"action": "goto", "url": "${login_url}", "timeout_ms": 20_000},
        {
            "action": "fill",
            "selector": str(config.get("accountSelector") or 'input[name="username"], input[name="account"], input[type="email"]'),
            "value_key": "account",
            "timeout_ms": 10_000,
        },
        {
            "action": "fill",
            "selector": str(config.get("passwordSelector") or 'input[type="password"]'),
            "value_key": "password",
            "timeout_ms": 10_000,
        },
        {
            "action": "click",
            "selector": str(config.get("loginButtonSelector") or 'button[type="submit"]'),
            "timeout_ms": 10_000,
        },
        {"action": "goto", "url": "${query_page_url}", "timeout_ms": 20_000},
    ]
    ready = str(config.get("queryReadySelector") or "").strip()
    if ready:
        steps.append({"action": "wait", "selector": ready, "timeout_ms": 15_000})
    return {"version": 1, "steps": steps, "metadata": {"profile": "connectivity_test"}}
