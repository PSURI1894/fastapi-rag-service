# FastAPI RAG Service — a learning project

A **production-shaped** FastAPI service that serves a Retrieval-Augmented
Generation assistant. It runs instantly with **no API keys** (a mock RAG backend
+ local SQLite by default), and flips to **real RAG** — semantic search over a
Chroma vector store + answers streamed from Claude — by setting two env vars. The
architecture is identical either way; only the backend swaps.

> Built to level up **advanced Python + FastAPI**: async, Pydantic v2, dependency
> injection, **OAuth2 + JWT auth**, **per-user authorization**, **async SQLAlchemy
> persistence (SQLite/Postgres) with Alembic migrations**, **real RAG (Chroma +
> Claude) behind a pluggable backend**, **background document ingestion (upload →
> job → poll)**, **per-user rate limiting + retrieval caching (in-memory or Redis)**,
> **observability (JSON logs, Prometheus `/metrics`, optional OpenTelemetry)**, SSE
> streaming, the service/repository split, middleware, and async testing.

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

**Upload a document** for background ingestion — returns **202** immediately with a
job id; the chunking + embedding happens in the background:

```bash
echo "The flux capacitor needs 1.21 gigawatts." > note.txt
JOB=$(curl -s -X POST http://127.0.0.1:8000/documents \
  -H "Authorization: Bearer $TOKEN" -F "file=@note.txt" \
  | python -c "import sys,json;print(json.load(sys.stdin)['job_id'])")

curl http://127.0.0.1:8000/jobs/$JOB -H "Authorization: Bearer $TOKEN"   # poll status
```

Poll `GET /jobs/{id}` until `status` is `succeeded`; then the uploaded content is
retrievable through `/chat`. (On Windows, prefer the **/docs** UI for file uploads —
native `curl.exe` mishandles `@`-file paths.)

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

## Rate limiting & caching

Both are **per-user** and default to **in-memory** (zero setup). The expensive
routers (`/chat`, `/documents`) enforce a fixed-window rate limit — exceed it and
you get **429** with a `Retry-After` header. Retrieval results are cached (keyed by
the normalised question) so identical queries skip the embedding + search; the TTL
is short to bound staleness after a new document is ingested.

To share limits and cache **across worker processes**, point them at Redis:

```bash
uv sync --extra redis
export REDIS_URL=redis://localhost:6379/0
export RATE_LIMIT_BACKEND=redis CACHE_BACKEND=redis
```

(PowerShell: `$env:REDIS_URL="redis://localhost:6379/0"`.) Tune with
`RATE_LIMIT_PER_MINUTE`, `CACHE_TTL_SECONDS`, or disable either with
`RATE_LIMIT_ENABLED=false` / `CACHE_ENABLED=false`.

---

## Observability (the three pillars)

- **Logs** — structured **JSON** to stdout (`LOG_FORMAT=json`, or `console` for
  local dev). The middleware stamps a request id into a `ContextVar`, so every log
  line emitted during a request carries the same `request_id` — grep one id to
  reconstruct a whole request.
- **Metrics** — `GET /metrics` serves Prometheus text: a request counter, a latency
  histogram, and an in-flight gauge, all labelled by the route *template* (not the
  raw path, to bound cardinality). Always on, no dependencies.
