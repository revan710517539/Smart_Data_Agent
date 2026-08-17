from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

from backend.platform.api.support import send_route_exception
from backend.platform.integrations.report_ingress import ReportIngressBinding, resolve_report_ingress_binding
from backend.platform.tenancy import ExecutionContext


MAX_SHARED_ROWS = 500
MAX_REFERENCED_TABLES = 8
BRIDGE_CHANNELS = {"workbuddy", "codex", "qwork"}
FORBIDDEN_EVIDENCE_FIELDS = {
    "conversation",
    "conversation_transcript",
    "transcript",
    "raw_data",
    "raw_rows",
    "credentials",
    "credential",
    "token",
    "authorization",
}


def handle_workbuddy_context_get(handler: Any, query: str) -> None:
    _handle_bridge_context_get(handler, query, "workbuddy")


def handle_codex_context_get(handler: Any, query: str) -> None:
    _handle_bridge_context_get(handler, query, "codex")


def handle_qwork_context_get(handler: Any, query: str) -> None:
    _handle_bridge_context_get(handler, query, "qwork")


def _handle_bridge_context_get(handler: Any, query: str, expected_channel: str) -> None:
    """Return active reusable context plus explicitly shared CSV metadata."""

    del query
    try:
        binding = _bridge_binding(handler, expected_channel)
        handler._send_json(build_sda_bridge_context(handler, binding))
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_workbuddy_data_get(handler: Any) -> None:
    _handle_bridge_data_get(handler, "workbuddy")


def handle_codex_data_get(handler: Any) -> None:
    _handle_bridge_data_get(handler, "codex")


def handle_qwork_data_get(handler: Any) -> None:
    _handle_bridge_data_get(handler, "qwork")


def _handle_bridge_data_get(handler: Any, expected_channel: str) -> None:
    """Read a bounded projection of a source that its SDA owner shared."""

    try:
        payload = handler._read_json()
        binding = _bridge_binding(handler, expected_channel)
        handler._send_json(read_sda_bridge_data(handler, binding, payload))
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_workbuddy_evidence_ingest(handler: Any) -> None:
    _handle_bridge_evidence_ingest(handler, "workbuddy")


def handle_codex_evidence_ingest(handler: Any) -> None:
    _handle_bridge_evidence_ingest(handler, "codex")


def handle_qwork_evidence_ingest(handler: Any) -> None:
    _handle_bridge_evidence_ingest(handler, "qwork")


def _handle_bridge_evidence_ingest(handler: Any, expected_channel: str) -> None:
    """Collect bounded analysis logic as review-only memory and Skill material."""

    try:
        payload = handler._read_json(max_bytes=256 * 1024)
        binding = _bridge_binding(handler, expected_channel)
        handler._send_json(ingest_sda_bridge_evidence(handler, binding, payload))
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def build_sda_bridge_context(handler: Any, binding: ReportIngressBinding) -> dict[str, Any]:
    tables = _shared_tables(handler, binding)
    published = handler.services.data_asset_store.list_published_bundle(binding.tenant_id)
    return {
        "tenant_id": binding.tenant_id,
        "channel": binding.channel,
        "raw_tables": [_safe_table_metadata(table) for table in tables],
        "memories": handler.services.memory_service.list_active(binding.tenant_id, binding.user_id),
        "skills": published.get("analysis_skills", []),
        "policy": "shared_only;csv_read_only;candidate_then_four_eyes_review",
    }


def read_sda_bridge_data(
    handler: Any,
    binding: ReportIngressBinding,
    payload: dict[str, Any],
) -> dict[str, Any]:
    source_key = str(payload.get("source_key") or payload.get("sourceKey") or "").strip()
    table = _shared_table(handler, binding, source_key)
    requested_columns = [
        str(value).strip()
        for value in (payload.get("columns") if isinstance(payload.get("columns"), list) else [])
        if str(value).strip()
    ]
    if len(requested_columns) > 50:
        raise ValueError("bridge_data_column_limit_exceeded")
    limit = max(1, min(int(payload.get("limit") or 100), MAX_SHARED_ROWS))
    csv_source = handler.services.data_acquisition_service.csv_source.for_tenant(binding.tenant_id)
    headers, rows = csv_source.read_rows(str(table["relativePath"]), max_rows=limit + 1)
    unknown_columns = [column for column in requested_columns if column not in headers]
    if unknown_columns:
        raise ValueError(f"bridge_data_columns_invalid:{','.join(unknown_columns)}")
    columns = requested_columns or headers[:50]
    truncated = len(rows) > limit
    rows = rows[:limit]
    handler.services.audit_store.write(
        binding.tenant_id,
        binding.user_id,
        f"{binding.channel}.bridge.data.read",
        "raw_table_source",
        source_key,
        {"binding_id": binding.binding_id, "row_count": len(rows), "column_count": len(columns)},
        handler.client_address[0] if handler.client_address else "",
    )
    return {
        "tenant_id": binding.tenant_id,
        "source_key": source_key,
        "table": _safe_table_metadata(table),
        "columns": columns,
        "rows": [{column: row.get(column, "") for column in columns} for row in rows],
        "row_count": len(rows),
        "truncated": truncated,
    }


