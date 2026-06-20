"""Unit tests for the chunker — pure function, no async, no app."""

from app.services.ingestion import chunk_text


def test_empty_text_yields_no_chunks() -> None:
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_short_text_is_one_chunk() -> None:
    assert chunk_text("hello world") == ["hello world"]


def test_long_text_is_split_with_overlap() -> None:
    text = " ".join(str(i) for i in range(250))
    chunks = chunk_text(text, words_per_chunk=100, overlap=20)

    assert len(chunks) >= 3
    assert all(len(c.split()) <= 100 for c in chunks)
    # The tail of one chunk overlaps the head of the next (step = 100 - 20 = 80).
    assert chunks[0].split()[-20:] == chunks[1].split()[:20]
