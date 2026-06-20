"""Document ingestion endpoint tests.

Note: under httpx's ASGITransport, a FastAPI BackgroundTask runs as part of the
request cycle — so by the time `client.post("/documents")` returns, the job has
already finished. That makes these tests deterministic. (In production with a
separate worker, the job would still be 'queued' when the POST returns — the
client would poll until 'succeeded'.)
"""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient

# A document with a distinctive word so we can prove it became retrievable.
DOC = {
    "file": (
        "policy.txt",
        b"The zorptastic widget requires calibration every fortnight.",
        "text/plain",
    )
}


async def test_upload_requires_auth(client: AsyncClient) -> None:
    resp = await client.post("/documents", files=DOC)
    assert resp.status_code == 401


async def test_upload_ingests_and_makes_content_retrievable(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.post("/documents", headers=auth_headers, files=DOC)
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"  # work hasn't run at response time
    job_id = body["job_id"]

    # The background task has run by now (see module docstring).
    job = await client.get(f"/jobs/{job_id}", headers=auth_headers)
    assert job.status_code == 200
    assert job.json()["status"] == "succeeded"
    assert job.json()["chunk_count"] >= 1

    # The uploaded content is now retrievable through the SAME RAG service.
    chat = await client.post("/chat", headers=auth_headers, json={"question": "zorptastic?"})
    assert chat.status_code == 200
    assert "zorptastic" in chat.json()["answer"].lower()


async def test_empty_upload_is_rejected(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/documents", headers=auth_headers, files={"file": ("empty.txt", b"   ", "text/plain")}
    )
    assert resp.status_code == 400


async def test_job_404_for_unknown_id(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.get("/jobs/does-not-exist", headers=auth_headers)
    assert resp.status_code == 404


async def test_cannot_read_another_users_job(
    client: AsyncClient,
    auth_headers: dict[str, str],
    make_user: Callable[[str, str], Awaitable[dict[str, str]]],
) -> None:
    created = await client.post("/documents", headers=auth_headers, files=DOC)
    job_id = created.json()["job_id"]

    mallory = await make_user("mallory", "mallory-password")
    resp = await client.get(f"/jobs/{job_id}", headers=mallory)
    assert resp.status_code == 403


async def test_jobs_listing_is_scoped_to_owner(
    client: AsyncClient,
    auth_headers: dict[str, str],
    make_user: Callable[[str, str], Awaitable[dict[str, str]]],
) -> None:
    await client.post("/documents", headers=auth_headers, files=DOC)
    await client.post("/documents", headers=auth_headers, files=DOC)

    bob = await make_user("bob", "bob-password")
    await client.post("/documents", headers=bob, files=DOC)

    mine = await client.get("/jobs", headers=auth_headers)
    assert mine.status_code == 200
    assert len(mine.json()) == 2

    bobs = await client.get("/jobs", headers=bob)
    assert len(bobs.json()) == 1
