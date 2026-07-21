from __future__ import annotations

from datetime import datetime, timezone

from .contracts import CrawlerErrorCode, CrawlerOperation, CrawlerRequest, CrawlerResult
from .diagnostics import stable_json_hash


class StubCrawlerTransport:
    """Contract gate used until a real, approved browser profile is enabled."""

    name = "stub"

    def execute(self, request: CrawlerRequest) -> CrawlerResult:
        if not request.tenant_id or not request.idempotency_key:
            raise ValueError("crawler_request_identity_required")
        connection = request.connection
        if not str(connection.get("loginUrl") or connection.get("apiUrl") or "").strip():
            raise ValueError("crawler_login_url_required")
        if not str(connection.get("queryPageUrl") or connection.get("apiUrl") or "").strip():
            raise ValueError("crawler_query_page_url_required")
        if request.operation_type == CrawlerOperation.DATA_QUERY and not request.readonly_sql:
            raise ValueError("crawler_readonly_sql_required")
        observed_at = datetime.now(timezone.utc).isoformat()
        snapshot = {
            "snapshot_id": f"crawler-stub:{stable_json_hash({'key': request.idempotency_key})[:20]}",
            "observed_at": observed_at,
            "source_version": "stub-contract-v1",
            "operation_type": request.operation_type.value,
            "transport": self.name,
        }
        return CrawlerResult(
            status="not_configured",
            diagnostics={
                "transport": self.name,
                "message": "爬虫参数与安全门禁已通过；启用 Playwright Worker 后执行真实登录和查询。",
                "automatic_application_allowed": False,
            },
            source_snapshot=snapshot,
            schema_hash=stable_json_hash({"operation": request.operation_type.value, "script": request.script}),
            error_code=CrawlerErrorCode.TRANSPORT_NOT_CONFIGURED,
        )

