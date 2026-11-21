"""Integration tests for authentication endpoints."""

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token, create_refresh_token
from app.models.user import User


@pytest.mark.asyncio
async def test_login_json_success(client: AsyncClient, student_user: User) -> None:
    """Verify JSON body login returns access and refresh tokens."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": student_user.email, "password": "StudentPass123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_form_success(client: AsyncClient, student_user: User) -> None:
    """Verify OAuth2 form login (Swagger UI) returns access and refresh tokens."""
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": student_user.email, "password": "StudentPass123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_invalid_password(client: AsyncClient, student_user: User) -> None:
    """Verify login with incorrect password returns 401 UNAUTHORIZED."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": student_user.email, "password": "WrongPassword999"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_login_unknown_email(client: AsyncClient) -> None:
    """Verify login with non-existent email returns 401 UNAUTHORIZED."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@hostel.example.com", "password": "Password123"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_login_validation_errors(client: AsyncClient) -> None:
    """Verify invalid email or missing fields return 422 VALIDATION_ERROR."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "not-an-email", "password": "Password123"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    resp_empty = await client.post(
        "/api/v1/auth/login",
        json={},
    )
    assert resp_empty.status_code == 422

    # Malformed JSON
    resp_malformed = await client.post(
        "/api/v1/auth/login",
        content="not valid json",
        headers={"Content-Type": "application/json"},
    )
    assert resp_malformed.status_code == 422
    assert resp_malformed.json()["error"]["code"] == "VALIDATION_ERROR"

    # JSON not an object
    resp_array = await client.post(
        "/api/v1/auth/login",
        json=["item1", "item2"],
    )
    assert resp_array.status_code == 422
    assert resp_array.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_refresh_token_endpoint(client: AsyncClient, student_user: User) -> None:
    """Verify refresh endpoint issues a new token pair."""
    refresh_token = create_refresh_token(user_id=student_user.id, role="student")

    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_refresh_token_with_access_token_rejected(
    client: AsyncClient, student_user: User
) -> None:
    """Verify refresh endpoint rejects access tokens."""
    access_token = create_access_token(user_id=student_user.id, role="student")

    resp = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": access_token},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_TOKEN_TYPE"


@pytest.mark.asyncio
async def test_get_me_endpoint(
    client: AsyncClient, student_user: User, student_headers: dict[str, str]
) -> None:
    """Verify GET /auth/me returns current user profile."""
    resp = await client.get("/api/v1/auth/me", headers=student_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(student_user.id)
    assert data["email"] == student_user.email
    assert data["role"] == "student"
    assert "hashed_password" not in data


@pytest.mark.asyncio
async def test_get_me_unauthenticated(client: AsyncClient) -> None:
    """Verify GET /auth/me without token returns 401 UNAUTHORIZED."""
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_change_password_endpoint(
    client: AsyncClient,
    student_user: User,
    student_headers: dict[str, str],
) -> None:
    """Verify change-password flow with valid and invalid inputs."""
    # Weak new password -> 422
    resp_weak = await client.post(
        "/api/v1/auth/change-password",
        headers=student_headers,
        json={"current_password": "StudentPass123", "new_password": "weak"},
    )
    assert resp_weak.status_code == 422

    # Wrong current password -> 401
    resp_wrong = await client.post(
        "/api/v1/auth/change-password",
        headers=student_headers,
        json={"current_password": "WrongOldPass123", "new_password": "NewStrongPass123"},
    )
    assert resp_wrong.status_code == 401
    assert resp_wrong.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"

    # Success
    resp_ok = await client.post(
        "/api/v1/auth/change-password",
        headers=student_headers,
        json={"current_password": "StudentPass123", "new_password": "NewStrongPass123"},
    )
    assert resp_ok.status_code == 200
    assert resp_ok.json()["message"] == "Password changed successfully"

    # Verify new password can be used to login
    resp_login = await client.post(
        "/api/v1/auth/login",
        json={"email": student_user.email, "password": "NewStrongPass123"},
    )
    assert resp_login.status_code == 200
