# FastAPI RAG Service — a learning project

A **production-shaped** FastAPI service that serves a Retrieval-Augmented
Generation assistant. It runs instantly with **no API keys** (a mock RAG backend
+ local SQLite by default), and flips to **real RAG** — semantic search over a
Chroma vector store + answers streamed from Claude — by setting two env vars. The
architecture is identical either way; only the backend swaps.

> Built to level up **advanced Python + FastAPI**: async, Pydantic v2, dependency
> injection, **OAuth2 + JWT auth**, **per-user authorization**, **async SQLAlchemy
> persistence (SQLite/Postgres) with Alembic migrations**, **real RAG (Chroma +
> Claude) behind a pluggable backend**, SSE streaming, the service/repository
> split, structured logging, middleware, and async testing.

---

## Quickstart

```bash
# from the project root
uv sync                 # create the venv + install deps (uv reads pyproject.toml)

uv run uvicorn app.main:app --reload     # start the dev server on :8000
```

Open the interactive docs (generated automatically from your Pydantic models):

- Swagger UI → http://127.0.0.1:8000/docs
- ReDoc      → http://127.0.0.1:8000/redoc

Run the tests:

```bash
uv run pytest            # all tests, in-process, no network
uv run ruff check .      # lint
uv run ruff format .     # format
uv run mypy              # static type-check (strict)
```

---

## Try it

Health (no auth):

```bash
curl http://127.0.0.1:8000/health
```

**Log in** to get a JWT (seed user: `demo` / `demo-password`). Note the
form-encoded body — that's the OAuth2 spec:

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/auth/token \
  -d "username=demo&password=demo-password" | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
```

Check who you are:

```bash
curl http://127.0.0.1:8000/auth/me -H "Authorization: Bearer $TOKEN"
```

Blocking chat (send the token as a Bearer header):

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the refund window for damaged goods?"}'
```

**Streaming** chat — watch tokens arrive live (`-N` disables curl buffering):

```bash
curl -N -X POST http://127.0.0.1:8000/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the refund window for damaged goods?"}'
```

List **your** conversations (scoped to the authenticated user):

```bash
curl http://127.0.0.1:8000/chat -H "Authorization: Bearer $TOKEN"
```

Conversations are owned by their creator: reading or continuing someone else's
conversation returns **403**, and a non-existent one returns **404**.

> In the **/docs** UI, click **Authorize**, enter the username/password, and Swagger
> will attach the Bearer token to every request for you.

You'll see Server-Sent Events stream in:

```
event: meta
data: {"conversation_id": "…", "citations": [...]}

event: token
data: {"text": "Based "}

event: token
data: {"text": "on "}
…
event: done
data: {"conversation_id": "…"}
```

---

## Database

By default the app uses a local **SQLite** file (`app.db`) and creates the schema
on startup — nothing to install. Data persists across restarts.

To develop against **Postgres** (the production target):

```bash
docker compose up -d                                   # start Postgres
export DATABASE_URL="postgresql+asyncpg://rag:ragpw@localhost:5432/ragdb"
export DB_AUTO_CREATE=false                             # let migrations own the schema
uv run alembic upgrade head                             # create tables via Alembic
uv run uvicorn app.main:app --reload
```

(PowerShell: `$env:DATABASE_URL = "..."`.) The **same** SQLAlchemy async code and
repositories drive both databases — only `DATABASE_URL` changes. Migrations:

```bash
uv run alembic upgrade head        # apply all migrations
uv run alembic downgrade -1        # roll back one
uv run alembic revision --autogenerate -m "add X"   # create a new migration
```

---

## RAG backend (mock vs. real)

`services/rag.py` defines a `RagService` interface with two implementations,
selected by `RAG_BACKEND`:

- **`mock`** (default) — keyword retrieval + a templated answer. Zero deps, no
  key, deterministic. This is what the test suite runs against.
- **`anthropic`** — **real RAG**: semantic search over a Chroma vector store
  (key-less local embedding model) + the answer streamed from Claude via the
  official `anthropic` SDK.

Turn on the real backend:

```bash
uv sync --extra rag            # installs anthropic + chromadb (heavy)
export RAG_BACKEND=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
# optional: export ANTHROPIC_MODEL=claude-sonnet-4-6   # cheaper than the default opus
uv run uvicorn app.main:app --reload
```

(PowerShell: `$env:RAG_BACKEND="anthropic"`.) The routes, auth, persistence, and
streaming are **unchanged** — only the service implementation swaps, because the
streaming endpoint already consumes an async token iterator. Default model is
`claude-opus-4-8` (most capable); switch to Sonnet/Haiku to cut cost. The first
real call downloads a ~80 MB local embedding model (one-time).

---

## How it's wired (read the code in this order)

