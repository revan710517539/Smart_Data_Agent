from __future__ import annotations

import json
from typing import Any

from backend.platform.security import validate_outbound_url


ALLOWED_ACTIONS = {
    "goto",
    "fill",
    "click",
    "wait",
    "submit_sql",
    "download_csv",
    "search_table",
    "open_metadata",
    "extract_metadata",
    "wait_for_url",
    "collect_system",
    "collect_funnel_analysis",
}
IMMUTABLE_SCRIPT_KEYS = {"query", "readonly_sql", "output_schema", "topic_table", "metric_definitions"}


def validate_browser_script(source: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(source, str):
        try:
            payload = json.loads(source)
        except json.JSONDecodeError as exc:
            raise ValueError("browser_script_must_be_json") from exc
    else:
        payload = dict(source)
    if not isinstance(payload, dict):
        raise ValueError("browser_script_must_be_object")
    if set(payload) - {"version", "steps", "metadata", *IMMUTABLE_SCRIPT_KEYS}:
        raise ValueError("browser_script_unknown_keys")
    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps or len(steps) > 100:
        raise ValueError("browser_script_steps_required")
    normalized_steps: list[dict[str, Any]] = []
    for position, item in enumerate(steps):
        if not isinstance(item, dict):
            raise ValueError(f"browser_step_must_be_object:{position}")
        action = str(item.get("action") or "").strip()
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"browser_action_not_allowed:{action or position}")
        selector = str(item.get("selector") or "").strip()
        if action not in {"goto", "wait", "wait_for_url", "collect_system", "collect_funnel_analysis"} and not selector:
            raise ValueError(f"browser_selector_required:{action}")
        if action == "collect_system":
            profile_id = str(item.get("profile_id") or "").strip()
            if not profile_id:
                raise ValueError("browser_crawler_profile_id_required")
        if action == "goto":
            url = str(item.get("url") or "").strip()
            if url and url not in {"${login_url}", "${query_page_url}"}:
                validate_outbound_url(url)
        timeout_ms = int(item.get("timeout_ms") or 15_000)
        max_timeout_ms = 900_000 if action in {"wait_for_url", "collect_system", "collect_funnel_analysis"} else 60_000
        if timeout_ms < 100 or timeout_ms > max_timeout_ms:
            raise ValueError("browser_step_timeout_out_of_range")
        normalized_steps.append({**item, "action": action, "selector": selector, "timeout_ms": timeout_ms})
    return {**payload, "version": int(payload.get("version") or 1), "steps": normalized_steps}


def validate_repair_candidate(original_source: str, candidate_source: str) -> str:
    original = validate_browser_script(original_source)
    candidate = validate_browser_script(candidate_source)
    for key in IMMUTABLE_SCRIPT_KEYS:
        if original.get(key) != candidate.get(key):
            raise ValueError(f"browser_repair_cannot_change:{key}")
    if len(original["steps"]) != len(candidate["steps"]):
        raise ValueError("browser_repair_cannot_change_step_count")
    for before, after in zip(original["steps"], candidate["steps"], strict=True):
        if before.get("action") != after.get("action"):
            raise ValueError("browser_repair_cannot_change_action_sequence")
        allowed_changes = {"selector", "timeout_ms", "url", "wait_until", "download_name", "column_selectors"}
        for key in set(before) | set(after):
            if key not in allowed_changes and before.get(key) != after.get(key):
                raise ValueError(f"browser_repair_field_not_allowed:{key}")
    return json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
