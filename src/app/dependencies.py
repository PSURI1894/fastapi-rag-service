"""Dependency providers — how routes get the repository and RAG service.

We create ONE repository and ONE RAG service at startup (in main.py's `lifespan`)
and stash them on `app.state`. These tiny functions read them back. Routes then
declare `repo: ConversationRepository = Depends(get_repository)` and FastAPI
injects the shared instance.

Why through `Depends` instead of importing a global? Because dependencies are
trivially OVERRIDABLE in tests (`app.dependency_overrides[...] = fake`), and they
keep your routes decoupled from construction details. This is FastAPI's core
design pattern — lean on it.
"""

from fastapi import Request

from app.repositories.conversations import ConversationRepository
from app.services.rag import RagService


def get_repository(request: Request) -> ConversationRepository:
    return request.app.state.repository  # type: ignore[no-any-return]


def get_rag_service(request: Request) -> RagService:
    return request.app.state.rag_service  # type: ignore[no-any-return]