- **Traces** — optional **OpenTelemetry** auto-instrumentation (every request → a
  span tree). Off by default; enable with:

  ```bash
  uv sync --extra otel
  export OTEL_ENABLED=true
  # prints spans to the console; or ship them somewhere:
  # export OTEL_EXPORTER_OTLP_ENDPOINT=https://api.smith.langchain.com/otel/v1/traces
  uv run uvicorn app.main:app
  ```

  With no OTLP endpoint, spans print to the console. Point the endpoint at a
  collector — or LangSmith's OTLP ingest — to centralise LLM/request traces.

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
| [`services/ingestion.py`](src/app/services/ingestion.py) | Chunking + the **background worker** that ingests an uploaded doc and updates its job |
| [`services/cache.py`](src/app/services/cache.py) | `Cache` interface (in-memory / Redis / no-op) + `retrieve_cached` helper |
| [`services/ratelimit.py`](src/app/services/ratelimit.py) | `RateLimiter` interface — **fixed-window** counter (in-memory / Redis) |
| [`limits.py`](src/app/limits.py) | `enforce_rate_limit` dependency (429 + `Retry-After`); separate module to avoid an import cycle |
| [`logging_config.py`](src/app/logging_config.py) | **JSON logs** + a `request_id` `ContextVar` + filter so every log line carries the id |
| [`metrics.py`](src/app/metrics.py) | In-process **Prometheus** registry (counter/histogram/gauge) → `GET /metrics` |
| [`tracing.py`](src/app/tracing.py) | Optional **OpenTelemetry** FastAPI auto-instrumentation (no-op unless enabled) |
| [`repositories/jobs.py`](src/app/repositories/jobs.py) | `JobStore` interface + in-memory impl tracking ingestion job lifecycle |
| [`routers/documents.py`](src/app/routers/documents.py) | **`POST /documents`** (202 + `BackgroundTasks`), `GET /jobs`, `GET /jobs/{id}` |
| [`dependencies.py`](src/app/dependencies.py) | **Session-per-request** (`get_session` yield-dep) + per-request repositories |
| [`routers/auth.py`](src/app/routers/auth.py) | **OAuth2 password flow**: `POST /auth/token` (login) + `GET /auth/me` |
| [`routers/chat.py`](src/app/routers/chat.py) | **Per-user authorization** (own-conversation 403/404), a `GET /chat` listing, **SSE streaming** |
| [`main.py`](src/app/main.py) | App factory, **lifespan** (engine, schema, seed, rate-limit/cache), observability middleware (request-id + metrics), tracing setup |
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
- [x] **Rung 6 — Background ingestion.** `POST /documents` returns 202 + a job id;
  a `BackgroundTask` chunks + indexes the doc into the RAG backend; `GET /jobs/{id}`
  / `GET /jobs` report status (owner-scoped). `JobStore` interface is built so the
  execution can later swap to ARQ/Celery + Redis. Uploaded content is retrievable
  via `/chat` once the job succeeds.
- [x] **Rung 7 — Rate limiting + caching.** Per-user fixed-window rate limit on
  `/chat` + `/documents` (429 + `Retry-After`) and retrieval caching, both behind
  interfaces with in-memory defaults and an optional Redis backend (`--extra redis`).
  Verified live (4th request → 429) and by unit tests (cache serves repeat queries).
- [x] **Rung 8 — Observability.** Structured JSON logs with a request-id that
  propagates via a `ContextVar`; a Prometheus `/metrics` endpoint (counter +
  latency histogram + in-flight gauge, route-template labels); optional
  OpenTelemetry auto-instrumentation (`--extra otel`) exporting to console or OTLP
  (collector / LangSmith). Verified live: spans, JSON logs, and `/metrics`.
- [ ] **Rung 9 — Deploy.** The `Dockerfile` is here; add CI (GitHub Actions: ruff
  + mypy + pytest) and ship it (Gunicorn + Uvicorn workers).

---

## Project layout

```
src/app/
  config.py                 # settings (JWT, DB, RAG, rate-limit/cache, observability)
  logging_config.py         # JSON logs + request-id ContextVar/filter
  metrics.py                # in-process Prometheus registry (/metrics)
  tracing.py                # optional OpenTelemetry setup
  limits.py                 # enforce_rate_limit dependency
  schemas.py                # Pydantic API models (ChatRequest, Token, UserPublic, …)
  db.py                     # SQLAlchemy async engine/sessionmaker + ORM models
  security.py               # password hashing + JWT + get_current_user
  dependencies.py           # DI: session-per-request + per-request repositories
  main.py                   # app factory + lifespan (engine, schema, seed) + middleware
  services/rag.py           # RagService ABC + mock & Anthropic (Chroma+Claude) backends
  services/ingestion.py     # chunk_text + background ingestion worker
  services/cache.py         # Cache ABC (in-memory/Redis/no-op) + retrieve_cached
  services/ratelimit.py     # RateLimiter ABC (fixed-window; in-memory/Redis)
  limits.py                 # enforce_rate_limit dependency (429 + Retry-After)
  repositories/conversations.py  # ConversationRepository: in-memory + SQLAlchemy
  repositories/users.py     # UserRepository: in-memory + SQLAlchemy
  repositories/jobs.py      # JobStore: ingestion job lifecycle (in-memory)
  routers/health.py         # GET /health
  routers/auth.py           # POST /auth/token, GET /auth/me
  routers/chat.py           # GET /chat (list), POST /chat, POST /chat/stream, GET /chat/{id}/history
  routers/documents.py      # POST /documents, GET /jobs, GET /jobs/{id}
alembic/                    # migration environment + versions/
alembic.ini                 # alembic config (URL comes from app settings)
docker-compose.yml          # local Postgres for the production DB path
tests/                      # async tests: health, auth, chat + test_repository.py
```
