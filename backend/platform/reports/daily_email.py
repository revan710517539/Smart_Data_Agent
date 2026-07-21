from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


class DailyEmailReportService:
    def __init__(self, report_store: Any, acquisition_store: Any, object_store: Any, automation_store: Any) -> None:
        self.report_store = report_store
        self.acquisition_store = acquisition_store
        self.object_store = object_store
        self.automation_store = automation_store

    def state(self, tenant_id: str, actor_user_id: str) -> dict[str, Any]:
        runs = [self._reconcile(tenant_id, actor_user_id, run) for run in self.report_store.list_daily_report_runs(tenant_id, actor_user_id)]
        subscriptions = [
            item for item in self.automation_store.list_subscriptions(tenant_id, actor_user_id)
            if item.get("channel_type") == "email" and item.get("status") == "active"
            and "report.daily.ready" in item.get("event_types", [])
        ]
        latest = runs[0] if runs else None
        return {
            "runs": runs,
            "latest": latest,
            "email_subscription_count": len(subscriptions),
            "delivery_summary": self._delivery_summary(tenant_id, latest) if latest else {},
        }

    def generate(
        self,
        tenant_id: str,
        actor_user_id: str,
        *,
        report_date: str | None = None,
        source_report_version_id: str | None = None,
    ) -> dict[str, Any]:
        date_value = report_date or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        versions = self.report_store.list_weekly_report_versions(tenant_id, actor_user_id)
        eligible = [
            version for version in versions
            if version.get("publicationStatus") == "ready"
            and bool((version.get("evidenceSummary") or {}).get("publishable"))
        ]
        if source_report_version_id:
            eligible = [version for version in eligible if version.get("id") == source_report_version_id]
        if not eligible:
            raise ValueError("publishable_report_version_required")
        source = eligible[0]
        subject = _subject(source, date_value)
        preview = _preview_text(source)
        body = _render_html(source, subject, preview).encode("utf-8")
        if len(body) > 2 * 1024 * 1024:
            raise ValueError("daily_report_body_too_large")
        stored = self.object_store.put(tenant_id, body, ".html")
        artifact = self.acquisition_store.create_artifact(
            tenant_id,
            object_uri=stored.object_uri,
            content_hash=stored.content_hash,
            content_type="text/html; charset=utf-8",
            size_bytes=stored.size_bytes,
            status="active",
            created_by=actor_user_id,
            artifact_type="export",
        )
        evidence = {
            **dict(source.get("evidenceSummary") or {}),
            "source_report_version_id": source["id"],
            "source_content_hash": source.get("contentHash"),
            "generated_from_immutable_artifact": True,
        }
        return self.report_store.create_daily_report_run(
            tenant_id,
            {
                "report_date": date_value,
                "source_report_version_id": source["id"],
                "subject": subject,
                "body_artifact_id": artifact["artifact_id"],
                "content_hash": artifact["content_hash"],
                "evidence_summary": evidence,
                "preview_text": preview,
            },
            actor_user_id,
        )

    def send(self, tenant_id: str, actor_user_id: str, daily_report_run_id: str) -> dict[str, Any]:
        run = self.report_store.get_daily_report_run(tenant_id, daily_report_run_id, actor_user_id)
        if not bool(run.get("evidence_summary", {}).get("publishable")):
            raise ValueError("daily_report_evidence_is_not_publishable")
        artifact = self.acquisition_store.get_artifact(tenant_id, str(run["body_artifact_id"]))
        if artifact.get("status") != "active" or artifact.get("content_hash") != run.get("content_hash"):
            raise ValueError("daily_report_artifact_is_not_active")
        subscriptions = [
            item for item in self.automation_store.list_subscriptions(tenant_id, actor_user_id)
            if item.get("channel_type") == "email" and item.get("status") == "active"
            and "report.daily.ready" in item.get("event_types", [])
        ]
        if not subscriptions:
            raise ValueError("active_daily_email_subscription_required")
        event = self.acquisition_store.enqueue_outbox_event_once(
            tenant_id,
            "daily_report_run",
            daily_report_run_id,
            "report.daily.ready",
            {
                "daily_report_run_id": daily_report_run_id,
                "body_artifact_id": run["body_artifact_id"],
                "body_hash": run["content_hash"],
                "subject": run["subject"],
                "report_date": run["report_date"],
                "source_report_version_id": run["source_report_version_id"],
            },
        )
        return self.report_store.update_daily_report_run(
            tenant_id,
            daily_report_run_id,
            actor_user_id,
            status="queued",
            outbox_event_id=str(event["outbox_event_id"]),
        )

    def _reconcile(self, tenant_id: str, actor_user_id: str, run: dict[str, Any]) -> dict[str, Any]:
        outbox_id = str(run.get("outbox_event_id") or "")
        if not outbox_id:
            return run
        deliveries = self.automation_store.list_deliveries_for_outbox(tenant_id, outbox_id)
        if not deliveries:
            status = "queued"
        elif all(item["status"] == "delivered" for item in deliveries):
            status = "delivered"
        elif all(item["status"] in {"dead_letter", "suppressed"} for item in deliveries):
            status = "failed"
        else:
            status = "sending"
        if run.get("status") != status:
            return self.report_store.update_daily_report_run(
                tenant_id, run["daily_report_run_id"], actor_user_id, status=status
            )
        return run

    def _delivery_summary(self, tenant_id: str, run: dict[str, Any] | None) -> dict[str, int]:
        if not run or not run.get("outbox_event_id"):
            return {}
        deliveries = self.automation_store.list_deliveries_for_outbox(tenant_id, str(run["outbox_event_id"]))
        summary: dict[str, int] = {}
        for delivery in deliveries:
            status = str(delivery["status"])
            summary[status] = summary.get(status, 0) + 1
        return summary


