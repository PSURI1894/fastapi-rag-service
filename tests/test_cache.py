"""Cache backend + retrieve_cached helper tests."""

from app.schemas import Citation
from app.services.cache import InMemoryCache, NoOpCache, retrieve_cached
from app.services.rag import MockRagService


class CountingRag(MockRagService):
    """A mock RAG that counts how many times retrieve() actually runs, so we can
    prove the cache short-circuits it."""

    def __init__(self) -> None:
        super().__init__(response_delay_ms=0)
        self.retrieve_calls = 0

    async def retrieve(self, question: str) -> list[Citation]:
        self.retrieve_calls += 1
        return await super().retrieve(question)


async def test_inmemory_cache_set_and_get() -> None:
    cache = InMemoryCache()
    assert await cache.get("missing") is None
    await cache.set("k", "v", 60)
    assert await cache.get("k") == "v"


async def test_inmemory_cache_expires() -> None:
    cache = InMemoryCache()
    await cache.set("k", "v", -1)  # already expired
    assert await cache.get("k") is None


async def test_noop_cache_never_stores() -> None:
    cache = NoOpCache()
    await cache.set("k", "v", 60)
    assert await cache.get("k") is None


async def test_retrieve_cached_serves_second_call_from_cache() -> None:
    cache = InMemoryCache()
    rag = CountingRag()

    first = await retrieve_cached(cache, rag, "refund window for damaged goods?", 60)
    second = await retrieve_cached(cache, rag, "refund window for damaged goods?", 60)

    assert first == second
    assert rag.retrieve_calls == 1  # the second call was served from the cache


async def test_noop_cache_disables_caching() -> None:
    cache = NoOpCache()
    rag = CountingRag()

    await retrieve_cached(cache, rag, "refund?", 60)
    await retrieve_cached(cache, rag, "refund?", 60)

    assert rag.retrieve_calls == 2  # no cache → both calls hit the RAG service
