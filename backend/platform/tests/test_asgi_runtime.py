from __future__ import annotations

import asyncio
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from backend.platform.api.asgi import SmartDataAgentASGI
from backend.platform.bootstrap import build_local_platform
from backend.platform.tests.governed_warehouse import attach_governed_test_warehouse


class ASGIRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.services = build_local_platform()
        attach_governed_test_warehouse(self.services)
        self.app = SmartDataAgentASGI(self.services, owns_services=False)

    def tearDown(self) -> None:
        self.services.close()

    def test_liveness_runs_through_asgi_without_threading_http_server(self) -> None:
        status, headers, payload = asyncio.run(self._request("GET", "/api/live"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["service"], "smart-data-agent-api")
        self.assertEqual(headers["x-content-type-options"], "nosniff")

    def test_lifespan_starts_worker_and_readiness_checks_real_dependencies(self) -> None:
        status, payload = asyncio.run(self._lifespan_ready())
        self.assertEqual(status, 200)
        self.assertTrue(payload["ready"])
        self.assertTrue(payload["checks"]["automation_worker"]["ready"])

    async def _lifespan_ready(self) -> tuple[int, dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        sent: list[dict] = []

        async def receive() -> dict:
            return await queue.get()

        async def send(message: dict) -> None:
            sent.append(message)

        lifespan = asyncio.create_task(
            self.app({"type": "lifespan"}, receive, send)
        )
        await queue.put({"type": "lifespan.startup"})
        while not any(item["type"] == "lifespan.startup.complete" for item in sent):
            await asyncio.sleep(0)
        status, _, payload = await self._request("GET", "/api/ready")
        await queue.put({"type": "lifespan.shutdown"})
        await lifespan
        return status, payload

    def test_analysis_route_preserves_auth_rate_limit_and_evidence_contract(self) -> None:
        body = json.dumps({"question": "各分行放款金额"}, ensure_ascii=False).encode("utf-8")
        status, _, payload = asyncio.run(
            self._request(
                "POST",
                "/api/analysis/run",
                body=body,
                headers=[
                    (b"content-type", b"application/json"),
                    (b"x-user-id", b"u_super_admin"),
                    (b"x-tenant-id", b"tenant_demo"),
                ],
            )
        )
        self.assertEqual(status, 200)
        result = payload["skill_results"][0]
        self.assertTrue(result["semantic_info"]["metric_definitions_bound"])
        self.assertTrue(result["evidence"]["evidence_id"].startswith("ev_"))

    def test_static_assets_negotiate_precompressed_brotli_and_gzip_variants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = b"console.log('compressed static asset');" * 20
            (root / "app.js").write_bytes(source)
            (root / "app.js.br").write_bytes(b"brotli-variant")
            (root / "app.js.gz").write_bytes(gzip.compress(source))
            app = SmartDataAgentASGI(self.services, owns_services=False, static_root=root)

            status, headers, body = asyncio.run(self._raw_request(app, "GET", "/app.js", headers=[(b"accept-encoding", b"br, gzip")]))
            self.assertEqual(status, 200)
            self.assertEqual(headers["content-encoding"], "br")
            self.assertEqual(headers["vary"], "Accept-Encoding")
            self.assertEqual(body, b"brotli-variant")

            status, headers, body = asyncio.run(self._raw_request(app, "GET", "/app.js", headers=[(b"accept-encoding", b"br;q=0.5, gzip")]))
            self.assertEqual(status, 200)
            self.assertEqual(headers["content-encoding"], "gzip")
            self.assertEqual(gzip.decompress(body), source)

            status, headers, body = asyncio.run(self._raw_request(app, "GET", "/app.js"))
            self.assertEqual(status, 200)
            self.assertNotIn("content-encoding", headers)
            self.assertEqual(headers["vary"], "Accept-Encoding")
            self.assertEqual(body, source)

    def test_fun_asr_websocket_ping_uses_asgi_auth_origin_and_message_contract(self) -> None:
        sent = asyncio.run(self._websocket_ping())
        self.assertEqual(sent[0]["type"], "websocket.accept")
        payloads = [
            json.loads(message["text"])
            for message in sent
            if message.get("type") == "websocket.send" and message.get("text")
        ]
        self.assertEqual(payloads[0], {"type": "connected"})
        self.assertIn({"type": "pong"}, payloads)
        self.assertEqual(sent[-1]["type"], "websocket.close")

    async def _websocket_ping(self) -> list[dict]:
        messages = iter(
            [
                {"type": "websocket.connect"},
                {"type": "websocket.receive", "text": '{"type":"ping"}'},
                {"type": "websocket.disconnect", "code": 1000},
            ]
        )
        sent: list[dict] = []

        async def receive() -> dict:
            return next(messages)

        async def send(message: dict) -> None:
            sent.append(message)

        await self.app(
            {
                "type": "websocket",
                "path": "/api/asr/fun-asr/realtime",
                "query_string": b"",
                "headers": [
                    (b"x-user-id", b"u_super_admin"),
                    (b"x-tenant-id", b"tenant_demo"),
                    (b"origin", b"http://localhost:5173"),
                ],
                "subprotocols": [],
                "client": ("127.0.0.1", 50001),
            },
            receive,
            send,
        )
        return sent

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes = b"",
        headers: list[tuple[bytes, bytes]] | None = None,
    ) -> tuple[int, dict[str, str], dict]:
        status, response_headers, response_body = await self._raw_request(self.app, method, path, body=body, headers=headers)
        return status, response_headers, json.loads(response_body.decode("utf-8"))

    async def _raw_request(
        self,
        app: SmartDataAgentASGI,
        method: str,
        path: str,
        *,
        body: bytes = b"",
        headers: list[tuple[bytes, bytes]] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        sent: list[dict] = []
        received = False

        async def receive() -> dict:
            nonlocal received
            if received:
                await asyncio.sleep(0)
                return {"type": "http.disconnect"}
            received = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message: dict) -> None:
            sent.append(message)

        request_headers = list(headers or [])
        request_headers.append((b"content-length", str(len(body)).encode("ascii")))
        await app(
            {
                "type": "http",
                "method": method,
                "path": path,
                "query_string": b"",
                "headers": request_headers,
                "client": ("127.0.0.1", 50000),
            },
            receive,
            send,
        )
        start = next(message for message in sent if message["type"] == "http.response.start")
        response = next(message for message in sent if message["type"] == "http.response.body")
        response_headers = {
            name.decode("latin-1"): value.decode("latin-1")
            for name, value in start["headers"]
        }
        return start["status"], response_headers, response["body"]


if __name__ == "__main__":
    unittest.main()