def _subject(version: dict[str, Any], report_date: str) -> str:
    report = version.get("report") if isinstance(version.get("report"), dict) else {}
    institution = str(report.get("institutionName") or "经营机构")
    return " ".join(f"{institution}经营日报 - {report_date}".replace("\r", " ").replace("\n", " ").split())[:998]


def _preview_text(version: dict[str, Any]) -> str:
    report = version.get("report") if isinstance(version.get("report"), dict) else {}
    lines: list[str] = []
    for section in report.get("sections", []) if isinstance(report.get("sections"), list) else []:
        if not isinstance(section, dict):
            continue
        for block in section.get("blocks", []) if isinstance(section.get("blocks"), list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text = str(block.get("content") or "").strip()
                if text:
                    lines.append(text)
                for item in block.get("contentItems", []) if isinstance(block.get("contentItems"), list) else []:
                    if isinstance(item, dict) and item.get("type") == "paragraph" and str(item.get("text") or "").strip():
                        lines.append(str(item["text"]).strip())
            elif block.get("type") == "table":
                title = str(block.get("title") or "数据表").strip()
                rows = block.get("rows") if isinstance(block.get("rows"), list) else []
                lines.append(f"{title}：{len(rows)} 行已验证数据。")
    return "\n".join(dict.fromkeys(lines))[:4000] or "该日报仅包含已验证的数据块，未发现可用于纯文本预览的结论。"


def _render_html(version: dict[str, Any], subject: str, preview: str) -> str:
    evidence = dict(version.get("evidenceSummary") or {})
    source_line = (
        f"来源版本 {version.get('id')} · 内容校验 {version.get('contentHash')} · "
        f"已验证数据块 {len(evidence.get('verified_block_ids') or [])}"
    )
    paragraphs = "".join(f"<p>{html.escape(line)}</p>" for line in preview.splitlines() if line.strip())
    evidence_json = html.escape(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return (
        "<!doctype html><html><head><meta charset='utf-8'></head>"
        "<body style='font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;color:#1d1d1f'>"
        f"<h2>{html.escape(subject)}</h2>{paragraphs}"
        f"<hr><p style='font-size:12px;color:#8a8a8e'>{html.escape(source_line)}</p>"
        f"<p style='font-size:10px;color:#aeaeb2'>Evidence: {evidence_json}</p>"
        "</body></html>"
    )
