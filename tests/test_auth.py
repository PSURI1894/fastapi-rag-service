"""Auth tests: login (success + failure) and the protected /auth/me route."""

from httpx import AsyncClient

from app.config import get_settings


async def test_login_succeeds_with_seed_credentials(client: AsyncClient) -> None:
    settings = get_settings()
    resp = await client.post(
        "/auth/token",
        data={"username": settings.demo_username, "password": settings.demo_password},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]  # a non-empty JWT string


async def test_login_fails_with_wrong_password(client: AsyncClient) -> None:
    settings = get_settings()
    resp = await client.post(
        "/auth/token",
        data={"username": settings.demo_username, "password": "wrong"},
    )
    assert resp.status_code == 401


async def test_login_fails_for_unknown_user(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/token",
        data={"username": "ghost", "password": "whatever"},
    )
    assert resp.status_code == 401


async def test_me_returns_current_user(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.get("/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == get_settings().demo_username
    # The public view must NOT leak the password hash.
    assert "hashed_password" not in body
    assert "password" not in body


async def test_me_requires_token(client: AsyncClient) -> None:
    resp = await client.get("/auth/me")
    assert resp.status_code == 401
