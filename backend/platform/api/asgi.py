from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import os
import ssl
import uuid
from email.message import Message
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs

import certifi
from websocket import ABNF, WebSocketConnectionClosedException, WebSocketTimeoutException

from backend.platform.automation import AutomationWorker
from backend.platform.bootstrap import PlatformServices, build_local_platform, build_production_platform
from backend.platform.runtime_config import load_runtime_config
from backend.platform.security import create_governed_websocket_connection

from .routes.asr import (
    FUN_ASR_REALTIME_PATH,
    FunAsrProxy,
    build_continue_task_event,
    build_finish_task_event,
    build_run_task_event,
    extract_fun_asr_transcript,
    _coerce_sample_rate,
    _first_error_message,
    _normalize_context,
)
from .server import AnalysisAPIHandler
from .support import MAX_UPLOAD_BODY_BYTES
from backend.platform.runtime_config import cors_origin_for_request


ASGIReceive = Callable[[], Awaitable[dict[str, Any]]]
ASGISend = Callable[[dict[str, Any]], Awaitable[None]]


def _scope_header(scope: dict[str, Any], expected_name: str) -> str:
    expected = expected_name.lower().encode("ascii")
    for name, value in scope.get("headers") or []:
        if bytes(name).lower() == expected:
            return bytes(value).decode("latin-1")
    return ""


def _select_precompressed_static_asset(candidate: Path, accept_encoding: str) -> tuple[Path, str | None]:
    accepted = _accepted_content_encodings(accept_encoding)
    selected: tuple[Path, str | None] = (candidate, None)
    selected_quality = 0.0
    for content_encoding, suffix in (("br", ".br"), ("gzip", ".gz")):
        variant = candidate.with_name(candidate.name + suffix)
        quality = accepted.get(content_encoding, accepted.get("*", 0.0))
        if quality > selected_quality and variant.is_file():
            selected = (variant, content_encoding)
            selected_quality = quality
    return selected


def _has_precompressed_static_asset(candidate: Path) -> bool:
    return any(candidate.with_name(candidate.name + suffix).is_file() for suffix in (".br", ".gz"))


def _accepted_content_encodings(value: str) -> dict[str, float]:
    accepted: dict[str, float] = {}
    for item in value.lower().split(","):
        parts = [part.strip() for part in item.split(";")]
        if not parts or not parts[0]:
            continue
        quality = 1.0
        for parameter in parts[1:]:
            if parameter.startswith("q="):
                try:
                    quality = max(0.0, min(float(parameter[2:]), 1.0))
                except ValueError:
                    quality = 0.0
        accepted[parts[0]] = quality
    return accepted


class ASGIRequestAdapter(AnalysisAPIHandler):
    """Run the existing governed route boundary without a ThreadingHTTPServer.

    This adapter keeps the route contracts stable while deployment moves to an
    ASGI process manager. Each synchronous business handler is isolated in the
    ASGI server's worker thread, so it does not block the event loop.
    """

    def __init__(
        self,
        services: PlatformServices,
        method: str,
        raw_path: str,
        query_string: bytes,
        headers: list[tuple[bytes, bytes]],
        body: bytes,
        client: tuple[str, int] | None,
        automation_worker: AutomationWorker | None = None,
    ) -> None:
        self.services = services
        self.command = method.upper()
        query = query_string.decode("ascii", errors="ignore")
        self.path = raw_path + (f"?{query}" if query else "")
        self.request_version = "HTTP/1.1"
        self.client_address = client or ("unknown", 0)
        self.server = SimpleNamespace(automation_worker=automation_worker)
        self.rfile = BytesIO(body)
        self.wfile = BytesIO()
        self.headers = Message()
        for name, value in headers:
            self.headers.add_header(
                name.decode("latin-1"),
                value.decode("latin-1"),
            )
        if self.headers.get("Content-Length") is None:
            self.headers["Content-Length"] = str(len(body))
        self.response_status = int(HTTPStatus.OK)
        self.response_headers: list[tuple[str, str]] = []
        self._headers_finished = False

    def send_response(self, code: int | HTTPStatus, message: str | None = None) -> None:
        del message
        self.response_status = int(code)

    def send_header(self, keyword: str, value: str) -> None:
        self.response_headers.append((str(keyword), str(value)))

    def end_headers(self) -> None:
        self._headers_finished = True

    def dispatch(self) -> tuple[int, list[tuple[str, str]], bytes]:
        handler = getattr(self, f"do_{self.command}", None)
        if not callable(handler):
            self._send_json({"error": "method_not_allowed"}, HTTPStatus.METHOD_NOT_ALLOWED)
        else:
            handler()
        return self.response_status, self.response_headers, self.wfile.getvalue()


