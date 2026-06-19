"""The RAG service — the "business logic" layer.

This is a MOCK that imitates a real Retrieval-Augmented-Generation pipeline:
    retrieve(question)            -> find relevant passages (like a vector search)
    stream_answer(question, ...)  -> generate the answer token-by-token (like an LLM)

It deliberately uses `async def`, `await asyncio.sleep(...)` (to imitate network
I/O), and an async generator for streaming — so the *shape* matches a real LLM
client. To go live you replace the body of these two methods with calls to your
retriever + `langchain-anthropic` / the Anthropic SDK. Routes, DI, and tests stay
identical.

It also reproduces the guardrail from your Policy/Contract Assistant: if nothing
relevant is retrieved, it answers "I don't know" instead of hallucinating.
"""

import asyncio
from collections.abc import AsyncIterator

from app.schemas import Citation

# A tiny fake "corpus". In a real service this lives in a vector DB.
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


class RagService:
    def __init__(self, response_delay_ms: int = 40) -> None:
        # Convert ms -> seconds once; reused to simulate per-call / per-token latency.
        self._delay_s = response_delay_ms / 1000

    async def retrieve(self, question: str, *, top_k: int = 2) -> list[Citation]:
        """Return the most relevant passages.

        Real version: embed `question`, run an ANN search against a vector store,
        maybe rerank. Mock version: naive word-overlap scoring — but the async
        signature and return type are exactly what a real retriever would expose.
        """
        await asyncio.sleep(self._delay_s)  # imitate vector-search network I/O

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
        return scored[:top_k]

    async def stream_answer(
        self, question: str, citations: list[Citation]
    ) -> AsyncIterator[str]:
        """Yield the answer one token at a time (an async generator).

        This is the crux of LLM serving: tokens arrive over time, and we forward
        each one to the client immediately instead of waiting for the whole answer.
        A real implementation would `async for chunk in llm.astream(...)`.
        """
        answer = self._compose(question, citations)
        for token in answer.split(" "):
            await asyncio.sleep(self._delay_s)  # imitate per-token generation latency
            yield token + " "

    async def answer(self, question: str, citations: list[Citation]) -> str:
        """Non-streaming convenience: drain the stream into a single string.

        Note how the blocking endpoint is implemented purely in terms of the
        streaming one — single source of truth for how answers are produced.
        """
        return "".join([token async for token in self.stream_answer(question, citations)]).strip()

    def _compose(self, question: str, citations: list[Citation]) -> str:
        # The guardrail: no evidence -> refuse rather than make something up.
        if not citations:
            return "I don't know based on the available documents."
        top = citations[0]
        return (
            f"Based on the documentation: {top.snippet} "
            f"(source: {top.source}). Let me know if you need more detail."
        )
