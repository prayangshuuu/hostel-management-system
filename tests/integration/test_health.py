"""Integration tests for health endpoint."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.main import create_app


@pytest.mark.asyncio
async def test_health_check_db_ok(client: AsyncClient) -> None:
    """Test health check endpoint returns 200 and database ok status."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": settings.APP_VERSION,
        "database": "ok",
    }
    assert "x-request-id" in response.headers


@pytest.mark.asyncio
async def test_health_check_db_down() -> None:
    """Test health check endpoint returns database down status on database connection failure."""
    app = create_app()

    async def _failing_get_db() -> AsyncGenerator[AsyncSession, None]:
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute.side_effect = ConnectionRefusedError("Database unreachable")
        yield mock_session

    app.dependency_overrides[get_db] = _failing_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "version": settings.APP_VERSION,
            "database": "down",
        }