class SmartDataAgentASGI:
    def __init__(
        self,
        services: PlatformServices,
        *,
        owns_services: bool = True,
        static_root: str | Path | None = None,
    ) -> None:
        self.services = services
        self.owns_services = owns_services
        embedded_default = not services.runtime_config.is_production
        embedded_enabled = os.getenv("SMART_DATA_AGENT_EMBEDDED_WORKER", "true" if embedded_default else "false").strip().lower() in {"1", "true", "yes"}
        self.worker = AutomationWorker(services.automation_runtime) if embedded_enabled else None
        self._started = False
        self.static_root = Path(static_root).resolve() if static_root else None

    async def __call__(self, scope: dict[str, Any], receive: ASGIReceive, send: ASGISend) -> None:
        scope_type = scope.get("type")
        if scope_type == "lifespan":
            await self._lifespan(receive, send)
            return
        if scope_type == "websocket":
            await self._websocket(scope, receive, send)
            return
        if scope_type != "http":
            await self._unsupported_scope(send)
            return
        if (
            str(scope.get("method") or "GET").upper() in {"GET", "HEAD"}
            and not str(scope.get("path") or "/").startswith(("/api/", "/mcp"))
            and self.static_root is not None
        ):
            static = await asyncio.to_thread(
                self._read_static,
                str(scope.get("path") or "/"),
                _scope_header(scope, "accept-encoding"),
            )
            if static is not None:
                status, headers, response_body = static
                await send({"type": "http.response.start", "status": status, "headers": headers})
                await send(
                    {
                        "type": "http.response.body",
                        "body": b"" if str(scope.get("method") or "GET").upper() == "HEAD" else response_body,
                    }
                )
                return
        body = await _read_body(receive)
        adapter = ASGIRequestAdapter(
            self.services,
            str(scope.get("method") or "GET"),
            str(scope.get("path") or "/"),
            bytes(scope.get("query_string") or b""),
            list(scope.get("headers") or []),
            body,
            scope.get("client"),
            self.worker,
        )
        status, headers, response_body = await asyncio.to_thread(adapter.dispatch)
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (name.lower().encode("latin-1"), value.encode("latin-1"))
                    for name, value in headers
                ],
            }
        )
        await send({"type": "http.response.body", "body": response_body})

    async def _websocket(self, scope: dict[str, Any], receive: ASGIReceive, send: ASGISend) -> None:
        connected = await receive()
        if connected.get("type") != "websocket.connect":
            await send({"type": "websocket.close", "code": 1002, "reason": "websocket_connect_required"})
            return
        path = str(scope.get("path") or "")
        if path != FUN_ASR_REALTIME_PATH:
            await send({"type": "websocket.close", "code": 1008, "reason": "websocket_route_not_found"})
            return
        raw_headers = list(scope.get("headers") or [])
        header_map = {
            name.decode("latin-1").lower(): value.decode("latin-1")
            for name, value in raw_headers
        }
        origin = header_map.get("origin")
        if not origin and self.services.runtime_config.environment in {"staging", "production"}:
            await send({"type": "websocket.close", "code": 1008, "reason": "websocket_origin_required"})
            return
        if origin and cors_origin_for_request(origin, self.services.runtime_config) is None:
            await send({"type": "websocket.close", "code": 1008, "reason": "websocket_origin_denied"})
            return
        query_string = bytes(scope.get("query_string") or b"")
        params = parse_qs(query_string.decode("ascii", errors="ignore"))
        adapter = ASGIRequestAdapter(
            self.services,
            "GET",
            path,
            query_string,
            raw_headers,
            b"",
            scope.get("client"),
            self.worker,
        )
        try:
            context = adapter._request_context(params=params)
            adapter._require_application_permission(context, "execute")
        except Exception:
            await send({"type": "websocket.close", "code": 1008, "reason": "websocket_auth_failed"})
            return
        protocols = [str(item) for item in scope.get("subprotocols") or []]
        await send(
            {
                "type": "websocket.accept",
                "subprotocol": "sda-session" if "sda-session" in protocols else None,
                "headers": [
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ],
            }
        )
        session = ASGIFunASRSession(adapter, params, context.tenant_id, context.user_id, receive, send)
        await session.run()

    async def _lifespan(self, receive: ASGIReceive, send: ASGISend) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                if not self._started:
                    if self.worker is not None:
                        self.worker.start()
                    self._started = True
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                if self._started:
                    if self.worker is not None:
                        self.worker.close()
                    self._started = False
                if self.owns_services:
                    self.services.close()
                await send({"type": "lifespan.shutdown.complete"})
                return

    @staticmethod
    async def _unsupported_scope(send: ASGISend) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": int(HTTPStatus.NOT_IMPLEMENTED),
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b'{"error":"unsupported_asgi_scope"}'})

    def _read_static(
        self,
        request_path: str,
        accept_encoding: str = "",
    ) -> tuple[int, list[tuple[bytes, bytes]], bytes] | None:
        if self.static_root is None or not self.static_root.is_dir():
            return None
        relative = request_path.lstrip("/") or "index.html"
        candidate = (self.static_root / relative).resolve()
        try:
            candidate.relative_to(self.static_root)
        except ValueError:
            return (int(HTTPStatus.FORBIDDEN), [(b"content-type", b"text/plain")], b"forbidden")
        if not candidate.is_file():
            candidate = self.static_root / "index.html"
        if not candidate.is_file():
            return None
        selected, content_encoding = _select_precompressed_static_asset(candidate, accept_encoding)
        body = selected.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        cache_control = "public, max-age=31536000, immutable" if candidate.name != "index.html" else "no-cache"
        headers: list[tuple[bytes, bytes]] = [
            (b"content-type", content_type.encode("ascii")),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"cache-control", cache_control.encode("ascii")),
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
        ]
        if content_encoding:
            headers.append((b"content-encoding", content_encoding.encode("ascii")))
        if content_encoding or _has_precompressed_static_asset(candidate):
            headers.append((b"vary", b"Accept-Encoding"))
        return (
            int(HTTPStatus.OK),
            headers,
            body,
        )


