"""Chat endpoints — the heart of the service, now scoped per user.

    GET  /chat                 -> list the caller's conversations
    POST /chat                 -> blocking: full answer as JSON
    POST /chat/stream          -> streaming: tokens as Server-Sent Events (SSE)
    GET  /chat/{id}/history    -> read one conversation back

Every route takes `current_user` (via the get_current_user dependency, which also
enforces auth) and only ever touches conversations that user owns. Accessing
someone else's conversation returns 403; a missing one returns 404.

SSE recap: keep the HTTP response open and write frames shaped like
`event: token\\n` + `data: {...}\\n` + a blank line. We drive it with Starlette's
StreamingResponse over an async generator — no extra library.
"""

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.dependencies import get_cache, get_rag_service, get_repository, get_sessionmaker
from app.limits import enforce_rate_limit
from app.repositories.conversations import (
    ConversationRepository,
    SqlAlchemyConversationRepository,
)
from app.schemas import ChatRequest, ChatResponse, ConversationSummary, Message, UserPublic
from app.security import get_current_user
from app.services.cache import Cache, retrieve_cached
from app.services.rag import RagService

# Every route here also enforces a per-user rate limit (429 when exceeded).
router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(enforce_rate_limit)])


async def _authorize_conversation(
    conversation_id: str, owner_username: str, repo: ConversationRepository
) -> None:
    """Allow access only to the caller's own conversation."""
    owner = await repo.get_owner(conversation_id)
    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"conversation '{conversation_id}' not found",
        )
    if owner != owner_username:
        # 403: it exists, but it's not yours. (Some APIs return 404 here instead, to
        # avoid revealing that the id exists at all — a deliberate security choice.)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="you do not have access to this conversation",
        )


async def _resolve_conversation(
    req: ChatRequest, owner_username: str, repo: ConversationRepository
) -> str:
    """Continue the caller's conversation, or start a new one they own."""
    if req.conversation_id is not None:
        await _authorize_conversation(req.conversation_id, owner_username, repo)
        return req.conversation_id
    return await repo.create(owner_username)


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    current_user: UserPublic = Depends(get_current_user),
    repo: ConversationRepository = Depends(get_repository),
) -> list[ConversationSummary]:
    """List only the conversations owned by the authenticated user."""
    return await repo.list_for_owner(current_user.username)


@router.post("", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    current_user: UserPublic = Depends(get_current_user),
    repo: ConversationRepository = Depends(get_repository),
    rag: RagService = Depends(get_rag_service),
    cache: Cache = Depends(get_cache),
    settings: Settings = Depends(get_settings),
) -> ChatResponse:
    """Blocking chat: retrieve (cached), generate the answer, persist, return JSON."""
    conversation_id = await _resolve_conversation(req, current_user.username, repo)
    await repo.add_message(conversation_id, "user", req.question)

    citations = await retrieve_cached(cache, rag, req.question, settings.cache_ttl_seconds)
    answer = await rag.answer(req.question, citations)

    await repo.add_message(conversation_id, "assistant", answer)
    return ChatResponse(conversation_id=conversation_id, answer=answer, citations=citations)


def _sse(event: str, data: dict[str, object]) -> str:
    """Format one Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    current_user: UserPublic = Depends(get_current_user),
    sessionmaker: async_sessionmaker[AsyncSession] = Depends(get_sessionmaker),
    rag: RagService = Depends(get_rag_service),
    cache: Cache = Depends(get_cache),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """Streaming chat over SSE: meta (citations) first, then tokens, then done.

    Uses the `sessionmaker` (not a request-scoped session) because the generator
    runs while the response streams — after the request scope, and its session,
    would already be gone. So we open one short session for the upfront writes and
    a second inside the generator for the final write.
    """
    # Authorize + persist the user's message before streaming starts, so a bad or
    # forbidden conversation_id returns a clean 404/403 (not a half-streamed error).
    async with sessionmaker() as session:
        repo = SqlAlchemyConversationRepository(session)
        conversation_id = await _resolve_conversation(req, current_user.username, repo)
        await repo.add_message(conversation_id, "user", req.question)
        await session.commit()

    async def event_generator() -> AsyncIterator[str]:
        # 1) Send retrieval results up front so the UI can show sources immediately.
        citations = await retrieve_cached(cache, rag, req.question, settings.cache_ttl_seconds)
        yield _sse(
            "meta",
            {"conversation_id": conversation_id, "citations": [c.model_dump() for c in citations]},
        )

        # 2) Stream the answer token-by-token as it's "generated".
        collected: list[str] = []
        async for token in rag.stream_answer(req.question, citations):
            collected.append(token)
            yield _sse("token", {"text": token})

        # 3) Persist the full answer in its OWN session, then signal completion.
        async with sessionmaker() as session:
            repo = SqlAlchemyConversationRepository(session)
            await repo.add_message(conversation_id, "assistant", "".join(collected).strip())
            await session.commit()
        yield _sse("done", {"conversation_id": conversation_id})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Disable proxy buffering (nginx) so chunks reach the client live.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{conversation_id}/history", response_model=list[Message])
async def history(
    conversation_id: str,
    current_user: UserPublic = Depends(get_current_user),
    repo: ConversationRepository = Depends(get_repository),
) -> list[Message]:
    await _authorize_conversation(conversation_id, current_user.username, repo)
    return await repo.history(conversation_id)
