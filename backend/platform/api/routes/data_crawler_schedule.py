from __future__ import annotations

import hashlib
import time
from calendar import monthrange
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import parse_qs
from uuid import uuid4
from zoneinfo import ZoneInfo

from backend.platform.api.support import first_query_value, send_route_exception
from backend.platform.integrations.data_crawler import client_for_tenant, endpoint_for_tenant


def _task_code(source_key: str) -> str:
    return f"data-crawler:{hashlib.sha256(source_key.encode('utf-8')).hexdigest()[:32]}"


def _optional_status_endpoint(tenant_id: str) -> Any | None:
    try:
        return endpoint_for_tenant(tenant_id)
    except (RuntimeError, PermissionError) as exc:
        if str(exc) in {"data_crawler_endpoint_not_configured", "data_crawler_tenant_binding_missing"}:
            return None
        raise


def _schedule_statuses(
    tasks: list[dict[str, Any]],
    valid_source_keys: set[str],
    institution_id: str,
) -> dict[str, dict[str, Any]]:
    statuses: dict[str, dict[str, Any]] = {}
    for task in tasks:
        config = task.get("task_config") if isinstance(task.get("task_config"), dict) else {}
        source_key = str(config.get("source_key") or "")
        if (
            str(task.get("handler_ref") or "") != "data_crawler.dispatch"
            or str(task.get("status") or "") != "active"
            or str(task.get("trigger_type") or "") != "schedule"
            or str(config.get("institution_id") or "") != institution_id
            or source_key not in valid_source_keys
        ):
            continue
        statuses[source_key] = {
            "scheduled": True,
            "recurrence": str(config.get("recurrence") or ""),
            "schedule_expression": str(task.get("schedule_expression") or ""),
            "next_run_at": str(task.get("next_run_at") or ""),
        }
    return statuses


def _raw_table(handler: Any, tenant_id: str, source_key: str) -> tuple[Any, dict[str, Any]]:
    catalog = handler.services.data_acquisition_service.csv_source.for_tenant(tenant_id)
    endpoint = endpoint_for_tenant(tenant_id)
    if catalog.root.name != endpoint.institution_directory:
        raise PermissionError("data_crawler_csv_institution_mismatch")
    table = next(
        (item for item in catalog.table_assets(force=True) if str(item.get("sourceKey") or "") == source_key),
        None,
    )
    if not isinstance(table, dict):
        raise KeyError("raw_table_not_found")
    return catalog, dict(table)


