from __future__ import annotations

import base64
import hashlib
import json
import os
import ssl
import struct
import threading
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs, urlparse, urlunparse

import certifi
from websocket import (
    ABNF,
    WebSocketBadStatusException,
    WebSocketConnectionClosedException,
    WebSocketTimeoutException,
    create_connection,
)

from backend.platform.api.support import first_query_value, send_route_exception
from backend.platform.security import EgressPolicyError, validate_outbound_url
from backend.platform.settings import list_models_for_application, normalize_application_module


FUN_ASR_REALTIME_PATH = "/api/asr/fun-asr/realtime"
FUN_ASR_RUNTIME_CONFIG_PATH = "/api/asr/fun-asr/runtime-config"
DEFAULT_FUN_ASR_WORKSPACE_ID = "ws-nvbkaw0atdgdbvv7"
DEFAULT_FUN_ASR_MODEL = "fun-asr-realtime"
DEFAULT_FUN_ASR_REGION = "cn-beijing"
DEFAULT_FUN_ASR_SAMPLE_RATE = 16000
_WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


@dataclass(frozen=True)
class FunAsrConfig:
    endpoint: str
    api_key: str
    model: str
    sample_rate: int
    integration_id: str = ""
    integration_name: str = "阿里云 Fun-ASR"


def handle_fun_asr_realtime_websocket(handler: Any, query: str) -> None:
    params = parse_qs(query)
    try:
        context = handler._request_context(params=params)
        handler._require_application_permission(context, "execute")
        if not _is_websocket_upgrade(handler):
            handler._send_json(
                {
                    "error": "websocket_required",
                    "message": "Fun-ASR realtime transcription must use a WebSocket connection.",
                },
                HTTPStatus.UPGRADE_REQUIRED,
            )
            return
        client = ClientWebSocket.accept(handler)
        FunAsrProxy(handler, client, params, context.tenant_id, context.user_id).run()
    except Exception as exc:
        send_route_exception(handler, exc)


def handle_fun_asr_runtime_config_get(handler: Any, query: str) -> None:
    params = parse_qs(query)
    try:
        context = handler._request_context(params=params)
        handler._require_application_permission(context, "execute")
        integration = _resolve_fun_asr_speech_integration(
            handler,
            context.tenant_id,
            {},
            params,
            context.user_id,
        )
        analysis_models = _resolve_runtime_analysis_models(handler, context.tenant_id, context.user_id)
        if not integration or _is_demo_fun_asr_integration(integration):
            handler._send_json({"available": False, "provider": "aliyun_fun_asr", "integration": None, "analysisModels": analysis_models})
            return
        handler._send_json(
            {
                "available": True,
                "provider": "aliyun_fun_asr",
                "integration": {
                    "id": str(integration.get("id") or ""),
                    "name": str(integration.get("name") or "阿里云 Fun-ASR"),
                    "provider": "aliyun_fun_asr",
                    "status": str(integration.get("status") or "available"),
                    "testStatus": str(integration.get("testStatus") or ""),
                    "applicationModule": _speech_application_module(integration),
                },
                "analysisModels": analysis_models,
            }
        )
    except Exception as exc:
        send_route_exception(handler, exc)


def _resolve_runtime_analysis_models(handler: Any, tenant_id: str, user_id: str) -> list[dict[str, Any]]:
    store = handler.services.system_config_store
    models = list_models_for_application(
        store,
        tenant_id,
        "intelligent_analysis_reasoning",
        user_id=user_id,
        reveal_secret=False,
    )
    deduplicated: dict[str, dict[str, Any]] = {}
    for model in models:
        model_id = str(model.get("id") or "").strip()
        if (
            not model_id
            or str(model.get("status") or "available") not in {"available", "draft"}
        ):
            continue
        current = deduplicated.get(model_id)
        if current:
            continue
        deduplicated[model_id] = {
            "id": model_id,
            "name": str(model.get("name") or ""),
            "modelName": str(model.get("modelName") or ""),
            "key": "",
            "value": "",
            "availableModels": list(model.get("availableModels") or []),
            "enabledModels": list(model.get("enabledModels") or []),
            "applicationModule": str(model.get("applicationModule") or ""),
            "testStatus": str(model.get("testStatus") or "untested"),
            "status": "available",
        }
    return list(deduplicated.values())


