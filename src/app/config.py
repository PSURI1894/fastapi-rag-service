"""Typed application settings (the "12-factor config" layer).

Why this matters: hard-coded constants and scattered `os.environ[...]` calls are
how real apps rot. Pydantic Settings gives you ONE typed object, validated at
startup, sourced from environment variables and an optional `.env` file. If a
value is missing or the wrong type, the app fails fast with a clear error instead
of blowing up deep in a request handler.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # env_file: load `.env` if present. extra="ignore": don't crash on unrelated
    # environment variables (there are always some in a real shell/container).
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"
    log_level: str = "INFO"
    llm_response_delay_ms: int = Field(default=40, ge=0)

    # --- Database ---
    # SQLAlchemy async URL. Default is a zero-setup local SQLite file. For Postgres:
    #   postgresql+asyncpg://user:password@localhost:5432/ragdb
    database_url: str = "sqlite+aiosqlite:///./app.db"
    # Create tables from the ORM metadata on startup. Handy for local/SQLite; in
    # production set this False and manage the schema with Alembic migrations.
    db_auto_create: bool = True
    # Echo SQL to the log — flip on when you want to SEE the queries SQLAlchemy emits.
    db_echo: bool = False

    # --- JWT auth ---
    # The signing secret. In prod, generate with `openssl rand -hex 32` and inject
    # via env — NEVER commit a real one. min_length guards against a weak key.
    jwt_secret_key: str = Field(default="dev-only-insecure-change-me-please", min_length=16)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = Field(default=30, ge=1)

    # --- Seed user (learning project only) ---
    # A real app stores users in a DB with a registration flow. Here we seed one
    # known user at startup so you have credentials to log in with.
    demo_username: str = "demo"
    demo_password: str = "demo-password"

    # --- RAG backend ---
    # "mock" (default): keyword retrieval + templated answer; zero deps, no key.
    # "anthropic": real semantic retrieval (Chroma) + Claude streaming. Needs the
    # `rag` extra installed (`uv sync --extra rag`) and an ANTHROPIC_API_KEY.
    rag_backend: Literal["mock", "anthropic"] = "mock"
    anthropic_api_key: str | None = None
    # Defaults to the most capable model. Switch to claude-sonnet-4-6 / claude-haiku-4-5
    # if you want lower cost — that's a deliberate choice, not a silent default.
    anthropic_model: str = "claude-opus-4-8"
    anthropic_max_tokens: int = Field(default=1024, ge=1)
    rag_top_k: int = Field(default=2, ge=1)


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton Settings instance.

    `@lru_cache` means the environment is parsed exactly once. It's also the
    standard FastAPI pattern: you depend on `get_settings`, and in tests you can
    override it. (We rely on the default values in tests, so no override needed.)
    """
    return Settings()
