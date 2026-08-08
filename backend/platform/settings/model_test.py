from __future__ import annotations

import json
import hashlib
import os
import socket
import ssl
from time import perf_counter, sleep
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request

import certifi
from backend.platform.security import EgressPolicyError, safe_urlopen

# Runtime integration check; do not let pytest collect the public helper merely
# because this compatibility module ends in ``_test.py``.
__test__ = False


def test_model_integration(model: dict[str, Any]) -> dict[str, Any]:
    model_id = str(model.get("id") or "").strip()
    model_name = str(model.get("name") or "").strip()
    source = str(model.get("modelName") or "中转站").strip() or "中转站"
    api_base = str(model.get("key") or "").strip()
    api_key = str(model.get("value") or "").strip()
    tested_at = datetime.now(timezone.utc).isoformat()
    started_at = perf_counter()
    if not model_id or not model_name or not api_base or not api_key:
        result = _result(model_id, model_name, source, False, "模型名称、API地址和API密钥不能为空。", [], "", tested_at)
        result.update({"error_code": "model_configuration_incomplete", "transient": False, "latency_ms": _elapsed_ms(started_at)})
        return result

    if _is_demo_model(model):
        result = _result(model_id, model_name, source, False, "Demo 密钥只能用于界面演示，未执行真实模型调用。", [], "", tested_at)
        result.update({"status": "mock", "execution_mode": "mock", "error_code": "model_demo_not_executed", "transient": False, "latency_ms": _elapsed_ms(started_at)})
        return result

    deadline = perf_counter() + _model_test_budget_seconds()
    try:
        if source == "中转站":
            models = _fetch_relay_models(api_base, api_key, deadline=deadline)
            if not models:
                result = _result(model_id, model_name, source, False, "接口可访问，但未返回可调用模型。", [], "", tested_at)
                result.update({"error_code": "provider_model_list_empty", "transient": False, "latency_ms": _elapsed_ms(started_at)})
                return result
            used_model, response_text, _usage = _call_first_available_chat(
                api_base,
                api_key,
                model,
                models,
                "你好",
                deadline=deadline,
                max_candidates=3,
            )
            response_preview = response_text[:240]
            result = _result(model_id, model_name, source, True, f"中转站可调用，返回 {len(models)} 个模型，已验证子模型 {used_model}。", models, response_preview, tested_at)
            result["used_model"] = used_model
            result.update({"transient": False, "latency_ms": _elapsed_ms(started_at)})
            return result
        used_model = _first_model_name(model)
        response_text, _usage = _call_chat_completion(api_base, api_key, used_model, "你好", deadline=deadline)
        response_preview = response_text[:240]
        result = _result(model_id, model_name, source, True, "具体模型调用成功。", [used_model], response_preview, tested_at)
        result["used_model"] = used_model
        result.update({"transient": False, "latency_ms": _elapsed_ms(started_at)})
        return result
    except EgressPolicyError as exc:
        error_code, message, transient = _classify_egress_policy_error(exc)
        result = _result(model_id, model_name, source, False, message, [], "", tested_at)
        result.update({"error_code": error_code, "transient": transient, "latency_ms": _elapsed_ms(started_at)})
        return result
    except Exception as exc:
        error_code, message, transient = _classify_model_test_error(exc)
        result = _result(model_id, model_name, source, False, message, [], "", tested_at)
        result.update({"error_code": error_code, "transient": transient, "latency_ms": _elapsed_ms(started_at)})
        return result


