from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse, urlunparse

import certifi
from backend.platform.security import (
    EgressPolicyError,
    classify_egress_policy_error,
    create_governed_websocket_connection,
)
from websocket import WebSocketBadStatusException, WebSocketException

try:
    from websocket import WebSocketTimeoutException
except ImportError:  # pragma: no cover - older websocket-client
    WebSocketTimeoutException = TimeoutError  # type: ignore[misc,assignment]

# Runtime integration check, not a test module.  Keep the legacy import path but
# exclude it from pytest collection.
__test__ = False


DEFAULT_FUN_ASR_WORKSPACE_ID = "ws-nvbkaw0atdgdbvv7"
DEFAULT_FUN_ASR_MODEL = "fun-asr-realtime"
DEFAULT_FUN_ASR_REGION = "cn-beijing"
DEFAULT_FUN_ASR_SAMPLE_RATE = 16000
_WORKSPACE_HOST_RE = re.compile(r"^ws-[a-z0-9]+$", re.I)
_TRUNCATED_MAAS_RE = re.compile(r"^(ws-[a-z0-9]+)\.(cn-beijing|ap-southeast-1)\.maas$", re.I)


def test_speech_integration(integration: dict[str, Any]) -> dict[str, Any]:
    integration_id = str(integration.get("id") or "").strip()
    name = str(integration.get("name") or "").strip()
    provider = str(integration.get("provider") or "aliyun_fun_asr").strip()
    source = str(integration.get("source") or "阿里云").strip()
    api_base = str(integration.get("apiBase") or "").strip()
    api_key = str(integration.get("apiKey") or "").strip()
    tested_at = datetime.now(timezone.utc).isoformat()
    if not integration_id or not name or not provider or not api_base or not api_key:
        return _result(integration_id, name, provider, source, False, "模型名称、模型来源、API地址和API密钥不能为空。", "", "", tested_at)
    if provider != "aliyun_fun_asr":
        return _result(integration_id, name, provider, source, False, "当前仅支持阿里云 Fun-ASR 语音转文字测试。", "", "", tested_at)
    if _is_demo_speech(integration):
        endpoint = build_fun_asr_endpoint(DEFAULT_FUN_ASR_WORKSPACE_ID, DEFAULT_FUN_ASR_REGION, api_base=api_base)
        result = _result(integration_id, name, provider, source, False, "Demo 密钥只能用于界面演示，未建立真实 Fun-ASR 连接。", endpoint, "", tested_at)
        result.update({"status": "mock", "execution_mode": "mock"})
        return result

    endpoint = ""
    ws = None
    try:
        endpoint = build_fun_asr_endpoint(DEFAULT_FUN_ASR_WORKSPACE_ID, DEFAULT_FUN_ASR_REGION, api_base=api_base)
        ws = create_governed_websocket_connection(
            endpoint,
            timeout=8,
            header=[
                f"Authorization: Bearer {api_key}",
                "User-Agent: SmartDataAgent/1.0 speech-test",
            ],
            ca_certs=certifi.where(),
        )
        task_id = str(uuid.uuid4())
        ws.send(json.dumps(build_run_task_event(task_id, model=DEFAULT_FUN_ASR_MODEL, sample_rate=DEFAULT_FUN_ASR_SAMPLE_RATE), ensure_ascii=False))
        response_preview = _wait_for_task_started(ws)
        try:
            ws.send(json.dumps(build_finish_task_event(task_id), ensure_ascii=False))
        except Exception:
            pass
        result = _result(integration_id, name, provider, source, True, "Fun-ASR 鉴权和任务启动成功。", endpoint, response_preview, tested_at)
        result["error_code"] = ""
        return result
    except WebSocketBadStatusException as exc:
        status_code = int(getattr(exc, "status_code", 0) or 0)
        if status_code in {401, 403}:
            message = f"Fun-ASR 鉴权失败（HTTP {status_code}），请检查 DashScope API Key 是否有效。"
            error_code = "fun_asr_authentication_failed"
        else:
            message = f"Fun-ASR WebSocket 握手失败：HTTP {status_code or 'unknown'}。"
            error_code = "fun_asr_handshake_failed"
        return _failed_result(integration_id, name, provider, source, message, endpoint, tested_at, error_code)
    except EgressPolicyError as exc:
        error_code, message, _transient = _classify_speech_egress_error(exc, endpoint)
        return _failed_result(integration_id, name, provider, source, message, endpoint, tested_at, error_code)
    except (TimeoutError, WebSocketTimeoutException):
        return _failed_result(
            integration_id, name, provider, source,
            "Fun-ASR 连接超时。请检查服务端网络、DNS 和完整 API 地址后重试。",
            endpoint, tested_at, "fun_asr_connection_timeout",
        )
    except WebSocketException as exc:
        return _failed_result(
            integration_id, name, provider, source,
            f"Fun-ASR 连接失败：{str(exc)[:180]}",
            endpoint, tested_at, "fun_asr_connection_error",
        )
    except ValueError as exc:
        return _failed_result(
            integration_id, name, provider, source,
            f"Fun-ASR 地址格式无效：{str(exc)[:180]}",
            endpoint, tested_at, "fun_asr_invalid_url",
        )
    except Exception as exc:
        return _failed_result(
            integration_id, name, provider, source,
            f"Fun-ASR 连通性测试失败：{str(exc)[:180]}",
            endpoint, tested_at, "fun_asr_test_failed",
        )
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass


