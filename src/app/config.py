"""Typed application settings (the "12-factor config" layer).

Why this matters: hard-coded constants and scattered `os.environ[...]` calls are
how real apps rot. Pydantic Settings gives you ONE typed object, validated at
startup, sourced from environment variables and an optional `.env` file. If a
value is missing or the wrong type, the app fails fast with a clear error instead
of blowing up deep in a request handler.
"""

from functools import lru_cache

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
    # Field(min_length=8) => a too-short key is rejected at startup, not at request time.
    api_key: str = Field(default="dev-secret-key-change-me", min_length=8)
    log_level: str = "INFO"
    llm_response_delay_ms: int = Field(default=40, ge=0)


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton Settings instance.

    `@lru_cache` means the environment is parsed exactly once. It's also the
    standard FastAPI pattern: you depend on `get_settings`, and in tests you can
    override it. (We rely on the default values in tests, so no override needed.)
    """
    return Settings()