def build_fun_asr_endpoint(workspace_id: str, region: str = DEFAULT_FUN_ASR_REGION, api_base: str = "") -> str:
    if api_base.strip():
        return dashscope_api_base_to_fun_asr_endpoint(api_base)
    normalized_workspace = (workspace_id or DEFAULT_FUN_ASR_WORKSPACE_ID).strip()
    normalized_region = (region or DEFAULT_FUN_ASR_REGION).strip()
    if normalized_region == "ap-southeast-1":
        return f"wss://{normalized_workspace}.ap-southeast-1.maas.aliyuncs.com/api-ws/v1/inference"
    return f"wss://{normalized_workspace}.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference"


def dashscope_api_base_to_fun_asr_endpoint(api_base: str) -> str:
    parsed = urlparse(api_base.strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("DASHSCOPE_API_BASE must be an absolute URL.")
    if parsed.scheme not in {"http", "https", "ws", "wss"}:
        raise ValueError("DASHSCOPE_API_BASE must use http, https, ws or wss.")
    scheme = "wss" if parsed.scheme in {"https", "wss"} else "ws"
    return urlunparse((scheme, parsed.netloc, "/api-ws/v1/inference", "", "", ""))


def build_run_task_event(
    task_id: str,
    *,
    model: str = DEFAULT_FUN_ASR_MODEL,
    sample_rate: int = DEFAULT_FUN_ASR_SAMPLE_RATE,
    context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    input_payload: dict[str, Any] = {}
    if context:
        input_payload["context"] = context
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
            },
            "input": input_payload,
        },
    }


