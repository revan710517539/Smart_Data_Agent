from __future__ import annotations

import http.client
import json
import threading
from tempfile import TemporaryDirectory
import unittest

from backend.platform.api.server import create_server
from backend.platform.security import InMemoryRateLimiter
from backend.platform.tests.governed_warehouse import attach_governed_test_warehouse


class _FixedClockRateLimiter(InMemoryRateLimiter):
    """Keep HTTP rate-limit assertions inside one deterministic fixed window."""

    def __init__(self, now: int) -> None:
        super().__init__()
        self._now = now

    def check(self, key: str, limit: int, window_seconds: int, now: int | None = None):
        return super().check(key, limit, window_seconds, now=self._now)

    def advance(self, seconds: int) -> None:
        self._now += seconds


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
            attach_governed_test_warehouse(server.services)
            limiter = _FixedClockRateLimiter(now=120)
            server.services.rate_limiter = limiter
            server.RequestHandlerClass.services = server.services
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            statuses: list[int] = []
            bodies: list[dict[str, object]] = []
            try:
                port = server.server_address[1]
                for index in range(11):
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
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
                            "X-User-Id": "u_super_admin",
                            "X-Tenant-Id": "tenant_demo",
                        },
                    )
                    response = connection.getresponse()
                    statuses.append(response.status)
                    bodies.append(json.loads(response.read().decode("utf-8")))
                    connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
                server.services.close()

        # The authorization result of the first ten requests depends on the
        # isolated test seed, but none may be throttled before the configured
        # user limit is exhausted.
        self.assertNotIn(429, statuses[:10])
        self.assertEqual(statuses[10], 429)
        self.assertEqual(bodies[10]["error"], "rate_limit_exceeded")
        self.assertGreaterEqual(int(bodies[10]["retry_after_seconds"]), 1)

        # A new fixed window must reset the counter instead of permanently
        # throttling this user key.
        limiter.advance(60)
        reset = limiter.check("user:u_super_admin:/api/analysis/run", 10, 60)
        self.assertTrue(reset.allowed)
        self.assertEqual(reset.remaining, 9)

if __name__ == "__main__":
    unittest.main()