def _wait_for_task_started(ws: Any) -> str:
    messages: list[str] = []
    for _ in range(8):
        raw = ws.recv()
        text = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else str(raw)
        messages.append(text[:240])
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        header = payload.get("header") if isinstance(payload, dict) else {}
        event = str(header.get("event") or header.get("name") or "").strip() if isinstance(header, dict) else ""
        if event == "task-started":
            return "task-started"
        if event in {"task-failed", "task-finished"}:
            raise RuntimeError(json.dumps(payload, ensure_ascii=False)[:240])
        if "task-started" in text:
            return text[:240]
    raise WebSocketException("已建立连接，但未收到 task-started 事件：" + " | ".join(messages[-2:]))


def build_fun_asr_endpoint(workspace_id: str, region: str = DEFAULT_FUN_ASR_REGION, api_base: str = "") -> str:
    if api_base.strip():
        return dashscope_api_base_to_fun_asr_endpoint(api_base)
    normalized_workspace = (workspace_id or DEFAULT_FUN_ASR_WORKSPACE_ID).strip()
    normalized_region = (region or DEFAULT_FUN_ASR_REGION).strip()
    if normalized_region == "ap-southeast-1":
        return f"wss://{normalized_workspace}.ap-southeast-1.maas.aliyuncs.com/api-ws/v1/inference"
    return f"wss://{normalized_workspace}.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference"


def normalize_fun_asr_api_base(api_base: str) -> str:
    raw = str(api_base or "").strip()
    if not raw:
        return raw
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host:
        return raw
    repaired = host
    if _WORKSPACE_HOST_RE.fullmatch(host):
        repaired = f"{host}.{DEFAULT_FUN_ASR_REGION}.maas.aliyuncs.com"
    else:
        truncated = _TRUNCATED_MAAS_RE.fullmatch(host)
        if truncated:
            repaired = f"{truncated.group(1)}.{truncated.group(2)}.maas.aliyuncs.com"
    if repaired == host:
        return urlunparse(parsed)
    netloc = repaired
    if parsed.port:
        netloc = f"{repaired}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def dashscope_api_base_to_fun_asr_endpoint(api_base: str) -> str:
    parsed = urlparse(normalize_fun_asr_api_base(api_base))
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("DASHSCOPE_API_BASE must be an absolute URL.")
    if parsed.scheme not in {"http", "https", "ws", "wss"}:
        raise ValueError("DASHSCOPE_API_BASE must use http, https, ws or wss.")
    scheme = "wss" if parsed.scheme in {"https", "wss"} else "ws"
    return urlunparse((scheme, parsed.netloc, "/api-ws/v1/inference", "", "", ""))


