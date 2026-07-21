from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


class ReportRetentionService:
    def __init__(self, report_store: Any, system_config_store: Any) -> None:
        self.report_store = report_store
        self.system_config_store = system_config_store

    def enforce(self, tenant_id: str, now: datetime | None = None) -> dict[str, Any]:
        try:
            days = int(self.system_config_store.get_system_param_value(tenant_id, "report_retention_days"))
        except (AttributeError, KeyError, TypeError, ValueError):
            days = 365
        days = max(1, min(days, 3650))
        reference = now or datetime.now(timezone.utc)
        cutoff = reference - timedelta(days=days)
        archive = getattr(self.report_store, "archive_expired", None)
        counts = archive(tenant_id, cutoff) if callable(archive) else {"analysis_results": 0, "weekly_versions": 0}
        return {
            "tenant_id": tenant_id,
            "retention_days": days,
            "cutoff": cutoff.isoformat(),
            "archived": counts,
        }
