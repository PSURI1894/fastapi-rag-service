"""Health endpoint — the first thing every deployment target hits.

Load balancers, Kubernetes, and Docker use a health check to decide if your
container is ready to receive traffic. Keep it cheap and dependency-light (a real
one might also ping the DB). No auth here — health checks are anonymous.
"""

from fastapi import APIRouter, Depends

from app import __version__
from app.config import Settings, get_settings
from app.schemas import HealthResponse

# An APIRouter is a mini-app you compose into the main app in main.py. Grouping
# routes into routers per resource is how FastAPI projects stay navigable.
router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(status="ok", env=settings.app_env, version=__version__)
