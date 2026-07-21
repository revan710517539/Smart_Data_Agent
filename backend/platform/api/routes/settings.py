from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from backend.platform.api.support import first_query_value, send_route_exception
from backend.platform.settings import test_data_connection, test_model_integration, test_speech_integration


def handle_system_config_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_system_config_permission(context, "read")
        config_scope = _account_config_scope(context)
        models = _list_account_models(handler, context, config_scope)
        speech_integrations = _list_account_speech_integrations(handler, context, config_scope)
        data_connections = _list_account_data_connections(handler, context, config_scope)
        system_params = handler.services.system_config_store.list_system_params(context.tenant_id)
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                "config_scope": config_scope,
                "config_owner_user_id": context.user_id,
                "models": models,
                "speech_integrations": speech_integrations,
                "data_connections": data_connections,
                "system_params": system_params,
                "count": {
                    "models": len(models),
                    "speech_integrations": len(speech_integrations),
                    "data_connections": len(data_connections),
                    "system_params": len(system_params),
                },
            }
        )
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_system_model_upsert(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        model = payload.get("model")
        if not isinstance(model, dict):
            raise ValueError("model must be an object.")
        handler._require_system_config_permission(context, "manage")
        config_scope = _account_config_scope(context)
        saved = handler.services.system_config_store.upsert_model(
            config_scope,
            model,
            updated_by=context.user_id,
        )
        handler._write_audit(context, "system.model.upsert", "model", str(saved.get("id") or ""))
        handler._send_json({"tenant_id": context.tenant_id, "config_scope": config_scope, "model": saved})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_system_model_delete(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        model_id = first_query_value(params, "model_id")
        if not model_id:
            raise ValueError("model_id is required.")
        handler._require_system_config_permission(context, "manage")
        config_scope = _account_config_scope(context)
        deleted = handler.services.system_config_store.delete_model(config_scope, model_id)
        handler._write_audit(context, "system.model.delete", "model", model_id, {"deleted": deleted})
        handler._send_json({"tenant_id": context.tenant_id, "config_scope": config_scope, "model_id": model_id, "deleted": deleted})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_system_model_test(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_system_config_permission(context, "manage")
        model = payload.get("model")
        model_id = str(payload.get("model_id") or "").strip()
        if model is None and model_id:
            getter = getattr(handler.services.system_config_store, "get_model", None)
            if not callable(getter):
                raise ValueError("system config store does not support model lookup.")
            model = getter(_account_config_scope(context), model_id, reveal_secret=True)
            if model is None:
                raise ValueError("model integration not found.")
        if not isinstance(model, dict):
            raise ValueError("model or model_id is required.")
        result = test_model_integration(model)
        saved_model = None
        if model.get("id"):
            previous_available_models = model.get("availableModels")
            if not isinstance(previous_available_models, list):
                previous_available_models = []
            available_models = result.get("available_models") if isinstance(result.get("available_models"), list) else []
            if not available_models:
                available_models = previous_available_models
            previous_enabled_models = model.get("enabledModels")
            if not isinstance(previous_enabled_models, list):
                previous_enabled_models = []
            used_model = str(result.get("used_model") or "").strip()
            if used_model:
                if used_model not in available_models:
                    available_models = [used_model, *available_models]
                enabled_models = [item for item in previous_enabled_models if not available_models or item in available_models]
                if not enabled_models:
                    enabled_models = [used_model]
            else:
                preserved_enabled = [item for item in previous_enabled_models if not available_models or item in available_models]
                enabled_models = preserved_enabled or (available_models[:1] if result.get("callable") else [])
            preserve_last_known_good = bool(
                result.get("transient")
                and model.get("status") == "available"
                and model.get("testStatus") == "connected"
            )
            if preserve_last_known_good:
                result["preserved_last_known_good"] = True
            saved_model = handler.services.system_config_store.upsert_model(
                _account_config_scope(context),
                {
                    **model,
                    "availableModels": available_models,
                    "enabledModels": enabled_models,
                    "testStatus": model.get("testStatus") if preserve_last_known_good else result.get("status"),
                    "testMessage": (
                        f"{result.get('message')}（当前仍使用上次成功连接状态）"
                        if preserve_last_known_good
                        else result.get("message")
                    ),
                    "testResponse": model.get("testResponse") if preserve_last_known_good else result.get("response_preview"),
                    "lastTestedAt": model.get("lastTestedAt") if preserve_last_known_good else result.get("tested_at"),
                    "status": "available",
                },
                updated_by=context.user_id,
            )
        handler._write_audit(
            context,
            "system.model.test",
            "model",
            str(result.get("model_id") or model_id),
            {"status": result.get("status"), "callable": result.get("callable"), "source": result.get("source")},
        )
        payload = {"tenant_id": context.tenant_id, "result": result}
        payload["config_scope"] = _account_config_scope(context)
        if saved_model is not None:
            payload["model"] = saved_model
        handler._send_json(payload)
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_system_speech_integration_upsert(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        integration = payload.get("speech_integration")
        if not isinstance(integration, dict):
            raise ValueError("speech_integration must be an object.")
        handler._require_system_config_permission(context, "manage")
        config_scope = _account_config_scope(context)
        saved = handler.services.system_config_store.upsert_speech_integration(
            config_scope,
            integration,
            updated_by=context.user_id,
        )
        handler._write_audit(context, "system.speech.upsert", "speech_integration", str(saved.get("id") or ""))
        handler._send_json({"tenant_id": context.tenant_id, "config_scope": config_scope, "speech_integration": saved})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_system_speech_integration_test(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_system_config_permission(context, "manage")
        integration = payload.get("speech_integration")
        integration_id = str(payload.get("integration_id") or "").strip()
        if integration is None and integration_id:
            getter = getattr(handler.services.system_config_store, "get_speech_integration", None)
            if callable(getter):
                integration = getter(_account_config_scope(context), integration_id, reveal_secret=True)
            else:
                integrations = handler.services.system_config_store.list_speech_integrations(_account_config_scope(context), reveal_secret=True)
                integration = next((item for item in integrations if item.get("id") == integration_id), None)
            if integration is None:
                raise ValueError("speech integration not found.")
        if not isinstance(integration, dict):
            raise ValueError("speech_integration or integration_id is required.")
        result = test_speech_integration(integration)
        saved_integration = None
        if integration.get("id"):
            saved_integration = handler.services.system_config_store.upsert_speech_integration(
                _account_config_scope(context),
                {
                    **integration,
                    "testStatus": result.get("status"),
                    "testMessage": result.get("message"),
                    "testResponse": result.get("response_preview") or result.get("endpoint"),
                    "lastTestedAt": result.get("tested_at"),
                    "status": "available",
                },
                updated_by=context.user_id,
            )
        handler._write_audit(
            context,
            "system.speech.test",
            "speech_integration",
            str(result.get("integration_id") or integration_id),
            {"status": result.get("status"), "callable": result.get("callable"), "provider": result.get("provider")},
        )
        response_payload = {"tenant_id": context.tenant_id, "result": result}
        response_payload["config_scope"] = _account_config_scope(context)
        if saved_integration is not None:
            response_payload["speech_integration"] = saved_integration
        handler._send_json(response_payload)
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_system_speech_integration_delete(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        integration_id = first_query_value(params, "integration_id")
        if not integration_id:
            raise ValueError("integration_id is required.")
        handler._require_system_config_permission(context, "manage")
        config_scope = _account_config_scope(context)
        deleted = handler.services.system_config_store.delete_speech_integration(config_scope, integration_id)
        handler._write_audit(context, "system.speech.delete", "speech_integration", integration_id, {"deleted": deleted})
        handler._send_json({"tenant_id": context.tenant_id, "config_scope": config_scope, "integration_id": integration_id, "deleted": deleted})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_system_data_connection_upsert(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        connection = payload.get("connection")
        if not isinstance(connection, dict):
            raise ValueError("connection must be an object.")
        handler._require_system_config_permission(context, "manage")
        config_scope = _account_config_scope(context)
        saved = handler.services.system_config_store.upsert_data_connection(
            config_scope,
            connection,
            updated_by=context.user_id,
        )
        handler._write_audit(context, "system.data_connection.upsert", "data_connection", str(saved.get("id") or ""))
        handler._send_json({"tenant_id": context.tenant_id, "config_scope": config_scope, "connection": saved})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_system_data_connection_test(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        handler._require_system_config_permission(context, "manage")
        connection = payload.get("connection")
        connection_id = str(payload.get("connection_id") or "").strip()
        if connection is None and connection_id:
            getter = getattr(handler.services.system_config_store, "get_data_connection", None)
            if not callable(getter):
                raise ValueError("system config store does not support connection lookup.")
            connection = getter(_account_config_scope(context), connection_id, reveal_secret=True)
            if connection is None:
                raise ValueError("data connection not found.")
        if not isinstance(connection, dict):
            raise ValueError("connection or connection_id is required.")
        result = test_data_connection({**connection, "tenant_id": context.tenant_id})
        saved_connection = None
        if connection.get("id") and connection_id:
            next_status = "verified" if result.get("verified") else "mock" if result.get("status") == "mock" else "draft"
            next_test_status = "verified" if result.get("verified") else "mock" if result.get("status") == "mock" else "failed"
            saved_connection = handler.services.system_config_store.upsert_data_connection(
                _account_config_scope(context),
                {
                    **connection,
                    "status": next_status,
                    "testStatus": next_test_status,
                    "testMessage": result.get("message"),
                    "lastTestedAt": result.get("tested_at") or result.get("verified_at") or "",
                },
                updated_by=context.user_id,
            )
        handler._write_audit(
            context,
            "system.data_connection.test",
            "data_connection",
            str(result.get("connection_id") or connection_id),
            {"status": result.get("status"), "callable": result.get("callable"), "dataset": result.get("dataset")},
        )
        response_payload = {"tenant_id": context.tenant_id, "config_scope": _account_config_scope(context), "result": result}
        if saved_connection is not None:
            response_payload["connection"] = saved_connection
        handler._send_json(response_payload)
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def handle_system_data_connection_delete(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        connection_id = first_query_value(params, "connection_id")
        if not connection_id:
            raise ValueError("connection_id is required.")
        handler._require_system_config_permission(context, "manage")
        config_scope = _account_config_scope(context)
        deleted = handler.services.system_config_store.delete_data_connection(config_scope, connection_id)
        handler._write_audit(
            context,
            "system.data_connection.delete",
            "data_connection",
            connection_id,
            {"deleted": deleted},
        )
        handler._send_json({"tenant_id": context.tenant_id, "config_scope": config_scope, "connection_id": connection_id, "deleted": deleted})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def _account_config_scope(context: Any) -> str:
    return context.tenant_id


def _list_account_models(handler: Any, context: Any, config_scope: str) -> list[dict[str, Any]]:
    return handler.services.system_config_store.list_models(config_scope)


def _list_account_speech_integrations(handler: Any, context: Any, config_scope: str) -> list[dict[str, Any]]:
    return handler.services.system_config_store.list_speech_integrations(config_scope)


def _list_account_data_connections(handler: Any, context: Any, config_scope: str) -> list[dict[str, Any]]:
    return handler.services.system_config_store.list_data_connections(config_scope)


def handle_system_param_upsert(handler: Any) -> None:
    try:
        payload = handler._read_json()
        context = handler._request_context(payload=payload)
        param = payload.get("param")
        if not isinstance(param, dict):
            raise ValueError("param must be an object.")
        handler._require_system_config_permission(context, "manage")
        saved = handler.services.system_config_store.upsert_system_param(
            context.tenant_id,
            param,
            updated_by=context.user_id,
        )
        handler._write_audit(context, "system.param.upsert", "system_param", str(saved.get("id") or ""))
        handler._send_json({"tenant_id": context.tenant_id, "param": saved})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)
