"""Unit tests for the RAG service layer — the backend factory and the mock
backend. These run without the `rag` extra: the factory validates and raises
before it ever imports anthropic/chromadb, and the mock backend has no deps.
"""

import pytest

from app.config import Settings
from app.services.rag import MockRagService, RagService, build_rag_service


def test_build_defaults_to_mock() -> None:
    service = build_rag_service(Settings())
    assert isinstance(service, MockRagService)
    assert isinstance(service, RagService)


def test_build_anthropic_without_key_raises() -> None:
    # Explicit kwargs beat env, so this is deterministic even if a real key is set.
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        build_rag_service(Settings(rag_backend="anthropic", anthropic_api_key=None))


async def test_mock_retrieves_and_answers() -> None:
    service = MockRagService(response_delay_ms=0)
    citations = await service.retrieve("What is the refund window for damaged goods?")
    assert citations
    assert "refund" in citations[0].snippet.lower()

    answer = await service.answer("refund?", citations)
    assert "refund" in answer.lower()


async def test_mock_guardrail_when_nothing_relevant() -> None:
    service = MockRagService(response_delay_ms=0)
    citations = await service.retrieve("zzqq xylophone quark")
    assert citations == []

    answer = await service.answer("zzqq", citations)
    assert "don't know" in answer.lower()
