"""User storage — same repository pattern as conversations.py.

The `User` model here is the INTERNAL/storage shape: it carries `hashed_password`.
That's deliberately different from `schemas.UserPublic`, the API shape, which has
no password field at all. Keeping storage models separate from API models is a
core backend habit — it's how you guarantee a secret can never leak out through a
response just because someone returned the wrong object.

As with conversations, this is in-memory today; implementing `UserRepository`
against a real database later requires no changes anywhere else.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import UserModel


class User(BaseModel):
    username: str
    hashed_password: str  # NEVER the plaintext; set via security.hash_password()
    full_name: str | None = None
    disabled: bool = False


class UserRepository(ABC):
    @abstractmethod
    async def get_by_username(self, username: str) -> User | None: ...

    @abstractmethod
    async def add(self, user: User) -> None: ...


class InMemoryUserRepository(UserRepository):
    def __init__(self) -> None:
        self._users: dict[str, User] = {}

    async def get_by_username(self, username: str) -> User | None:
        return self._users.get(username)

    async def add(self, user: User) -> None:
        self._users[user.username] = user


class SqlAlchemyUserRepository(UserRepository):
    """Durable user store backed by an AsyncSession. Maps the `UserModel` row to
    the `User` domain model (and back) — the session owner handles commit/rollback."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_username(self, username: str) -> User | None:
        row = await self._session.get(UserModel, username)
        if row is None:
            return None
        return User(
            username=row.username,
            hashed_password=row.hashed_password,
            full_name=row.full_name,
            disabled=row.disabled,
        )

    async def add(self, user: User) -> None:
        self._session.add(
            UserModel(
                username=user.username,
                hashed_password=user.hashed_password,
                full_name=user.full_name,
                disabled=user.disabled,
            )
        )
        await self._session.flush()
