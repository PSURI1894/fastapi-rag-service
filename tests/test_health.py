"""Health endpoint tests. `asyncio_mode = auto` (pyproject) runs these on the
event loop without needing a marker."""

from httpx import AsyncClient


async def test_health_returns_ok(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200

    body = resp.json()
    assert body["status"] == "ok"
    assert body["env"] == "local"
    assert "version" in body


async def test_middleware_adds_tracing_headers(client: AsyncClient) -> None:
    resp = await client.get("/health")
    # The custom middleware should stamp these on every response.
    assert "X-Request-ID" in resp.headers
    assert "X-Process-Time-ms" in resp.headers
