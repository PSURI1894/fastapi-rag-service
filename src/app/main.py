"""The application factory — assembles everything into one FastAPI app.

Two ideas worth internalizing here:

1. App factory (`create_app`): building the app inside a function (instead of at
   import time) means tests can spin up a fresh, isolated app per test. The
   module-level `app = create_app()` at the bottom is what uvicorn imports.

2. Lifespan: the modern replacement for the deprecated `@app.on_event("startup")`.
   Everything before `yield` runs once at startup (build the repo + service,
   configure logging); everything after runs at shutdown (close DB pools, flush
   clients). We stash shared singletons on `app.state` for the DI providers to read.
"""

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings
from app.db import create_all, create_engine, create_sessionmaker
from app.logging_config import configure_logging
from app.repositories.jobs import InMemoryJobStore
from app.repositories.users import SqlAlchemyUserRepository, User
from app.routers import auth, chat, documents, health
from app.security import hash_password
from app.services.rag import build_rag_service

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)

    # Singletons that live for the whole process: the RAG service, and the DB
    # engine + session factory (the engine owns ONE connection pool — never make a
    # new engine per request).
    app.state.rag_service = build_rag_service(settings)
    app.state.job_store = InMemoryJobStore()
    engine = create_engine(settings)
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)

    # Local/dev convenience: build the schema straight from the ORM metadata. In
    # production set DB_AUTO_CREATE=false and run `alembic upgrade head` instead.
    if settings.db_auto_create:
        await create_all(engine)

    # Seed one known user so there are credentials to log in with. Idempotent: only
    # inserts if missing, so restarts don't fail on a duplicate primary key.
    async with app.state.sessionmaker() as session:
        users = SqlAlchemyUserRepository(session)
        if await users.get_by_username(settings.demo_username) is None:
            await users.add(
                User(
                    username=settings.demo_username,
                    hashed_password=hash_password(settings.demo_password),
                    full_name="Demo User",
                )
            )
            await session.commit()

    # Log the DB backend, never the full URL (it may carry a password).
    db_backend = settings.database_url.split("://", 1)[0]
    logger.info(
        "startup complete env=%s db=%s version=%s", settings.app_env, db_backend, __version__
    )
    yield
    # --- shutdown ---
    await engine.dispose()
    logger.info("shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="FastAPI RAG Service",
        version=__version__,
        summary="Serve a (mock) RAG assistant with streaming, auth, and clean layering.",
        lifespan=lifespan,
    )

    # CORS: allow browser front-ends to call the API. Lock `allow_origins` down
    # to your real domains in production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Middleware runs around every request. This one tags each request with an id
    # and records how long it took — the foundation of request tracing.
    @app.middleware("http")
    async def add_request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = uuid4().hex[:12]
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-ms"] = f"{elapsed_ms:.1f}"
        logger.info(
            "%s %s -> %s (%.1fms) rid=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            request_id,
        )
        return response

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(documents.router)
    return app


# The ASGI app object uvicorn/gunicorn import: `uvicorn app.main:app`.
app = create_app()
