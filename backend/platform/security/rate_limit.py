from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class RateLimitExceeded(ValueError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("rate_limit_exceeded")
        self.retry_after_seconds = max(1, int(retry_after_seconds))


class RateLimiter(Protocol):
    def check(self, key: str, limit: int, window_seconds: int, now: int | None = None) -> RateLimitDecision:
        ...


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, tuple[int, int]] = {}
        self._lock = threading.RLock()

    def close(self) -> None:
        return None

    def health(self) -> dict[str, object]:
        return {"ready": True, "backend": "memory", "distributed": False}

    def check(self, key: str, limit: int, window_seconds: int, now: int | None = None) -> RateLimitDecision:
        current = int(time.time() if now is None else now)
        bounded_limit = max(1, int(limit))
        bounded_window = max(1, int(window_seconds))
        bucket_start = current - (current % bounded_window)
        bucket_key = f"{key}:{bucket_start}"
        with self._lock:
            count, _ = self._buckets.get(bucket_key, (0, bucket_start))
            count += 1
            self._buckets[bucket_key] = (count, bucket_start)
            if len(self._buckets) > 10_000:
                cutoff = current - bounded_window * 2
                self._buckets = {name: value for name, value in self._buckets.items() if value[1] >= cutoff}
        retry_after = max(1, bucket_start + bounded_window - current)
        return RateLimitDecision(
            allowed=count <= bounded_limit,
            limit=bounded_limit,
            remaining=max(0, bounded_limit - count),
            retry_after_seconds=retry_after,
        )


class RedisRateLimiter:
    def __init__(self, redis_url: str) -> None:
        try:
            import redis
        except ImportError as exc:  # pragma: no cover - production dependency check.
            raise RuntimeError("redis_package_required_for_production_rate_limit") from exc
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)

    def close(self) -> None:
        self._client.close()

    def health(self) -> dict[str, object]:
        try:
            return {"ready": bool(self._client.ping()), "backend": "redis", "distributed": True}
        except Exception as exc:
            return {"ready": False, "backend": "redis", "distributed": True, "error": type(exc).__name__}

    def check(self, key: str, limit: int, window_seconds: int, now: int | None = None) -> RateLimitDecision:
        current = int(time.time() if now is None else now)
        bounded_window = max(1, int(window_seconds))
        bucket_start = current - (current % bounded_window)
        redis_key = f"sda:rate:{key}:{bucket_start}"
        pipeline = self._client.pipeline(transaction=True)
        pipeline.incr(redis_key)
        pipeline.expire(redis_key, bounded_window * 2, nx=True)
        count, _ = pipeline.execute()
        bounded_limit = max(1, int(limit))
        return RateLimitDecision(
            allowed=int(count) <= bounded_limit,
            limit=bounded_limit,
            remaining=max(0, bounded_limit - int(count)),
            retry_after_seconds=max(1, bucket_start + bounded_window - current),
        )


def build_rate_limiter(environment: str) -> RateLimiter:
    redis_url = os.getenv("SMART_DATA_AGENT_REDIS_URL", "").strip()
    if environment in {"staging", "production"}:
        if not redis_url:
            raise RuntimeError("SMART_DATA_AGENT_REDIS_URL is required for distributed rate limits")
        return RedisRateLimiter(redis_url)
    return InMemoryRateLimiter()


def request_limits(path: str) -> tuple[int, int, int]:
    """Return IP, user and tenant requests per 60-second window."""

    if path in {"/api/auth/login", "/api/auth/register", "/api/auth/oidc/start", "/api/auth/refresh"}:
        return (10, 0, 0)
    if path in {
        "/api/integrations/bridge/enrollment/start",
        "/api/integrations/bridge/enrollment/poll",
        "/api/integrations/bridge/enrollment/verify",
    }:
        return (30, 0, 0)
    if path in {"/api/analysis/run", "/api/analysis/run-async"}:
        return (60, 10, 50)
    if path in {"/api/system-config/model/test", "/api/system-config/data-connection/test"}:
        return (30, 10, 20)
    if path == "/api/mcp/call":
        return (60, 30, 100)
    return (300, 120, 500)
