# FastAPI RAG Service — a learning project

A **production-shaped** FastAPI service that serves a (mock) Retrieval-Augmented
Generation assistant. The RAG core is faked so it runs instantly with **no API
keys or database**, but the *architecture* is the real thing — so every pattern
you learn here transfers directly to a live LLM/RAG service.

> Built to level up **advanced Python + FastAPI**: async, Pydantic v2, dependency
> injection, **OAuth2 + JWT auth**, SSE streaming, the service/repository split,
> structured logging, middleware, and async testing.

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

## How it's wired (read the code in this order)

| File | Concept it teaches |
|---|---|
| [`config.py`](src/app/config.py) | Typed settings from env / `.env` (Pydantic Settings), fail-fast validation |
| [`schemas.py`](src/app/schemas.py) | Pydantic v2 models = request/response contract; storage vs API models (`UserPublic` hides the hash) |
| [`security.py`](src/app/security.py) | **Password hashing (Argon2), JWT issue/verify, `get_current_user` dependency** |
| [`repositories/users.py`](src/app/repositories/users.py) | User store; internal `User` (has hash) vs API `UserPublic` |
| [`repositories/conversations.py`](src/app/repositories/conversations.py) | Repository pattern — data access behind an interface |
| [`services/rag.py`](src/app/services/rag.py) | Business logic; **async generators** for token streaming |
| [`dependencies.py`](src/app/dependencies.py) | DI providers reading shared singletons off `app.state` |
| [`routers/auth.py`](src/app/routers/auth.py) | **OAuth2 password flow**: `POST /auth/token` (login) + `GET /auth/me` |
| [`routers/chat.py`](src/app/routers/chat.py) | Routing, `Depends`, validation, **SSE streaming** (now JWT-protected) |
| [`main.py`](src/app/main.py) | App factory, **lifespan** (startup/shutdown, seeds the demo user), middleware |
| [`tests/conftest.py`](tests/conftest.py) | Async tests via httpx `ASGITransport`; `auth_headers` fixture logs in for a token |

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
- [ ] **Rung 3 — Real persistence.** Add `SqlAlchemyConversationRepository` /
  `SqlAlchemyUserRepository` (SQLAlchemy 2.0 async + `asyncpg` + Alembic) behind
  the SAME interfaces. Swap a line in `main.py`. This is why the repos exist.
- [ ] **Rung 4 — Per-user data (authorization).** Now that requests carry an
  identity, scope conversations to their owner: inject `current_user` into the
  chat handlers and key conversations by user id (403 on someone else's data).
- [ ] **Rung 5 — Real RAG.** Replace the body of `services/rag.py` with a vector
  retriever (Chroma/pgvector) + `langchain-anthropic` streaming. The `async for`
  shape is already correct, so routes/tests stay put.
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
  config.py                 # settings (incl. JWT + seed-user config)
  logging_config.py         # logging setup
  schemas.py                # Pydantic API models (ChatRequest, Token, UserPublic, …)
  security.py               # password hashing + JWT + get_current_user
  dependencies.py           # DI providers
  main.py                   # app factory + lifespan (seeds demo user) + middleware
  services/rag.py           # the (mock) RAG pipeline
  repositories/conversations.py  # conversation storage behind an interface
  repositories/users.py     # user storage behind an interface
  routers/health.py         # GET /health
  routers/auth.py           # POST /auth/token, GET /auth/me
  routers/chat.py           # POST /chat, POST /chat/stream, GET /chat/{id}/history
tests/                      # async tests (pytest + httpx): health, auth, chat
```
