"""Health check router."""

from fastapi import APIRouter

from app.schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Return application health status and version."""
    return HealthResponse(status="ok", version="0.1.0")
