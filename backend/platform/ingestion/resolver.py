from __future__ import annotations

from typing import Any


class TopicDataResolver:
    """Single upper-layer contract for offline and explicitly requested realtime topic data."""

    def __init__(self, acquisition_service: Any) -> None:
        self.acquisition_service = acquisition_service

    def resolve_topic_data(
        self,
        tenant_id: str,
        topic_table_id: str,
        org_id: str | None,
        *,
        mode: str = "offline",
        actor_user_id: str = "",
        acquisition_job_id: str | None = None,
        idempotency_key: str | None = None,
        freshness_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if mode not in {"offline", "realtime", "prefer_offline"}:
            raise ValueError("invalid_topic_data_resolve_mode")
        if mode in {"offline", "prefer_offline"}:
            try:
                artifact = self.acquisition_service.latest_csv(
                    tenant_id,
                    topic_table_id,
                    org_id,
                    include_content=True,
                )
                return {"mode": "offline", "artifact": artifact, "freshness_policy": freshness_policy or {}}
            except KeyError:
                if mode == "offline":
                    raise
        if not acquisition_job_id:
            raise ValueError("realtime_acquisition_job_id_required")
        run = self.acquisition_service.run_job(
            tenant_id,
            acquisition_job_id,
            actor_user_id,
            idempotency_key or f"realtime:{topic_table_id}:{org_id or 'all'}",
            org_unit_id=org_id,
            input_cursor={"operation_type": "data_query"},
        )
        return {"mode": "realtime", "run": run, "freshness_policy": freshness_policy or {}}

    # Compatibility alias for existing design documentation.
    def resolveTopicData(self, *args: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: N802
        return self.resolve_topic_data(*args, **kwargs)

