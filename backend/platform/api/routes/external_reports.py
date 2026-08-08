from __future__ import annotations

from typing import Any

from backend.platform.api.support import send_route_exception
from backend.platform.integrations.report_ingress import build_external_report, resolve_report_ingress_binding


def handle_external_report_import(handler: Any) -> None:
    """Accept a token-bound report from WorkBuddy or another registered channel."""

    try:
        payload = handler._read_json()
        binding = resolve_report_ingress_binding(handler.headers.get("Authorization"))
        report = build_external_report(payload, binding)
        topic_reference = handler.services.topic_data_store.record_saved_report_snapshot(
            tenant_id=binding.tenant_id,
            user_id=binding.user_id,
            report_id=str(report["id"]),
            report=report,
            source=f"external:{binding.channel}",
        )
        saved = handler.services.report_store.upsert_analysis_result(
            binding.tenant_id,
            {**report, "topicData": topic_reference, "ownerUserId": binding.user_id},
            updated_by=binding.user_id,
        )
        source = saved.get("source") if isinstance(saved.get("source"), dict) else {}
        handler.services.lineage_store.record_edge(
            binding.tenant_id,
            {
                "source_type": f"external_report:{binding.channel}",
                "source_id": str(source.get("runId") or ""),
                "target_type": "saved_analysis_result",
                "target_id": str(saved.get("id") or ""),
                "edge_type": "publishes",
                "metadata": {"channel": binding.channel, "binding_id": binding.binding_id},
            },
            binding.user_id,
        )
        handler.services.audit_store.write(
            tenant_id=binding.tenant_id,
            actor_user_id=binding.user_id,
            action="external_report.import",
            target_type="saved_analysis_result",
            target_id=str(saved.get("id") or ""),
            detail={"channel": binding.channel, "binding_id": binding.binding_id, "source_run_id": source.get("runId")},
            ip_address=handler.client_address[0] if handler.client_address else "",
        )
        handler._send_json(
            {
                "tenant_id": binding.tenant_id,
                "result": saved,
                "created_or_updated": "upserted",
                "channel": binding.channel,
            }
        )
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)
