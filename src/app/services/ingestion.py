"""Document ingestion — chunking + the background worker that runs after upload.

`chunk_text` splits a document into overlapping windows (real RAG over long docs
needs chunks small enough to embed and retrieve precisely; overlap avoids losing
context that straddles a boundary). `run_ingestion` is what `BackgroundTasks`
executes after the upload response is sent: it drives one job through its
lifecycle and indexes the chunks into the RAG backend.
"""

from app.repositories.jobs import JobStore
from app.services.rag import RagService


def chunk_text(text: str, *, words_per_chunk: int = 120, overlap: int = 20) -> list[str]:
    """Split text into overlapping word windows. Dependency-free; a real pipeline
    might use a token-aware splitter (e.g. langchain-text-splitters)."""
    words = text.split()
    if not words:
        return []
    step = max(1, words_per_chunk - overlap)
    chunks: list[str] = []
    for start in range(0, len(words), step):
        chunks.append(" ".join(words[start : start + words_per_chunk]))
        if start + words_per_chunk >= len(words):
            break  # this window reached the end; don't emit trailing duplicates
    return chunks


async def run_ingestion(
    job_store: JobStore,
    rag: RagService,
    job_id: str,
    source: str,
    text: str,
    words_per_chunk: int,
    overlap: int,
) -> None:
    """Background task: chunk the document, index it, and record the outcome on the
    job. Any failure is captured onto the job rather than crashing the worker —
    the client sees status='failed' with the error, not a lost task."""
    await job_store.mark_running(job_id)
    try:
        chunks = chunk_text(text, words_per_chunk=words_per_chunk, overlap=overlap)
        indexed = await rag.index_document(source, chunks)
        await job_store.mark_succeeded(job_id, chunk_count=indexed)
    except Exception as exc:  # broad on purpose: persist ANY failure onto the job
        await job_store.mark_failed(job_id, error=str(exc))