def ingest_sda_bridge_evidence(
    handler: Any,
    binding: ReportIngressBinding,
    payload: dict[str, Any],
) -> dict[str, Any]:
    forbidden = sorted(FORBIDDEN_EVIDENCE_FIELDS.intersection(payload))
    if forbidden:
        raise ValueError(f"bridge_evidence_forbidden_fields:{','.join(forbidden)}")
    references = _validated_references(handler, binding, payload)
    source_keys = [reference["source_key"] for reference in references]
    run_id = _text(payload.get("run_id") or payload.get("runId"), 160)
    if not run_id:
        raise ValueError("bridge_evidence_run_id_required")
    evidence = {
        "channel": binding.channel,
        "binding_id": binding.binding_id,
        "references": references,
        "source_keys": source_keys,
        "run_id": run_id,
        "report_id": _text(payload.get("report_id") or payload.get("reportId"), 200),
        "title": _text(payload.get("title"), 500) or "授权原始表分析",
        "question": _text(payload.get("question") or payload.get("query"), 4_000),
        "summary": _text(payload.get("summary") or payload.get("conclusion"), 10_000),
        "methodology": _text(payload.get("methodology") or payload.get("plan"), 4_000),
        "analysis_content": _text(payload.get("analysis_content") or payload.get("analysisContent"), 20_000),
        "logic_steps": _string_list(payload.get("logic_steps") or payload.get("logicSteps"), 40),
        "findings": _string_list(payload.get("findings"), 40),
        "assumptions": _string_list(payload.get("assumptions"), 20),
        "limitations": _string_list(payload.get("limitations"), 20),
        "metrics": _string_list(payload.get("metrics"), 12),
        "dimensions": _string_list(payload.get("dimensions"), 12),
        "chart_types": _string_list(payload.get("chart_types") or payload.get("chartTypes"), 8),
    }
    if not evidence["summary"]:
        raise ValueError("bridge_evidence_summary_required")
    if not evidence["methodology"] and not evidence["logic_steps"]:
        raise ValueError("bridge_evidence_logic_required")
    content_hash = hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    memory_id = f"{binding.channel}-evidence-{hashlib.sha256((binding.binding_id + ':' + ':'.join(source_keys) + ':' + run_id).encode('utf-8')).hexdigest()[:24]}"
    try:
        existing = handler.services.memory_service.get(binding.tenant_id, memory_id)
    except KeyError:
        existing = None
    if existing is not None:
        existing_evidence = existing.get("content", {}).get("evidence") if isinstance(existing.get("content"), dict) else None
        existing_hash = hashlib.sha256(json.dumps(existing_evidence, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        if existing_hash != content_hash:
            raise ValueError("bridge_operation_idempotency_conflict")
        return {
            "tenant_id": binding.tenant_id,
            "accepted": True,
            "memory_candidate_id": memory_id,
            "skill_candidate_id": None,
            "review_required": True,
            "idempotent_replay": True,
        }
    event = handler.services.audit_store.write(
        binding.tenant_id,
        binding.user_id,
        f"{binding.channel}.bridge.evidence.ingested",
        "external_analysis_evidence",
        run_id,
        {"binding_id": binding.binding_id, "run_id": run_id, "source_keys": source_keys, "content_hash": content_hash},
        handler.client_address[0] if handler.client_address else "",
    )
    handler.services.memory_service.create_candidate(
        binding.tenant_id,
        {
            "memory_id": memory_id,
            "memory_type": "analysis_case",
            "subject_type": "user",
            "subject_id": binding.user_id,
            "title": f"{binding.label} 分析材料：{evidence['title']}",
            "content": {"learning_origin": f"{binding.channel}.bridge", "evidence": evidence, "review_policy": "candidate_only"},
            "confidence": 0.6,
            "weight": 1.0,
            "evidence": {"evidence_type": f"{binding.channel}_analysis", "evidence_id": str(event.get("event_id") or run_id), "evidence_hash": content_hash},
        },
        binding.user_id,
    )
    learning = handler.services.learning_service.observe_analysis_result(
        ExecutionContext(user_id=binding.user_id, tenant_id=binding.tenant_id),
        SimpleNamespace(
            task_id=f"{binding.channel}:{binding.binding_id}:{run_id}",
            execution_id="",
            analysis_plan={
                "intent_rule_id": f"{binding.channel}_external_analysis",
                "dataset_id": source_keys[0],
                "source_keys": source_keys,
                "metrics": evidence["metrics"],
                "dimensions": evidence["dimensions"],
                "chart_types": evidence["chart_types"],
                "procedure_steps": evidence["logic_steps"],
                "methodology": evidence["methodology"],
                "evidence_memory_ids": [memory_id],
            },
            review={"status": "passed", "publication_gate": "review_required"},
        ),
    )
    return {
        "tenant_id": binding.tenant_id,
        "accepted": True,
        "memory_candidate_id": memory_id,
        "skill_candidate_id": learning.get("candidate_id"),
        "review_required": True,
        "idempotent_replay": False,
    }


def _bridge_binding(handler: Any, expected_channel: str) -> ReportIngressBinding:
    if expected_channel not in BRIDGE_CHANNELS:
        raise PermissionError("bridge_channel_unsupported")
    binding = resolve_report_ingress_binding(handler.headers.get("Authorization"), handler.services.bridge_auth_store)
    if binding.channel != expected_channel:
        raise PermissionError(f"{expected_channel}_binding_required")
    return binding


def _shared_tables(handler: Any, binding: ReportIngressBinding) -> list[dict[str, Any]]:
    catalog = handler.services.data_acquisition_service.csv_source.for_tenant(binding.tenant_id)
    references = handler.services.data_asset_store.list_raw_table_external_references(binding.tenant_id)
    return [
        table
        for table in catalog.table_assets()
        if (reference := references.get(str(table.get("sourceKey") or "")))
        and reference.get("mode") == "shared"
        and str(reference.get("schemaFingerprint") or "") == str(table.get("schemaFingerprint") or "")
    ]


def _shared_table(handler: Any, binding: ReportIngressBinding, source_key: str) -> dict[str, Any]:
    if not source_key:
        raise ValueError("bridge_source_key_required")
    table = next((item for item in _shared_tables(handler, binding) if str(item.get("sourceKey") or "") == source_key), None)
    if table is None:
        raise PermissionError("bridge_source_not_shared")
    return table


def _validated_references(handler: Any, binding: ReportIngressBinding, payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_references = payload.get("references")
    if not isinstance(raw_references, list):
        source_key = str(payload.get("source_key") or payload.get("sourceKey") or "").strip()
        schema_fingerprint = str(payload.get("schema_fingerprint") or payload.get("schemaFingerprint") or "").strip()
        raw_references = [{"source_key": source_key, "schema_fingerprint": schema_fingerprint}]
    if not raw_references or len(raw_references) > MAX_REFERENCED_TABLES:
        raise ValueError("bridge_evidence_references_required")
    references: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_references:
        if not isinstance(item, dict):
            raise ValueError("bridge_evidence_reference_invalid")
        source_key = str(item.get("source_key") or item.get("sourceKey") or "").strip()
        if not source_key or source_key in seen:
            raise ValueError("bridge_evidence_reference_invalid")
        table = _shared_table(handler, binding, source_key)
        schema_fingerprint = str(item.get("schema_fingerprint") or item.get("schemaFingerprint") or "").strip()
        if schema_fingerprint != str(table.get("schemaFingerprint") or ""):
            raise PermissionError("bridge_source_schema_changed")
        available_columns = {
            str(value or "")
            for field in table.get("fields", [])
            if isinstance(field, dict)
            for value in (field.get("fieldNameCn"), field.get("fieldNameEn"), field.get("name"))
            if str(value or "").strip()
        }
        raw_columns = item.get("columns")
        if not isinstance(raw_columns, list) or not raw_columns:
            raise ValueError("bridge_evidence_reference_columns_required")
        columns = [str(value).strip() for value in raw_columns if str(value).strip()]
        if not columns:
            raise ValueError("bridge_evidence_reference_columns_required")
        if len(columns) > 50:
            raise ValueError("bridge_evidence_reference_column_limit_exceeded")
        unknown_columns = [column for column in columns if column not in available_columns]
        if unknown_columns:
            raise ValueError(f"bridge_evidence_reference_columns_invalid:{','.join(unknown_columns)}")
        references.append({
            "source_key": source_key,
            "schema_fingerprint": schema_fingerprint,
            "columns": columns,
        })
        seen.add(source_key)
    return references


def _safe_table_metadata(table: dict[str, Any]) -> dict[str, Any]:
    return {
        key: table.get(key)
        for key in ("id", "sourceKey", "schemaFingerprint", "tableNameEn", "tableNameCn", "description", "rowCount", "fields", "updatedAt", "contentHash")
    }


def _text(value: Any, maximum: int) -> str:
    return str(value or "").strip()[:maximum]


def _string_list(value: Any, maximum: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (_text(entry, 200) for entry in value) if item][:maximum]
