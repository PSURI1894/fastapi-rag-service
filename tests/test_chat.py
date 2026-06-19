"""Chat endpoint tests: auth, the blocking route, SSE streaming, and history.

These double as documentation — read them to see exactly how a client uses the API.
"""

from httpx import AsyncClient

HEADERS = {"X-API-Key": "dev-secret-key-change-me"}  # matches config default


async def test_chat_requires_api_key(client: AsyncClient) -> None:
    # No X-API-Key header -> blocked by the require_api_key dependency.
    resp = await client.post("/chat", json={"question": "What is the refund policy?"})
    assert resp.status_code == 401


async def test_chat_returns_answer_and_citations(client: AsyncClient) -> None:
    resp = await client.post(
        "/chat",
        headers=HEADERS,
        json={"question": "What is the refund window for damaged goods?"},
    )
    assert resp.status_code == 200

    body = resp.json()
    assert body["conversation_id"]
    assert "refund" in body["answer"].lower()
    assert len(body["citations"]) >= 1
    assert 0.0 <= body["citations"][0]["score"] <= 1.0


async def test_unknown_question_triggers_guardrail(client: AsyncClient) -> None:
    # Nothing in the corpus overlaps -> the "I don't know" guardrail fires.
    resp = await client.post(
        "/chat",
        headers=HEADERS,
        json={"question": "zzqq xylophone quark?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["citations"] == []
    assert "don't know" in body["answer"].lower()


async def test_validation_rejects_empty_question(client: AsyncClient) -> None:
    # min_length=1 on the schema -> 422 Unprocessable Entity, handled by FastAPI.
    resp = await client.post("/chat", headers=HEADERS, json={"question": ""})
    assert resp.status_code == 422


async def test_conversation_is_persisted_and_continuable(client: AsyncClient) -> None:
    first = await client.post(
        "/chat", headers=HEADERS, json={"question": "What is the refund policy?"}
    )
    cid = first.json()["conversation_id"]

    # Continue the same conversation by passing its id back.
    await client.post(
        "/chat",
        headers=HEADERS,
        json={"question": "And the warranty coverage?", "conversation_id": cid},
    )

    history = await client.get(f"/chat/{cid}/history", headers=HEADERS)
    assert history.status_code == 200
    messages = history.json()
    # 2 user turns + 2 assistant turns.
    assert len(messages) == 4
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"


async def test_history_404_for_unknown_conversation(client: AsyncClient) -> None:
    resp = await client.get("/chat/does-not-exist/history", headers=HEADERS)
    assert resp.status_code == 404


async def test_streaming_emits_sse_events(client: AsyncClient) -> None:
    resp = await client.post(
        "/chat/stream",
        headers=HEADERS,
        json={"question": "What is the refund window for damaged goods?"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    text = resp.text
    # The three event types our generator emits.
    assert "event: meta" in text
    assert "event: token" in text
    assert "event: done" in text
