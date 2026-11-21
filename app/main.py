"""Application entrypoint and factory."""

from fastapi import FastAPI

from app.api.v1 import api_router
from app.core.config import settings


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
    )

    application.include_router(api_router, prefix="/api/v1")

    return application


app = create_app()