def call_model_completion(model: dict[str, Any], prompt: str) -> dict[str, Any]:
    model_id = str(model.get("id") or "").strip()
    model_name = str(model.get("name") or "").strip()
    source = str(model.get("modelName") or "中转站").strip() or "中转站"
    api_base = str(model.get("key") or "").strip()
    api_key = str(model.get("value") or "").strip()
    model_for_call = _first_model_name(model)
    called_at = datetime.now(timezone.utc).isoformat()
    request_hash = _completion_request_hash(model_id, model_for_call, prompt)
    input_tokens = _estimate_tokens(prompt)
    started_at = perf_counter()
    if not model_id or not model_name or not api_base or not api_key:
        return {
            "model_id": model_id,
            "model_name": model_name,
            "source": source,
            "status": "skipped",
            "callable": False,
            "message": "模型名称、API地址和API密钥不能为空。",
            "response_preview": "",
            "used_model": model_for_call,
            "called_at": called_at,
            "request_hash": request_hash,
            "response_hash": "",
            "input_tokens": input_tokens,
            "output_tokens": 0,
            "usage_source": "estimated",
            "latency_ms": _elapsed_ms(started_at),
            "error_code": "model_configuration_incomplete",
        }
    if _is_demo_model(model):
        return {
            "model_id": model_id,
            "model_name": model_name,
            "source": source,
            "status": "mock",
            "callable": False,
            "execution_mode": "mock",
            "message": "Demo 密钥未执行真实模型调用。",
            "response_preview": "",
            "used_model": model_for_call,
            "called_at": called_at,
            "request_hash": request_hash,
            "response_hash": "",
            "input_tokens": input_tokens,
            "output_tokens": 0,
            "usage_source": "estimated",
            "latency_ms": _elapsed_ms(started_at),
            "error_code": "model_demo_not_executed",
        }
    try:
        source_models = _safe_string_list(model.get("enabledModels")) + [
            item for item in _safe_string_list(model.get("availableModels")) if item not in _safe_string_list(model.get("enabledModels"))
        ]
        used_model, response_text, usage = _call_first_available_chat(
            api_base,
            api_key,
            model,
            source_models or [model_for_call],
            prompt,
        )
        response_preview = response_text[:240]
        provider_input_tokens = _safe_nonnegative_int(usage.get("prompt_tokens"))
        provider_output_tokens = _safe_nonnegative_int(usage.get("completion_tokens"))
        return {
            "model_id": model_id,
            "model_name": model_name,
            "source": source,
            "status": "connected",
            "callable": True,
            "message": "模型调用成功。",
            "response_preview": response_preview,
            "used_model": used_model,
            "called_at": called_at,
            "request_hash": _completion_request_hash(model_id, used_model, prompt),
            "response_hash": hashlib.sha256(response_text.encode("utf-8")).hexdigest(),
            "input_tokens": provider_input_tokens or input_tokens,
            "output_tokens": provider_output_tokens or _estimate_tokens(response_text),
            "usage_source": "provider" if provider_input_tokens or provider_output_tokens else "estimated",
            "latency_ms": _elapsed_ms(started_at),
        }
    except EgressPolicyError as exc:
        error_code, message, _transient = _classify_egress_policy_error(exc)
        return {
            "model_id": model_id,
            "model_name": model_name,
            "source": source,
            "status": "failed",
            "callable": False,
            "error_code": error_code,
            "message": message,
            "response_preview": "",
            "used_model": model_for_call,
            "called_at": called_at,
            "request_hash": request_hash,
            "response_hash": "",
            "input_tokens": input_tokens,
            "output_tokens": 0,
            "usage_source": "estimated",
            "latency_ms": _elapsed_ms(started_at),
        }
    except Exception as exc:
        error_code, message, _transient = _classify_model_test_error(exc)
        return {
            "model_id": model_id,
            "model_name": model_name,
            "source": source,
            "status": "failed",
            "callable": False,
            "error_code": error_code,
            "message": message,
            "response_preview": "",
            "used_model": model_for_call,
            "called_at": called_at,
            "request_hash": request_hash,
            "response_hash": "",
            "input_tokens": input_tokens,
            "output_tokens": 0,
            "usage_source": "estimated",
            "latency_ms": _elapsed_ms(started_at),
        }


