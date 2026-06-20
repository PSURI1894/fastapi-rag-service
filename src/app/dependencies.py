"""Dependency providers — how routes get their session, repositories, and service.

The big change from the in-memory rungs: the conversation/user repositories are no
longer app-wide singletons. They're built PER REQUEST around a per-request
`AsyncSession`, because a DB session/transaction must not be shared across
concurrent requests.

`get_session` is a *yield dependency*: FastAPI runs the code up to `yield` before
the handler, injects the session, then runs the code after `yield` once the handler
returns — committing on success, rolling back on error. Within one request, FastAPI
caches `get_session`, so `get_repository` and `get_user_repository` share the same
session and therefore the same transaction.

The engine + sessionmaker themselves ARE singletons (one connection pool for the
whole app); they're created in lifespan and read back via `app.state`.
"""

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.conversations import (
    ConversationRepository,
    SqlAlchemyConversationRepository,
)
from app.repositories.jobs import JobStore
from app.repositories.users import SqlAlchemyUserRepository, UserRepository
from app.services.cache import Cache
from app.services.rag import RagService
from app.services.ratelimit import RateLimiter


def get_rag_service(request: Request) -> RagService:
    return request.app.state.rag_service  # type: ignore[no-any-return]


def get_job_store(request: Request) -> JobStore:
    return request.app.state.job_store  # type: ignore[no-any-return]


def get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter  # type: ignore[no-any-return]


def get_cache(request: Request) -> Cache:
    return request.app.state.cache  # type: ignore[no-any-return]


def get_sessionmaker(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.sessionmaker  # type: ignore[no-any-return]


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    sessionmaker = get_sessionmaker(request)
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_repository(
    session: AsyncSession = Depends(get_session),
) -> ConversationRepository:
    return SqlAlchemyConversationRepository(session)


def get_user_repository(
    session: AsyncSession = Depends(get_session),
) -> UserRepository:
    return SqlAlchemyUserRepository(session)
