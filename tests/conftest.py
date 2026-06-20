"""Shared pytest fixtures.

The important subtlety: we test the app IN-PROCESS (no real network) using
httpx's `ASGITransport`, which calls the ASGI app directly. But `ASGITransport`
does NOT run startup/shutdown events — so `app.state.repository` would be missing.

Fix: enter the app's own lifespan context manually with
`app.router.lifespan_context(app)`. That runs the exact startup code (building the
repo + RAG service) your production server runs, so tests exercise real wiring.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import create_app


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    # Run startup (populate app.state, seed the demo user), serve, then shut down.
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    """Log in as the seeded demo user and return a ready-to-use Bearer header.

    Note `data=` (not `json=`): the OAuth2 token endpoint expects form-encoded
    fields `username`/`password`, per the OAuth2 spec.
    """
    settings = get_settings()
    resp = await client.post(
        "/auth/token",
        data={"username": settings.demo_username, "password": settings.demo_password},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
