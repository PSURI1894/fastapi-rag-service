"""Rate limiting — a fixed-window counter behind an interface.

Fixed window: count requests per key within a clock window (e.g. one minute);
once the count exceeds the limit, deny until the window rolls over. Simple and
predictable (the trade-off vs. a token bucket is a burst right at a window
boundary). `build_rate_limiter(settings)` picks the backend; Redis is an optional
extra, imported lazily, so this module loads without it.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.config import Settings


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: int  # seconds until the window resets (when denied)


class RateLimiter(ABC):
    @abstractmethod
    async def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        """Record one request for `key` and report whether it's within `limit`."""

    async def close(self) -> None:
        """Release resources (e.g. a Redis pool). No-op for in-memory backends."""
        return None


class InMemoryRateLimiter(RateLimiter):
    """Per-process fixed-window counter. A multi-process deployment needs Redis so
    the limit is enforced across all workers, not per-worker."""

    def __init__(self) -> None:
        self._windows: dict[str, tuple[int, float]] = {}  # key -> (count, window_start)

    async def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        now = time.time()
        count, start = self._windows.get(key, (0, now))
        if now - start >= window_seconds:  # window expired → reset
            count, start = 0, now
        count += 1
        self._windows[key] = (count, start)

        if count > limit:
            retry_after = int(window_seconds - (now - start)) + 1
            return RateLimitResult(allowed=False, remaining=0, retry_after=retry_after)
        return RateLimitResult(allowed=True, remaining=limit - count, retry_after=0)


class RedisRateLimiter(RateLimiter):
    """Cross-process fixed-window counter using INCR + EXPIRE. `redis` is an
    optional extra, imported lazily."""

    def __init__(self, redis_url: str) -> None:
        import redis.asyncio as redis  # lazy: only when this backend is selected

        self._redis = redis.from_url(redis_url, decode_responses=True)

    async def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        bucket = int(time.time() // window_seconds)
        redis_key = f"ratelimit:{key}:{bucket}"
        count = await self._redis.incr(redis_key)
        if count == 1:  # first hit in this window → set the window's TTL
            await self._redis.expire(redis_key, window_seconds)

        if count > limit:
            ttl = await self._redis.ttl(redis_key)
            return RateLimitResult(allowed=False, remaining=0, retry_after=max(ttl, 1))
        return RateLimitResult(allowed=True, remaining=limit - count, retry_after=0)

    async def close(self) -> None:
        await self._redis.aclose()


def build_rate_limiter(settings: Settings) -> RateLimiter:
    if settings.rate_limit_backend == "redis":
        if not settings.redis_url:
            raise ValueError("rate_limit_backend='redis' requires REDIS_URL to be set")
        return RedisRateLimiter(settings.redis_url)
    return InMemoryRateLimiter()