def _classify_speech_egress_error(exc: EgressPolicyError, endpoint: str) -> tuple[str, str, bool]:
    code, _message, transient = classify_egress_policy_error(exc)
    host = (urlparse(endpoint).hostname or urlparse(str(exc)).hostname or "").rstrip(".")
    detail = str(exc)
    example = "https://ws-xxx.cn-beijing.maas.aliyuncs.com/api/v1"
    if code == "dns_resolution_failed":
        if host.endswith(".maas") and not host.endswith(".maas.aliyuncs.com"):
            hint = f"当前主机名「{host}」缺少 .aliyuncs.com。"
        elif host:
            hint = f"当前解析目标是「{host}」。"
        else:
            hint = ""
        return (
            code,
            f"Fun-ASR 地址域名无法解析。{hint}请填写完整地址，例如 {example}。",
            transient,
        )
    if "not allowlisted" in detail:
        return (
            code,
            f"Fun-ASR 地址不在服务端出站白名单内（{host or '未知主机'}）。请将 *.aliyuncs.com 加入 SMART_DATA_AGENT_EGRESS_ALLOWED_HOSTS。",
            transient,
        )
    if "blocked address" in detail:
        return (
            code,
            f"Fun-ASR 地址解析到内网或本机代理假 IP，已被出站策略拦截（{host or '未知主机'}）。若使用 Clash fake-IP，请将 *.aliyuncs.com 加入 SMART_DATA_AGENT_EGRESS_PRIVATE_HOSTS。",
            transient,
        )
    if "scheme must be" in detail:
        return code, "Fun-ASR 地址协议无效，请使用 https 或 wss 地址。", transient
    return code, f"Fun-ASR 地址不符合服务端出站安全策略（{host or detail[:120]}）。", transient


def _failed_result(
    integration_id: str,
    name: str,
    provider: str,
    source: str,
    message: str,
    endpoint: str,
    tested_at: str,
    error_code: str,
) -> dict[str, Any]:
    result = _result(integration_id, name, provider, source, False, message, endpoint, "", tested_at)
    result["error_code"] = error_code
    return result


def build_run_task_event(
    task_id: str,
    *,
    model: str = DEFAULT_FUN_ASR_MODEL,
    sample_rate: int = DEFAULT_FUN_ASR_SAMPLE_RATE,
) -> dict[str, Any]:
    return {
        "header": {
            "action": "run-task",
            "task_id": task_id,
            "streaming": "duplex",
        },
        "payload": {
            "task_group": "audio",
            "task": "asr",
            "function": "recognition",
            "model": model or DEFAULT_FUN_ASR_MODEL,
            "parameters": {
                "format": "pcm",
                "sample_rate": sample_rate or DEFAULT_FUN_ASR_SAMPLE_RATE,
                "language_hints": ["zh"],
                "heartbeat": True,
            },
            "input": {},
        },
    }


def build_finish_task_event(task_id: str) -> dict[str, Any]:
    return {
        "header": {
            "action": "finish-task",
            "task_id": task_id,
            "streaming": "duplex",
        },
        "payload": {"input": {}},
    }


def _result(
    integration_id: str,
    name: str,
    provider: str,
    source: str,
    callable_: bool,
    message: str,
    endpoint: str,
    response_preview: str,
    tested_at: str,
) -> dict[str, Any]:
    return {
        "integration_id": integration_id,
        "name": name,
        "provider": provider,
        "source": source,
        "callable": callable_,
        "status": "connected" if callable_ else "failed",
        "message": message,
        "endpoint": endpoint,
        "response_preview": response_preview,
        "tested_at": tested_at,
    }


def _is_demo_speech(integration: dict[str, Any]) -> bool:
    api_key = str(integration.get("apiKey") or "").strip().lower()
    api_base = str(integration.get("apiBase") or "").strip().lower()
    return api_key in {"dashscope-demo-key", "demo-key", "demo"} or "example.local" in api_base


test_speech_integration.__test__ = False