class ASGIFunASRSession:
    """ASGI-native client side of the existing governed Fun-ASR proxy contract."""

    def __init__(
        self,
        handler: ASGIRequestAdapter,
        params: dict[str, list[str]],
        tenant_id: str,
        user_id: str,
        receive: ASGIReceive,
        send: ASGISend,
    ) -> None:
        self.handler = handler
        self.params = params
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.receive = receive
        self.send = send
        self.task_id = str(uuid.uuid4())
        self.remote: Any | None = None
        self.remote_ready = asyncio.Event()
        self.stopped = asyncio.Event()
        self.finish_sent = False
        self.reader_task: asyncio.Task | None = None
        self.send_lock = asyncio.Lock()
        self.remote_send_lock = asyncio.Lock()

    async def run(self) -> None:
        await self._send_json({"type": "connected"})
        try:
            async with asyncio.timeout(1800):
                while not self.stopped.is_set():
                    message = await self.receive()
                    message_type = message.get("type")
                    if message_type == "websocket.disconnect":
                        break
                    if message_type != "websocket.receive":
                        continue
                    text = message.get("text")
                    binary = message.get("bytes")
                    if text is not None:
                        await self._handle_event(str(text))
                    elif isinstance(binary, bytes):
                        if len(binary) > 1_048_576:
                            await self._send_error("audio_frame_too_large")
                            break
                        await self._forward_audio(binary)
        except TimeoutError:
            await self._send_error("fun_asr_session_timeout")
        except Exception:
            await self._send_error("fun_asr_proxy_failed")
        finally:
            self.stopped.set()
            await self._finish_remote()
            if self.reader_task:
                self.reader_task.cancel()
                await asyncio.gather(self.reader_task, return_exceptions=True)
            await self._close_remote()
            async with self.send_lock:
                try:
                    await self.send({"type": "websocket.close", "code": 1000})
                except Exception:
                    pass

    async def _handle_event(self, raw: str) -> None:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            await self._send_error("invalid_client_event")
            return
        if not isinstance(event, dict):
            await self._send_error("invalid_client_event")
            return
        event_type = str(event.get("type") or "")
        if event_type == "start":
            await self._start_remote(event)
        elif event_type == "context":
            context = _normalize_context(event.get("context"))
            if self.remote is not None and context and not self.finish_sent:
                await self._remote_send_json(build_continue_task_event(self.task_id, context=context))
        elif event_type == "finish":
            await self._finish_remote()
        elif event_type == "ping":
            await self._send_json({"type": "pong"})
        else:
            await self._send_error("unsupported_client_event")

    async def _start_remote(self, event: dict[str, Any]) -> None:
        if self.remote is not None:
            return
        resolver = FunAsrProxy(self.handler, None, self.params, self.tenant_id, self.user_id)
        config = resolver._resolve_config(event, sample_rate=_coerce_sample_rate(event.get("sampleRate")))
        headers = [
            f"Authorization: Bearer {config.api_key}",
            "user-agent: SmartDataAgent/1.0 Fun-ASR realtime ASGI proxy",
        ]
        # Production ASGI must use the same governed transport as the local
        # HTTP proxy. websocket-client create_connection inherits HTTP(S)_PROXY
        # and that TLS path is what surfaces as a browser reconnect banner.
        self.remote = await asyncio.to_thread(
            create_governed_websocket_connection,
            config.endpoint,
            timeout=10,
            header=headers,
            ca_certs=certifi.where(),
        )
        self.remote.settimeout(1)
        await self._remote_send_json(
            build_run_task_event(
                self.task_id,
                model=config.model,
                sample_rate=config.sample_rate,
                context=_normalize_context(event.get("context")),
            )
        )
        self.reader_task = asyncio.create_task(self._read_remote_events())

    async def _forward_audio(self, payload: bytes) -> None:
        if not payload or self.remote is None or not self.remote_ready.is_set() or self.finish_sent:
            return
        async with self.remote_send_lock:
            await asyncio.to_thread(self.remote.send, payload, opcode=ABNF.OPCODE_BINARY)

    async def _read_remote_events(self) -> None:
        while not self.stopped.is_set() and self.remote is not None:
            try:
                message = await asyncio.to_thread(self.remote.recv)
            except WebSocketTimeoutException:
                continue
            except WebSocketConnectionClosedException:
                return
            except Exception:
                await self._send_error("fun_asr_connection_error")
                self.stopped.set()
                return
            if not isinstance(message, str):
                continue
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                continue
            header = payload.get("header") if isinstance(payload, dict) else {}
            event = str(header.get("event") or "") if isinstance(header, dict) else ""
            if event == "task-started":
                self.remote_ready.set()
                await self._send_json({"type": "ready", "taskId": self.task_id})
            elif event == "result-generated":
                transcript = extract_fun_asr_transcript(payload)
                if transcript:
                    await self._send_json(transcript)
            elif event == "task-finished":
                await self._send_json({"type": "finished", "taskId": self.task_id})
                self.stopped.set()
            elif event == "task-failed":
                await self._send_error(_first_error_message(payload) or "fun_asr_task_failed")
                self.stopped.set()

    async def _finish_remote(self) -> None:
        if self.remote is None or self.finish_sent:
            return
        self.finish_sent = True
        try:
            await self._remote_send_json(build_finish_task_event(self.task_id))
        except Exception:
            pass

    async def _close_remote(self) -> None:
        if self.remote is None:
            return
        remote = self.remote
        self.remote = None
        try:
            await asyncio.to_thread(remote.close)
        except Exception:
            pass

    async def _remote_send_json(self, payload: dict[str, Any]) -> None:
        if self.remote is None:
            return
        serialized = json.dumps(payload, ensure_ascii=False)
        async with self.remote_send_lock:
            await asyncio.to_thread(self.remote.send, serialized, opcode=ABNF.OPCODE_TEXT)

    async def _send_json(self, payload: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.send({"type": "websocket.send", "text": json.dumps(payload, ensure_ascii=False)})

    async def _send_error(self, message: str) -> None:
        try:
            await self._send_json({"type": "error", "message": message})
        except Exception:
            pass


async def _read_body(receive: ASGIReceive) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        message = await receive()
        if message.get("type") != "http.request":
            continue
        chunk = bytes(message.get("body") or b"")
        size += len(chunk)
        if size > MAX_UPLOAD_BODY_BYTES:
            # Preserve the same stable oversized-body response path by giving
            # the route boundary a body whose declared length exceeds its cap.
            return b" " * (MAX_UPLOAD_BODY_BYTES + 1)
        chunks.append(chunk)
        if not message.get("more_body", False):
            return b"".join(chunks)


def create_application(
    test_sqlite_db: str | None = None,
    static_root: str | Path | None = None,
) -> SmartDataAgentASGI:
    configured_static_root = static_root or os.getenv("SMART_DATA_AGENT_STATIC_ROOT", "").strip() or None
    services = (
        build_local_platform(db_path=test_sqlite_db)
        if test_sqlite_db is not None
        else build_production_platform(load_runtime_config())
    )
    return SmartDataAgentASGI(services, static_root=configured_static_root)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Smart Data Agent with an ASGI process server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--test-sqlite-db", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--static-root", default=os.getenv("SMART_DATA_AGENT_STATIC_ROOT", "dist"))
    args = parser.parse_args()
    import uvicorn

    runtime_config = load_runtime_config()
    if args.test_sqlite_db is None:
        os.environ["SMART_DATA_AGENT_STATIC_ROOT"] = args.static_root
        uvicorn.run(
            "backend.platform.api.asgi:create_application",
            factory=True,
            host=args.host,
            port=args.port,
            workers=max(1, args.workers),
            access_log=True,
            proxy_headers=True,
        )
    else:
        if args.workers != 1:
            raise SystemExit("The explicit SQLite test adapter requires --workers 1")
        uvicorn.run(
            create_application(args.test_sqlite_db, args.static_root),
            host=args.host,
            port=args.port,
            workers=1,
            access_log=True,
            proxy_headers=True,
        )


if __name__ == "__main__":
    main()
