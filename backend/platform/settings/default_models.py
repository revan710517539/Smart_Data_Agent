from __future__ import annotations

import os
from typing import Any, Iterable

from .store import account_system_config_scope


DEFAULT_RELAY_MODEL_ID = "model_default_intelligent_analysis_relay"
DEFAULT_RELAY_MODEL_API_BASE = "https://litellm-dev.sandbox.deepbank.daikuan.qihoo.net"
DEFAULT_RELAY_MODEL_API_KEY_ENV = "SMART_DATA_AGENT_DEFAULT_MODEL_API_KEY"
DEFAULT_MODEL_TEMPLATE_SCOPE = "system:default-model-template"


def default_relay_model_from_environment() -> dict[str, Any] | None:
    """Return the install-wide default model only when its secret is configured.

    The API key intentionally comes only from the process environment.  This
    keeps source control, test fixtures, and HTTP responses free of credentials.
    """

    api_key = os.getenv(DEFAULT_RELAY_MODEL_API_KEY_ENV, "").strip()
    if not api_key:
        return None
    return _default_relay_model(api_key)


def configure_default_relay_model(
    system_config_store: Any,
    api_key: str,
    *,
    api_base: str = DEFAULT_RELAY_MODEL_API_BASE,
    updated_by: str = "system",
) -> dict[str, Any]:
    """Persist the default relay template using the settings store encryption."""

    api_key = str(api_key or "").strip()
    if not api_key:
        raise ValueError("default_model_api_key_required")
    return system_config_store.upsert_model(
        DEFAULT_MODEL_TEMPLATE_SCOPE,
        _default_relay_model(api_key, api_base=api_base),
        updated_by=updated_by,
    )


def _default_relay_model(api_key: str, *, api_base: str | None = None) -> dict[str, Any]:
    return {
        "id": DEFAULT_RELAY_MODEL_ID,
        "name": "智能分析默认中转模型",
        "modelName": "中转站",
        "key": str(api_base or os.getenv("SMART_DATA_AGENT_DEFAULT_MODEL_API_BASE", DEFAULT_RELAY_MODEL_API_BASE)).strip()
        or DEFAULT_RELAY_MODEL_API_BASE,
        "value": api_key,
        "applicationModule": "global_text_model",
        "availableModels": [],
        "enabledModels": [],
        "testStatus": "untested",
        "status": "draft",
    }


def ensure_default_models_for_account(system_config_store: Any, user_id: str, *, updated_by: str = "system") -> list[str]:
    """Idempotently add each install-wide default model to one account scope."""

    user_id = str(user_id or "").strip()
    template = _configured_default_relay_model(system_config_store)
    if not user_id or template is None:
        return []
    scope = account_system_config_scope(user_id)
    existing = system_config_store.get_model(scope, DEFAULT_RELAY_MODEL_ID, reveal_secret=False)
    if existing is not None:
        return []
    system_config_store.upsert_model(scope, template, updated_by=updated_by)
    return [DEFAULT_RELAY_MODEL_ID]


def ensure_default_models_for_accounts(
    system_config_store: Any,
    user_ids: Iterable[str],
    *,
    updated_by: str = "system",
) -> dict[str, list[str]]:
    """Backfill account defaults without replacing any saved account model."""

    created: dict[str, list[str]] = {}
    for user_id in user_ids:
        model_ids = ensure_default_models_for_account(system_config_store, user_id, updated_by=updated_by)
        if model_ids:
            created[str(user_id)] = model_ids
    return created


def _configured_default_relay_model(system_config_store: Any) -> dict[str, Any] | None:
    try:
        template = system_config_store.get_model(
            DEFAULT_MODEL_TEMPLATE_SCOPE,
            DEFAULT_RELAY_MODEL_ID,
            reveal_secret=True,
        )
    except Exception:
        template = None
    return template or default_relay_model_from_environment()
