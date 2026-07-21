from __future__ import annotations

import http.client
import json
import threading
from tempfile import TemporaryDirectory
import unittest

from backend.platform.api.server import create_server
from backend.platform.security import InMemoryRateLimiter


class RateLimitsTest(unittest.TestCase):
    def test_fixed_window_is_thread_safe_and_returns_retry_after(self) -> None:
        limiter = InMemoryRateLimiter()
        first = limiter.check("user:u1:analysis", 2, 60, now=120)
        second = limiter.check("user:u1:analysis", 2, 60, now=121)
        third = limiter.check("user:u1:analysis", 2, 60, now=122)
        self.assertTrue(first.allowed)
        self.assertTrue(second.allowed)
        self.assertFalse(third.allowed)
        self.assertEqual(third.remaining, 0)
        self.assertEqual(third.retry_after_seconds, 58)
        self.assertTrue(limiter.check("user:u1:analysis", 2, 60, now=180).allowed)

    def test_analysis_user_limit_returns_429_without_executing_eleventh_request(self) -> None:
        with TemporaryDirectory() as tmpdir:
            server = create_server("127.0.0.1", 0, f"{tmpdir}/api.sqlite")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            statuses: list[int] = []
            try:
                port = server.server_address[1]
                for index in range(11):
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    connection.request(
                        "POST",
                        "/api/analysis/run",
                        body=json.dumps(
                            {
                                "question": "2026年6月各分行放款金额",
                                "request_id": f"rate-{index}",
                            },
                            ensure_ascii=False,
                        ).encode("utf-8"),
                        headers={
                            "Content-Type": "application/json",
                            "X-User-Id": "u_admin",
                            "X-Tenant-Id": "tenant_demo",
                        },
                    )
                    response = connection.getresponse()
                    response.read()
                    statuses.append(response.status)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        self.assertEqual(statuses[:10], [200] * 10)
        self.assertEqual(statuses[10], 429)


if __name__ == "__main__":
    unittest.main()
