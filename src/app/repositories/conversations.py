"""The repository pattern: data access hidden behind an interface.

Two implementations of one interface live here — `InMemory...` (simple, for
reference) and `SqlAlchemy...` (the real one). The rest of the app only ever sees
`ConversationRepository`, so swapping backends touches nothing above this file.

Conversations are now OWNED: `create()` records an owner, `get_owner()` lets a
route enforce access, and `list_for_owner()` powers a per-user listing. Mapping
between ORM rows and the Pydantic models (`Message`, `ConversationSummary`) happens
here so nothing upstream touches a SQLAlchemy object.
"""

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import ConversationModel, MessageModel
from app.schemas import ConversationSummary, Message


class ConversationRepository(ABC):
    """The contract every storage backend must satisfy."""

    @abstractmethod
    async def create(self, owner_username: str) -> str:
        """Create an empty conversation owned by `owner_username`; return its id."""

    @abstractmethod
    async def get_owner(self, conversation_id: str) -> str | None:
        """Return the owning username, or None if the conversation doesn't exist.

        Routes use this to choose between 404 (None) and 403 (someone else's)."""

    @abstractmethod
    async def add_message(self, conversation_id: str, role: str, content: str) -> None: ...

    @abstractmethod
    async def history(self, conversation_id: str) -> list[Message]: ...

    @abstractmethod
    async def list_for_owner(self, owner_username: str) -> list[ConversationSummary]: ...


class InMemoryConversationRepository(ConversationRepository):
    """A dict-backed implementation. Great for tests and quick reference; data is
    lost on restart. Methods are `async` to match the interface."""

    def __init__(self) -> None:
        self._owners: dict[str, str] = {}
        self._created: dict[str, datetime] = {}
        self._messages: dict[str, list[Message]] = {}

    async def create(self, owner_username: str) -> str:
        conversation_id = uuid4().hex
        self._owners[conversation_id] = owner_username
        self._created[conversation_id] = datetime.now(UTC)
        self._messages[conversation_id] = []
        return conversation_id

    async def get_owner(self, conversation_id: str) -> str | None:
        return self._owners.get(conversation_id)

    async def add_message(self, conversation_id: str, role: str, content: str) -> None:
        self._messages[conversation_id].append(
            Message(role=role, content=content, created_at=datetime.now(UTC))
        )

    async def history(self, conversation_id: str) -> list[Message]:
        return list(self._messages.get(conversation_id, []))

    async def list_for_owner(self, owner_username: str) -> list[ConversationSummary]:
        return [
            ConversationSummary(
                conversation_id=cid,
                created_at=self._created[cid],
                message_count=len(self._messages.get(cid, [])),
            )
            for cid, owner in self._owners.items()
            if owner == owner_username
        ]


class SqlAlchemyConversationRepository(ConversationRepository):
    """The durable implementation — same methods, backed by Postgres or SQLite via
    an AsyncSession. Flushes (to assign ids) but does not commit; the session owner
    controls the transaction boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, owner_username: str) -> str:
        conversation = ConversationModel(
            id=uuid4().hex, owner_username=owner_username, created_at=datetime.now(UTC)
        )
        self._session.add(conversation)
        await self._session.flush()
        return conversation.id

    async def get_owner(self, conversation_id: str) -> str | None:
        conversation = await self._session.get(ConversationModel, conversation_id)
        return conversation.owner_username if conversation is not None else None

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

    async def list_for_owner(self, owner_username: str) -> list[ConversationSummary]:
        # One query: each owned conversation plus a LEFT JOIN count of its messages.
        stmt = (
            select(
                ConversationModel.id,
                ConversationModel.created_at,
                func.count(MessageModel.id),
            )
            .outerjoin(MessageModel, MessageModel.conversation_id == ConversationModel.id)
            .where(ConversationModel.owner_username == owner_username)
            .group_by(ConversationModel.id, ConversationModel.created_at)
            .order_by(ConversationModel.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            ConversationSummary(conversation_id=row[0], created_at=row[1], message_count=row[2])
            for row in rows
        ]
