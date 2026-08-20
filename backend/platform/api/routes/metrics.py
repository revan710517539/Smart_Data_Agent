from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import MAX_UPLOAD_BODY_BYTES, first_query_value, send_route_exception
from backend.authz.models import RoleLevel
from backend.platform.metrics.excel_import import parse_metric_workbook


def handle_metric_dictionary_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_metric_permission(context, "read")
        roles = _context_roles(handler, context)
        list_visible = getattr(handler.services.metric_dictionary_store, "list_visible", None)
        if callable(list_visible):
            metrics = list_visible(
                context.tenant_id,
                {role.name for role in roles if role.tenant_id == context.tenant_id},
                context.user_id,
                # Data Assets is always scoped by the left-navigation
                # institution.  A super administrator may switch institutions,
                # but may not receive another institution's dictionary merely
                # because they have global administration permission.
                is_super_admin=False,
            )
            metrics = [
                item
                for item in metrics
                if str(item.get("tenantId") or context.tenant_id) == context.tenant_id
            ]
        else:
            list_all = getattr(handler.services.metric_dictionary_store, "list_all", None)
            metrics = list_all() if callable(list_all) else handler.services.metric_dictionary_store.list(context.tenant_id)
            metrics = [
                metric
                for metric in metrics
                if _metric_visible_to_context(handler, context, metric)
            ]
        handler._send_json({"tenant_id": context.tenant_id, "metrics": metrics, "count": len(metrics)})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_metric_dictionary_replace(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        metrics = payload.get("metrics")
        if not isinstance(metrics, list) or any(not isinstance(metric, dict) for metric in metrics):
            raise ValueError("metrics must be a list of objects.")
        handler._require_metric_permission(context, "create")
        saved = handler.services.metric_dictionary_store.replace_all(
            context.tenant_id,
            metrics,
            updated_by=context.user_id,
        )
        handler._write_audit(context, "metric.dictionary.replace", "metric_dictionary", "bulk", {"count": len(saved)})
        handler._send_json({"tenant_id": context.tenant_id, "metrics": saved, "count": len(saved)})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_metric_dictionary_upsert(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        metric = payload.get("metric")
        if not isinstance(metric, dict):
            raise ValueError("metric must be an object.")
        metric = _normalize_metric_visibility(handler, context, metric)
        metric_id = str(metric.get("metricId") or "").strip()
        getter = getattr(handler.services.metric_dictionary_store, "get", None)
        existing_metric = getter(context.tenant_id, metric_id) if callable(getter) and metric_id else None
        if existing_metric:
            _require_metric_owner_or_permission(handler, context, existing_metric, "update")
        else:
            handler._require_metric_permission(context, "create")
        saved = handler.services.metric_dictionary_store.upsert(
            context.tenant_id,
            metric,
            updated_by=context.user_id,
        )
        handler._write_audit(context, "metric.dictionary.upsert", "metric", str(saved.get("metricId") or ""))
        handler._send_json({"tenant_id": context.tenant_id, "metric": saved})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_metric_dictionary_import(handler: Any) -> None:
    try:
        payload = handler._read_json(MAX_UPLOAD_BODY_BYTES)
        context = handler._request_context(payload=payload)
        handler._require_metric_permission(context, "create")
        file_name = str(payload.get("file_name") or "").strip()
        if not file_name.lower().endswith(".xlsx"):
            raise ValueError("请上传 .xlsx 格式的指标文件。")
        rows = parse_metric_workbook(str(payload.get("file_content_base64") or ""))
        existing = handler.services.metric_dictionary_store.list(context.tenant_id)
        existing_names = {str(metric.get("metricName") or "").strip() for metric in existing}
        rows, duplicate_names, skipped_names, skipped_count = _prepare_metric_import(rows, existing_names)
        if duplicate_names:
            raise ValueError(f"metric_dictionary_duplicate_names:{'、'.join(duplicate_names[:20])}")
        used_ids = {str(metric.get("metricId") or "").strip() for metric in existing}
        next_number = _next_metric_number(used_ids)
        created: list[dict[str, Any]] = []
        for metric in rows:
            name = metric["metricName"].strip()
            while f"M{next_number:05d}" in used_ids:
                next_number += 1
            normalized = _normalize_metric_visibility(handler, context, {**metric, "metricId": f"M{next_number:05d}"})
            created.append(normalized)
            used_ids.add(normalized["metricId"])
            next_number += 1
        store = handler.services.metric_dictionary_store
        upsert_many = getattr(store, "upsert_many", None)
        if created and callable(upsert_many):
            upsert_many(context.tenant_id, created, updated_by=context.user_id)
        else:
            for metric in created:
                store.upsert(context.tenant_id, metric, updated_by=context.user_id)
        handler._write_audit(
            context,
            "metric.dictionary.import",
            "metric_dictionary",
            "xlsx",
            {"file_name": file_name, "created": len(created), "skipped": skipped_count},
        )
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                "created": created,
                "created_count": len(created),
                "skipped_count": skipped_count,
                "skipped_names": skipped_names,
            }
        )
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_metric_dictionary_delete(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        metric_id = first_query_value(params, "metric_id")
        if not metric_id:
            raise ValueError("metric_id is required.")
        getter = getattr(handler.services.metric_dictionary_store, "get", None)
        existing_metric = getter(context.tenant_id, metric_id) if callable(getter) else None
        if existing_metric:
            _require_metric_owner_or_permission(handler, context, existing_metric, "delete")
        else:
            handler._require_metric_permission(context, "delete")
        deleted = handler.services.metric_dictionary_store.delete(context.tenant_id, metric_id)
        handler._write_audit(context, "metric.dictionary.delete", "metric", metric_id, {"deleted": deleted})
        handler._send_json({"tenant_id": context.tenant_id, "metric_id": metric_id, "deleted": deleted})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_metric_versions_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_metric_permission(context, "read")
        metric_key = first_query_value(params, "metric_key")
        versions = handler.services.metric_version_service.list(context.tenant_id, metric_key)
        handler._send_json({"metric_key": metric_key, "versions": versions, "count": len(versions)})
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_metric_version_diff_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_metric_permission(context, "read")
        result = handler.services.metric_version_service.diff(
            context.tenant_id,
            first_query_value(params, "metric_key"),
            first_query_value(params, "left_version_id"),
            first_query_value(params, "right_version_id"),
        )
        handler._send_json(result)
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_metric_version_impact_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_metric_permission(context, "read")
        handler._send_json(handler.services.metric_version_service.impact(context.tenant_id, first_query_value(params, "metric_key")))
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_metric_version_create(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_metric_permission(context, "update")
        definition = payload.get("definition")
        if not isinstance(definition, dict):
            raise ValueError("metric_version_definition_required")
        version = handler.services.metric_version_service.create(
            context.tenant_id,
            str(payload.get("metric_key") or ""),
            context.user_id,
            definition,
            str(payload.get("parent_version_id") or "") or None,
        )
        handler._write_audit(context, "metric.version.create", "metric_version", version["version_id"], {"metric_key": version["metric_key"], "version_no": version["version_no"]})
        handler._send_json({"version": version})
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_metric_version_transition(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        action = str(payload.get("action") or "")
        handler._require_metric_permission(context, "publish" if action == "publish" else "update")
        version = handler.services.metric_version_service.review(
            context.tenant_id,
            str(payload.get("version_id") or ""),
            context.user_id,
            action,
            str(payload.get("comment") or ""),
        )
        handler._write_audit(context, f"metric.version.{action}", "metric_version", version["version_id"], {"status": version["status"]})
        handler._send_json({"version": version})
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_metric_version_rollback(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_metric_permission(context, "update")
        version = handler.services.metric_version_service.rollback(
            context.tenant_id,
            str(payload.get("metric_key") or ""),
            str(payload.get("version_id") or ""),
            context.user_id,
        )
        handler._write_audit(context, "metric.version.rollback", "metric_version", version["version_id"], {"rollback_of": version["rollback_of"]})
        handler._send_json({"version": version})
    except Exception as exc:
        send_route_exception(handler, exc)


def _require_metric_owner_or_permission(handler: Any, context: Any, metric: dict[str, Any], action: str) -> None:
    created_by = str(metric.get("createdBy") or metric.get("created_by") or "").strip()
    if created_by and created_by == context.user_id:
        return
    handler._require_metric_permission(context, action)


def _metric_visible_to_context(handler: Any, context: Any, metric: dict[str, Any]) -> bool:
    metric_tenant_id = str(metric.get("tenantId") or context.tenant_id)
    created_by = str(metric.get("createdBy") or "").strip()
    if created_by and created_by == context.user_id and metric_tenant_id == context.tenant_id:
        return True
    roles = _context_roles(handler, context)
    tenant_label = context.tenant_id.removeprefix("tenant:")
    visible_institutions = _string_list(metric.get("visibleInstitutions"))
    visible_roles = _string_list(metric.get("visibleRoles"))
    role_names = {role.name for role in roles if role.tenant_id == context.tenant_id}
    institution_visible = tenant_label in visible_institutions or "全部机构" in visible_institutions
    role_visible = bool(role_names & set(visible_roles))

    if visible_institutions and visible_roles:
        return institution_visible and role_visible
    if visible_institutions:
        return institution_visible
    if visible_roles:
        return metric_tenant_id == context.tenant_id and role_visible
    return False


def _normalize_metric_visibility(handler: Any, context: Any, metric: dict[str, Any]) -> dict[str, Any]:
    roles = _context_roles(handler, context)
    if any(role.level == RoleLevel.SUPER_ADMIN for role in roles):
        return metric
    is_tenant_admin = any(role.level == RoleLevel.TENANT_ADMIN and role.tenant_id == context.tenant_id for role in roles)
    if is_tenant_admin:
        visible_roles = _string_list(metric.get("visibleRoles"))
        return {
            **metric,
            "visibleInstitutions": [context.tenant_id.removeprefix("tenant:")] if visible_roles else [],
            "visibleRoles": visible_roles,
        }
    return {**metric, "visibleInstitutions": [], "visibleRoles": []}


def _context_roles(handler: Any, context: Any):
    assignments = handler.services.permission_broker.enforcer.repository.get_user_roles(
        context.user_id,
        context.tenant_id,
    )
    roles = []
    for assignment in assignments:
        role = handler.services.permission_broker.enforcer.repository.get_role(assignment.role_id)
        if role:
            roles.append(role)
    return roles


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _next_metric_number(metric_ids: set[str]) -> int:
    values = [int(metric_id[1:]) for metric_id in metric_ids if metric_id.startswith("M") and metric_id[1:].isdigit()]
    return max(values, default=-1) + 1


def _prepare_metric_import(
    rows: list[dict[str, Any]],
    existing_names: set[str],
) -> tuple[list[dict[str, Any]], list[str], list[str], int]:
    """Collapse exact workbook duplicates without weakening name conflicts.

    A repeated row with the same normalized payload carries no second metric
    definition, so importing it once is lossless.  The same name with a
    different payload, or any name already present in the tenant dictionary,
    still blocks the entire batch before the first write.
    """

    accepted: list[dict[str, Any]] = []
    seen: dict[str, tuple[tuple[str, str], ...]] = {}
    conflicts: list[str] = []
    skipped_names: list[str] = []
    skipped_count = 0
    for metric in rows:
        name = str(metric.get("metricName") or "").strip()
        signature = tuple(sorted((str(key), str(value or "").strip()) for key, value in metric.items()))
        if name in existing_names:
            conflicts.append(name)
        previous = seen.get(name)
        if previous is None:
            seen[name] = signature
            accepted.append(metric)
            continue
        if previous == signature:
            skipped_count += 1
            skipped_names.append(name)
            continue
        conflicts.append(name)
    conflict_names = set(conflicts)
    ordered_conflicts = list(dict.fromkeys(
        str(metric.get("metricName") or "").strip()
        for metric in rows
        if str(metric.get("metricName") or "").strip() in conflict_names
    ))
    return (
        accepted,
        ordered_conflicts,
        list(dict.fromkeys(skipped_names)),
        skipped_count,
    )


def _duplicate_metric_names(rows: list[dict[str, Any]], existing_names: set[str]) -> list[str]:
    return _prepare_metric_import(rows, existing_names)[1]
