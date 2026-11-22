"""Integration tests for Request-ID middleware and request timing."""

import logging
import re
import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_request_id_generated_when_not_provided(client: AsyncClient) -> None:
    """Verify that requests without X-Request-ID receive a generated UUID hex header."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    req_id = response.headers.get("x-request-id")
    assert req_id is not None
    # Verify it matches 32 hex characters
    assert re.fullmatch(r"[0-9a-f]{32}", req_id) is not None


@pytest.mark.asyncio
async def test_request_id_echoed_when_provided(client: AsyncClient) -> None:
    """Verify that custom X-Request-ID header from client is preserved and echoed."""
    custom_id = f"custom-req-{uuid.uuid4()}"
    response = await client.get("/api/v1/health", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers.get("x-request-id") == custom_id


@pytest.mark.asyncio
async def test_request_timing_logged(client: AsyncClient) -> None:
    """Verify that request timing and method are logged with request ID."""
    logger = logging.getLogger("app.middleware.request")
    logger.setLevel(logging.INFO)
    logger.disabled = False

    class RecordHandler(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.records: list[logging.LogRecord] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.records.append(record)

    handler = RecordHandler()
    logger.addHandler(handler)
    try:
        response = await client.get("/api/v1/health")
        assert response.status_code == 200

        matching_records = [rec for rec in handler.records if "GET" in rec.getMessage()]
        assert len(matching_records) >= 1
        record = matching_records[0]
        msg = record.getMessage()
        assert "/api/v1/health" in msg
        assert "200" in msg
        assert "ms" in msg
    finally:
        logger.removeHandler(handler)
