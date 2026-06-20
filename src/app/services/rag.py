"""The RAG service layer — a pluggable interface with two backends.

`RagService` is an ABC (same pattern as the repositories). Two implementations:

  MockRagService      -> keyword-overlap retrieval + a templated answer. No
                         dependencies, no API key, deterministic. The default,
                         and what the test suite runs against.
  AnthropicRagService -> REAL retrieval-augmented generation: semantic search
                         over a Chroma vector store (key-less local embeddings)
                         + answer streamed from Claude via the official SDK.

`build_rag_service(settings)` picks the backend from config. The heavy deps
(`anthropic`, `chromadb`) are an optional extra and are imported LAZILY inside
AnthropicRagService — so this module imports fine without them installed, which
keeps the default path and the tests dependency-free.

Both backends honour the same guardrail: if retrieval finds nothing relevant,
the answer is "I don't know" rather than a hallucination.
"""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.config import Settings
from app.schemas import Citation

# A tiny fake "corpus". The mock scores it by keyword overlap; the real backend
# embeds it into a vector store. In production this lives in a real vector DB
# populated by an ingestion pipeline (a later rung).
_CORPUS: list[tuple[str, str]] = [
    ("returns-policy.md#refunds",
     "Customers may request a refund within 30 days of delivery for damaged or defective goods."),
    ("returns-policy.md#exchanges",
     "Exchanges are accepted within 14 days if the item is unused and in original packaging."),
    ("shipping.md#delivery",
     "Standard delivery takes 3-5 business days; express delivery arrives next business day."),
    ("warranty.md#coverage",
     "All electronics include a 1-year limited warranty covering manufacturing defects."),
]

# Shared system prompt for the real backend: ground answers in the context and
# refuse otherwise. The "answer directly" line keeps Opus from narrating its
# reasoning into the visible response when thinking is off.
_SYSTEM_PROMPT = (
    "You are a support assistant. Answer the user's question using ONLY the provided "
    "context passages. If the context does not contain the answer, say you don't know — "
    "do not use outside knowledge or guess. Cite the source of any fact you use. "
    "Answer directly and concisely; do not narrate your reasoning."
)


class RagService(ABC):
    """The contract both backends satisfy."""

    @abstractmethod
    async def retrieve(self, question: str) -> list[Citation]:
        """Return the passages most relevant to the question."""

    @abstractmethod
    def stream_answer(self, question: str, citations: list[Citation]) -> AsyncIterator[str]:
        """Yield the answer one chunk at a time (an async generator)."""

    async def answer(self, question: str, citations: list[Citation]) -> str:
        """Non-streaming convenience: drain the stream into one string.

        Concrete on the ABC so both backends share it — the blocking endpoint is
        always defined in terms of the streaming one (single source of truth)."""
        chunks = [chunk async for chunk in self.stream_answer(question, citations)]
        return "".join(chunks).strip()


class MockRagService(RagService):
    """Dependency-free backend: naive keyword retrieval + a templated answer.
    Async + delay-simulated so its shape matches a real LLM client."""

    def __init__(self, response_delay_ms: int = 40, top_k: int = 2) -> None:
        self._delay_s = response_delay_ms / 1000
        self._top_k = top_k

    async def retrieve(self, question: str) -> list[Citation]:
        await asyncio.sleep(self._delay_s)  # imitate vector-search I/O
        query_words = {w.strip(".,?!").lower() for w in question.split()}
        scored: list[Citation] = []
        for source, text in _CORPUS:
            doc_words = {w.strip(".,?!").lower() for w in text.split()}
            overlap = query_words & doc_words
            if not overlap:
                continue
            score = len(overlap) / len(query_words or {""})
            scored.append(Citation(source=source, snippet=text, score=min(score, 1.0)))
        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[: self._top_k]

    async def stream_answer(
        self, question: str, citations: list[Citation]
    ) -> AsyncIterator[str]:
        for token in self._compose(question, citations).split(" "):
            await asyncio.sleep(self._delay_s)  # imitate per-token generation
            yield token + " "

    def _compose(self, question: str, citations: list[Citation]) -> str:
        if not citations:
            return "I don't know based on the available documents."
        top = citations[0]
        return (
            f"Based on the documentation: {top.snippet} "
            f"(source: {top.source}). Let me know if you need more detail."
        )


class AnthropicRagService(RagService):
    """Real RAG: Chroma semantic retrieval + Claude answer streaming.

    Heavy imports are done lazily in __init__ so importing this module never
    requires the `rag` extra. The Chroma collection is built once at construction
    (in lifespan) using Chroma's default key-less local embedding model — the
    first build downloads a small embedding model."""

    def __init__(self, settings: Settings) -> None:
        import anthropic  # lazy: only needed for the real backend
        import chromadb

        self._model = settings.anthropic_model
        self._max_tokens = settings.anthropic_max_tokens
        self._top_k = settings.rag_top_k
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

        # In-memory vector store seeded with the built-in corpus. No embedding
        # function passed → Chroma uses its default local (ONNX) model — key-less.
        collection = chromadb.EphemeralClient().create_collection("documents")
        collection.add(
            ids=[f"doc-{i}" for i in range(len(_CORPUS))],
            documents=[text for _, text in _CORPUS],
            metadatas=[{"source": source} for source, _ in _CORPUS],
        )
        self._collection = collection

    async def retrieve(self, question: str) -> list[Citation]:
        # Chroma's client is synchronous; run it off the event loop so it doesn't
        # block other requests.
        result = await asyncio.to_thread(
            self._collection.query, query_texts=[question], n_results=self._top_k
        )
        # Chroma types these result fields as Optional; default to empty for safety.
        documents = (result["documents"] or [[]])[0]
        metadatas = (result["metadatas"] or [[]])[0]
        distances = (result["distances"] or [[]])[0]

        citations: list[Citation] = []
        for document, metadata, distance in zip(documents, metadatas, distances, strict=False):
            # Map distance (0 = identical) to a 0..1 similarity-ish score.
            score = 1.0 / (1.0 + float(distance))
            citations.append(
                Citation(source=str(metadata.get("source", "")), snippet=document, score=score)
            )
        return citations

    async def stream_answer(
        self, question: str, citations: list[Citation]
    ) -> AsyncIterator[str]:
        if not citations:
            yield "I don't know based on the available documents."
            return

        context = "\n\n".join(f"[{c.source}] {c.snippet}" for c in citations)
        user_prompt = f"Context:\n{context}\n\nQuestion: {question}"
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=self._max_tokens,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            async for text in stream.text_stream:
                yield text


def build_rag_service(settings: Settings) -> RagService:
    """Pick the backend from config. Fails fast if 'anthropic' is selected without
    an API key — a misconfiguration we want surfaced at startup, not mid-request."""
    if settings.rag_backend == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("rag_backend='anthropic' requires ANTHROPIC_API_KEY to be set")
        return AnthropicRagService(settings)
    return MockRagService(
        response_delay_ms=settings.llm_response_delay_ms, top_k=settings.rag_top_k
    )
