# FastAPI RAG Service — a learning project

A **production-shaped** FastAPI service that serves a (mock) Retrieval-Augmented
Generation assistant. The RAG core is faked so it runs instantly with **no API
keys or database**, but the *architecture* is the real thing — so every pattern
you learn here transfers directly to a live LLM/RAG service.

> Built to level up **advanced Python + FastAPI**: async, Pydantic v2, dependency
> injection, SSE streaming, the service/repository split, structured logging,
> middleware, and async testing.

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

Blocking chat (needs the API key header):

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "X-API-Key: dev-secret-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the refund window for damaged goods?"}'
```

**Streaming** chat — watch tokens arrive live (`-N` disables curl buffering):

```bash
curl -N -X POST http://127.0.0.1:8000/chat/stream \
  -H "X-API-Key: dev-secret-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the refund window for damaged goods?"}'
```

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
| [`schemas.py`](src/app/schemas.py) | Pydantic v2 models = request/response contract + free OpenAPI docs |
| [`security.py`](src/app/security.py) | Auth as a **dependency** (swap API-key → JWT later, routes unchanged) |
| [`repositories/conversations.py`](src/app/repositories/conversations.py) | Repository pattern — data access behind an interface |
| [`services/rag.py`](src/app/services/rag.py) | Business logic; **async generators** for token streaming |
| [`dependencies.py`](src/app/dependencies.py) | DI providers reading shared singletons off `app.state` |
| [`routers/chat.py`](src/app/routers/chat.py) | Routing, `Depends`, validation, **SSE streaming** |
| [`main.py`](src/app/main.py) | App factory, **lifespan** (startup/shutdown), middleware (request id + timing) |
| [`tests/conftest.py`](tests/conftest.py) | Async tests via httpx `ASGITransport` + running lifespan correctly |

The request flow for `POST /chat`:

```
client → middleware (request id + timer)
       → require_api_key dependency (401 if bad)
       → validate body against ChatRequest (422 if bad)
       → handler: repo.create/exists → rag.retrieve → rag.answer → repo.add_message
       → serialize ChatResponse → JSON
```

---

## The lesson ladder (what to build next)

This project is **Rung 1** of a bigger plan. Each rung adds ONE production layer.
Suggested order — and each is a self-contained lesson:

1. **JWT auth** — replace `security.py`'s API key with OAuth2 password flow + JWT
   (`python-jose`/`pyjwt`, `passlib`). Routes don't change; only `security.py` does.
2. **Real persistence** — add `SqlAlchemyConversationRepository` (SQLAlchemy 2.0
   async + `asyncpg` + Alembic migrations) implementing the same interface. Swap
   one line in `main.py`. This is why the repository pattern exists.
3. **Real RAG** — replace the body of `services/rag.py` with a vector retriever
   (Chroma/pgvector) + `langchain-anthropic` streaming. The `async for` shape is
   already correct, so routes/tests stay put. (You've done the RAG part before —
   this is where it plugs in.)
4. **Background ingestion** — add a `POST /documents` upload that chunks + embeds
   in the background. Start with `BackgroundTasks`, graduate to a task queue
   (ARQ/Celery + Redis) and a `GET /jobs/{id}` status endpoint.
5. **Rate limiting + caching** — Redis-backed rate limits per API key; cache
   retrievals.
6. **Observability** — JSON logs with the request id from the middleware,
   OpenTelemetry traces, Prometheus metrics, LangSmith for LLM traces.
7. **Deploy** — the `Dockerfile` is here; add CI (GitHub Actions: ruff + mypy +
   pytest) and ship it (Gunicorn + Uvicorn workers).

---

## Project layout

```
src/app/
  config.py                 # settings
  logging_config.py         # logging setup
  schemas.py                # Pydantic models
  security.py               # auth dependency
  dependencies.py           # DI providers
  main.py                   # app factory + lifespan + middleware
  services/rag.py           # the (mock) RAG pipeline
  repositories/conversations.py  # storage behind an interface
  routers/health.py         # GET /health
  routers/chat.py           # POST /chat, POST /chat/stream, GET /chat/{id}/history
tests/                      # async tests (pytest + httpx)
```
