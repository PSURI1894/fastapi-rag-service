"""Rate limiter unit test + an end-to-end 429 on the chat endpoint."""

from fastapi import FastAPI
from httpx import AsyncClient

from app.config import Settings, get_settings
from app.services.ratelimit import InMemoryRateLimiter


async def test_inmemory_limiter_allows_then_denies() -> None:
    limiter = InMemoryRateLimiter()
    for _ in range(3):
        assert (await limiter.hit("user:demo", limit=3, window_seconds=60)).allowed

    denied = await limiter.hit("user:demo", limit=3, window_seconds=60)
    assert not denied.allowed
    assert denied.retry_after >= 1


async def test_chat_returns_429_when_over_limit(
    app: FastAPI, client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # Force a tiny limit by overriding the settings dependency for this app only.
    app.dependency_overrides[get_settings] = lambda: Settings(rate_limit_per_minute=2)
    try:
        for _ in range(2):
            ok = await client.post("/chat", headers=auth_headers, json={"question": "refund?"})
            assert ok.status_code == 200

        blocked = await client.post("/chat", headers=auth_headers, json={"question": "refund?"})
        assert blocked.status_code == 429
        assert "retry-after" in {k.lower() for k in blocked.headers}
    finally:
        app.dependency_overrides.pop(get_settings, None)