def call_model_text_completion(
    model: dict[str, Any],
    prompt: str,
    *,
    max_tokens: int = 1200,
) -> dict[str, Any]:
    """Server-only full-text completion for governed generated artifacts.

    Callers must never return ``response_text`` directly to an untrusted client;
    it is intended for validation followed by a separately reviewed artifact.
    """
    model_id = str(model.get("id") or "").strip()
    model_name = str(model.get("name") or "").strip()
    api_base = str(model.get("key") or "").strip()
    api_key = str(model.get("value") or "").strip()
    model_for_call = _first_model_name(model)
    started_at = perf_counter()
    request_hash = _completion_request_hash(model_id, model_for_call, prompt)
    if not model_id or not model_name or not api_base or not api_key:
        return {
            "status": "skipped",
            "error_code": "model_configuration_incomplete",
            "response_text": "",
            "request_hash": request_hash,
            "response_hash": "",
            "latency_ms": _elapsed_ms(started_at),
            "input_tokens": _estimate_tokens(prompt),
            "output_tokens": 0,
            "usage_source": "estimated",
            "model_id": model_id,
            "used_model": model_for_call,
        }
    if _is_demo_model(model):
        return {
            "status": "mock",
            "error_code": "model_demo_not_executed",
            "response_text": "",
            "request_hash": request_hash,
            "response_hash": "",
            "latency_ms": _elapsed_ms(started_at),
            "input_tokens": _estimate_tokens(prompt),
            "output_tokens": 0,
            "usage_source": "estimated",
            "model_id": model_id,
            "used_model": model_for_call,
        }
    try:
        available = _safe_string_list(model.get("availableModels")) or [model_for_call]
        used_model, response_text, usage = _call_first_available_chat(
            api_base,
            api_key,
            model,
            available,
            prompt,
            max_tokens=max_tokens,
        )
        provider_input_tokens = _safe_nonnegative_int(usage.get("prompt_tokens"))
        provider_output_tokens = _safe_nonnegative_int(usage.get("completion_tokens"))
        return {
            "status": "connected",
            "response_text": response_text,
            "request_hash": _completion_request_hash(model_id, used_model, prompt),
            "response_hash": hashlib.sha256(response_text.encode("utf-8")).hexdigest(),
            "latency_ms": _elapsed_ms(started_at),
            "input_tokens": provider_input_tokens or _estimate_tokens(prompt),
            "output_tokens": provider_output_tokens or _estimate_tokens(response_text),
            "usage_source": "provider" if provider_input_tokens or provider_output_tokens else "estimated",
            "model_id": model_id,
            "used_model": used_model,
        }
    except EgressPolicyError as exc:
        error_code, message, _transient = _classify_egress_policy_error(exc)
    except Exception as exc:
        error_code, message, _transient = _classify_model_test_error(exc)
    return {
        "status": "failed",
        "error_code": error_code,
        "message": message,
        "response_text": "",
        "request_hash": request_hash,
        "response_hash": "",
        "latency_ms": _elapsed_ms(started_at),
        "input_tokens": _estimate_tokens(prompt),
        "output_tokens": 0,
        "usage_source": "estimated",
        "model_id": model_id,
        "used_model": model_for_call,
    }


def _result(
    model_id: str,
    model_name: str,
    source: str,
    callable_: bool,
    message: str,
    available_models: list[str],
    response_preview: str,
    tested_at: str,
) -> dict[str, Any]:
    return {
        "model_id": model_id,
        "model_name": model_name,
        "source": source,
        "callable": callable_,
        "status": "connected" if callable_ else "failed",
        "message": message,
        "available_models": available_models,
        "response_preview": response_preview,
        "tested_at": tested_at,
    }


def _classify_egress_policy_error(exc: EgressPolicyError) -> tuple[str, str, bool]:
    detail = str(exc).strip()
    if "cannot be resolved" in detail:
        return (
            "dns_resolution_failed",
            "模型地址域名无法解析：运行 Smart Data Agent 后端的服务器无法解析该地址。请在该服务器接入企业 DNS/VPN，或改用该服务器可解析的企业网关 API 地址后重试。",
            False,
        )
    if "has no resolved address" in detail:
        return (
            "dns_resolution_failed",
            "运行 Smart Data Agent 后端的服务器未获得模型地址的解析结果。请检查企业 DNS/VPN 或网关地址后重试。",
            False,
        )
    if "scheme must be" in detail:
        return "egress_policy_rejected", "模型地址协议不符合服务端出站安全策略，请使用允许的 http/https 地址。", False
    if "blocked address" in detail:
        return "egress_policy_rejected", "模型地址解析到内网或受限地址，已被服务端出站安全策略拦截。", False
    if "not allowlisted" in detail:
        return "egress_policy_rejected", "模型地址不在服务端出站白名单内。", False
    return "egress_policy_rejected", "模型地址不符合服务端出站安全策略。", False