def _delivery_relative_path(value: Any, institution_directory: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/"):
        return ""
    parts = PurePosixPath(raw).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return ""
    if parts[0] == institution_directory:
        parts = parts[1:]
    return "/".join(parts)


def _binding_matches_table(binding: dict[str, Any], table: dict[str, Any], institution_directory: str) -> bool:
    delivery = binding.get("latestDelivery") if isinstance(binding.get("latestDelivery"), dict) else {}
    delivery_path = _delivery_relative_path(delivery.get("path"), institution_directory)
    table_path = _delivery_relative_path(table.get("relativePath"), institution_directory)
    delivery_digest = str(delivery.get("sha256") or "").lower()
    table_digest = str(table.get("contentHash") or "").lower()
    return bool(
        delivery_path
        and table_path
        and delivery_path == table_path
        and len(delivery_digest) == 64
        and delivery_digest == table_digest
    )


def _configuration_binding_for_table(client: Any, table: dict[str, Any], sql_id: str = "") -> dict[str, Any]:
    """Read a display binding without treating a changing CSV digest as a validation failure."""
    if sql_id:
        return dict(client.binding(sql_id))
    institution_directory = str(client.endpoint.institution_directory or "")
    table_path = _delivery_relative_path(table.get("relativePath"), institution_directory)
    bindings = client.list_bindings().get("items") or []
    matches = []
    for item in bindings:
        if not isinstance(item, dict):
            continue
        delivery = item.get("latestDelivery") if isinstance(item.get("latestDelivery"), dict) else {}
        if _delivery_relative_path(delivery.get("path"), institution_directory) == table_path:
            matches.append(item)
    return dict(matches[0]) if len(matches) == 1 else {}


def _binding_for_table(client: Any, table: dict[str, Any], sql_id: str = "") -> dict[str, Any]:
    institution_directory = str(client.endpoint.institution_directory or "")
    if sql_id:
        binding = client.binding(sql_id)
        if not _binding_matches_table(binding, table, institution_directory):
            raise PermissionError("data_crawler_csv_receipt_mismatch")
    else:
        bindings = client.list_bindings().get("items") or []
        matches = [
            item
            for item in bindings
            if isinstance(item, dict) and _binding_matches_table(item, table, institution_directory)
        ]
        if len(matches) > 1:
            raise PermissionError("data_crawler_csv_receipt_ambiguous")
        binding = matches[0] if matches else {}
    return dict(binding)


def _cron(recurrence: str, time_value: str, weekday: int, month_day: int) -> tuple[str, str]:
    try:
        hour, minute = [int(value) for value in time_value.split(":", 1)]
    except Exception as exc:
        raise ValueError("schedule_time_invalid") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("schedule_time_invalid")
    if recurrence == "daily":
        return "schedule", f"{minute} {hour} * * *"
    if recurrence in {"weekly", "biweekly"}:
        if weekday not in range(0, 7):
            raise ValueError("schedule_weekday_invalid")
        return "schedule", f"{minute} {hour} * * {weekday}"
    if recurrence == "monthly":
        if month_day not in range(1, 29):
            raise ValueError("schedule_month_day_invalid")
        return "schedule", f"{minute} {hour} {month_day} * *"
    if recurrence in {"", "none", "manual"}:
        return "manual", ""
    raise ValueError("schedule_recurrence_invalid")


def _execution_at(payload: dict[str, Any], zone: ZoneInfo) -> tuple[datetime, bool]:
    raw = str(payload.get("executionAt") or "").strip()
    if raw:
        try:
            value = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError("schedule_execution_at_invalid") from exc
        if value.tzinfo is None:
            value = value.replace(tzinfo=zone)
        return value.astimezone(zone), True
    try:
        hour, minute = [int(value) for value in str(payload.get("time") or "09:00").split(":", 1)]
        value = datetime.now(zone).replace(hour=hour, minute=minute, second=0, microsecond=0)
    except Exception as exc:
        raise ValueError("schedule_execution_at_invalid") from exc
    return value, False


def _shift_months(value: datetime, months: int) -> datetime:
    month_index = value.year * 12 + value.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    return value.replace(year=year, month=month, day=min(value.day, monthrange(year, month)[1]))


def _format_temporal_value(parameter_type: str, value: datetime) -> str:
    if parameter_type == "month":
        return value.strftime("%Y-%m")
    if parameter_type == "datetime":
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value.strftime("%Y-%m-%d")


def _normalize_fixed_temporal_value(parameter_type: str, raw: Any) -> str:
    value = str(raw or "").strip()
    if not value:
        raise ValueError("sql_parameter_fixed_value_required")
    try:
        if parameter_type == "month":
            parsed = datetime.strptime(value, "%Y-%m")
            return parsed.strftime("%Y-%m")
        if parameter_type == "datetime":
            parsed = datetime.fromisoformat(value.replace(" ", "T"))
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        parsed = datetime.strptime(value, "%Y-%m-%d")
        return parsed.strftime("%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("sql_parameter_fixed_value_invalid") from exc


def _resolve_temporal_parameters(
    binding: dict[str, Any],
    parameters: dict[str, Any],
    parameter_bindings: dict[str, Any],
    reference: datetime,
) -> dict[str, str]:
    specs = {
        str(item.get("name") or ""): str(item.get("type") or "")
        for item in binding.get("parameters") or []
        if isinstance(item, dict) and str(item.get("name") or "")
    }
    if set(parameters) - set(specs) or set(parameter_bindings) - set(specs):
        raise ValueError("sql_parameter_not_in_binding")
    if any(kind not in {"date", "month", "datetime"} for kind in specs.values()):
        raise ValueError("non_temporal_sql_parameters_not_supported")
    next_month = (reference.replace(day=28) + timedelta(days=4)).replace(day=1)
    previous_month_end = reference.replace(day=1) - timedelta(days=1)
    legacy_values = {
        "execution_date": reference.strftime("%Y-%m-%d"),
        "previous_date": (reference - timedelta(days=1)).strftime("%Y-%m-%d"),
        "month_start": reference.replace(day=1).strftime("%Y-%m-%d"),
        "month_end": (next_month - timedelta(days=1)).strftime("%Y-%m-%d"),
        "previous_month_start": previous_month_end.replace(day=1).strftime("%Y-%m-%d"),
        "previous_month_end": previous_month_end.strftime("%Y-%m-%d"),
        "execution_month": reference.strftime("%Y-%m"),
        "previous_month": previous_month_end.strftime("%Y-%m"),
        "year_start_month": reference.replace(month=1).strftime("%Y-%m"),
        "execution_datetime": reference.strftime("%Y-%m-%d %H:%M:%S"),
        "day_start": reference.replace(hour=0, minute=0, second=0).strftime("%Y-%m-%d %H:%M:%S"),
        "day_end": reference.replace(hour=23, minute=59, second=59).strftime("%Y-%m-%d %H:%M:%S"),
    }
    resolved: dict[str, str] = {}
    for name, parameter_type in specs.items():
        rule = str(parameter_bindings.get(name) or "").strip()
        if not rule:
            resolved[name] = _normalize_fixed_temporal_value(parameter_type, parameters.get(name))
            continue
        if rule == "reference":
            resolved[name] = _format_temporal_value(parameter_type, reference)
            continue
        if rule.startswith("before:"):
            try:
                offset = int(rule.split(":", 1)[1])
            except (TypeError, ValueError) as exc:
                raise ValueError("sql_parameter_offset_invalid") from exc
            if offset < 1 or offset > 36_500:
                raise ValueError("sql_parameter_offset_invalid")
            shifted = _shift_months(reference, offset) if parameter_type == "month" else reference - timedelta(days=offset)
            resolved[name] = _format_temporal_value(parameter_type, shifted)
            continue
        if rule in legacy_values:
            resolved[name] = legacy_values[rule]
            continue
        raise ValueError("sql_parameter_binding_invalid")
    return resolved


def _task_definition(source_key: str, table: dict[str, Any], binding: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    recurrence = str(payload.get("recurrence") or "none").strip().lower()
    zone = ZoneInfo("Asia/Shanghai")
    execution_at, has_explicit_execution_at = _execution_at(payload, zone)
    weekday = (execution_at.weekday() + 1) % 7 if has_explicit_execution_at else int(payload.get("weekday") or 1)
    month_day = execution_at.day if has_explicit_execution_at else int(payload.get("monthDay") or 1)
    trigger_type, schedule = _cron(
        recurrence,
        execution_at.strftime("%H:%M"),
        weekday,
        month_day,
    )
    parameters = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
    parameter_bindings = payload.get("parameterBindings") if isinstance(payload.get("parameterBindings"), dict) else {}
    allowed = {str(item.get("name") or ""): str(item.get("type") or "") for item in binding.get("parameters") or []}
    if set(parameters) - set(allowed) or set(parameter_bindings) - set(allowed):
        raise ValueError("sql_parameter_not_in_binding")
    if any(kind not in {"date", "month", "datetime"} for kind in allowed.values()):
        raise ValueError("non_temporal_sql_parameters_not_supported")
    if not allowed and trigger_type == "schedule":
        raise ValueError("parameterless_sql_must_be_one_shot")
    _resolve_temporal_parameters(binding, parameters, parameter_bindings, execution_at)
    biweekly_anchor = execution_at.date().isoformat()
    if not has_explicit_execution_at and str(payload.get("biweeklyAnchor") or "").strip():
        try:
            biweekly_anchor = datetime.fromisoformat(str(payload["biweeklyAnchor"])).date().isoformat()
        except ValueError as exc:
            raise ValueError("schedule_biweekly_anchor_invalid") from exc
    return {
        "task_code": _task_code(source_key),
        "task_name": f"{table.get('tableNameCn') or source_key} 数据采集",
        "task_type": "acquisition",
        "trigger_type": trigger_type,
        "schedule_expression": schedule,
        "handler_ref": "data_crawler.dispatch",
        "task_config": {
            "timezone": "Asia/Shanghai",
            "source_key": source_key,
            "sql_id": str(binding["sqlId"]),
            "sql_name": str(binding.get("sqlName") or ""),
            "institution_id": str(binding["institutionId"]),
            "csv_content_hash": str(table.get("contentHash") or ""),
            "parameters": parameters,
            "parameter_bindings": parameter_bindings,
            "recurrence": recurrence,
            "execution_at": execution_at.strftime("%Y-%m-%dT%H:%M"),
            "biweekly_anchor": biweekly_anchor,
        },
        "retry_policy": {"max_attempts": 2, "backoff_seconds": 60},
        "timeout_seconds": 1800,
        "max_concurrency": 1,
        "status": "active",
    }


def _save(handler: Any, context: Any, source_key: str, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    _catalog, table = _raw_table(handler, context.tenant_id, source_key)
    client = client_for_tenant(context.tenant_id)
    binding = _binding_for_table(client, table, str(payload.get("sqlId") or ""))
    if not binding:
        raise ValueError("data_crawler_sql_binding_not_found")
    definition = _task_definition(source_key, table, binding, payload)
    zone = ZoneInfo(str(definition["task_config"].get("timezone") or "Asia/Shanghai"))
    resolved_parameters = _resolve_temporal_parameters(
        binding,
        dict(definition["task_config"]["parameters"]),
        dict(definition["task_config"]["parameter_bindings"]),
        datetime.now(zone),
    )
    store = handler.services.automation_store
    existing = store.get_task_by_code(context.tenant_id, definition["task_code"])
    if existing:
        task = handler.services.automation_runtime.update_task(
            context.tenant_id,
            str(existing["automation_task_id"]),
            definition,
            context.user_id,
            int(existing.get("lock_version") or 0),
        )
    else:
        task = handler.services.automation_runtime.create_task(context.tenant_id, definition, context.user_id)
    control = client.claim(
        str(binding["sqlId"]),
        {
            "active": str(definition["trigger_type"]) == "schedule",
            "schedule": {
                "recurrence": definition["task_config"]["recurrence"],
                "expression": definition["schedule_expression"],
                "timezone": "Asia/Shanghai",
            },
            "parameters": resolved_parameters,
            "parameterBindings": {},
        },
    )
    return task, control


def handle_data_crawler_schedule_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_asset_permission(context, "read")
        source_key = str(first_query_value(params, "source_key") or "").strip()
        _catalog, table = _raw_table(handler, context.tenant_id, source_key)
        existing = handler.services.automation_store.get_task_by_code(context.tenant_id, _task_code(source_key))
        sql_id = str((existing or {}).get("task_config", {}).get("sql_id") or "")
        client = client_for_tenant(context.tenant_id)
        binding = _configuration_binding_for_table(client, table, sql_id)
        available = [] if binding else client.list_bindings().get("items") or []
        handler._send_json({
            "tenant_id": context.tenant_id,
            "source_key": source_key,
            "institution_id": endpoint_for_tenant(context.tenant_id).institution_id,
            "institution_directory": endpoint_for_tenant(context.tenant_id).institution_directory,
            "binding": binding or None,
            "validation_required": True,
            "available_bindings": [
                {"sqlId": item.get("sqlId"), "sqlName": item.get("sqlName"), "parameters": item.get("parameters") or []}
                for item in available
            ],
            "task": existing,
        })
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_data_crawler_schedule_statuses_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_asset_permission(context, "read")
        catalog = handler.services.data_acquisition_service.csv_source.for_tenant(context.tenant_id)
        endpoint = _optional_status_endpoint(context.tenant_id)
        if endpoint is None:
            handler._send_json({
                "tenant_id": context.tenant_id,
                "institution_id": "",
                "institution_directory": catalog.root.name,
                "available": False,
                "items": {},
                "count": 0,
            })
            return
        if catalog.root.name != endpoint.institution_directory:
            raise PermissionError("data_crawler_csv_institution_mismatch")
        valid_source_keys = {
            str(item.get("sourceKey") or "")
            for item in catalog.table_assets()
            if str(item.get("sourceKey") or "")
        }
        items = _schedule_statuses(
            handler.services.automation_store.list_tasks(context.tenant_id),
            valid_source_keys,
            endpoint.institution_id,
        )
        handler._send_json({
            "tenant_id": context.tenant_id,
            "institution_id": endpoint.institution_id,
            "institution_directory": endpoint.institution_directory,
            "available": True,
            "items": items,
            "count": len(items),
        })
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_data_crawler_schedule_save(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_asset_permission(context, "create")
        handler._require_automation_permission(context, "create")
        source_key = str(payload.get("source_key") or "").strip()
        task, control = _save(handler, context, source_key, payload)
        handler._write_audit(context, "data_crawler.schedule.save", "raw_table", source_key, {"automation_task_id": task["automation_task_id"], "sql_id": task["task_config"]["sql_id"]})
        handler._send_json({"tenant_id": context.tenant_id, "task": task, "control": control})
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_data_crawler_schedule_test(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_asset_permission(context, "read")
        source_key = str(payload.get("source_key") or "").strip()
        _catalog, table = _raw_table(handler, context.tenant_id, source_key)
        client = client_for_tenant(context.tenant_id)
        binding = _binding_for_table(client, table, str(payload.get("sqlId") or ""))
        if not binding:
            raise ValueError("data_crawler_sql_binding_not_found")
        definition = _task_definition(source_key, table, binding, payload)
        zone = ZoneInfo(str(definition["task_config"].get("timezone") or "Asia/Shanghai"))
        resolved = _resolve_temporal_parameters(
            binding,
            dict(definition["task_config"]["parameters"]),
            dict(definition["task_config"]["parameter_bindings"]),
            datetime.now(zone),
        )
        handler._send_json({
            "tenant_id": context.tenant_id,
            "connected": True,
            "institution_id": client.endpoint.institution_id,
            "sql_id": str(binding.get("sqlId") or ""),
            "parameter_count": len(resolved),
            "receipt_sha256": str(table.get("contentHash") or ""),
        })
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_data_crawler_schedule_execute(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_asset_permission(context, "create")
        handler._require_automation_permission(context, "create")
        source_key = str(payload.get("source_key") or "").strip()
        task, _control = _save(handler, context, source_key, payload)
        run = handler.services.automation_runtime.trigger(
            context.tenant_id,
            str(task["automation_task_id"]),
            context.user_id,
            str(payload.get("idempotency_key") or f"data-crawler-{uuid4().hex}"),
            {"force": True},
        )
        handler._send_json({"tenant_id": context.tenant_id, "task": task, "run": run})
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_data_crawler_schedule_delete(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_automation_permission(context, "create")
        source_key = str(payload.get("source_key") or "").strip()
        task = handler.services.automation_store.get_task_by_code(context.tenant_id, _task_code(source_key))
        if not task:
            handler._send_json({"tenant_id": context.tenant_id, "cleared": False})
            return
        task = handler.services.automation_runtime.update_task(
            context.tenant_id,
            str(task["automation_task_id"]),
            {"status": "disabled"},
            context.user_id,
            int(task.get("lock_version") or 0),
        )
        client_for_tenant(context.tenant_id).release(str(task["task_config"]["sql_id"]))
        handler._send_json({"tenant_id": context.tenant_id, "cleared": True, "task": task})
    except Exception as exc:
        send_route_exception(handler, exc)


def data_crawler_dispatch_handler(tenant_id: str, config: dict[str, Any], trigger_payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    recurrence = str(config.get("recurrence") or "none")
    if recurrence == "biweekly" and not trigger_payload.get("force"):
        zone = ZoneInfo(str(config.get("timezone") or "Asia/Shanghai"))
        today = datetime.now(zone).date()
        anchor = datetime.fromisoformat(str(config.get("biweekly_anchor"))).date()
        elapsed_days = (today - anchor).days
        if elapsed_days < 0 or (elapsed_days // 7) % 2 != 0:
            return {"status": "skipped", "reason": "biweekly_off_week"}
    client = client_for_tenant(tenant_id)
    if client.endpoint.institution_id != str(config.get("institution_id") or ""):
        raise PermissionError("data_crawler_task_institution_mismatch")
    binding = client.binding(str(config["sql_id"]))
    zone = ZoneInfo(str(config.get("timezone") or "Asia/Shanghai"))
    resolved_parameters = _resolve_temporal_parameters(
        binding,
        dict(config.get("parameters") or {}),
        dict(config.get("parameter_bindings") or {}),
        datetime.now(zone),
    )
    execution = client.execute(
        str(config["sql_id"]),
        {
            "executionId": str(context.get("automation_run_id") or ""),
            "parameters": resolved_parameters,
            "parameterBindings": {},
            "timezone": str(config.get("timezone") or "Asia/Shanghai"),
        },
    )
    deadline = time.monotonic() + 1740
    result = execution
    while str(result.get("status") or "") not in {"succeeded", "failed"}:
        if callable(context.get("is_cancelled")) and context["is_cancelled"]():
            raise RuntimeError("data_crawler_execution_cancelled")
        if time.monotonic() >= deadline:
            raise TimeoutError("data_crawler_execution_timeout")
        time.sleep(1)
        result = client.execution(str(execution["runId"]))
    if result.get("status") != "succeeded":
        raise RuntimeError(str(result.get("message") or "data_crawler_execution_failed"))
    delivery = result.get("latestDelivery") if isinstance(result.get("latestDelivery"), dict) else {}
    if (
        str(delivery.get("institutionId") or "") != client.endpoint.institution_id
        or str(delivery.get("runId") or "") != str(execution["runId"])
    ):
        raise PermissionError("data_crawler_delivery_receipt_mismatch")
    return {
        "data_crawler_run_id": execution["runId"],
        "institution_id": execution["institutionId"],
        "sql_id": execution["sqlId"],
        "delivery_path": str(delivery.get("path") or ""),
        "delivery_sha256": str(delivery.get("sha256") or ""),
    }
