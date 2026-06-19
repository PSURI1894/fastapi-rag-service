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
