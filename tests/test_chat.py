"""Chat endpoint tests: auth, the blocking route, SSE streaming, and history.

These double as documentation — read them to see exactly how a client uses the API.
Every protected call now carries a JWT via the `auth_headers` fixture (conftest.py).
"""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient


async def test_chat_requires_auth(client: AsyncClient) -> None:
    # No Authorization header -> blocked by the get_current_user dependency.
    resp = await client.post("/chat", json={"question": "What is the refund policy?"})
    assert resp.status_code == 401


async def test_chat_rejects_bogus_token(client: AsyncClient) -> None:
    resp = await client.post(
        "/chat",
        headers={"Authorization": "Bearer not-a-real-jwt"},
        json={"question": "What is the refund policy?"},
    )
    assert resp.status_code == 401


async def test_chat_returns_answer_and_citations(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/chat",
        headers=auth_headers,
        json={"question": "What is the refund window for damaged goods?"},
    )
    assert resp.status_code == 200

    body = resp.json()
    assert body["conversation_id"]
    assert "refund" in body["answer"].lower()
    assert len(body["citations"]) >= 1
    assert 0.0 <= body["citations"][0]["score"] <= 1.0


async def test_unknown_question_triggers_guardrail(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # Nothing in the corpus overlaps -> the "I don't know" guardrail fires.
    resp = await client.post(
        "/chat",
        headers=auth_headers,
        json={"question": "zzqq xylophone quark?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["citations"] == []
    assert "don't know" in body["answer"].lower()


async def test_validation_rejects_empty_question(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # min_length=1 on the schema -> 422 Unprocessable Entity, handled by FastAPI.
    resp = await client.post("/chat", headers=auth_headers, json={"question": ""})
    assert resp.status_code == 422


async def test_conversation_is_persisted_and_continuable(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    first = await client.post(
        "/chat", headers=auth_headers, json={"question": "What is the refund policy?"}
    )
    cid = first.json()["conversation_id"]

    # Continue the same conversation by passing its id back.
    await client.post(
        "/chat",
        headers=auth_headers,
        json={"question": "And the warranty coverage?", "conversation_id": cid},
    )

    history = await client.get(f"/chat/{cid}/history", headers=auth_headers)
    assert history.status_code == 200
    messages = history.json()
    # 2 user turns + 2 assistant turns.
    assert len(messages) == 4
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"


async def test_history_404_for_unknown_conversation(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.get("/chat/does-not-exist/history", headers=auth_headers)
    assert resp.status_code == 404


async def test_streaming_emits_sse_events(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/chat/stream",
        headers=auth_headers,
        json={"question": "What is the refund window for damaged goods?"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    text = resp.text
    # The three event types our generator emits.
    assert "event: meta" in text
    assert "event: token" in text
    assert "event: done" in text


async def test_cannot_read_another_users_conversation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    make_user: Callable[[str, str], Awaitable[dict[str, str]]],
) -> None:
    # demo creates a conversation...
    created = await client.post(
        "/chat", headers=auth_headers, json={"question": "What is the refund policy?"}
    )
    cid = created.json()["conversation_id"]

    # ...a different user must not be able to read it.
    mallory = await make_user("mallory", "mallory-password")
    resp = await client.get(f"/chat/{cid}/history", headers=mallory)
    assert resp.status_code == 403


async def test_cannot_continue_another_users_conversation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    make_user: Callable[[str, str], Awaitable[dict[str, str]]],
) -> None:
    created = await client.post(
        "/chat", headers=auth_headers, json={"question": "What is the refund policy?"}
    )
    cid = created.json()["conversation_id"]

    mallory = await make_user("mallory", "mallory-password")
    resp = await client.post(
        "/chat",
        headers=mallory,
        json={"question": "sneaking in", "conversation_id": cid},
    )
    assert resp.status_code == 403


async def test_list_conversations_is_scoped_to_owner(
    client: AsyncClient,
    auth_headers: dict[str, str],
    make_user: Callable[[str, str], Awaitable[dict[str, str]]],
) -> None:
    # demo starts two conversations.
    await client.post("/chat", headers=auth_headers, json={"question": "first?"})
    await client.post("/chat", headers=auth_headers, json={"question": "second?"})

    # bob starts one.
    bob = await make_user("bob", "bob-password")
    await client.post("/chat", headers=bob, json={"question": "bob's one?"})

    mine = await client.get("/chat", headers=auth_headers)
    assert mine.status_code == 200
    assert len(mine.json()) == 2  # only demo's conversations

    bobs = await client.get("/chat", headers=bob)
    assert len(bobs.json()) == 1  # only bob's
