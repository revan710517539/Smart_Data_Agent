from __future__ import annotations

from typing import Any



MODEL_APPLICATION_MODULES: dict[str, str] = {
    "global_text_model": "全局文本模型（非语音）",
    "global_voice_model": "全局语音模型",
    "realtime_voice_input": "实时语音录入",
    "popup_voice_input": "弹窗语音录入",
    "intelligent_analysis_reasoning": "智能分析推理分析",
    "weekly_report_conclusion_regeneration": "周报结论重新生成",
    "automatic_analysis": "自动分析任务",
    "memory_extraction": "记忆模块",
    "skill_evolution_learning": "Skill自学习与演化",
}

VOICE_APPLICATION_MODULES = {"global_voice_model", "realtime_voice_input", "popup_voice_input"}
RETIRED_DEFAULT_RELAY_MODEL_ID = "model_default_intelligent_analysis_relay"


def is_retired_default_model(model: dict[str, Any] | str) -> bool:
    model_id = model if isinstance(model, str) else model.get("id")
    return str(model_id or "").strip() == RETIRED_DEFAULT_RELAY_MODEL_ID

# Existing saved integrations are never deleted merely because a retired
# feature is removed.  The former collector-repair binding is presented as the
# supported Skill evolution module on read, without changing its stored row.
LEGACY_APPLICATION_MODULE_ALIASES = {
    "crawler_exception_optimization": "skill_evolution_learning",
}

def normalize_application_module(value: Any, *, allow_empty: bool = True) -> str:
    normalized = str(value or "").strip()
    if not normalized and allow_empty:
        return ""
    normalized = LEGACY_APPLICATION_MODULE_ALIASES.get(normalized, normalized)
    if normalized in MODEL_APPLICATION_MODULES:
        return normalized
    by_label = {label: key for key, label in MODEL_APPLICATION_MODULES.items()}
    if normalized in by_label:
        return by_label[normalized]
    raise ValueError("invalid_model_application_module")


def application_module_label(value: Any) -> str:
    key = normalize_application_module(value)
    return MODEL_APPLICATION_MODULES.get(key, "未分配")


def list_models_for_application(
    system_config_store: Any,
    tenant_id: str,
    application_module: str,
    *,
    user_id: str = "",
    reveal_secret: bool = True,
) -> list[dict[str, Any]]:
    module_key = normalize_application_module(application_module, allow_empty=False)
    account_models: list[dict[str, Any]] = []
    if user_id:
        try:
            account_models = list(
                system_config_store.list_models(
                    f"account:{str(user_id).strip() or 'anonymous'}",
                    reveal_secret=reveal_secret,
                )
            )
        except Exception:
            account_models = []
    # Account-owned integrations are intentionally considered first.  A model
    # added by an account administrator is shared by every institution of that
    # account and must take precedence over a legacy institution copy with the
    # same integration ID.
    # Once an authenticated account is known, its account scope is the only
    # model authority.  Falling back to legacy institution rows makes a model
    # reappear after the account deletes it and leaks institution-era routing
    # back into an account that switches institutions.
    models = account_models if user_id else system_config_store.list_models(tenant_id, reveal_secret=reveal_secret)
    resolved: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for model in models:
        if is_retired_default_model(model):
            continue
        model_module = normalize_application_module(model.get("applicationModule"))
        enabled_models = [str(item).strip() for item in model.get("enabledModels") or [] if str(item).strip()]
        if (
            model_module != module_key
            and not (model_module == "global_text_model" and module_key not in VOICE_APPLICATION_MODULES)
            or str(model.get("status") or "available") != "available"
            or str(model.get("testStatus") or "").strip().lower() not in {"connected", "mock"}
            or not enabled_models
        ):
            continue
        identity = (str(model.get("id") or ""), module_key)
        if identity in seen:
            continue
        seen.add(identity)
        resolved.append(dict(model))
    has_usable_bound_model = any(
        str(item).strip()
        for model in resolved
        for item in [*(model.get("enabledModels") or []), *(model.get("availableModels") or [])]
    )
    if not has_usable_bound_model and account_models:
        # Older account-bound integrations predate application-module bindings.
        # Keep them on the governed application-module route while requiring a
        # previously connected account model; do not use untested demo rows.
        for model in account_models:
            if is_retired_default_model(model):
                continue
            if (
                str(model.get("applicationModule") or "").strip()
                or str(model.get("status") or "available") != "available"
                or str(model.get("testStatus") or "") not in {"connected", "mock"}
                or not any(str(item).strip() for item in model.get("enabledModels") or [])
            ):
                continue
            identity = (str(model.get("id") or ""), module_key)
            if identity in seen:
                continue
            seen.add(identity)
            resolved.append({**model, "applicationModule": module_key, "legacyAccountBinding": True})
    return resolved


def resolve_model_for_application(
    system_config_store: Any,
    tenant_id: str,
    application_module: str,
    *,
    user_id: str = "",
    reveal_secret: bool = True,
) -> dict[str, Any] | None:
    candidates = list_models_for_application(
        system_config_store,
        tenant_id,
        application_module,
        user_id=user_id,
        reveal_secret=reveal_secret,
    )
    return candidates[0] if candidates else None


def select_model_for_application(
    system_config_store: Any,
    tenant_id: str,
    application_module: str,
    selection: dict[str, Any] | None,
    *,
    user_id: str = "",
    reveal_secret: bool = True,
) -> dict[str, Any] | None:
    candidates = list_models_for_application(
        system_config_store,
        tenant_id,
        application_module,
        user_id=user_id,
        reveal_secret=reveal_secret,
    )
    if not candidates:
        return None
    if not selection:
        return candidates[0]
    integration_id = str(selection.get("integrationId") or selection.get("integration_id") or "").strip()
    selected = next((model for model in candidates if str(model.get("id") or "") == integration_id), None)
    if selected is None:
        raise PermissionError("selected_model_not_registered_for_application_module")
    requested_submodel = str(
        selection.get("selectedModelName") or selection.get("selected_model_name") or ""
    ).strip()
    if not requested_submodel:
        return selected
    enabled = [str(item).strip() for item in selected.get("enabledModels") or [] if str(item).strip()]
    available = [str(item).strip() for item in selected.get("availableModels") or [] if str(item).strip()]
    allowed_submodels = set(enabled or available)
    if requested_submodel not in allowed_submodels:
        raise PermissionError("selected_submodel_not_enabled_for_application_module")
    return {
        **selected,
        "enabledModels": [requested_submodel],
        "availableModels": [requested_submodel],
        "selectedModelName": requested_submodel,
        "strictModelSelection": True,
    }


def require_model_for_application(
    system_config_store: Any,
    tenant_id: str,
    application_module: str,
    *,
    user_id: str = "",
    reveal_secret: bool = True,
) -> dict[str, Any]:
    model = resolve_model_for_application(
        system_config_store,
        tenant_id,
        application_module,
        user_id=user_id,
        reveal_secret=reveal_secret,
    )
    if model is None:
        label = application_module_label(application_module)
        raise ValueError(f"model_application_module_not_ready:{label}")
    return model
