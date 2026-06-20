"""Unit tests for the SQLAlchemy repositories, exercised directly against an
in-memory SQLite database (no HTTP, no FastAPI). This is the data layer in
isolation — fast and precise, complementing the end-to-end tests in test_chat.py.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import create_all, create_engine, create_sessionmaker
from app.repositories.conversations import SqlAlchemyConversationRepository
from app.repositories.users import SqlAlchemyUserRepository, User


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    # Explicit kwargs beat any env var, so this is hermetic regardless of test order.
    settings = Settings(database_url="sqlite+aiosqlite://", db_auto_create=True)
    engine = create_engine(settings)
    await create_all(engine)
    sessionmaker = create_sessionmaker(engine)
    async with sessionmaker() as s:
        yield s
    await engine.dispose()


async def test_conversation_roundtrip(session: AsyncSession) -> None:
    repo = SqlAlchemyConversationRepository(session)

    conversation_id = await repo.create()
    assert await repo.exists(conversation_id) is True
    assert await repo.exists("does-not-exist") is False

    await repo.add_message(conversation_id, "user", "hi")
    await repo.add_message(conversation_id, "assistant", "hello")
    await session.commit()

    history = await repo.history(conversation_id)
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[0].content == "hi"
    assert history[0].created_at is not None  # timestamp was persisted


async def test_user_roundtrip(session: AsyncSession) -> None:
    repo = SqlAlchemyUserRepository(session)

    assert await repo.get_by_username("alice") is None

    await repo.add(User(username="alice", hashed_password="not-a-real-hash", full_name="Alice"))
    await session.commit()

    got = await repo.get_by_username("alice")
    assert got is not None
    assert got.username == "alice"
    assert got.full_name == "Alice"
    assert got.disabled is False
    assert got.hashed_password == "not-a-real-hash"
