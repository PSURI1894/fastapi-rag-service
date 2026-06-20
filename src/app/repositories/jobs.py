"""Job tracking for background ingestion — the same repository pattern again.

A `Job` records the lifecycle of one background task: queued → running →
succeeded/failed. The `JobStore` is the interface; `InMemoryJobStore` is the
implementation used here.

Trade-off worth naming: this store is in-memory, so jobs vanish on restart and
aren't shared across processes. That's exactly why FastAPI `BackgroundTasks`
(in-process) is the matching execution mechanism. A production system that runs
work in a separate worker pool (ARQ/Celery + Redis) would persist jobs to Redis
or the database instead — and would implement THIS interface to do it.
"""

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

JobStatus = Literal["queued", "running", "succeeded", "failed"]


class Job(BaseModel):
    id: str
    owner_username: str
    document_name: str
    status: JobStatus
    chunk_count: int | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class JobStore(ABC):
    @abstractmethod
    async def create(self, owner_username: str, document_name: str) -> Job: ...

    @abstractmethod
    async def get(self, job_id: str) -> Job | None: ...

    @abstractmethod
    async def mark_running(self, job_id: str) -> None: ...

    @abstractmethod
    async def mark_succeeded(self, job_id: str, chunk_count: int) -> None: ...

    @abstractmethod
    async def mark_failed(self, job_id: str, error: str) -> None: ...

    @abstractmethod
    async def list_for_owner(self, owner_username: str) -> list[Job]: ...


class InMemoryJobStore(JobStore):
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    async def create(self, owner_username: str, document_name: str) -> Job:
        now = datetime.now(UTC)
        job = Job(
            id=uuid4().hex,
            owner_username=owner_username,
            document_name=document_name,
            status="queued",
            created_at=now,
            updated_at=now,
        )
        self._jobs[job.id] = job
        return job

    async def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    async def mark_running(self, job_id: str) -> None:
        self._update(job_id, status="running")

    async def mark_succeeded(self, job_id: str, chunk_count: int) -> None:
        self._update(job_id, status="succeeded", chunk_count=chunk_count)

    async def mark_failed(self, job_id: str, error: str) -> None:
        self._update(job_id, status="failed", error=error)

    async def list_for_owner(self, owner_username: str) -> list[Job]:
        return [job for job in self._jobs.values() if job.owner_username == owner_username]

    def _update(
        self,
        job_id: str,
        *,
        status: JobStatus,
        chunk_count: int | None = None,
        error: str | None = None,
    ) -> None:
        job = self._jobs.get(job_id)
        if job is None:  # the job was never created / already gone — nothing to update
            return
        job.status = status
        job.updated_at = datetime.now(UTC)
        if chunk_count is not None:
            job.chunk_count = chunk_count
        if error is not None:
            job.error = error
