"""Shared pytest fixtures.

The important subtlety: we test the app IN-PROCESS (no real network) using
httpx's `ASGITransport`, which calls the ASGI app directly. But `ASGITransport`
does NOT run startup/shutdown events — so `app.state.repository` would be missing.

Fix: enter the app's own lifespan context manually with
`app.router.lifespan_context(app)`. That runs the exact startup code (building the
repo + RAG service) your production server runs, so tests exercise real wiring.
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import create_app


@pytest.fixture
def api_key() -> str:
    # Tests rely on config defaults (no .env present), so this matches the app.
    return get_settings().api_key


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    # Run startup (populate app.state), serve requests, then run shutdown.
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
