"""The rate-limit dependency.

Lives in its own module (not dependencies.py) because it imports
`get_current_user` from security.py, and security.py already imports from
dependencies.py — putting this there would create an import cycle. Nothing imports
this module except routers, so it's a safe leaf.

Attach to a router with `dependencies=[Depends(enforce_rate_limit)]`. It runs
before the handler and raises 429 (with Retry-After) when the caller is over their
per-minute budget.
"""

from fastapi import Depends, HTTPException, status

from app.config import Settings, get_settings
from app.dependencies import get_rate_limiter
from app.schemas import UserPublic
from app.security import get_current_user
from app.services.ratelimit import RateLimiter


async def enforce_rate_limit(
    current_user: UserPublic = Depends(get_current_user),
    limiter: RateLimiter = Depends(get_rate_limiter),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.rate_limit_enabled:
        return
    result = await limiter.hit(
        key=f"user:{current_user.username}",
        limit=settings.rate_limit_per_minute,
        window_seconds=60,
    )
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded; slow down",
            headers={"Retry-After": str(result.retry_after)},
        )
