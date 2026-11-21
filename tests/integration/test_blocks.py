"""Integration tests for block endpoints and warden access scoping."""

import pytest
from httpx import AsyncClient

from app.models.user import User


@pytest.mark.asyncio
async def test_block_crud_lifecycle(
    client: AsyncClient,
    admin_headers: dict[str, str],
    student_headers: dict[str, str],
) -> None:
    """Verify admin can create, update, and delete blocks; student receives 403."""
    hostel_resp = await client.post(
        "/api/v1/hostels",
        json={"name": "Engineering Hostel", "code": "ENG-01", "gender_type": "mixed"},
        headers=admin_headers,
    )
    hostel_id = hostel_resp.json()["id"]

    # Student cannot create block -> 403
    resp_student_create = await client.post(
        f"/api/v1/hostels/{hostel_id}/blocks",
        json={"name": "Block 1", "floor_count": 3},
        headers=student_headers,
    )
    assert resp_student_create.status_code == 403

    # Admin creates block -> 201
    resp_admin_create = await client.post(
        f"/api/v1/hostels/{hostel_id}/blocks",
        json={"name": "Block 1", "floor_count": 3},
        headers=admin_headers,
    )
    assert resp_admin_create.status_code == 201
    block = resp_admin_create.json()
    assert block["name"] == "Block 1"
    assert block["floor_count"] == 3
    block_id = block["id"]

    # Duplicate block name in same hostel -> 409
    resp_dup = await client.post(
        f"/api/v1/hostels/{hostel_id}/blocks",
        json={"name": "Block 1", "floor_count": 2},
        headers=admin_headers,
    )
    assert resp_dup.status_code == 409
    assert resp_dup.json()["error"]["code"] == "BLOCK_NAME_EXISTS"

    # Admin updates block -> 200
    resp_update = await client.patch(
        f"/api/v1/blocks/{block_id}",
        json={"name": "Block A-North", "floor_count": 5},
        headers=admin_headers,
    )
    assert resp_update.status_code == 200
    assert resp_update.json()["name"] == "Block A-North"
    assert resp_update.json()["floor_count"] == 5

    # Student cannot update block -> 403
    resp_student_update = await client.patch(
        f"/api/v1/blocks/{block_id}",
        json={"name": "Hacked Name"},
        headers=student_headers,
    )
    assert resp_student_update.status_code == 403

    # Admin deletes block -> 204
    resp_delete = await client.delete(f"/api/v1/blocks/{block_id}", headers=admin_headers)
    assert resp_delete.status_code == 204

    # Subsequent GET returns 404
    resp_get = await client.get(f"/api/v1/blocks/{block_id}", headers=admin_headers)
    assert resp_get.status_code == 404
    assert resp_get.json()["error"]["code"] == "BLOCK_NOT_FOUND"


@pytest.mark.asyncio
async def test_warden_scoping_for_blocks(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_headers: dict[str, str],
    warden_user: User,
    student_headers: dict[str, str],
) -> None:
    """Verify warden can read blocks of assigned hostel, gets 403 on unassigned hostel."""
    # Create two hostels
    h1 = await client.post(
        "/api/v1/hostels",
        json={"name": "Assigned Hall", "code": "AH-SCOPE", "gender_type": "mixed"},
        headers=admin_headers,
    )
    h1_id = h1.json()["id"]

    h2 = await client.post(
        "/api/v1/hostels",
        json={"name": "Unassigned Hall", "code": "UH-SCOPE", "gender_type": "mixed"},
        headers=admin_headers,
    )
    h2_id = h2.json()["id"]

    # Create blocks in both
    b1_resp = await client.post(
        f"/api/v1/hostels/{h1_id}/blocks",
        json={"name": "Assigned Block", "floor_count": 2},
        headers=admin_headers,
    )
    b1_id = b1_resp.json()["id"]

    b2_resp = await client.post(
        f"/api/v1/hostels/{h2_id}/blocks",
        json={"name": "Unassigned Block", "floor_count": 2},
        headers=admin_headers,
    )
    b2_id = b2_resp.json()["id"]

    # Assign warden_user to hostel 1
    assign_resp = await client.post(
        f"/api/v1/hostels/{h1_id}/wardens",
        json={"user_id": str(warden_user.id)},
        headers=admin_headers,
    )
    assert assign_resp.status_code == 201

    # Warden listing blocks of assigned hostel -> 200
    resp_assigned = await client.get(
        f"/api/v1/hostels/{h1_id}/blocks",
        headers=warden_headers,
    )
    assert resp_assigned.status_code == 200
    assert len(resp_assigned.json()) == 1
    assert resp_assigned.json()[0]["id"] == b1_id

    # Warden getting block in assigned hostel -> 200
    resp_block_ok = await client.get(f"/api/v1/blocks/{b1_id}", headers=warden_headers)
    assert resp_block_ok.status_code == 200

    # Warden listing blocks of unassigned hostel -> 403
    resp_unassigned = await client.get(
        f"/api/v1/hostels/{h2_id}/blocks",
        headers=warden_headers,
    )
    assert resp_unassigned.status_code == 403
    assert resp_unassigned.json()["error"]["code"] == "FORBIDDEN"

    # Warden getting block in unassigned hostel -> 403
    resp_block_forbidden = await client.get(f"/api/v1/blocks/{b2_id}", headers=warden_headers)
    assert resp_block_forbidden.status_code == 403
    assert resp_block_forbidden.json()["error"]["code"] == "FORBIDDEN"

    # Student listing blocks -> 403
    resp_student = await client.get(f"/api/v1/hostels/{h1_id}/blocks", headers=student_headers)
    assert resp_student.status_code == 403
    assert resp_student.json()["error"]["code"] == "FORBIDDEN"
