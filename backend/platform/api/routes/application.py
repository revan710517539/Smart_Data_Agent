from __future__ import annotations

import re
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import first_query_value, send_route_exception
from backend.platform.api.routes.assets import (
    CUSTOMER_SEGMENT_PAGE_DATA_SCOPE,
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
        _attach_registration_todos(handler, context, module_key, module)
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
        if action == "set_page_data_layout" and module_key in {"dashboard", "weekly_report", "institution_supervision", "customer_segment_analysis"}:
            action_payload = dict(action_payload or {})
            if not handler.services.permission_broker.enforcer.has_super_admin_role(
                context.user_id, context.tenant_id,
            ):
                raise PermissionError("global_super_admin_required_for_page_layout")
            requested_ids = action_payload.get("assetIds")
            if not isinstance(requested_ids, list):
                raise ValueError("page_data_layout_invalid")
            published = handler.services.data_asset_store.list_published_bundle(context.tenant_id)
            published_page_data = [item for item in published.get("page_data", []) if isinstance(item, dict)]
            allowed_ids = {
                str(item.get("id") or "")
                for item in published_page_data
                if module_key in item.get("targetPages", [])
                and (
                    (_page_data_scope(item) == MULTI_INSTITUTION_PAGE_DATA_SCOPE)
                    if module_key == "dashboard"
                    else (_page_data_scope(item) == CUSTOMER_SEGMENT_PAGE_DATA_SCOPE)
                    if module_key == "customer_segment_analysis"
                    else (_page_data_scope(item) not in {MULTI_INSTITUTION_PAGE_DATA_SCOPE, CUSTOMER_SEGMENT_PAGE_DATA_SCOPE})
                )
            }
            normalized_ids = [str(asset_id or "").strip() for asset_id in requested_ids]
            if len(normalized_ids) != len(set(normalized_ids)) or any(asset_id not in allowed_ids for asset_id in normalized_ids):
                raise PermissionError("page_data_layout_asset_unavailable")
            cards = action_payload.get("cards")
            if cards is not None and not isinstance(cards, list):
                raise ValueError("page_data_cards_invalid")
            for card in cards or []:
                if not isinstance(card, dict):
                    raise ValueError("page_data_cards_invalid")
                source_id = str(card.get("sourceAssetId") or "").strip()
                if source_id not in allowed_ids or source_id not in normalized_ids:
                    raise PermissionError("page_data_card_asset_unavailable")
            public_filters = action_payload.get("publicFilters")
            if public_filters is not None and not isinstance(public_filters, list):
                raise ValueError("page_data_public_filters_invalid")
            allowed_by_id = {str(item.get("id") or ""): item for item in published_page_data if str(item.get("id") or "") in allowed_ids}
            for group in public_filters or []:
                if not isinstance(group, dict):
                    raise ValueError("page_data_public_filters_invalid")
                dataset_ids = [str(item or "").strip() for item in group.get("datasetIds") or []]
                fields = [str(item or "").strip() for item in group.get("fields") or []]
                if not dataset_ids or any(dataset_id not in normalized_ids or dataset_id not in allowed_by_id for dataset_id in dataset_ids):
                    raise PermissionError("page_data_public_filter_asset_unavailable")
                common_fields = None
                for dataset_id in dataset_ids:
                    field_codes = {
                        str(field.get("fieldNameEn") or "").strip()
                        for field in allowed_by_id[dataset_id].get("sourceFields") or []
                        if isinstance(field, dict) and str(field.get("fieldNameEn") or "").strip()
                    }
                    common_fields = field_codes if common_fields is None else common_fields & field_codes
                if not fields or any(field not in (common_fields or set()) for field in fields):
                    raise ValueError("page_data_public_filter_field_unavailable")
            action_payload["assetIds"] = normalized_ids
        if action == "set_page_visual_layout" and module_key in {"customer_insight", "competition_analysis"}:
            action_payload = dict(action_payload or {})
            if not handler.services.permission_broker.enforcer.has_super_admin_role(
                context.user_id, context.tenant_id,
            ):
                raise PermissionError("global_super_admin_required_for_page_layout")
            if not isinstance(action_payload.get("items"), list):
                raise ValueError("page_visual_layout_invalid")
        if action == "set_page_data_notes" and module_key in {"dashboard", "weekly_report", "institution_supervision", "customer_segment_analysis"}:
            action_payload = dict(action_payload or {})
            published = handler.services.data_asset_store.list_published_bundle(context.tenant_id)
            allowed_ids = {
                str(item.get("id") or "")
                for item in published.get("page_data", [])
                if module_key in item.get("targetPages", [])
                and (
                    (_page_data_scope(item) == MULTI_INSTITUTION_PAGE_DATA_SCOPE)
                    if module_key == "dashboard"
                    else (_page_data_scope(item) == CUSTOMER_SEGMENT_PAGE_DATA_SCOPE)
                    if module_key == "customer_segment_analysis"
                    else (_page_data_scope(item) not in {MULTI_INSTITUTION_PAGE_DATA_SCOPE, CUSTOMER_SEGMENT_PAGE_DATA_SCOPE})
                )
            }
            notes = action_payload.get("notes")
            if notes is not None and not isinstance(notes, list):
                raise ValueError("page_data_notes_invalid")
            for note in notes or []:
                if not isinstance(note, dict):
                    raise ValueError("page_data_notes_invalid")
                source_id = str(note.get("sourceAssetId") or "").strip()
                if source_id and source_id not in allowed_ids:
                    raise PermissionError("page_data_note_asset_unavailable")
            existing_state = handler.services.application_store.get_module(
                context.tenant_id, module_key, actor_user_id=context.user_id
            ).get("state") or {}
            action_payload["notes"] = _merge_page_data_notes(
                existing_state.get("pageDataNotes") or [],
                notes or [],
                context.user_id,
                handler.services.permission_broker.enforcer.has_super_admin_role(context.user_id, context.tenant_id),
            )
        if module_key == "self_analysis" and action == "upsert_visual_report":
            action_payload = _prepare_visual_report_upsert_payload(handler, context, action_payload or {})
        if module_key == "self_analysis" and action == "delete_visual_report":
            action_payload = dict(action_payload or {})
            _authorize_visual_report_delete(handler, context, str(action_payload.get("reportId") or action_payload.get("id") or ""))
        handler._require_application_permission(context, "execute")
        if module_key == "agent_workspace" and action in {"approve_registration", "reject_registration"}:
            reviewed = _review_registration(handler, context, action, action_payload or {})
            module = handler.services.application_store.get_module(
                context.tenant_id, module_key, actor_user_id=context.user_id
            )
            _attach_registration_todos(handler, context, module_key, module)
            handler._write_audit(
                context,
                f"application.{action}",
                "application_module",
                target_id=module_key,
                detail={"payload": action_payload or {}, "result": reviewed},
            )
            handler._send_json(
                {
                    "tenant_id": context.tenant_id,
                    "module_key": module_key,
                    "action": {
                        "id": f"act_{action}",
                        "moduleKey": module_key,
                        "action": action,
                        "status": "completed",
                        "payload": action_payload or {},
                        "result": reviewed,
                        "createdBy": context.user_id,
                        "createdAt": module.get("updated_at") or "",
                    },
                    "result": reviewed,
                    "module": module,
                }
            )
            return
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


def _review_registration(handler: Any, context: Any, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not handler.services.access_service._is_super_admin(context.user_id):
        raise PermissionError("global_super_admin_required")
    request_id = str(
        payload.get("requestId")
        or payload.get("registrationRequestId")
        or payload.get("todoId")
        or payload.get("id")
        or ""
    ).strip()
    reviewed = handler.services.access_service.review_registration(
        context.to_execution_context(),
        request_id,
        approved=action == "approve_registration",
    )
    return reviewed


def _attach_registration_todos(handler: Any, context: Any, module_key: str, module: dict[str, Any]) -> None:
    if module_key != "agent_workspace" or not handler.services.access_service._is_super_admin(context.user_id):
        return
    state = module.get("state") if isinstance(module.get("state"), dict) else {}
    todos = [item for item in (state.get("todos") or []) if isinstance(item, dict)]
    existing = {str(item.get("id") or "") for item in todos}
    for todo in handler.services.access_service.registration_todos():
        todo_id = str(todo.get("id") or "")
        if todo_id and todo_id not in existing:
            todos.insert(0, todo)
    state["todos"] = todos
    module["state"] = state


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
    dataset_id_aliases: dict[str, str] = {}
    for raw_card in cards:
        if not isinstance(raw_card, dict) or not isinstance(raw_card.get("dataset"), dict):
            raise ValueError("visual_report_dataset_invalid")
        requested_dataset = raw_card["dataset"]
        dataset_id = str(requested_dataset.get("id") or "").strip()
        dataset_kind = str(requested_dataset.get("kind") or "").strip()
        if dataset_kind == "raw":
            source = _resolve_visual_report_raw_source(requested_dataset, raw_tables, raw_tables_by_source_key)
        elif dataset_kind == "page_data":
            source = multi_page_data.get(dataset_id)
        else:
            source = visualization_topics.get(dataset_id) if dataset_kind == "topic" else None
        if source is None:
            raise PermissionError("visual_report_dataset_unavailable")
        requested_schema = str(requested_dataset.get("schemaFingerprint") or "").strip()
        current_schema = str(source.get("schemaFingerprint") or source.get("schemaVersion") or "").strip()
        if requested_schema and current_schema and requested_schema != current_schema:
            raw_fields_compatible = dataset_kind == "raw" and _visual_report_fields_remain_compatible(
                requested_dataset.get("fields"),
                source.get("fields"),
            )
            if not raw_fields_compatible:
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
        bound_dataset_id = str(source.get("id") or dataset_id)
        dataset_id_aliases[f"{dataset_kind}:{dataset_id}"] = f"{dataset_kind}:{bound_dataset_id}"
        bound_cards.append({
            **raw_card,
            "dataset": {
                "id": bound_dataset_id,
                "kind": dataset_kind,
                "name": name,
                "code": code,
                "sourceKey": str(source.get("sourceKey") or ""),
                "schemaFingerprint": current_schema,
                "relationshipGroupId": current_relationship,
                "fields": fields,
            },
        })
    public_filters = []
    for raw_group in report.get("publicFilters") if isinstance(report.get("publicFilters"), list) else []:
        if not isinstance(raw_group, dict):
            public_filters.append(raw_group)
            continue
        rebound_ids = []
        for raw_dataset_id in raw_group.get("datasetIds") if isinstance(raw_group.get("datasetIds"), list) else []:
            rebound_id = dataset_id_aliases.get(str(raw_dataset_id), str(raw_dataset_id))
            if rebound_id not in rebound_ids:
                rebound_ids.append(rebound_id)
        public_filters.append({**raw_group, "datasetIds": rebound_ids})
    return {**payload, "report": {**report, "cards": bound_cards, "publicFilters": public_filters}}


def _resolve_visual_report_raw_source(
    requested_dataset: dict[str, Any],
    raw_tables: dict[str, dict[str, Any]],
    raw_tables_by_source_key: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    requested_source_key = str(requested_dataset.get("sourceKey") or "").strip()
    if requested_source_key and requested_source_key in raw_tables_by_source_key:
        return raw_tables_by_source_key[requested_source_key]
    dataset_id = str(requested_dataset.get("id") or "").strip()
    if dataset_id and dataset_id in raw_tables:
        return raw_tables[dataset_id]
    requested_titles = {
        _visual_report_logical_title(str(value or ""))
        for value in (requested_dataset.get("name"), requested_dataset.get("code"))
        if _visual_report_logical_title_candidate(str(value or ""))
    }
    requested_titles.discard("")
    if not requested_titles:
        return None
    matches = [
        item
        for item in raw_tables.values()
        if requested_titles.intersection(
            {
                _visual_report_logical_title(str(item.get(key) or ""))
                for key in ("tableNameCn", "tableNameEn", "fileName", "relativePath")
            }
        )
    ]
    return matches[0] if len(matches) == 1 else None


def _visual_report_fields_remain_compatible(saved_fields: Any, current_fields: Any) -> bool:
    """Allow a refreshed delivery when its stored physical columns still match.

    Raw-table fingerprints also change when field governance adds semantic roles,
    primary-key flags, or specializes a decimal column as a rate.  Those metadata
    improvements must not invalidate an existing chart.  A missing/renamed field
    or a change between numeric, temporal, boolean and text families still fails
    closed.
    """

    saved = {
        str(field.get("fieldNameEn") or "").strip(): field
        for field in saved_fields if isinstance(field, dict) and str(field.get("fieldNameEn") or "").strip()
    } if isinstance(saved_fields, list) else {}
    current = {
        str(field.get("fieldNameEn") or "").strip(): field
        for field in current_fields if isinstance(field, dict) and str(field.get("fieldNameEn") or "").strip()
    } if isinstance(current_fields, list) else {}
    if not saved:
        return False
    return all(
        code in current
        and _visual_report_field_label(field) == _visual_report_field_label(current[code])
        and _visual_report_field_type_family(field.get("type"))
        == _visual_report_field_type_family(current[code].get("type"))
        for code, field in saved.items()
    )


def _visual_report_field_label(field: dict[str, Any]) -> str:
    return str(field.get("fieldNameCn") or field.get("fieldNameEn") or "").strip()


def _visual_report_field_type_family(value: Any) -> str:
    field_type = str(value or "string").strip().casefold()
    if re.search(r"int|decimal|number|numeric|float|double|real|rate|percent|currency|money", field_type):
        return "number"
    if re.search(r"date|time|timestamp", field_type):
        return "temporal"
    if re.search(r"bool", field_type):
        return "boolean"
    return "text"


def _visual_report_logical_title_candidate(value: str) -> bool:
    title = _visual_report_logical_title(value)
    return bool(title) and re.fullmatch(r"csv[0-9a-f]{8,}", title) is None


def _visual_report_logical_title(value: str) -> str:
    stem = re.sub(r"\.csv$", "", str(value or "").strip(), flags=re.I)
    without_prefix = re.sub(r"^\d{8}(?:_\d{6})?_", "", stem)
    without_suffix = re.sub(r"_\d{4}-\d{2}-\d{2}(?:_历史数据)?$", "", without_prefix)
    title = without_suffix.rsplit("/", 1)[-1]
    return re.sub(r"[\s_\-./]+", "", title).casefold()


def _merge_page_data_notes(
    existing: list[Any],
    requested: list[Any],
    actor_user_id: str,
    can_override: bool,
) -> list[dict[str, Any]]:
    actor = str(actor_user_id or "").strip()
    existing_notes = [item for item in existing if isinstance(item, dict) and str(item.get("id") or "").strip()]
    existing_by_id = {str(item.get("id") or ""): item for item in existing_notes}
    requested_ids: set[str] = set()
    merged: list[dict[str, Any]] = []
    for item in requested:
        if not isinstance(item, dict):
            continue
        note_id = str(item.get("id") or "").strip()
        if not note_id or note_id in requested_ids:
            continue
        requested_ids.add(note_id)
        previous = existing_by_id.get(note_id)
        owner = str((previous or item).get("createdByUserId") or "").strip()
        if previous and owner and owner != actor and not can_override:
            merged.append(dict(previous))
            continue
        merged.append({**item, "createdByUserId": owner or actor})
    for previous in existing_notes:
        note_id = str(previous.get("id") or "").strip()
        if note_id in requested_ids:
            continue
        owner = str(previous.get("createdByUserId") or "").strip()
        if owner == actor or can_override:
            continue
        merged.append(dict(previous))
    return merged


def _visual_reports_from_module(handler: Any, context: Any) -> list[dict[str, Any]]:
    module = handler.services.application_store.get_module(
        context.tenant_id, "self_analysis", actor_user_id=context.user_id
    )
    reports = (module.get("state") or {}).get("visualReports") or []
    return [item for item in reports if isinstance(item, dict)]


def _prepare_visual_report_upsert_payload(handler: Any, context: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Skip dataset rebinding when the only change is removing a report from 经营周报.

    Weekly unpublish must still work after the original raw/topic/page dataset has
    rotated or been unbound; otherwise edit-mode delete appears to do nothing.
    """

    incoming = dict(payload or {})
    report = incoming.get("report") if isinstance(incoming.get("report"), dict) else {}
    report_id = str(report.get("id") or "").strip()
    existing = next(
        (item for item in _visual_reports_from_module(handler, context) if str(item.get("id") or "") == report_id),
        None,
    )
    requested_destinations = (
        [str(item) for item in report.get("destinations") if str(item)]
        if isinstance(report.get("destinations"), list)
        else []
    )
    existing_destinations = [
        str(item) for item in (existing or {}).get("destinations") or [] if str(item)
    ]
    removing_weekly = bool(existing) and "weekly" in existing_destinations and "weekly" not in requested_destinations
    if removing_weekly:
        authorized = _authorize_visual_report_upsert(handler, context, incoming)
        destinations = [
            str(item)
            for item in ((authorized.get("report") or {}).get("destinations") or requested_destinations)
            if str(item) and str(item) != "weekly"
        ]
        return {**authorized, "report": {**existing, "destinations": destinations}}
    return _authorize_visual_report_upsert(
        handler, context, _bind_visual_report_payload(handler, context, incoming)
    )


def _authorize_visual_report_upsert(handler: Any, context: Any, payload: dict[str, Any]) -> dict[str, Any]:
    report = payload.get("report")
    if not isinstance(report, dict):
        return payload
    report_id = str(report.get("id") or "").strip()
    existing = next((item for item in _visual_reports_from_module(handler, context) if str(item.get("id") or "") == report_id), None)
    if existing is None:
        return payload
    owner = str(existing.get("ownerUserId") or "").strip()
    if owner in {"", context.user_id}:
        return payload
    requested_destinations = report.get("destinations") if isinstance(report.get("destinations"), list) else []
    existing_destinations = existing.get("destinations") if isinstance(existing.get("destinations"), list) else []
    removing_weekly = "weekly" in existing_destinations and "weekly" not in [str(item) for item in requested_destinations]
    if removing_weekly and handler.services.permission_broker.enforcer.can_manage_shared_visual(
        context.user_id, context.tenant_id, owner
    ):
        return {**payload, "report": {**existing, "destinations": [str(item) for item in requested_destinations if str(item)]}}
    raise PermissionError("visual_report_owner_required")


def _authorize_visual_report_delete(handler: Any, context: Any, report_id: str) -> None:
    existing = next((item for item in _visual_reports_from_module(handler, context) if str(item.get("id") or "") == report_id), None)
    if existing is None:
        return
    owner = str(existing.get("ownerUserId") or "").strip()
    if owner in {"", context.user_id}:
        return
    raise PermissionError("visual_report_owner_required")
