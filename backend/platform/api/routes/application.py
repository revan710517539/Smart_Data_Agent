from __future__ import annotations

from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import first_query_value, send_route_exception
from backend.platform.api.routes.assets import (
    MULTI_INSTITUTION_PAGE_DATA_SCOPE,
    _page_data_scope,
    _visualization_topic_tables,
)
from backend.platform.application.store import ApplicationActionUnavailable, UnsupportedApplicationAction


def handle_application_module_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        module_key = first_query_value(params, "module_key")
        if not module_key:
            raise ValueError("module_key is required.")
        handler._require_application_permission(context, "read")
        module = handler.services.application_store.get_module(context.tenant_id, module_key, actor_user_id=context.user_id)
        handler._send_json(module)
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_application_action_post(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        module_key = str(payload.get("module_key") or "").strip()
        action = str(payload.get("action") or "").strip()
        action_payload = payload.get("payload")
        if not module_key:
            raise ValueError("module_key is required.")
        if not action:
            raise ValueError("action is required.")
        if action_payload is not None and not isinstance(action_payload, dict):
            raise ValueError("payload must be an object.")
        if module_key == "agent_workspace" and action in {"create_todo", "update_todo", "create_task", "update_task"}:
            action_payload = dict(action_payload or {})
            if action in {"create_todo", "create_task"}:
                action_payload["ownerUserId"] = context.user_id
            if action == "create_todo":
                profile = handler.services.access_service.user_store.get_profile(context.user_id)
                action_payload["actorDisplayName"] = str(getattr(profile, "name", "") or "当前用户").strip()
            if action in {"create_task", "update_task"} and isinstance(action_payload.get("task"), dict):
                task_payload = dict(action_payload["task"])
                if action == "create_task":
                    task_payload["ownerUserId"] = context.user_id
                    task_payload["createdBy"] = context.user_id
                action_payload["task"] = task_payload
        if action == "set_page_data_layout" and module_key in {"dashboard", "weekly_report", "institution_supervision"}:
            action_payload = dict(action_payload or {})
            if module_key in {"dashboard", "institution_supervision"} and not handler.services.permission_broker.enforcer.has_super_admin_role(
                context.user_id, context.tenant_id,
            ):
                raise PermissionError("global_super_admin_required_for_page_layout")
            requested_ids = action_payload.get("assetIds")
            if not isinstance(requested_ids, list):
                raise ValueError("page_data_layout_invalid")
            published = handler.services.data_asset_store.list_published_bundle(context.tenant_id)
            allowed_ids = {
                str(item.get("id") or "")
                for item in published.get("page_data", [])
                if module_key in item.get("targetPages", [])
                and (
                    (_page_data_scope(item) == MULTI_INSTITUTION_PAGE_DATA_SCOPE)
                    if module_key == "dashboard"
                    else (_page_data_scope(item) != MULTI_INSTITUTION_PAGE_DATA_SCOPE)
                )
            }
            normalized_ids = [str(asset_id or "").strip() for asset_id in requested_ids]
            if len(normalized_ids) != len(set(normalized_ids)) or any(asset_id not in allowed_ids for asset_id in normalized_ids):
                raise PermissionError("page_data_layout_asset_unavailable")
            action_payload["assetIds"] = normalized_ids
        if module_key == "self_analysis" and action == "upsert_visual_report":
            action_payload = _bind_visual_report_payload(handler, context, action_payload or {})
        handler._require_application_permission(context, "execute")
        result = handler.services.application_store.run_action(
            context.tenant_id,
            module_key,
            action,
            payload=action_payload or {},
            actor_user_id=context.user_id,
        )
        handler._write_audit(
            context,
            f"application.{action}",
            "application_module",
            target_id=module_key,
            detail={"payload": action_payload or {}, "result": result.get("result", {})},
        )
        handler._send_json(result)
    except UnsupportedApplicationAction as exc:
        handler._send_json(
            {"error": "unsupported_application_action", "message": "The application action is not registered."},
            HTTPStatus.BAD_REQUEST,
        )
    except ApplicationActionUnavailable as exc:
        handler._send_json(
            {"error": "application_action_not_implemented", "message": "The application action has no production handler."},
            HTTPStatus.NOT_IMPLEMENTED,
        )
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def _bind_visual_report_payload(handler: Any, context: Any, payload: dict[str, Any]) -> dict[str, Any]:
    report = payload.get("report")
    if not isinstance(report, dict):
        raise ValueError("visual_report_invalid")
    cards = report.get("cards")
    if not isinstance(cards, list) or len(cards) > 40:
        raise ValueError("visual_report_cards_invalid")

    requested_topic_ids = {
        str(card.get("dataset", {}).get("id") or "").strip()
        for card in cards
        if isinstance(card, dict)
        and isinstance(card.get("dataset"), dict)
        and str(card["dataset"].get("kind") or "").strip() == "topic"
        and str(card["dataset"].get("id") or "").strip()
    }
    visualization_topics = {
        str(item.get("id") or ""): item
        for item in _visualization_topic_tables(handler, context.tenant_id, requested_topic_ids)
        if isinstance(item, dict) and str(item.get("id") or "")
    }
    published_reader = getattr(handler.services.data_asset_store, "list_published_bundle", None)
    published_bundle = published_reader(context.tenant_id) if callable(published_reader) else {}
    multi_page_data = {
        str(item.get("id") or ""): item
        for item in published_bundle.get("page_data", [])
        if isinstance(item, dict)
        and str(item.get("id") or "")
        and str(item.get("institutionScope") or "") == "multi_institution"
    }
    raw_tables: dict[str, dict[str, Any]] = {}
    raw_tables_by_source_key: dict[str, dict[str, Any]] = {}
    csv_source = getattr(handler.services.data_acquisition_service, "csv_source", None)
    if csv_source is not None:
        catalog = csv_source.for_tenant(context.tenant_id)
        raw_tables = {
            str(item.get("id") or ""): item
            for item in catalog.table_assets()
            if isinstance(item, dict) and str(item.get("id") or "")
        }
        raw_tables_by_source_key = {
            str(item.get("sourceKey") or ""): item
            for item in raw_tables.values()
            if str(item.get("sourceKey") or "")
        }

    bound_cards = []
    for raw_card in cards:
        if not isinstance(raw_card, dict) or not isinstance(raw_card.get("dataset"), dict):
            raise ValueError("visual_report_dataset_invalid")
        requested_dataset = raw_card["dataset"]
        dataset_id = str(requested_dataset.get("id") or "").strip()
        dataset_kind = str(requested_dataset.get("kind") or "").strip()
        requested_source_key = str(requested_dataset.get("sourceKey") or "").strip()
        if dataset_kind == "raw":
            source = raw_tables_by_source_key.get(requested_source_key) if requested_source_key else raw_tables.get(dataset_id)
        elif dataset_kind == "page_data":
            source = multi_page_data.get(dataset_id)
        else:
            source = visualization_topics.get(dataset_id) if dataset_kind == "topic" else None
        if source is None:
            raise PermissionError("visual_report_dataset_unavailable")
        requested_schema = str(requested_dataset.get("schemaFingerprint") or "").strip()
        current_schema = str(source.get("schemaFingerprint") or source.get("schemaVersion") or "").strip()
        if requested_schema and current_schema and requested_schema != current_schema:
            raise PermissionError("visual_report_dataset_schema_changed")
        requested_relationship = str(requested_dataset.get("relationshipGroupId") or "").strip()
        current_relationship = str(source.get("relationshipGroupId") or "").strip()
        if dataset_kind == "page_data" and requested_relationship and requested_relationship != current_relationship:
            raise PermissionError("visual_report_dataset_relationship_changed")
        fields_key = "sourceFields" if dataset_kind == "page_data" else "fields"
        fields = source.get(fields_key) if isinstance(source.get(fields_key), list) else []
        if dataset_kind == "raw":
            name = str(source.get("tableNameCn") or source.get("tableNameEn") or dataset_id)
            code = str(source.get("tableNameEn") or dataset_id)
        elif dataset_kind == "topic":
            name = str(source.get("name") or source.get("code") or dataset_id)
            code = str(source.get("code") or dataset_id)
        else:
            name = str(source.get("name") or source.get("sourceTableName") or "多机构页面数据")
            code = f"page_data_{dataset_id}"
        bound_cards.append({
            **raw_card,
            "dataset": {
                "id": str(source.get("id") or dataset_id),
                "kind": dataset_kind,
                "name": name,
                "code": code,
                "sourceKey": str(source.get("sourceKey") or ""),
                "schemaFingerprint": current_schema,
                "relationshipGroupId": current_relationship,
                "fields": fields,
            },
        })
    return {**payload, "report": {**report, "cards": bound_cards}}