def _egress_policy_message(exc: EgressPolicyError) -> str:
    """Compatibility helper for callers that require the user-facing message."""

    return _classify_egress_policy_error(exc)[1]


def _is_demo_model(model: dict[str, Any]) -> bool:
    api_key = str(model.get("value") or "").strip().lower()
    api_base = str(model.get("key") or "").strip().lower()
    return api_key in {"zetatechs-demo-key", "demo-key", "demo"} or "example.local" in api_base


def _fetch_relay_models(api_base: str, api_key: str, *, deadline: float | None = None) -> list[str]:
    payload = _request_json_from_candidates(_candidate_endpoints(api_base, "/models"), api_key, method="GET", deadline=deadline)
    models: list[str] = []
    data = payload.get("data")
    if isinstance(data, list):
        models.extend(str(item.get("id") or item.get("name") or "").strip() for item in data if isinstance(item, dict))
    for key in ("models", "model_list", "available_models"):
        value = payload.get(key)
        if isinstance(value, list):
            models.extend(str(item.get("id") or item.get("name") or item).strip() for item in value)
    return [model for model in dict.fromkeys(models) if model]


def _call_chat_completion(
    api_base: str,
    api_key: str,
    model_name: str,
    prompt: str,
    max_tokens: int = 128,
    *,
    deadline: float | None = None,
) -> tuple[str, dict[str, Any]]:
    payload = _request_json_from_candidates(
        _candidate_endpoints(api_base, "/chat/completions"),
        api_key,
        method="POST",
        body={
            "model": model_name,
            "messages": [{"role": "user", "content": prompt or "你好"}],
            "temperature": 0,
            "max_tokens": max(1, min(int(max_tokens), 4096)),
        },
        deadline=deadline,
    )
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                return str(message.get("content") or "").strip(), _usage_payload(payload)
            return str(first.get("text") or "").strip(), _usage_payload(payload)
    return json.dumps(payload, ensure_ascii=False), _usage_payload(payload)


def _call_first_available_chat(
    api_base: str,
    api_key: str,
    model: dict[str, Any],
    available_models: list[str],
    prompt: str,
    max_tokens: int = 128,
    *,
    deadline: float | None = None,
    max_candidates: int = 8,
) -> tuple[str, str, dict[str, Any]]:
    preferred = _safe_string_list(model.get("enabledModels"))
    candidates = preferred + [item for item in available_models if item not in preferred]
    errors: list[str] = []
    attempts_per_model = 2 if model.get("strictModelSelection") is True else 1
    for model_name in candidates[:max(1, max_candidates)]:
        for attempt in range(attempts_per_model):
            try:
                response_text, usage = _call_chat_completion(
                    api_base,
                    api_key,
                    model_name,
                    prompt,
                    max_tokens=max_tokens,
                    deadline=deadline,
                )
                return model_name, response_text, usage
            except EgressPolicyError:
                raise
            except Exception as exc:
                errors.append(f"{model_name}[{attempt + 1}]: {str(exc)[:120]}")
                if attempt + 1 < attempts_per_model:
                    sleep(0.25 * (attempt + 1))
    raise RuntimeError("没有可成功调用的子模型：" + "；".join(errors[-4:]))


def _usage_payload(payload: dict[str, Any]) -> dict[str, Any]:
    usage = payload.get("usage")
    return dict(usage) if isinstance(usage, dict) else {}


def _completion_request_hash(model_id: str, model_name: str, prompt: str) -> str:
    canonical = json.dumps(
        {"model_id": model_id, "model_name": model_name, "prompt": prompt},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _estimate_tokens(value: str) -> int:
    # Deterministic fallback for providers that do not expose usage.  It is
    # deliberately labelled as estimated in the audit record.
    normalized = str(value or "")
    return 0 if not normalized else max(1, (len(normalized.encode("utf-8")) + 3) // 4)


def _safe_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))


