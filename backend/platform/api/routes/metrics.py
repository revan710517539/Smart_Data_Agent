from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import first_query_value, send_route_exception
from backend.authz.models import RoleLevel


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
                is_super_admin=any(role.level == RoleLevel.SUPER_ADMIN for role in roles),
            )
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
    if any(role.level == RoleLevel.SUPER_ADMIN for role in roles):
        return True

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
