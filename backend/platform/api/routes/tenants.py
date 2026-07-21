from __future__ import annotations

from typing import Any

from backend.authz import normalize_tenant_id
from backend.authz.seed import OPERATING_TENANTS
from backend.platform.api.support import send_route_exception


def handle_tenants_get(handler: Any, query: str) -> None:
    try:
        tenants = [
            {
                "id": normalize_tenant_id(name),
                "name": name,
                "status": "active",
            }
            for name in OPERATING_TENANTS
        ]
        handler._send_json({"tenants": tenants, "count": len(tenants)})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)
