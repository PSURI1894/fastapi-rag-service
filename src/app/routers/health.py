"""Health endpoint — the first thing every deployment target hits.

Load balancers, Kubernetes, and Docker use a health check to decide if your
container is ready to receive traffic. Keep it cheap and dependency-light (a real
one might also ping the DB). No auth here — health checks are anonymous.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from app import __version__
from app.config import Settings, get_settings
from app.dependencies import get_metrics
from app.metrics import Metrics
from app.schemas import HealthResponse

# An APIRouter is a mini-app you compose into the main app in main.py. Grouping
# routes into routers per resource is how FastAPI projects stay navigable.
router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(status="ok", env=settings.app_env, version=__version__)


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
async def metrics(registry: Metrics = Depends(get_metrics)) -> PlainTextResponse:
    """Prometheus scrape target. Anonymous, like /health — in production you'd
    restrict it to your monitoring network rather than exposing it publicly."""
    return PlainTextResponse(
        registry.render(), media_type="text/plain; version=0.0.4; charset=utf-8"
    )
