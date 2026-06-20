"""Shared pytest fixtures.

We test the app IN-PROCESS (no real network) using httpx's `ASGITransport`. Since
that transport does NOT run startup/shutdown, the `app` fixture enters the app's own
lifespan with `app.router.lifespan_context(app)` — so the real startup code runs
(open engine, create schema, seed the demo user) and tests exercise real wiring.

Each test gets a fresh in-memory SQLite DB (StaticPool keeps the schema alive for
the test). The `make_user` fixture lets a test create a *second* user, which is how
the per-user authorization tests check cross-user access.
"""

import os
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import create_app
from app.repositories.users import SqlAlchemyUserRepository, User
from app.security import hash_password


@pytest_asyncio.fixture
async def app() -> AsyncIterator[FastAPI]:
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"
    os.environ["DB_AUTO_CREATE"] = "true"
    get_settings.cache_clear()  # drop any cached Settings so the env above wins

    application = create_app()
    async with application.router.lifespan_context(application):  # run startup/shutdown
        yield application
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _login(client: AsyncClient, username: str, password: str) -> dict[str, str]:
    # `data=` (form-encoded) — the OAuth2 token endpoint expects form fields.
    resp = await client.post("/auth/token", data={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    """Bearer header for the seeded demo user."""
    settings = get_settings()
    return await _login(client, settings.demo_username, settings.demo_password)


@pytest_asyncio.fixture
async def make_user(
    app: FastAPI, client: AsyncClient
) -> Callable[[str, str], Awaitable[dict[str, str]]]:
    """Return a helper that creates a user (straight into the DB) and logs them in,
    returning ready-to-use Bearer headers — for multi-user authorization tests."""

    async def _make(username: str, password: str) -> dict[str, str]:
        async with app.state.sessionmaker() as session:
            repo = SqlAlchemyUserRepository(session)
            if await repo.get_by_username(username) is None:
                await repo.add(User(username=username, hashed_password=hash_password(password)))
                await session.commit()
        return await _login(client, username, password)

    return _make
