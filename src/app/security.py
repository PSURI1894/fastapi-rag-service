"""Authentication, expressed as a FastAPI dependency.

Key idea: in FastAPI, auth is "just a dependency". A route (or whole router) that
needs auth declares `dependencies=[Depends(require_api_key)]`. The dependency runs
BEFORE the handler; if it raises `HTTPException`, the handler never executes.

This is API-key auth (simplest real-world scheme). The natural next lesson is
swapping this single function for OAuth2 + JWT — the routes won't change, only
this file does. That's the payoff of putting auth behind a dependency.
"""

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings


async def require_api_key(
    # Header(alias=...) maps the HTTP header `X-API-Key` to this parameter and
    # documents it in OpenAPI. default=None so a *missing* header is a clean 401,
    # not a 422 validation error.
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    if x_api_key is None or x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
