from __future__ import annotations

import http.client
import json
import threading
import unittest

from backend.platform.api.server import AnalysisAPIHandler, AnalysisAPIServer


class ApiStartupReadinessTest(unittest.TestCase):
    def test_live_succeeds_and_app_routes_wait_while_bootstrap_is_running(self) -> None:
        server = AnalysisAPIServer(("127.0.0.1", 0), AnalysisAPIHandler)
        server.startup_status = "starting"
        server.startup_error = ""
        server.services = None
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = int(server.server_address[1])
            live = self._json("GET", "/api/live", port)
            self.assertEqual(live[0], 200)
            self.assertEqual(live[1]["startup"], "starting")
            health = self._json("GET", "/api/health", port)
            self.assertEqual(health[0], 503)
            self.assertEqual(health[1]["error"], "api_starting")
            navigation = self._json("GET", "/api/navigation", port)
            self.assertEqual(navigation[0], 503)
            self.assertEqual(navigation[1]["error"], "api_starting")
            self.assertIn("正在启动", navigation[1]["message"])
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

    def test_failed_bootstrap_returns_unavailable_without_exiting(self) -> None:
        server = AnalysisAPIServer(("127.0.0.1", 0), AnalysisAPIHandler)
        server.startup_status = "failed"
        server.startup_error = "MySQLMigrationError: mysql_schema_checksum_drift"
        server.services = None
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = int(server.server_address[1])
            payload = self._json("GET", "/api/auth/me", port)
            self.assertEqual(payload[0], 503)
            self.assertEqual(payload[1]["error"], "api_unavailable")
            self.assertIn("mysql_schema_checksum_drift", payload[1]["message"])
        finally:
            server.shutdown()
            thread.join(timeout=2)
            server.server_close()

    def _json(self, method: str, path: str, port: int) -> tuple[int, dict]:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            body = response.read().decode("utf-8")
            return response.status, json.loads(body)
        finally:
            connection.close()
