"""Unit tests for the SQLAlchemy repositories, exercised directly against an
in-memory SQLite database (no HTTP, no FastAPI). The data layer in isolation —
fast and precise, complementing the end-to-end tests in test_chat.py.
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
    await SqlAlchemyUserRepository(session).add(User(username="demo", hashed_password="x"))
    repo = SqlAlchemyConversationRepository(session)

    conversation_id = await repo.create("demo")
    assert await repo.get_owner(conversation_id) == "demo"
    assert await repo.get_owner("does-not-exist") is None

    await repo.add_message(conversation_id, "user", "hi")
    await repo.add_message(conversation_id, "assistant", "hello")
    await session.commit()

    history = await repo.history(conversation_id)
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[0].content == "hi"
    assert history[0].created_at is not None  # timestamp was persisted


async def test_list_for_owner_is_scoped(session: AsyncSession) -> None:
    users = SqlAlchemyUserRepository(session)
    await users.add(User(username="alice", hashed_password="x"))
    await users.add(User(username="bob", hashed_password="x"))
    repo = SqlAlchemyConversationRepository(session)

    a1 = await repo.create("alice")
    await repo.add_message(a1, "user", "hi")
    await repo.create("alice")
    await repo.create("bob")
    await session.commit()

    alice = await repo.list_for_owner("alice")
    bob = await repo.list_for_owner("bob")
    assert len(alice) == 2
    assert len(bob) == 1
    counts = {s.conversation_id: s.message_count for s in alice}
    assert counts[a1] == 1  # the message count is computed in the query


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
