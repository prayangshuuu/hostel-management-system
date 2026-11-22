"""Integration tests for user management and RBAC access control."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.models.user import User


@pytest.mark.asyncio
async def test_create_user_admin_only(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_headers: dict[str, str],
    student_headers: dict[str, str],
) -> None:
    """Verify only admin can create new users, warden/student receive 403."""
    user_payload = {
        "email": "new_created@hostel.example.com",
        "full_name": "Created Person",
        "password": "Password123",
        "role": "warden",
    }

    # Unauthenticated -> 401
    resp_unauth = await client.post("/api/v1/users", json=user_payload)
    assert resp_unauth.status_code == 401

    # Student -> 403
    resp_student = await client.post("/api/v1/users", json=user_payload, headers=student_headers)
    assert resp_student.status_code == 403
    assert resp_student.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"

    # Warden -> 403
    resp_warden = await client.post("/api/v1/users", json=user_payload, headers=warden_headers)
    assert resp_warden.status_code == 403
    assert resp_warden.json()["error"]["code"] == "INSUFFICIENT_PERMISSIONS"

    # Admin -> 201
    resp_admin = await client.post("/api/v1/users", json=user_payload, headers=admin_headers)
    assert resp_admin.status_code == 201
    data = resp_admin.json()
    assert data["email"] == "new_created@hostel.example.com"
    assert data["role"] == "warden"
    assert "hashed_password" not in data


@pytest.mark.asyncio
async def test_create_user_duplicate_email(
    client: AsyncClient, admin_headers: dict[str, str], student_user: User
) -> None:
    """Verify creating a user with existing email returns 409 CONFLICT."""
    resp = await client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "email": student_user.email,
            "full_name": "Duplicate Person",
            "password": "Password123",
            "role": "student",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "EMAIL_EXISTS"


@pytest.mark.asyncio
async def test_create_user_weak_password(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    """Verify weak password returns 422 VALIDATION_ERROR."""
    resp = await client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "email": "weakpw@hostel.example.com",
            "full_name": "Weak PW",
            "password": "short",
            "role": "student",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_list_users_admin(
    client: AsyncClient,
    admin_headers: dict[str, str],
    admin_user: User,
    warden_user: User,
    student_user: User,
) -> None:
    """Verify admin can list users with pagination, filtering, and search."""
    resp = await client.get("/api/v1/users?page=1&size=10", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 3
    assert len(data["items"]) >= 3

    # Filter by role
    resp_warden = await client.get("/api/v1/users?role=warden", headers=admin_headers)
    assert resp_warden.status_code == 200
    assert all(u["role"] == "warden" for u in resp_warden.json()["items"])

    # Search
    resp_search = await client.get("/api/v1/users?search=student", headers=admin_headers)
    assert resp_search.status_code == 200
    assert any(u["id"] == str(student_user.id) for u in resp_search.json()["items"])


@pytest.mark.asyncio
async def test_get_user_by_id(
    client: AsyncClient,
    admin_headers: dict[str, str],
    student_headers: dict[str, str],
    student_user: User,
) -> None:
    """Verify admin can get user by ID; non-admin gets 403."""
    # Student -> 403
    resp_forbidden = await client.get(f"/api/v1/users/{student_user.id}", headers=student_headers)
    assert resp_forbidden.status_code == 403

    # Admin -> 200
    resp_admin = await client.get(f"/api/v1/users/{student_user.id}", headers=admin_headers)
    assert resp_admin.status_code == 200
    assert resp_admin.json()["id"] == str(student_user.id)

    # 404 for unknown user
    resp_not_found = await client.get(f"/api/v1/users/{uuid4()}", headers=admin_headers)
    assert resp_not_found.status_code == 404
    assert resp_not_found.json()["error"]["code"] == "USER_NOT_FOUND"


@pytest.mark.asyncio
async def test_update_and_deactivate_user(
    client: AsyncClient,
    admin_headers: dict[str, str],
    student_user: User,
) -> None:
    """Verify admin can update user fields and deactivate user."""
    # Update full_name and phone
    resp_update = await client.patch(
        f"/api/v1/users/{student_user.id}",
        headers=admin_headers,
        json={"full_name": "Updated Full Name", "phone": "+9876543210"},
    )
    assert resp_update.status_code == 200
    assert resp_update.json()["full_name"] == "Updated Full Name"
    assert resp_update.json()["phone"] == "+9876543210"

    # Deactivate user
    resp_deact = await client.post(
        f"/api/v1/users/{student_user.id}/deactivate",
        headers=admin_headers,
    )
    assert resp_deact.status_code == 200
    assert resp_deact.json()["is_active"] is False

    # Deactivated user cannot log in
    from app.core.rate_limit import limiter

    limiter.reset()
    resp_login = await client.post(
        "/api/v1/auth/login",
        json={"email": student_user.email, "password": "StudentPass123"},
    )
    assert resp_login.status_code == 401
    assert resp_login.json()["error"]["code"] == "INACTIVE_USER"