def _request_json_from_candidates(
    urls: list[str],
    api_key: str,
    *,
    method: str,
    body: dict[str, Any] | None = None,
    deadline: float | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    for url in urls:
        try:
            return _request_json(url, api_key, method=method, body=body, deadline=deadline)
        except EgressPolicyError:
            raise
        except Exception as exc:
            errors.append(str(exc))
            if str(exc) == "provider_timeout":
                break
            continue
    raise RuntimeError(max(errors, key=_provider_error_priority) if errors else "model_provider_unavailable")


def _provider_error_priority(detail: str) -> int:
    normalized = str(detail or "").lower()
    if "user_location_not_supported" in normalized or "billing_required" in normalized:
        return 100
    if "provider_http_401" in normalized or "provider_http_403" in normalized:
        return 90
    if "provider_http_429" in normalized or "provider_http_400" in normalized:
        return 80
    if "provider_timeout" in normalized or "provider_unreachable" in normalized:
        return 70
    if any(f"provider_http_{code}" in normalized for code in range(500, 600)):
        return 60
    if "provider_http_404" in normalized:
        return 10
    return 50


def _request_json(
    url: str,
    api_key: str,
    *,
    method: str,
    body: dict[str, Any] | None = None,
    deadline: float | None = None,
) -> dict[str, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "SmartDataAgent/1.0 model-test",
        },
    )
    request_timeout = _model_request_timeout(method)
    if deadline is not None:
        remaining = deadline - perf_counter()
        if remaining <= 0:
            raise RuntimeError("provider_timeout")
        request_timeout = max(1.0, min(float(request_timeout), remaining, float(_model_test_request_timeout(method))))
    try:
        with safe_urlopen(
            request,
            timeout=request_timeout,
            context=ssl.create_default_context(cafile=certifi.where()),
            allowed_schemes=_model_allowed_schemes(),
        ) as response:
            raw = response.read(256_000)
    except HTTPError as exc:
        marker = _provider_http_error_marker(exc)
        raise RuntimeError(f"provider_http_{exc.code}{f':{marker}' if marker else ''}") from exc
    except URLError as exc:
        if isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout)):
            raise RuntimeError("provider_timeout") from exc
        raise RuntimeError("provider_unreachable") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError("provider_timeout") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("provider_invalid_response") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("接口未返回 JSON 对象。")
    return payload


def _candidate_endpoints(api_base: str, suffix: str) -> list[str]:
    parsed = urlparse(api_base.strip())
    if not parsed.scheme or not parsed.netloc:
        raise RuntimeError("API地址必须是完整 URL。")
    path = parsed.path.rstrip("/")
    candidates: list[str] = []

    def add(next_path: str) -> None:
        url = urlunparse((parsed.scheme, parsed.netloc, next_path, "", "", ""))
        if url not in candidates:
            candidates.append(url)

    if path.endswith(suffix):
        add(path)
    elif path.endswith("/v1") or path.endswith("/api/v1"):
        add(f"{path}{suffix}")
    elif path:
        add(f"{path}{suffix}")
        add(f"{path}/v1{suffix}")
        add(f"{path}/api/v1{suffix}")
    else:
        add(f"/v1{suffix}")
        add(f"/api/v1{suffix}")
        add(suffix)
    return candidates


