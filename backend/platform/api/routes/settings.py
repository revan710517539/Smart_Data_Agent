from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from backend.authz import normalize_tenant_id
from backend.authz.seed import OPERATING_TENANTS
from backend.platform.api.support import first_query_value, send_route_exception
from backend.platform.settings import (
    DEFAULT_RELAY_MODEL_ID,
    account_system_config_scope,
    default_relay_model_preset,
    ensure_default_models_for_account,
    test_model_integration,
    test_speech_integration,
)
from backend.platform.settings.store import MASKED_SECRET
from backend.platform.tenancy import ExecutionContext


def handle_system_config_get(handler: Any, query: str) -> None:
    try:
        params = parse_qs(query)
        context = handler._request_context(params=params)
        handler._require_system_config_permission(context, "read")
        config_scope = _account_config_scope(context)
        ensure_default_models_for_account(handler.services.system_config_store, context.user_id)
        models = _list_account_models(handler, context, config_scope)
        if not any(str(model.get("id") or "") == DEFAULT_RELAY_MODEL_ID for model in models):
            models = [default_relay_model_preset(), *models]
        speech_integrations = _list_account_speech_integrations(handler, context, config_scope)
        parameter_scopes = _available_system_parameter_scopes(handler, context)
        parameter_tenant_ids = tuple(tenant_id for tenant_id, _ in parameter_scopes)
        system_params = [
            {
                **param,
                "tenantId": tenant_id,
                "institution": _institution_label(tenant_id),
            }
            for tenant_id, params in parameter_scopes
            for param in params
        ]
        handler._send_json(
            {
                "tenant_id": context.tenant_id,
                "config_scope": config_scope,
                "model_config_scope": _model_account_scope(context),
                "config_owner_user_id": context.user_id,
                "parameter_tenant_ids": list(parameter_tenant_ids),
                "models": models,
                "speech_integrations": speech_integrations,
                "system_params": system_params,
                "count": {
                    "models": len(models),
                    "speech_integrations": len(speech_integrations),
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
        model = {**model, "applicationModule": "global_text_model"}
        if str(model.get("value") or "") == MASKED_SECRET:
            existing = _get_account_model(handler, context, str(model.get("id") or ""), reveal_secret=True)
            if existing and existing.get("value"):
                model = {**model, "value": existing["value"]}
        config_scope = _model_account_scope(context)
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
        if model_id == DEFAULT_RELAY_MODEL_ID:
            raise ValueError("default_model_cannot_be_deleted")
        config_scope = _model_account_scope(context)
        deleted = False
        for scope in _model_scope_candidates(context):
            if handler.services.system_config_store.delete_model(scope, model_id):
                deleted = True
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
        model_scope = _model_storage_scope(handler, context, model_id)
        if model is None and model_id:
            getter = getattr(handler.services.system_config_store, "get_model", None)
            if not callable(getter):
                raise ValueError("system config store does not support model lookup.")
            model = _get_account_model(handler, context, model_id, reveal_secret=True)
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
                model_scope,
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
                    # A failed first connection test must not stay selectable
                    # by the application router.  Draft retains the saved
                    # endpoint and encrypted secret for correction/retest;
                    # model_modules additionally excludes testStatus=failed.
                    "status": "available" if result.get("callable") or preserve_last_known_good or result.get("status") == "mock" else "draft",
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
        payload["model_config_scope"] = _model_account_scope(context)
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
        integration = {**integration, "applicationModule": "global_voice_model"}
        if str(integration.get("apiKey") or "") == MASKED_SECRET:
            existing = _get_account_speech_integration(
                handler, context, str(integration.get("id") or ""), reveal_secret=True
            )
            if existing and existing.get("apiKey"):
                integration = {**integration, "apiKey": existing["apiKey"]}
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
            integration = _get_account_speech_integration(handler, context, integration_id, reveal_secret=True)
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
                    "applicationModule": "global_voice_model",
                    "testStatus": result.get("status"),
                    "testMessage": result.get("message"),
                    "testResponse": result.get("response_preview") or result.get("endpoint"),
                    "lastTestedAt": result.get("tested_at"),
                    "status": "available" if result.get("callable") or result.get("status") == "mock" else "draft",
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
        deleted = False
        for scope in _model_scope_candidates(context):
            if handler.services.system_config_store.delete_speech_integration(scope, integration_id):
                deleted = True
        handler._write_audit(context, "system.speech.delete", "speech_integration", integration_id, {"deleted": deleted})
        handler._send_json({"tenant_id": context.tenant_id, "config_scope": config_scope, "integration_id": integration_id, "deleted": deleted})
    except Exception as exc:  # pragma: no cover - covered at HTTP boundary.
        send_route_exception(handler, exc)


def _account_config_scope(context: Any) -> str:
    return account_system_config_scope(context.user_id)


def _institution_label(tenant_id: str) -> str:
    return str(tenant_id or "").split(":", 1)[-1].strip()


def _authorized_system_config_tenant_ids(handler: Any, context: Any) -> tuple[str, ...]:
    """Return user-authorised configuration scopes; never enumerate tenants blindly."""
    repository = handler.services.permission_broker.enforcer.repository
    candidates: set[str] = {str(context.tenant_id)}
    for assignment in repository.list_user_assignments(context.user_id):
        tenant_id = str(assignment.tenant_id or "").strip()
        if tenant_id == "*":
            candidates.update(normalize_tenant_id(name) for name in OPERATING_TENANTS)
        elif tenant_id:
            candidates.add(tenant_id)
    allowed: list[str] = []
    for tenant_id in sorted(candidates):
        try:
            handler.services.permission_broker.require_resource(
                ExecutionContext(user_id=context.user_id, tenant_id=tenant_id),
                "system_config:*",
                "read",
            )
        except PermissionError:
            continue
        allowed.append(tenant_id)
    return tuple(allowed)


def _available_system_parameter_scopes(
    handler: Any,
    context: Any,
) -> tuple[tuple[str, list[dict[str, Any]]], ...]:
    """Read only authorized scopes that exist in the relational tenant catalog.

    A global administrator's wildcard grant is broader than the set of tenants
    already provisioned in a minimal deployment. Missing tenants therefore
    contribute no parameter rows; every other storage failure remains fatal.
    """

    available: list[tuple[str, list[dict[str, Any]]]] = []
    for tenant_id in _authorized_system_config_tenant_ids(handler, context):
        try:
            params = handler.services.system_config_store.list_system_params(tenant_id)
        except KeyError as exc:
            if exc.args != ("tenant_not_provisioned",):
                raise
            continue
        available.append((tenant_id, params))
    return tuple(available)


def _list_account_models(handler: Any, context: Any, config_scope: str) -> list[dict[str, Any]]:
    for model in handler.services.system_config_store.list_models(config_scope, reveal_secret=True):
        if str(model.get("status") or "") == "disabled":
            continue
        if str(model.get("applicationModule") or "") == "global_text_model":
            continue
        handler.services.system_config_store.upsert_model(
            config_scope,
            {**model, "applicationModule": "global_text_model"},
            updated_by=context.user_id,
        )
    return _merge_legacy_tenant_integrations(
        [
            model
            for model in handler.services.system_config_store.list_models(config_scope)
            if str(model.get("status") or "") != "disabled"
        ],
        handler.services.system_config_store.list_models(context.tenant_id),
    )


def _get_account_model(handler: Any, context: Any, model_id: str, *, reveal_secret: bool) -> dict[str, Any] | None:
    getter = getattr(handler.services.system_config_store, "get_model", None)
    if not callable(getter):
        return None
    for scope in _model_scope_candidates(context):
        try:
            model = getter(scope, model_id, reveal_secret=reveal_secret)
        except Exception:
            continue
        if model is not None:
            return model
    return None


def _model_storage_scope(handler: Any, context: Any, model_id: str) -> str:
    getter = getattr(handler.services.system_config_store, "get_model", None)
    if callable(getter):
        for scope in _model_scope_candidates(context):
            try:
                if getter(scope, model_id, reveal_secret=False) is not None:
                    return scope
            except Exception:
                continue
    return _model_account_scope(context)


def _model_scope_candidates(context: Any) -> tuple[str, ...]:
    account_scope = _model_account_scope(context)
    scopes = [account_scope]
    if str(context.tenant_id) not in scopes:
        scopes.append(str(context.tenant_id))
    return tuple(scopes)


def _model_account_scope(context: Any) -> str:
    return account_system_config_scope(context.user_id)


def _get_account_speech_integration(handler: Any, context: Any, integration_id: str, *, reveal_secret: bool) -> dict[str, Any] | None:
    getter = getattr(handler.services.system_config_store, "get_speech_integration", None)
    if callable(getter):
        for scope in _model_scope_candidates(context):
            try:
                integration = getter(scope, integration_id, reveal_secret=reveal_secret)
            except Exception:
                continue
            if integration is not None:
                return integration
        return None
    for scope in _model_scope_candidates(context):
        integrations = handler.services.system_config_store.list_speech_integrations(scope, reveal_secret=reveal_secret)
        found = next((item for item in integrations if item.get("id") == integration_id), None)
        if found is not None:
            return found
    return None


def _list_account_speech_integrations(handler: Any, context: Any, config_scope: str) -> list[dict[str, Any]]:
    for integration in handler.services.system_config_store.list_speech_integrations(config_scope, reveal_secret=True):
        if str(integration.get("status") or "") == "disabled":
            continue
        if str(integration.get("applicationModule") or "") == "global_voice_model":
            continue
        handler.services.system_config_store.upsert_speech_integration(
            config_scope,
            {**integration, "applicationModule": "global_voice_model"},
            updated_by=context.user_id,
        )
    account_items = [
        item
        for item in handler.services.system_config_store.list_speech_integrations(config_scope)
        if str(item.get("status") or "") != "disabled"
    ]
    # One account-owned Fun-ASR is the system speech model. Leftover institution
    # rows stay in storage but must not appear beside it as a second接入.
    if account_items:
        return account_items
    return [
        item
        for item in handler.services.system_config_store.list_speech_integrations(context.tenant_id)
        if str(item.get("status") or "") != "disabled"
        and str(item.get("modelName") or item.get("provider") or "") != "historical"
    ]


def _merge_legacy_tenant_integrations(
    account_items: list[dict[str, Any]],
    tenant_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep account-owned rows first, then leftover current-tenant rows.

    Pre-account migrations stored some user-created models and speech on the
    institution tenant. Those rows stay visible on that institution only and
    never replace an account-scoped id.
    """

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*account_items, *tenant_items]:
        item_id = str(item.get("id") or "").strip()
        if not item_id or item_id in seen:
            continue
        if str(item.get("status") or "") == "disabled":
            continue
        if str(item.get("modelName") or item.get("provider") or "") == "historical":
            continue
        seen.add(item_id)
        merged.append(item)
    return merged


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
