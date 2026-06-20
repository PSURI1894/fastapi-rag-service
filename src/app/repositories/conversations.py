"""The repository pattern: data access hidden behind an interface.

Why bother with an abstract base class for an in-memory dict? Because it draws a
hard line between "what the rest of the app needs" (the `ConversationRepository`
methods) and "how storage actually works" (today a dict, tomorrow Postgres).

When you add a database, you write `SqlAlchemyConversationRepository` implementing
the SAME interface and change ONE line in main.py. No route, service, or test
that talks to the interface has to change. That swappability is the whole point.
"""

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import ConversationModel, MessageModel
from app.schemas import Message


class ConversationRepository(ABC):
    """The contract every storage backend must satisfy."""

    @abstractmethod
    async def create(self) -> str:
        """Create an empty conversation and return its new id."""

    @abstractmethod
    async def exists(self, conversation_id: str) -> bool: ...

    @abstractmethod
    async def add_message(self, conversation_id: str, role: str, content: str) -> None: ...

    @abstractmethod
    async def history(self, conversation_id: str) -> list[Message]: ...


class InMemoryConversationRepository(ConversationRepository):
    """A dict-backed implementation. Great for tests and local dev; data is lost
    on restart. Methods are `async` to match the interface so swapping in a real
    async DB driver later requires zero signature changes."""

    def __init__(self) -> None:
        self._store: dict[str, list[Message]] = {}

    async def create(self) -> str:
        conversation_id = uuid4().hex
        self._store[conversation_id] = []
        return conversation_id

    async def exists(self, conversation_id: str) -> bool:
        return conversation_id in self._store

    async def add_message(self, conversation_id: str, role: str, content: str) -> None:
        self._store[conversation_id].append(
            Message(role=role, content=content, created_at=datetime.now(UTC))
        )

    async def history(self, conversation_id: str) -> list[Message]:
        # Return a copy so callers can't mutate our internal state.
        return list(self._store.get(conversation_id, []))


class SqlAlchemyConversationRepository(ConversationRepository):
    """The real, durable implementation — same four methods, backed by Postgres or
    SQLite via an AsyncSession. It maps ORM rows to the `Message` Pydantic model so
    the rest of the app never touches a SQLAlchemy object.

    Methods `flush` (send SQL now, get generated ids) but do NOT `commit` — the
    transaction boundary is owned by whoever created the session (the request-scoped
    `get_session` dependency, or the streaming route's explicit `async with`)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self) -> str:
        conversation = ConversationModel(id=uuid4().hex, created_at=datetime.now(UTC))
        self._session.add(conversation)
        await self._session.flush()
        return conversation.id

    async def exists(self, conversation_id: str) -> bool:
        return await self._session.get(ConversationModel, conversation_id) is not None

    async def add_message(self, conversation_id: str, role: str, content: str) -> None:
        self._session.add(
            MessageModel(
                conversation_id=conversation_id,
                role=role,
                content=content,
                created_at=datetime.now(UTC),
            )
        )
        await self._session.flush()

    async def history(self, conversation_id: str) -> list[Message]:
        stmt = (
            select(MessageModel)
            .where(MessageModel.conversation_id == conversation_id)
            .order_by(MessageModel.id)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [Message(role=m.role, content=m.content, created_at=m.created_at) for m in rows]
