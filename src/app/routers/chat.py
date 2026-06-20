"""Chat endpoints — the heart of the service.

Three routes, all requiring auth (declared once at the router level):
    POST /chat            -> blocking: return the full answer as JSON
    POST /chat/stream     -> streaming: push tokens as Server-Sent Events (SSE)
    GET  /chat/{id}/history -> read a conversation back

The streaming route is the important one for LLM serving. SSE is a dead-simple
text protocol over a normal HTTP response: you keep the connection open and write
chunks shaped like:

    event: token\\n
    data: {"text": "Based "}\\n
    \\n                       <- blank line terminates one event

Browsers consume this natively via `EventSource`; any HTTP client can read it as
a stream. We use Starlette's `StreamingResponse` driven by an async generator —
no extra library needed.
"""

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.dependencies import get_rag_service, get_repository
from app.repositories.conversations import ConversationRepository
from app.schemas import ChatRequest, ChatResponse, Message
from app.security import get_current_user
from app.services.rag import RagService

# dependencies=[Depends(get_current_user)] applies JWT auth to EVERY route below.
# (We don't need the user object in these handlers yet — we only need to require a
# valid token. Inject `current_user: UserPublic = Depends(get_current_user)` into a
# handler when you want to scope data per user — that's the next enhancement.)
router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(get_current_user)])


async def _resolve_conversation(req: ChatRequest, repo: ConversationRepository) -> str:
    """Continue the given conversation, or start a fresh one. 404 if the id is bogus."""
    if req.conversation_id is not None:
        if not await repo.exists(req.conversation_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"conversation '{req.conversation_id}' not found",
            )
        return req.conversation_id
    return await repo.create()


@router.post("", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    repo: ConversationRepository = Depends(get_repository),
    rag: RagService = Depends(get_rag_service),
) -> ChatResponse:
    """Blocking chat: retrieve, generate the whole answer, persist, return JSON."""
    conversation_id = await _resolve_conversation(req, repo)
    await repo.add_message(conversation_id, "user", req.question)

    citations = await rag.retrieve(req.question)
    answer = await rag.answer(req.question, citations)

    await repo.add_message(conversation_id, "assistant", answer)
    return ChatResponse(conversation_id=conversation_id, answer=answer, citations=citations)


def _sse(event: str, data: dict[str, object]) -> str:
    """Format one Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    repo: ConversationRepository = Depends(get_repository),
    rag: RagService = Depends(get_rag_service),
) -> StreamingResponse:
    """Streaming chat over SSE: meta (citations) first, then tokens, then done."""
    conversation_id = await _resolve_conversation(req, repo)
    await repo.add_message(conversation_id, "user", req.question)

    async def event_generator() -> AsyncIterator[str]:
        # 1) Send retrieval results up front so the UI can show sources immediately.
        citations = await rag.retrieve(req.question)
        yield _sse(
            "meta",
            {"conversation_id": conversation_id, "citations": [c.model_dump() for c in citations]},
        )

        # 2) Stream the answer token-by-token as it's "generated".
        collected: list[str] = []
        async for token in rag.stream_answer(req.question, citations):
            collected.append(token)
            yield _sse("token", {"text": token})

        # 3) Persist the full answer and tell the client we're finished.
        await repo.add_message(conversation_id, "assistant", "".join(collected).strip())
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
    repo: ConversationRepository = Depends(get_repository),
) -> list[Message]:
    if not await repo.exists(conversation_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"conversation '{conversation_id}' not found",
        )
    return await repo.history(conversation_id)
