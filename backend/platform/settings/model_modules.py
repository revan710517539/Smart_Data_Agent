from __future__ import annotations

from typing import Any


MODEL_APPLICATION_MODULES: dict[str, str] = {
    "realtime_voice_input": "实时语音录入",
    "popup_voice_input": "弹窗语音录入",
    "crawler_exception_optimization": "爬虫异常优化",
    "intelligent_analysis_reasoning": "智能分析推理分析",
    "weekly_report_conclusion_regeneration": "周报结论重新生成",
    "automatic_analysis": "自动分析任务",
    "memory_extraction": "记忆模块",
}

def normalize_application_module(value: Any, *, allow_empty: bool = True) -> str:
    normalized = str(value or "").strip()
    if not normalized and allow_empty:
        return ""
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
    list_owned = getattr(system_config_store, "list_models_owned_by", None)
    models = list(system_config_store.list_models(tenant_id, reveal_secret=reveal_secret))
    if user_id and callable(list_owned):
        models.extend(list_owned(user_id, tenant_id, reveal_secret=reveal_secret))
    resolved: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for model in models:
        if (
            normalize_application_module(model.get("applicationModule")) != module_key
            or str(model.get("status") or "available") not in {"available", "draft"}
        ):
            continue
        identity = (str(model.get("id") or ""), module_key)
        if identity in seen:
            continue
        seen.add(identity)
        resolved.append(dict(model))
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