def _provider_http_error_marker(exc: HTTPError) -> str:
    try:
        payload = json.loads(exc.read(32_000).decode("utf-8", "replace"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return ""
    status = str(error.get("status") or "").strip().lower()
    message = str(error.get("message") or "").strip().lower()
    if "location" in message and ("not supported" in message or "unsupported" in message):
        return "user_location_not_supported"
    if "billing" in message and ("enable" in message or "required" in message):
        return "billing_required"
    return status if status.replace("_", "").isalnum() else ""


def _model_allowed_schemes() -> tuple[str, ...]:
    environment = os.getenv("SMART_DATA_AGENT_ENV", "development").strip().lower()
    allow_http = os.getenv("SMART_DATA_AGENT_ALLOW_HTTP_MODEL_EGRESS", "").strip().lower() in {"1", "true", "yes", "on"}
    if environment == "development" or allow_http:
        return ("https", "http")
    return ("https",)


def _model_request_timeout(method: str) -> int:
    # Planning/final-analysis responses are intentionally richer than the
    # connectivity probe and commonly need more than 30 seconds on relays.
    default_timeout = 60 if str(method).upper() == "POST" else 8
    configured = os.getenv("SMART_DATA_AGENT_MODEL_TIMEOUT_SECONDS", "").strip()
    if not configured:
        return default_timeout
    try:
        return min(max(int(configured), 5), 120)
    except ValueError:
        return default_timeout


def _model_test_budget_seconds() -> int:
    configured = os.getenv("SMART_DATA_AGENT_MODEL_TEST_BUDGET_SECONDS", "").strip()
    if not configured:
        return 50
    try:
        return min(max(int(configured), 15), 55)
    except ValueError:
        return 50


def _model_test_request_timeout(method: str) -> int:
    default_timeout = 18 if str(method).upper() == "POST" else 6
    configured = os.getenv("SMART_DATA_AGENT_MODEL_TEST_REQUEST_TIMEOUT_SECONDS", "").strip()
    if not configured:
        return default_timeout
    try:
        return min(max(int(configured), 3), 30)
    except ValueError:
        return default_timeout


def _classify_model_test_error(exc: Exception) -> tuple[str, str, bool]:
    detail = str(exc).strip().lower()
    if "user_location_not_supported" in detail:
        return "provider_location_unsupported", "Gemini 上游拒绝当前中转站出口地区，请在中转站切换到 Gemini 支持地区，或为对应 Google AI 项目启用支持该地区的计费方案。", False
    if "billing_required" in detail:
        return "provider_billing_required", "Gemini 上游要求启用计费方案，请在 Google AI 项目或中转站账户中完成计费配置后重试。", False
    if "provider_timeout" in detail:
        return "request_timeout", "模型服务在测试时限内未响应，请稍后重试；已保留上次成功配置。", True
    if "provider_http_401" in detail or "provider_http_403" in detail:
        return "authentication_failed", "模型服务鉴权失败，请检查 API 密钥和账号权限。", False
    if "provider_http_429" in detail:
        return "rate_limited", "模型服务请求频率受限，请稍后重试；已保留上次成功配置。", True
    if any(f"provider_http_{code}" in detail for code in range(500, 600)):
        return "provider_unavailable", "模型服务暂时不可用，请稍后重试；已保留上次成功配置。", True
    if "provider_unreachable" in detail:
        return "provider_unreachable", "模型服务当前无法连接，请检查网络后重试；已保留上次成功配置。", True
    if "provider_http_404" in detail:
        return "endpoint_not_found", "模型 API 地址未找到兼容的模型列表或对话接口，请检查地址。", False
    if "provider_http_400" in detail:
        return "provider_request_rejected", "模型服务拒绝了测试请求，请检查子模型是否支持 OpenAI 兼容对话接口。", False
    if "provider_invalid_response" in detail:
        return "invalid_provider_response", "模型服务返回了无法解析的响应，请检查中转站兼容性。", False
    return "model_provider_unavailable", "模型接入测试失败，请通过 request_id 查询服务端日志。", True


def _endpoint(api_base: str, suffix: str) -> str:
    parsed = urlparse(api_base.strip())
    if not parsed.scheme or not parsed.netloc:
        raise RuntimeError("API地址必须是完整 URL。")
    path = parsed.path.rstrip("/")
    if path.endswith(suffix):
        next_path = path
    elif path.endswith("/v1") or path.endswith("/api/v1"):
        next_path = f"{path}{suffix}"
    else:
        next_path = f"{path}{suffix}"
    return urlunparse((parsed.scheme, parsed.netloc, next_path, "", "", ""))


def _first_model_name(model: dict[str, Any]) -> str:
    for key in ("enabledModels", "availableModels"):
        value = model.get(key)
        if isinstance(value, list) and value:
            return str(value[0] or "").strip()
    return str(model.get("name") or "default").strip()


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item or "").strip() for item in value if str(item or "").strip()]


test_model_integration.__test__ = False