| File | Concept it teaches |
|---|---|
| [`config.py`](src/app/config.py) | Typed settings from env / `.env` (Pydantic Settings), fail-fast validation |
| [`schemas.py`](src/app/schemas.py) | Pydantic v2 models = request/response contract; storage vs API models (`UserPublic` hides the hash) |
| [`db.py`](src/app/db.py) | **SQLAlchemy 2.0 async**: engine factory, session maker, ORM models (`*Model`) |
| [`security.py`](src/app/security.py) | Password hashing (Argon2), JWT issue/verify, `get_current_user` dependency |
| [`repositories/conversations.py`](src/app/repositories/conversations.py) | **Two impls of one interface**: in-memory *and* `SqlAlchemyConversationRepository` |
| [`repositories/users.py`](src/app/repositories/users.py) | User store (in-memory + SQLAlchemy); internal `User` vs API `UserPublic` |
| [`services/rag.py`](src/app/services/rag.py) | **Pluggable RAG**: `RagService` ABC + mock & Anthropic backends, a factory, **async generators** for token streaming, **optional deps via lazy imports** |
| [`dependencies.py`](src/app/dependencies.py) | **Session-per-request** (`get_session` yield-dep) + per-request repositories |
| [`routers/auth.py`](src/app/routers/auth.py) | **OAuth2 password flow**: `POST /auth/token` (login) + `GET /auth/me` |
| [`routers/chat.py`](src/app/routers/chat.py) | **Per-user authorization** (own-conversation 403/404), a `GET /chat` listing, **SSE streaming** |
| [`main.py`](src/app/main.py) | App factory, **lifespan** (opens engine, creates schema, seeds user), middleware |
| [`alembic/`](alembic/) | Async migration env + the initial schema migration |
| [`tests/`](tests/) | Async HTTP tests (in-memory SQLite) + `test_repository.py` (data layer in isolation) |

The request flow for `POST /chat`:

```
client → middleware (request id + timer)
       → get_current_user dependency: decode+verify JWT, load user (401 if bad)
       → validate body against ChatRequest (422 if bad)
       → handler: repo.create/exists → rag.retrieve → rag.answer → repo.add_message
       → serialize ChatResponse → JSON
```

…and to get that token in the first place:

```
client → POST /auth/token (username+password, form-encoded)
       → authenticate_user: look up user, verify_password against Argon2 hash
       → create_access_token: sign a JWT { sub, exp } with the secret
       → { access_token, token_type: "bearer" }
```

---

## The lesson ladder (what to build next)

Each rung adds ONE production layer; each is a self-contained lesson.

- [x] **Rung 1 — Core service.** App factory, lifespan, DI, repository pattern,
  async RAG service, SSE streaming, structured logging, middleware, async tests.
- [x] **Rung 2 — OAuth2 + JWT auth.** Argon2 password hashing, a login endpoint
  issuing signed JWTs, `get_current_user` verifying them, a user store. Only
  `security.py` + the router's dependency changed on the protected routes.
- [x] **Rung 3 — Real persistence.** `SqlAlchemyConversationRepository` /
  `SqlAlchemyUserRepository` (SQLAlchemy 2.0 async; SQLite by default, Postgres via
  `asyncpg`) behind the SAME interfaces, with Alembic migrations. Routes/services
  unchanged; the DI moved to session-per-request. Data survives restarts.
- [x] **Rung 4 — Per-user data (authorization).** Conversations are owned;
  handlers inject `current_user` and only touch the caller's data (403 on
  someone else's, 404 if missing). Added `GET /chat` to list your own. Migration
  0002 adds the `owner_username` column + index + FK.
- [x] **Rung 5 — Real RAG.** `services/rag.py` is now a `RagService` ABC with a
  mock backend (default) and an `AnthropicRagService` (Chroma semantic search +
  Claude streaming via the official SDK), chosen by a factory. Heavy deps are an
  optional extra with lazy imports; routes/tests stay put. (Retrieval verified
  end-to-end with real embeddings; generation needs your `ANTHROPIC_API_KEY`.)
- [ ] **Rung 6 — Background ingestion.** A `POST /documents` upload that chunks +
  embeds in the background (`BackgroundTasks` → ARQ/Celery + Redis) with a
  `GET /jobs/{id}` status endpoint.
- [ ] **Rung 7 — Rate limiting + caching.** Redis-backed per-user rate limits;
  cache retrievals.
- [ ] **Rung 8 — Observability.** JSON logs carrying the request id, OpenTelemetry
  traces, Prometheus metrics, LangSmith for LLM traces.
- [ ] **Rung 9 — Deploy.** The `Dockerfile` is here; add CI (GitHub Actions: ruff
  + mypy + pytest) and ship it (Gunicorn + Uvicorn workers).

---

## Project layout

```
src/app/
  config.py                 # settings (incl. JWT, seed-user, and DB config)
  logging_config.py         # logging setup
  schemas.py                # Pydantic API models (ChatRequest, Token, UserPublic, …)
  db.py                     # SQLAlchemy async engine/sessionmaker + ORM models
  security.py               # password hashing + JWT + get_current_user
  dependencies.py           # DI: session-per-request + per-request repositories
  main.py                   # app factory + lifespan (engine, schema, seed) + middleware
  services/rag.py           # RagService ABC + mock & Anthropic (Chroma+Claude) backends
  repositories/conversations.py  # ConversationRepository: in-memory + SQLAlchemy
  repositories/users.py     # UserRepository: in-memory + SQLAlchemy
  routers/health.py         # GET /health
  routers/auth.py           # POST /auth/token, GET /auth/me
  routers/chat.py           # GET /chat (list), POST /chat, POST /chat/stream, GET /chat/{id}/history
alembic/                    # migration environment + versions/
alembic.ini                 # alembic config (URL comes from app settings)
docker-compose.yml          # local Postgres for the production DB path
tests/                      # async tests: health, auth, chat + test_repository.py
```
