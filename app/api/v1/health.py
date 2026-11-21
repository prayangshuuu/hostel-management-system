"""Health check router."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.schemas.health import HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def get_health(db: Annotated[AsyncSession, Depends(get_db)]) -> HealthResponse:
    """Return application health status, version, and database connectivity."""
    db_status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("Database health check failed: %s", exc)
        db_status = "down"

    return HealthResponse(
        status="ok",
        version=settings.APP_VERSION,
        database=db_status,
    )
