from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

from backend.platform.api.routes.external_reports import import_external_report
from backend.platform.api.routes.workbuddy_bridge import (
    build_sda_bridge_context,
    ingest_sda_bridge_evidence,
    read_sda_bridge_data,
)
from backend.platform.api.support import APIRequestContext, send_route_exception
from backend.platform.integrations.bridge_connectors import BridgeConnectorRegistry, invoke_http_connector
from backend.platform.integrations.report_ingress import ReportIngressBinding, resolve_report_ingress_binding
from backend.platform.tenancy import ExecutionContext


_RESERVED_CLIENT_IDENTITY_FIELDS = {
    "tenant_id", "tenantId", "user_id", "userId", "binding_id", "bindingId",
    "authorization", "token", "credentials", "credential",
}
_FORBIDDEN_LEARNING_FIELDS = {
    "conversation", "conversation_transcript", "transcript", "raw_data",
    "raw_rows", "credentials", "credential", "token", "authorization",
}


def handle_bridge_manifest_get(handler: Any, query: str) -> None:
    del query
    try:
        binding = _binding(handler)
        manifest = BridgeConnectorRegistry().public_manifest(binding.channel)
        handler._send_json({
            **manifest,
            "channel": binding.channel,
            "identity_scope": "server_bound",
        })
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def handle_bridge_system_context(handler: Any) -> None:
    _handle_module(handler, "read", context_mode=True)


def handle_bridge_system_read(handler: Any) -> None:
    _handle_module(handler, "read")


def handle_bridge_system_action(handler: Any) -> None:
    _handle_module(handler, "configuration")


def handle_bridge_system_sync(handler: Any) -> None:
    _handle_module(handler, "analysis_sync")


def handle_bridge_system_evidence(handler: Any) -> None:
    _handle_module(handler, "learning")


def _handle_module(handler: Any, module: str, *, context_mode: bool = False) -> None:
    try:
        payload = handler._read_json(max_bytes=256 * 1024)
        binding = _binding(handler)
        system_id = str(payload.get("system_id") or payload.get("systemId") or "").strip().lower()
        if not system_id:
            raise ValueError("bridge_system_id_required")
        registry = BridgeConnectorRegistry()
        connector = registry.require(system_id, binding.channel)
        action = str(payload.get("action") or "").strip()
        input_payload = payload.get("input") if isinstance(payload.get("input"), dict) else {}
        _validate_client_input(module, input_payload)
        if connector["adapter"] == "builtin_sda":
            result = _invoke_sda(handler, binding, module, payload, action=action, context_mode=context_mode)
        else:
            forwarded = dict(payload)
            if context_mode:
                forwarded = {**forwarded, "input": {"resource": "authorized_context"}}
            result = invoke_http_connector(
                connector,
                module,
                binding=binding,
                payload=forwarded,
                action=action,
            )
            _audit(handler, binding, connector["id"], module, action, payload)
        handler._send_json({
            "schema_version": "bridge_response_v1",
            "contract_version": "1.0",
            "system_id": connector["id"],
            "module": module,
            "result": result,
        })
    except Exception as exc:  # pragma: no cover - HTTP boundary.
        send_route_exception(handler, exc)


