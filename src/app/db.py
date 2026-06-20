"""SQLAlchemy 2.0 async database layer: engine, session factory, and ORM models.

This file is the ONLY place that knows we use SQLAlchemy. The repositories build
on the `AsyncSession` it produces; everything above the repositories stays
database-agnostic.

ORM models here (`*Model`) are the STORAGE shape — rows in tables. They are
distinct from the Pydantic models in schemas.py (the API shape) and the small
domain models in the repositories. Mapping between them happens inside the
repositories, so a column rename never ripples out to the API.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool

from app.config import Settings


class Base(DeclarativeBase):
    """Declarative base — `Base.metadata` is the catalogue of all tables, used by
    both `create_all` (dev) and Alembic (prod) to build the schema."""


class UserModel(Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(255), primary_key=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str | None] = mapped_column(String(255), default=None)
    disabled: Mapped[bool] = mapped_column(default=False)


class ConversationModel(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MessageModel(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def create_engine(settings: Settings) -> AsyncEngine:
    """Build the async engine. In-memory SQLite needs special treatment: a single
    shared connection (StaticPool), otherwise every connection would see its own
    empty database and the schema/data would 'vanish' between calls."""
    url = settings.database_url
    if url.startswith("sqlite") and (url.endswith("://") or ":memory:" in url):
        return create_async_engine(
            url,
            echo=settings.db_echo,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_async_engine(url, echo=settings.db_echo)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: ORM objects stay readable after commit, so we can map
    # them to Pydantic models without triggering surprise lazy-loads.
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_all(engine: AsyncEngine) -> None:
    """Create every table declared on Base.metadata. Dev/local convenience — the
    production schema is owned by Alembic migrations instead."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
