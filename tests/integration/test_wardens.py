"""Integration tests for warden assignment endpoints."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.models.user import User


@pytest.mark.asyncio
async def test_warden_assignment_lifecycle(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_headers: dict[str, str],
    warden_user: User,
    student_headers: dict[str, str],
    student_user: User,
) -> None:
    """Verify warden assignment creation, role validation, listing, and removal."""
    hostel_resp = await client.post(
        "/api/v1/hostels",
        json={"name": "Science Hostel", "code": "SCI-01", "gender_type": "female"},
        headers=admin_headers,
    )
    hostel_id = hostel_resp.json()["id"]

    # Student cannot assign warden -> 403
    resp_student = await client.post(
        f"/api/v1/hostels/{hostel_id}/wardens",
        json={"user_id": str(warden_user.id)},
        headers=student_headers,
    )
    assert resp_student.status_code == 403

    # Assign non-existent user -> 404
    resp_ghost = await client.post(
        f"/api/v1/hostels/{hostel_id}/wardens",
        json={"user_id": str(uuid4())},
        headers=admin_headers,
    )
    assert resp_ghost.status_code == 404
    assert resp_ghost.json()["error"]["code"] == "USER_NOT_FOUND"

    # Assign user with student role -> 422
    resp_wrong_role = await client.post(
        f"/api/v1/hostels/{hostel_id}/wardens",
        json={"user_id": str(student_user.id)},
        headers=admin_headers,
    )
    assert resp_wrong_role.status_code == 422
    assert resp_wrong_role.json()["error"]["code"] == "INVALID_WARDEN_ROLE"

    # Assign valid warden -> 201
    resp_assign = await client.post(
        f"/api/v1/hostels/{hostel_id}/wardens",
        json={"user_id": str(warden_user.id)},
        headers=admin_headers,
    )
    assert resp_assign.status_code == 201
    assign_data = resp_assign.json()
    assert assign_data["user_id"] == str(warden_user.id)
    assert assign_data["hostel_id"] == hostel_id
    assert assign_data["user_email"] == warden_user.email
    assert assign_data["user_full_name"] == warden_user.full_name

    # Duplicate assignment -> 409
    resp_dup = await client.post(
        f"/api/v1/hostels/{hostel_id}/wardens",
        json={"user_id": str(warden_user.id)},
        headers=admin_headers,
    )
    assert resp_dup.status_code == 409
    assert resp_dup.json()["error"]["code"] == "WARDEN_ALREADY_ASSIGNED"

    # Assigned warden can list wardens -> 200
    resp_list_warden = await client.get(
        f"/api/v1/hostels/{hostel_id}/wardens",
        headers=warden_headers,
    )
    assert resp_list_warden.status_code == 200
    assert len(resp_list_warden.json()) == 1
    assert resp_list_warden.json()[0]["user_id"] == str(warden_user.id)

    # Student cannot list wardens -> 403
    resp_list_student = await client.get(
        f"/api/v1/hostels/{hostel_id}/wardens",
        headers=student_headers,
    )
    assert resp_list_student.status_code == 403

    # Student cannot remove warden -> 403
    resp_rem_student = await client.delete(
        f"/api/v1/hostels/{hostel_id}/wardens/{warden_user.id}",
        headers=student_headers,
    )
    assert resp_rem_student.status_code == 403

    # Remove non-existent assignment -> 404
    resp_rem_nf = await client.delete(
        f"/api/v1/hostels/{hostel_id}/wardens/{uuid4()}",
        headers=admin_headers,
    )
    assert resp_rem_nf.status_code == 404
    assert resp_rem_nf.json()["error"]["code"] == "WARDEN_ASSIGNMENT_NOT_FOUND"

    # Admin removes warden -> 204
    resp_remove = await client.delete(
        f"/api/v1/hostels/{hostel_id}/wardens/{warden_user.id}",
        headers=admin_headers,
    )
    assert resp_remove.status_code == 204

    # List is now empty
    resp_list_after = await client.get(
        f"/api/v1/hostels/{hostel_id}/wardens",
        headers=admin_headers,
    )
    assert resp_list_after.status_code == 200
    assert len(resp_list_after.json()) == 0
