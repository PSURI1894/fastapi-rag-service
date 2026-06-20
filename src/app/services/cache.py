"""Caching layer — an interface with in-memory, Redis, and no-op backends.

Used to cache RAG *retrieval* results: identical questions skip the (real)
embedding + vector search. The trade-off is staleness — a freshly ingested
document won't appear in a cached query until its entry expires — so we keep the
TTL short. (Cache invalidation is famously one of the two hard problems.)

`build_cache(settings)` picks the backend; `NoOpCache` makes "caching disabled" a
real object so callers never branch on a flag. Redis is an optional extra, imported
lazily, so this module loads without it.
"""

import hashlib
import json
import time
from abc import ABC, abstractmethod

from app.config import Settings
from app.schemas import Citation
from app.services.rag import RagService


class Cache(ABC):
    @abstractmethod
    async def get(self, key: str) -> str | None: ...

    @abstractmethod
    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...

    async def close(self) -> None:
        """Release resources (e.g. a Redis pool). No-op for in-memory backends."""
        return None


class NoOpCache(Cache):
    """Caching disabled: never stores, always misses."""

    async def get(self, key: str) -> str | None:
        return None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        return None


class InMemoryCache(Cache):
    """A dict with per-key expiry. Fine for one process / tests; a multi-process
    deployment needs Redis so all workers share the cache."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float]] = {}

    async def get(self, key: str) -> str | None:
        item = self._store.get(key)
        if item is None:
            return None
        value, expires_at = item
        if time.time() >= expires_at:
            del self._store[key]  # lazy expiry on read
            return None
        return value

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._store[key] = (value, time.time() + ttl_seconds)


class RedisCache(Cache):
    """Shared cache across processes. `redis` is an optional extra, imported lazily."""

    def __init__(self, redis_url: str) -> None:
        import redis.asyncio as redis  # lazy: only when this backend is selected

        self._redis = redis.from_url(redis_url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        value = await self._redis.get(key)  # str with decode_responses=True
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else value

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await self._redis.set(key, value, ex=ttl_seconds)

    async def close(self) -> None:
        await self._redis.aclose()


def build_cache(settings: Settings) -> Cache:
    if not settings.cache_enabled:
        return NoOpCache()
    if settings.cache_backend == "redis":
        if not settings.redis_url:
            raise ValueError("cache_backend='redis' requires REDIS_URL to be set")
        return RedisCache(settings.redis_url)
    return InMemoryCache()


async def retrieve_cached(
    cache: Cache, rag: RagService, question: str, ttl_seconds: int
) -> list[Citation]:
    """Return retrieval results for `question`, served from cache when possible.

    The key normalises the question (trim + lowercase) and hashes it, so it's safe
    and bounded regardless of input. Retrieval isn't user-specific (the corpus is
    shared), so the cache is shared across users — if documents were per-tenant,
    the key would need the tenant id."""
    key = "retrieval:" + hashlib.sha256(question.strip().lower().encode()).hexdigest()
    cached = await cache.get(key)
    if cached is not None:
        return [Citation.model_validate(item) for item in json.loads(cached)]

    citations = await rag.retrieve(question)
    await cache.set(key, json.dumps([c.model_dump() for c in citations]), ttl_seconds)
    return citations