def build_continue_task_event(task_id: str, *, context: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    input_payload: dict[str, Any] = {}
    if context:
        input_payload["context"] = context
    return {
        "header": {
            "action": "continue-task",
            "task_id": task_id,
            "streaming": "duplex",
        },
        "payload": {"input": input_payload},
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


def extract_fun_asr_transcript(payload: dict[str, Any]) -> dict[str, Any] | None:
    output = _dict_at(payload, "payload", "output")
    if not output:
        return None
    sentence = output.get("sentence")
    if isinstance(sentence, dict):
        text = str(sentence.get("text") or "").strip()
        if not text:
            return None
        return {
            "type": "transcript",
            "text": text,
            "final": bool(sentence.get("sentence_end")),
            "beginTime": sentence.get("begin_time"),
            "endTime": sentence.get("end_time"),
        }
    text = str(output.get("text") or output.get("transcription") or "").strip()
    if not text:
        return None
    return {"type": "transcript", "text": text, "final": bool(output.get("sentence_end") or output.get("finished"))}


class FunAsrProxy:
    def __init__(self, handler: Any, client: "ClientWebSocket", params: dict[str, list[str]], tenant_id: str, user_id: str) -> None:
        self.handler = handler
        self.client = client
        self.params = params
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.task_id = str(uuid.uuid4())
        self.remote = None
        self.remote_lock = threading.Lock()
        self.remote_reader: threading.Thread | None = None
        self.stopped = threading.Event()
        self.remote_ready = threading.Event()
        self.finish_sent = False

    def run(self) -> None:
        try:
            self.client.send_json({"type": "connected"})
            while not self.stopped.is_set():
                frame = self.client.read_frame()
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    self.client.send_pong(payload)
                    continue
                if opcode == 0x1:
                    self._handle_client_event(payload)
                    continue
                if opcode == 0x2:
                    self._forward_audio(payload)
        except Exception as exc:
            self._send_client_error(_public_fun_asr_error(exc))
        finally:
            self.stopped.set()
            self._finish_remote()
            self._close_remote()
            self.client.close()

    def _handle_client_event(self, payload: bytes) -> None:
        try:
            event = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_client_error("invalid_client_event")
            return
        event_type = str(event.get("type") or "")
        if event_type == "start":
            self._start_remote(event)
        elif event_type == "context":
            self._update_remote_context(event)
        elif event_type == "finish":
            self._finish_remote()
        elif event_type == "ping":
            self.client.send_json({"type": "pong"})

    def _start_remote(self, event: dict[str, Any]) -> None:
        if self.remote is not None:
            return
        sample_rate = _coerce_sample_rate(event.get("sampleRate"))
        config = self._resolve_config(event, sample_rate=sample_rate)
        self.client.send_json(
            {
                "type": "config",
                "provider": "aliyun_fun_asr",
                "integrationId": config.integration_id,
                "integrationName": config.integration_name,
                "model": config.model,
            }
        )
        headers = [
            f"Authorization: Bearer {config.api_key}",
            "user-agent: SmartDataAgent/1.0 Fun-ASR realtime proxy",
        ]
        validate_outbound_url(config.endpoint, allowed_schemes=("wss",))
        self.remote = create_connection(
            config.endpoint,
            header=headers,
            timeout=10,
            sslopt={"cert_reqs": ssl.CERT_REQUIRED, "ca_certs": certifi.where()},
        )
        self.remote.settimeout(1)
        self._remote_send_json(
            build_run_task_event(
                self.task_id,
                model=config.model,
                sample_rate=config.sample_rate,
                context=_normalize_context(event.get("context")),
            )
        )
        self.remote_reader = threading.Thread(target=self._read_remote_events, daemon=True)
        self.remote_reader.start()

    def _update_remote_context(self, event: dict[str, Any]) -> None:
        if self.remote is None or self.finish_sent:
            return
        context = _normalize_context(event.get("context"))
        if not context:
            return
        self._remote_send_json(build_continue_task_event(self.task_id, context=context))

    def _forward_audio(self, payload: bytes) -> None:
        if not payload or self.remote is None or not self.remote_ready.is_set() or self.finish_sent:
            return
        with self.remote_lock:
            self.remote.send(payload, opcode=ABNF.OPCODE_BINARY)

    def _read_remote_events(self) -> None:
        while not self.stopped.is_set() and self.remote is not None:
            try:
                message = self.remote.recv()
            except WebSocketTimeoutException:
                continue
            except WebSocketConnectionClosedException:
                break
            except Exception as exc:
                self._send_client_error(f"fun_asr_connection_error: {exc}")
                break
            if not isinstance(message, str):
                continue
            self._handle_remote_message(message)

    def _handle_remote_message(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return
        header = payload.get("header") if isinstance(payload, dict) else {}
        event = str(header.get("event") or "") if isinstance(header, dict) else ""
        if event == "task-started":
            self.remote_ready.set()
            self.client.send_json({"type": "ready", "taskId": self.task_id})
            return
        if event == "result-generated":
            transcript = extract_fun_asr_transcript(payload)
            if transcript:
                self.client.send_json(transcript)
            return
        if event == "task-finished":
            self.client.send_json({"type": "finished", "taskId": self.task_id})
            self.stopped.set()
            return
        if event == "task-failed":
            message = _first_error_message(payload) or "fun_asr_task_failed"
            self._send_client_error(message)
            self.stopped.set()

    def _finish_remote(self) -> None:
        if self.remote is None or self.finish_sent:
            return
        self.finish_sent = True
        try:
            self._remote_send_json(build_finish_task_event(self.task_id))
        except Exception:
            pass

    def _close_remote(self) -> None:
        if self.remote is None:
            return
        try:
            self.remote.close()
        except Exception:
            pass
        self.remote = None

    def _remote_send_json(self, payload: dict[str, Any]) -> None:
        if self.remote is None:
            return
        with self.remote_lock:
            self.remote.send(json.dumps(payload, ensure_ascii=False), opcode=ABNF.OPCODE_TEXT)

    def _send_client_error(self, message: str) -> None:
        try:
            self.client.send_json({"type": "error", "message": message})
        except Exception:
            pass

    def _resolve_config(self, event: dict[str, Any], *, sample_rate: int) -> FunAsrConfig:
        speech_integration = _resolve_fun_asr_speech_integration(
            self.handler,
            self.tenant_id,
            event,
            self.params,
            self.user_id,
        )
        if event.get("speechIntegrationId") and not speech_integration:
            raise ValueError("fun_asr_configuration_missing: requested speech integration is unavailable.")
        if speech_integration and _is_demo_fun_asr_integration(speech_integration):
            raise ValueError("fun_asr_configuration_invalid: replace the demo Aliyun Fun-ASR credential.")
        api_base = str(
            speech_integration.get("apiBase")
            or os.getenv("DASHSCOPE_API_BASE")
            or ""
        ).strip()
        api_key = _resolve_fun_asr_api_key(self.handler, self.tenant_id, event, self.params, speech_integration)
        if not api_key:
            raise ValueError("dashscope_api_key_missing: configure speech integration API key or DASHSCOPE_API_KEY for Fun-ASR realtime transcription.")
        return FunAsrConfig(
            endpoint=build_fun_asr_endpoint(DEFAULT_FUN_ASR_WORKSPACE_ID, DEFAULT_FUN_ASR_REGION, api_base=api_base),
            api_key=api_key,
            model=DEFAULT_FUN_ASR_MODEL,
            sample_rate=sample_rate,
            integration_id=str(speech_integration.get("id") or "environment:dashscope"),
            integration_name=str(speech_integration.get("name") or "阿里云 Fun-ASR"),
        )


class ClientWebSocket:
    def __init__(self, handler: Any) -> None:
        self.handler = handler
        self.lock = threading.Lock()
        self.closed = False

    @classmethod
    def accept(cls, handler: Any) -> "ClientWebSocket":
        key = handler.headers.get("Sec-WebSocket-Key", "")
        accept_value = base64.b64encode(hashlib.sha1(f"{key}{_WEBSOCKET_GUID}".encode("ascii")).digest()).decode("ascii")
        handler.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
        handler.send_header("Upgrade", "websocket")
        handler.send_header("Connection", "Upgrade")
        handler.send_header("Sec-WebSocket-Accept", accept_value)
        if _has_websocket_protocol(handler, "sda-session"):
            handler.send_header("Sec-WebSocket-Protocol", "sda-session")
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.end_headers()
        return cls(handler)

    def read_frame(self) -> tuple[int, bytes] | None:
        header = self.handler.rfile.read(2)
        if len(header) < 2:
            return None
        first, second = header
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]
        mask = self._read_exact(4) if masked else b""
        payload = self._read_exact(length) if length else b""
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def send_json(self, payload: dict[str, Any]) -> None:
        self._send_frame(0x1, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def send_pong(self, payload: bytes) -> None:
        self._send_frame(0xA, payload)

    def close(self, code: int = 1000, reason: str = "") -> None:
        if self.closed:
            return
        body = struct.pack("!H", code) + reason.encode("utf-8")
        try:
            self._send_frame(0x8, body)
        except Exception:
            pass
        self.closed = True

    def _read_exact(self, length: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < length:
            chunk = self.handler.rfile.read(length - len(chunks))
            if not chunk:
                raise ConnectionError("client_websocket_closed")
            chunks.extend(chunk)
        return bytes(chunks)

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        if self.closed and opcode != 0x8:
            return
        length = len(payload)
        header = bytearray([0x80 | opcode])
        if length < 126:
            header.append(length)
        elif length < (1 << 16):
            header.append(126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(127)
            header.extend(struct.pack("!Q", length))
        with self.lock:
            self.handler.request.sendall(bytes(header) + payload)


def _resolve_fun_asr_api_key(
    handler: Any,
    tenant_id: str,
    event: dict[str, Any],
    params: dict[str, list[str]],
    speech_integration: dict[str, str] | None = None,
) -> str:
    if speech_integration:
        api_key = str(speech_integration.get("apiKey") or "").strip()
        if api_key:
            return api_key
    return os.getenv("DASHSCOPE_API_KEY", "").strip()


def _resolve_fun_asr_speech_integration(
    handler: Any,
    tenant_id: str,
    event: dict[str, Any],
    params: dict[str, list[str]],
    user_id: str = "",
) -> dict[str, str]:
    list_integrations = getattr(handler.services.system_config_store, "list_speech_integrations", None)
    if not callable(list_integrations):
        return {}
    requested_id = str(event.get("speechIntegrationId") or first_query_value(params, "speech_integration_id") or "").strip()
    requested_module = str(event.get("applicationModule") or first_query_value(params, "application_module") or "").strip()
    if requested_module:
        requested_module = normalize_application_module(requested_module, allow_empty=False)
    integrations = list_integrations(tenant_id, reveal_secret=True)
    list_owned = getattr(handler.services.system_config_store, "list_speech_integrations_owned_by", None)
    if user_id and callable(list_owned):
        owned = list_owned(user_id, tenant_id, reveal_secret=True)
        seen = {(str(item.get("id") or ""), str(item.get("apiKey") or "")) for item in integrations}
        integrations.extend(
            item
            for item in owned
            if (str(item.get("id") or ""), str(item.get("apiKey") or "")) not in seen
        )
    candidates = [
        integration
        for integration in integrations
        if str(integration.get("provider") or "") == "aliyun_fun_asr"
        and str(integration.get("status") or "available") in {"available", "draft"}
        and (not requested_module or requested_module == _speech_application_module(integration))
    ]
    if requested_id:
        for integration in candidates:
            if integration.get("id") == requested_id:
                return integration
        return {}
    candidates.sort(
        key=lambda integration: (
            1 if _is_demo_fun_asr_integration(integration) else 0,
            str(integration.get("id") or ""),
        )
    )
    return candidates[0] if candidates else {}


def _speech_application_module(integration: dict[str, Any]) -> str:
    direct = str(integration.get("applicationModule") or integration.get("application_module") or "").strip()
    legacy = integration.get("applicationModules") or integration.get("application_modules") or []
    legacy_first = next((str(item).strip() for item in legacy if str(item).strip()), "") if isinstance(legacy, (list, tuple)) else ""
    return normalize_application_module(direct or legacy_first or "realtime_voice_input", allow_empty=False)


def _is_demo_fun_asr_integration(integration: dict[str, Any]) -> bool:
    api_key = str(integration.get("apiKey") or "").strip().lower()
    api_base = str(integration.get("apiBase") or "").strip().lower()
    return api_key in {"dashscope-demo-key", "demo-key", "demo"} or "example.local" in api_base


def _public_fun_asr_error(exc: Exception) -> str:
    detail = str(exc or "").strip()
    if "fun_asr_configuration_not_verified" in detail or "fun_asr_configuration_invalid" in detail:
        return "fun_asr_configuration_invalid"
    if "dashscope_api_key_missing" in detail or "fun_asr_configuration_missing" in detail:
        return "fun_asr_configuration_missing"
    if isinstance(exc, EgressPolicyError):
        return "fun_asr_egress_rejected"
    if isinstance(exc, WebSocketBadStatusException):
        status_code = int(getattr(exc, "status_code", 0) or 0)
        if status_code in {401, 403}:
            return "fun_asr_authentication_failed"
        return f"fun_asr_handshake_failed:{status_code or 'unknown'}"
    if isinstance(exc, (TimeoutError, WebSocketTimeoutException)):
        return "fun_asr_connection_timeout"
    if "demo" in detail.lower():
        return "fun_asr_configuration_invalid"
    if "Name or service not known" in detail or "nodename nor servname" in detail:
        return "fun_asr_dns_failed"
    return "fun_asr_proxy_failed"


def _is_websocket_upgrade(handler: Any) -> bool:
    connection = handler.headers.get("Connection", "").lower()
    upgrade = handler.headers.get("Upgrade", "").lower()
    return "upgrade" in connection and upgrade == "websocket" and bool(handler.headers.get("Sec-WebSocket-Key"))


def _has_websocket_protocol(handler: Any, protocol: str) -> bool:
    protocols = [item.strip() for item in handler.headers.get("Sec-WebSocket-Protocol", "").split(",")]
    return protocol in protocols


def _coerce_sample_rate(value: Any) -> int:
    try:
        sample_rate = int(value or DEFAULT_FUN_ASR_SAMPLE_RATE)
    except (TypeError, ValueError):
        return DEFAULT_FUN_ASR_SAMPLE_RATE
    return sample_rate if sample_rate > 0 else DEFAULT_FUN_ASR_SAMPLE_RATE


def _normalize_context(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    user_count = 0
    assistant_count = 0
    for item in value[-12:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        if role == "user" and user_count >= 5:
            continue
        if role == "assistant" and assistant_count >= 5:
            continue
        content_type = "input_text" if role == "user" else "text"
        text = _context_text(item).strip()
        if not text:
            continue
        normalized.append(
            {
                "role": role,
                "content": [
                    {
                        "type": content_type,
                        "text": text[:400],
                    }
                ],
            }
        )
        if role == "user":
            user_count += 1
        else:
            assistant_count += 1
    return normalized


def _context_text(item: dict[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for entry in content:
            if isinstance(entry, dict):
                texts.append(str(entry.get("text") or ""))
        return " ".join(texts)
    return str(item.get("text") or "")


def _dict_at(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _first_error_message(payload: dict[str, Any]) -> str:
    for container in (payload.get("header"), payload.get("payload")):
        if isinstance(container, dict):
            for key in ("message", "error_message", "error"):
                value = str(container.get(key) or "").strip()
                if value:
                    return value
    return ""
