"""Document ingestion endpoints.

    POST /documents       -> upload a text file; returns 202 + a job id immediately
    GET  /jobs            -> list the caller's ingestion jobs
    GET  /jobs/{job_id}   -> poll one job's status/result

The upload handler does the *fast* part inline (validate, create the job) and
hands the *slow* part (chunk + embed + index) to a BackgroundTask, so the client
isn't blocked on embedding. Jobs are owned, like conversations: 403 for someone
else's, 404 if missing.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status

from app.config import Settings, get_settings
from app.dependencies import get_job_store, get_rag_service
from app.limits import enforce_rate_limit
from app.repositories.jobs import Job, JobStore
from app.schemas import DocumentAccepted, JobPublic, UserPublic
from app.security import get_current_user
from app.services.ingestion import run_ingestion
from app.services.rag import RagService

# Per-user rate limit applies to uploads and job polling too.
router = APIRouter(tags=["documents"], dependencies=[Depends(enforce_rate_limit)])


def _to_public(job: Job) -> JobPublic:
    return JobPublic(
        job_id=job.id,
        status=job.status,
        document_name=job.document_name,
        chunk_count=job.chunk_count,
        error=job.error,
        created_at=job.created_at,
    )


@router.post("/documents", status_code=status.HTTP_202_ACCEPTED, response_model=DocumentAccepted)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: UserPublic = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    rag: RagService = Depends(get_rag_service),
    settings: Settings = Depends(get_settings),
) -> DocumentAccepted:
    raw = await file.read()
    if not raw.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="uploaded file is empty")
    text = raw.decode("utf-8", errors="replace")
    source = file.filename or "uploaded-document"

    job = await job_store.create(owner_username=current_user.username, document_name=source)
    # Schedule the slow work to run AFTER this response is sent.
    background_tasks.add_task(
        run_ingestion,
        job_store,
        rag,
        job.id,
        source,
        text,
        settings.chunk_words,
        settings.chunk_overlap,
    )
    return DocumentAccepted(job_id=job.id, status=job.status)


@router.get("/jobs", response_model=list[JobPublic])
async def list_jobs(
    current_user: UserPublic = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
) -> list[JobPublic]:
    jobs = await job_store.list_for_owner(current_user.username)
    return [_to_public(job) for job in jobs]


@router.get("/jobs/{job_id}", response_model=JobPublic)
async def get_job(
    job_id: str,
    current_user: UserPublic = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
) -> JobPublic:
    job = await job_store.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"job '{job_id}' not found")
    if job.owner_username != current_user.username:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="you do not have access to this job")
    return _to_public(job)