def _invoke_sda(
    handler: Any,
    binding: ReportIngressBinding,
    module: str,
    payload: dict[str, Any],
    *,
    action: str,
    context_mode: bool,
) -> dict[str, Any]:
    input_payload = payload.get("input") if isinstance(payload.get("input"), dict) else {}
    operation_id = str(payload.get("operation_id") or payload.get("operationId") or "").strip()
    if module == "read":
        resource = "authorized_context" if context_mode else str(payload.get("resource") or input_payload.get("resource") or "").strip()
        if resource == "authorized_context":
            return build_sda_bridge_context(handler, binding)
        if resource == "raw_table.rows":
            return read_sda_bridge_data(handler, binding, input_payload)
        raise PermissionError("bridge_read_resource_not_allowed")
    if module == "analysis_sync":
        _require_operation_id(operation_id)
        report_payload = input_payload.get("report_package") if isinstance(input_payload.get("report_package"), dict) else input_payload
        source = report_payload.get("source") if isinstance(report_payload.get("source"), dict) else {}
        if str(source.get("run_id") or source.get("runId") or "").strip() != operation_id:
            raise ValueError("bridge_sync_operation_id_mismatch")
        return import_external_report(handler, report_payload, binding)
    if module == "learning":
        _require_operation_id(operation_id)
        if str(input_payload.get("run_id") or input_payload.get("runId") or "").strip() != operation_id:
            raise ValueError("bridge_evidence_operation_id_mismatch")
        if isinstance(input_payload.get("references"), list) or input_payload.get("source_key") or input_payload.get("sourceKey"):
            return ingest_sda_bridge_evidence(handler, binding, input_payload)
        return _ingest_sda_operation_evidence(handler, binding, input_payload, operation_id)
    if module == "configuration":
        _require_operation_id(operation_id)
        if action != "analysis_shortcut.upsert":
            raise PermissionError("bridge_configuration_action_not_allowed")
        context = APIRequestContext(user_id=binding.user_id, tenant_id=binding.tenant_id)
        handler._require_asset_permission(context, "manage")
        item = input_payload.get("item") if isinstance(input_payload.get("item"), dict) else input_payload
        allowed = {
            "id", "title", "query", "skillIds", "tableIds", "memoryIds",
            "visible", "sortOrder",
        }
        shortcut = {key: value for key, value in item.items() if key in allowed}
        shortcut["id"] = str(shortcut.get("id") or "").strip()
        shortcut["ownerUserId"] = binding.user_id
        if not shortcut["id"] or not shortcut["id"].startswith("shortcut-"):
            raise ValueError("bridge_analysis_shortcut_id_invalid")
        saved = handler.services.data_asset_store.upsert_item(
            binding.tenant_id,
            "analysis_shortcut",
            shortcut,
            updated_by=binding.user_id,
            lifecycle_status="active",
        )
        _audit(handler, binding, "sda", module, action, payload, target_id=str(saved.get("id") or ""))
        return {"item": saved, "operation_id": operation_id}
    raise ValueError("bridge_module_invalid")


def _binding(handler: Any) -> ReportIngressBinding:
    binding = resolve_report_ingress_binding(
        handler.headers.get("Authorization"),
        handler.services.bridge_auth_store,
    )
    requested_channel = str(handler.headers.get("X-Bridge-Channel") or "").strip().lower()
    if requested_channel and requested_channel != binding.channel:
        raise PermissionError("bridge_channel_binding_mismatch")
    return binding


