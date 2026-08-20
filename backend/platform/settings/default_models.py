from __future__ import annotations

import os
from typing import Any, Iterable

from backend.authz import SUPER_ADMIN_USER_ID

from .store import account_system_config_scope


DEFAULT_RELAY_MODEL_ID = "model_default_intelligent_analysis_relay"
DEFAULT_RELAY_MODEL_API_BASE = "https://litellm-dev.sandbox.deepbank.daikuan.qihoo.net"
DEFAULT_RELAY_MODEL_API_KEY_ENV = "SMART_DATA_AGENT_DEFAULT_MODEL_API_KEY"
DEFAULT_MODEL_TEMPLATE_SCOPE = "system:default-model-template"
DEFAULT_RELAY_SHARED_MODELS = (
    "360/deepseek-v4-flash",
    "360/deepseek-v4-pro",
    "deepbank/glm-5.2",
    "glm-5.2-codex",
    "gpt-5.5",
)


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


def default_relay_model_preset() -> dict[str, Any]:
    """Return a display-only safe preset when no protected credential exists."""

    return {**_default_relay_model(""), "requiresCredential": True}


def _default_relay_model(api_key: str, *, api_base: str | None = None) -> dict[str, Any]:
    return {
        "id": DEFAULT_RELAY_MODEL_ID,
        "name": "默认模型",
        "modelName": "中转站",
        "key": str(api_base or os.getenv("SMART_DATA_AGENT_DEFAULT_MODEL_API_BASE", DEFAULT_RELAY_MODEL_API_BASE)).strip()
        or DEFAULT_RELAY_MODEL_API_BASE,
        "value": api_key,
        "applicationModule": "global_text_model",
        "availableModels": list(DEFAULT_RELAY_SHARED_MODELS),
        "enabledModels": list(DEFAULT_RELAY_SHARED_MODELS),
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
    existing = system_config_store.get_model(scope, DEFAULT_RELAY_MODEL_ID, reveal_secret=True)
    if existing is not None:
        # Keep the display identity of the system default, but never clobber an
        # account-edited API address, secret, or last successful probe result.
        canonical = _canonical_default_relay(_account_owned_default_relay(existing, template))
        if any(existing.get(key) != canonical.get(key) for key in ("name", "modelName", "applicationModule")):
            system_config_store.upsert_model(scope, canonical, updated_by=updated_by)
        return []
    system_config_store.upsert_model(scope, template, updated_by=updated_by)
    return [DEFAULT_RELAY_MODEL_ID]


def ensure_default_models_for_accounts(
    system_config_store: Any,
    user_ids: Iterable[str],
    *,
    updated_by: str = "system",
) -> dict[str, list[str]]:
    """Backfill and reconcile the protected default relay for known accounts."""

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
    if not _is_usable_default_relay(template):
        template = _promote_connected_super_admin_default(system_config_store) or template
    configured = template or default_relay_model_from_environment()
    if configured is None:
        return None
    canonical = _canonical_default_relay(configured)
    # Keep the protected template's display identity in sync. URL and secret
    # stay on the stored template so an operator can change the install default.
    if isinstance(template, dict) and any(
        template.get(key) != canonical.get(key)
        for key in ("name", "modelName", "applicationModule")
    ):
        try:
            system_config_store.upsert_model(
                DEFAULT_MODEL_TEMPLATE_SCOPE,
                canonical,
                updated_by=SUPER_ADMIN_USER_ID,
            )
        except Exception:
            pass
    return canonical


def _canonical_default_relay(model: dict[str, Any]) -> dict[str, Any]:
    """Normalize the protected relay while retaining its URL, secret, and probe state."""

    available_models = [str(item).strip() for item in model.get("availableModels") or [] if str(item).strip()]
    enabled_models = [str(item).strip() for item in model.get("enabledModels") or [] if str(item).strip()]
    if not available_models:
        available_models = list(DEFAULT_RELAY_SHARED_MODELS)
    if not enabled_models:
        enabled_models = [item for item in DEFAULT_RELAY_SHARED_MODELS if item in available_models]
    api_base = str(model.get("key") or "").strip() or DEFAULT_RELAY_MODEL_API_BASE
    return {
        **model,
        "id": DEFAULT_RELAY_MODEL_ID,
        "name": "默认模型",
        "modelName": "中转站",
        "key": api_base,
        "applicationModule": "global_text_model",
        "availableModels": available_models,
        "enabledModels": enabled_models,
    }


def _account_owned_default_relay(existing: dict[str, Any], template: dict[str, Any]) -> dict[str, Any]:
    """Prefer account-edited credentials over the install-wide seed."""

    merged = dict(template)
    for field in ("key", "value"):
        current = str(existing.get(field) or "").strip()
        if current:
            merged[field] = current
    for field in ("availableModels", "enabledModels", "testStatus", "testMessage", "testResponse", "lastTestedAt", "status"):
        if existing.get(field) not in (None, "", []):
            merged[field] = existing.get(field)
    return merged


def _is_usable_default_relay(model: dict[str, Any] | None) -> bool:
    if not isinstance(model, dict):
        return False
    if str(model.get("id") or "") != DEFAULT_RELAY_MODEL_ID:
        return False
    if str(model.get("status") or "") != "available" or str(model.get("testStatus") or "") != "connected":
        return False
    if not str(model.get("key") or "").strip() or not str(model.get("value") or "").strip():
        return False
    return any(str(item or "").strip() for item in [*(model.get("enabledModels") or []), *(model.get("availableModels") or [])])


def _promote_connected_super_admin_default(system_config_store: Any) -> dict[str, Any] | None:
    """Recover an older blank template from the sole global administrator's relay.

    Earlier local builds stored the real default under the global
    administrator's account but left the system template as an empty draft.
    Only the fixed global-super-admin account is eligible as the migration
    source, so an ordinary account cannot become a system-wide model source.
    """

    try:
        source = system_config_store.get_model(
            account_system_config_scope(SUPER_ADMIN_USER_ID),
            DEFAULT_RELAY_MODEL_ID,
            reveal_secret=True,
        )
    except Exception:
        return None
    if not _is_usable_default_relay(source):
        return None
    canonical = _canonical_default_relay(source)
    try:
        system_config_store.upsert_model(
            DEFAULT_MODEL_TEMPLATE_SCOPE,
            canonical,
            updated_by=SUPER_ADMIN_USER_ID,
        )
        return system_config_store.get_model(
            DEFAULT_MODEL_TEMPLATE_SCOPE,
            DEFAULT_RELAY_MODEL_ID,
            reveal_secret=True,
        )
    except Exception:
        return None
