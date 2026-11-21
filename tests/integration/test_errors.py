"""Integration tests for global exception handlers."""

from collections.abc import AsyncGenerator

import pytest
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationAppError,
)
from app.main import create_app

error_router = APIRouter(prefix="/test-errors")


class ItemPayload(BaseModel):
    """Test schema for validation testing."""

    name: str
    quantity: int


@error_router.get("/not-found")
async def trigger_not_found() -> None:
    raise NotFoundError("Room not found", details={"room_id": "123"})


@error_router.get("/conflict")
async def trigger_conflict() -> None:
    raise ConflictError("Bed already assigned", details={"bed_id": "456"})


@error_router.get("/forbidden")
async def trigger_forbidden() -> None:
    raise ForbiddenError("Warden not assigned to this hostel")


@error_router.get("/unauthorized")
async def trigger_unauthorized() -> None:
    raise UnauthorizedError("Missing bearer token")


@error_router.get("/validation-app")
async def trigger_validation_app() -> None:
    raise ValidationAppError("Date range is invalid", details={"field": "end_date"})


@error_router.get("/business-rule")
async def trigger_business_rule() -> None:
    raise BusinessRuleError("Cannot allocate bed in maintenance room")


@error_router.post("/validation-schema")
async def trigger_schema_validation(payload: ItemPayload) -> ItemPayload:
    return payload


@error_router.get("/unhandled-500")
async def trigger_unhandled() -> None:
    raise RuntimeError("Sensitive database credentials leaking test!")


@pytest.fixture
async def error_client() -> AsyncGenerator[AsyncClient, None]:
    """Test client equipped with exception-triggering test endpoints."""
    app = create_app()
    app.include_router(error_router)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_404_starlette_not_found(error_client: AsyncClient) -> None:
    """Test that requesting an unmapped URL returns standardized 404 JSON shape."""
    response = await error_client.get("/nonexistent-endpoint")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert "message" in body["error"]
    assert body["error"]["details"] == {}


@pytest.mark.asyncio
async def test_404_not_found_error(error_client: AsyncClient) -> None:
    """Test NotFoundError exception formatting."""
    response = await error_client.get("/test-errors/not-found")
    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "Room not found",
            "details": {"room_id": "123"},
        }
    }


@pytest.mark.asyncio
async def test_409_conflict_error(error_client: AsyncClient) -> None:
    """Test ConflictError exception formatting."""
    response = await error_client.get("/test-errors/conflict")
    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "CONFLICT",
            "message": "Bed already assigned",
            "details": {"bed_id": "456"},
        }
    }


@pytest.mark.asyncio
async def test_403_forbidden_error(error_client: AsyncClient) -> None:
    """Test ForbiddenError exception formatting."""
    response = await error_client.get("/test-errors/forbidden")
    assert response.status_code == 403
    assert response.json() == {
        "error": {
            "code": "FORBIDDEN",
            "message": "Warden not assigned to this hostel",
            "details": {},
        }
    }


@pytest.mark.asyncio
async def test_401_unauthorized_error(error_client: AsyncClient) -> None:
    """Test UnauthorizedError exception formatting."""
    response = await error_client.get("/test-errors/unauthorized")
    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "UNAUTHORIZED",
            "message": "Missing bearer token",
            "details": {},
        }
    }


@pytest.mark.asyncio
async def test_422_validation_app_error(error_client: AsyncClient) -> None:
    """Test ValidationAppError exception formatting."""
    response = await error_client.get("/test-errors/validation-app")
    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Date range is invalid",
            "details": {"field": "end_date"},
        }
    }


@pytest.mark.asyncio
async def test_400_business_rule_error(error_client: AsyncClient) -> None:
    """Test BusinessRuleError exception formatting."""
    response = await error_client.get("/test-errors/business-rule")
    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "BUSINESS_RULE_VIOLATION",
            "message": "Cannot allocate bed in maintenance room",
            "details": {},
        }
    }


@pytest.mark.asyncio
async def test_422_request_validation_error(error_client: AsyncClient) -> None:
    """Test FastAPI RequestValidationError formatting on invalid payload."""
    response = await error_client.post(
        "/test-errors/validation-schema",
        json={"name": "Chair", "quantity": "invalid_number"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Request validation failed"
    assert "errors" in body["error"]["details"]
    assert len(body["error"]["details"]["errors"]) > 0


@pytest.mark.asyncio
async def test_500_unhandled_exception(error_client: AsyncClient) -> None:
    """Test that unexpected exceptions return 500 without leaking stack traces or messages."""
    response = await error_client.get("/test-errors/unhandled-500")
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "An internal server error occurred",
            "details": {},
        }
    }
    assert "Sensitive" not in response.text


@pytest.mark.asyncio
async def test_unhandled_exception_handler_direct() -> None:
    """Test direct invocation of the registered global unhandled Exception handler."""
    import inspect

    from starlette.requests import Request

    app = create_app()
    handler = app.exception_handlers[Exception]
    req = Request(scope={"type": "http", "method": "GET", "path": "/test", "headers": []})
    result = handler(req, RuntimeError("Database leak test"))
    response = await result if inspect.isawaitable(result) else result
    assert response.status_code == 500
    assert response.body == (
        b'{"error":{"code":"INTERNAL_SERVER_ERROR",'
        b'"message":"An internal server error occurred","details":{}}}'
    )