def _ingest_sda_operation_evidence(
    handler: Any,
    binding: ReportIngressBinding,
    payload: dict[str, Any],
    operation_id: str,
) -> dict[str, Any]:
    forbidden = _FORBIDDEN_LEARNING_FIELDS.intersection(payload)
    if forbidden:
        raise ValueError(f"bridge_evidence_forbidden_fields:{','.join(sorted(forbidden))}")
    action = str(payload.get("action") or "").strip()[:160]
    summary = str(payload.get("summary") or payload.get("result_summary") or "").strip()[:10_000]
    logic_steps = [str(item).strip()[:500] for item in payload.get("logic_steps", []) if str(item).strip()][:40] if isinstance(payload.get("logic_steps"), list) else []
    if not action or not summary or not logic_steps:
        raise ValueError("bridge_operation_evidence_incomplete")
    evidence = {
        "channel": binding.channel,
        "binding_id": binding.binding_id,
        "system_id": "sda",
        "evidence_type": "configuration_operation",
        "run_id": operation_id,
        "action": action,
        "title": str(payload.get("title") or action).strip()[:500],
        "summary": summary,
        "methodology": str(payload.get("methodology") or "").strip()[:4_000],
        "logic_steps": logic_steps,
        "findings": [str(item).strip()[:500] for item in payload.get("findings", []) if str(item).strip()][:40] if isinstance(payload.get("findings"), list) else [],
        "assumptions": [str(item).strip()[:500] for item in payload.get("assumptions", []) if str(item).strip()][:20] if isinstance(payload.get("assumptions"), list) else [],
        "limitations": [str(item).strip()[:500] for item in payload.get("limitations", []) if str(item).strip()][:20] if isinstance(payload.get("limitations"), list) else [],
    }
    content_hash = hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    memory_id = f"{binding.channel}-operation-{hashlib.sha256((binding.binding_id + ':' + operation_id).encode('utf-8')).hexdigest()[:24]}"
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
            "accepted": True,
            "memory_candidate_id": memory_id,
            "skill_candidate_id": None,
            "review_required": True,
            "idempotent_replay": True,
        }
    event = handler.services.audit_store.write(
        binding.tenant_id,
        binding.user_id,
        f"{binding.channel}.bridge.operation_evidence.ingested",
        "bridge_configuration_evidence",
        operation_id,
        {"binding_id": binding.binding_id, "action": action, "content_hash": content_hash},
        handler.client_address[0] if handler.client_address else "",
    )
    handler.services.memory_service.create_candidate(
        binding.tenant_id,
        {
            "memory_id": memory_id,
            "memory_type": "analysis_case",
            "subject_type": "user",
            "subject_id": binding.user_id,
            "title": f"{binding.label} 配置操作材料：{evidence['title']}",
            "content": {"learning_origin": f"{binding.channel}.bridge", "evidence": evidence, "review_policy": "candidate_only"},
            "confidence": 0.55,
            "weight": 1.0,
            "evidence": {"evidence_type": "bridge_configuration_operation", "evidence_id": str(event.get("event_id") or operation_id), "evidence_hash": content_hash},
        },
        binding.user_id,
    )
    learning = handler.services.learning_service.observe_analysis_result(
        ExecutionContext(user_id=binding.user_id, tenant_id=binding.tenant_id),
        SimpleNamespace(
            task_id=f"{binding.channel}:configuration:{operation_id}",
            execution_id="",
            analysis_plan={
                "intent_rule_id": f"bridge_configuration:{action}",
                "dataset_id": "bridge-system:sda",
                "procedure_steps": logic_steps,
                "methodology": evidence["methodology"],
                "evidence_memory_ids": [memory_id],
            },
            review={"status": "passed", "publication_gate": "review_required"},
        ),
    )
    return {
        "accepted": True,
        "memory_candidate_id": memory_id,
        "skill_candidate_id": learning.get("candidate_id"),
        "review_required": True,
        "idempotent_replay": False,
    }


def _require_operation_id(value: str) -> None:
    if not value or len(value) > 200:
        raise ValueError("bridge_operation_id_required")


def _validate_client_input(module: str, payload: dict[str, Any]) -> None:
    reserved = _RESERVED_CLIENT_IDENTITY_FIELDS.intersection(payload)
    if reserved:
        raise ValueError(f"bridge_client_identity_override_forbidden:{','.join(sorted(reserved))}")
    if module == "learning":
        forbidden = _FORBIDDEN_LEARNING_FIELDS.intersection(payload)
        if forbidden:
            raise ValueError(f"bridge_evidence_forbidden_fields:{','.join(sorted(forbidden))}")


def _audit(
    handler: Any,
    binding: ReportIngressBinding,
    system_id: str,
    module: str,
    action: str,
    payload: dict[str, Any],
    *,
    target_id: str = "",
) -> None:
    handler.services.audit_store.write(
        binding.tenant_id,
        binding.user_id,
        f"bridge.hub.{module}.completed",
        "bridge_system",
        target_id or system_id,
        {
            "system_id": system_id,
            "module": module,
            "action": action,
            "operation_id": str(payload.get("operation_id") or payload.get("operationId") or "")[:200],
            "binding_id": binding.binding_id,
            "channel": binding.channel,
        },
        handler.client_address[0] if handler.client_address else "",
    )
