"""Integration tests for hostel endpoints."""

from uuid import uuid4

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_hostel_admin_only(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_headers: dict[str, str],
    student_headers: dict[str, str],
) -> None:
    """Verify only admin can create hostels; non-admin receives 403."""
    payload = {
        "name": "Mandela Hall",
        "code": "MH-01",
        "gender_type": "male",
        "address": "North Campus",
    }

    # Unauthenticated
    resp_unauth = await client.post("/api/v1/hostels", json=payload)
    assert resp_unauth.status_code == 401

    # Student -> 403
    resp_student = await client.post("/api/v1/hostels", json=payload, headers=student_headers)
    assert resp_student.status_code == 403

    # Warden -> 403
    resp_warden = await client.post("/api/v1/hostels", json=payload, headers=warden_headers)
    assert resp_warden.status_code == 403

    # Admin -> 201
    resp_admin = await client.post("/api/v1/hostels", json=payload, headers=admin_headers)
    assert resp_admin.status_code == 201
    data = resp_admin.json()
    assert data["name"] == "Mandela Hall"
    assert data["code"] == "MH-01"
    assert data["gender_type"] == "male"
    assert data["total_capacity"] == 0
    assert data["is_deleted"] is False


@pytest.mark.asyncio
async def test_create_hostel_duplicate_code(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Verify duplicate hostel code returns 409 Conflict."""
    payload = {
        "name": "Alpha Hostel",
        "code": "DUP-01",
        "gender_type": "mixed",
    }
    resp1 = await client.post("/api/v1/hostels", json=payload, headers=admin_headers)
    assert resp1.status_code == 201

    resp2 = await client.post("/api/v1/hostels", json=payload, headers=admin_headers)
    assert resp2.status_code == 409
    assert resp2.json()["error"]["code"] == "HOSTEL_CODE_EXISTS"


@pytest.mark.asyncio
async def test_list_and_get_hostels(
    client: AsyncClient,
    admin_headers: dict[str, str],
    student_headers: dict[str, str],
) -> None:
    """Verify all authenticated users can list and get hostels with filtering/search."""
    # Create test hostels
    h1_resp = await client.post(
        "/api/v1/hostels",
        json={"name": "Boys Wing One", "code": "BW-01", "gender_type": "male"},
        headers=admin_headers,
    )
    assert h1_resp.status_code == 201
    h1_id = h1_resp.json()["id"]

    h2_resp = await client.post(
        "/api/v1/hostels",
        json={"name": "Girls Wing One", "code": "GW-01", "gender_type": "female"},
        headers=admin_headers,
    )
    assert h2_resp.status_code == 201

    # Student lists all
    resp_list = await client.get("/api/v1/hostels?page=1&size=10", headers=student_headers)
    assert resp_list.status_code == 200
    data = resp_list.json()
    assert data["total"] >= 2
    assert len(data["items"]) >= 2

    # Filter by gender_type
    resp_filter = await client.get("/api/v1/hostels?gender_type=female", headers=student_headers)
    assert resp_filter.status_code == 200
    items = resp_filter.json()["items"]
    assert all(item["gender_type"] == "female" for item in items)

    # Search by code
    resp_search = await client.get("/api/v1/hostels?search=BW-01", headers=student_headers)
    assert resp_search.status_code == 200
    search_items = resp_search.json()["items"]
    assert any(item["code"] == "BW-01" for item in search_items)

    # Get by ID
    resp_get = await client.get(f"/api/v1/hostels/{h1_id}", headers=student_headers)
    assert resp_get.status_code == 200
    assert resp_get.json()["id"] == h1_id
    assert resp_get.json()["total_capacity"] == 0

    # Get non-existent
    resp_nf = await client.get(f"/api/v1/hostels/{uuid4()}", headers=student_headers)
    assert resp_nf.status_code == 404
    assert resp_nf.json()["error"]["code"] == "HOSTEL_NOT_FOUND"


@pytest.mark.asyncio
async def test_update_hostel(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_headers: dict[str, str],
) -> None:
    """Verify admin can update hostel fields; non-admin receives 403; duplicate code gets 409."""
    h1 = await client.post(
        "/api/v1/hostels",
        json={"name": "Hostel 1", "code": "UPD-01", "gender_type": "male"},
        headers=admin_headers,
    )
    h1_id = h1.json()["id"]

    h2 = await client.post(
        "/api/v1/hostels",
        json={"name": "Hostel 2", "code": "UPD-02", "gender_type": "female"},
        headers=admin_headers,
    )
    h2_id = h2.json()["id"]

    # Warden forbidden
    resp_warden = await client.patch(
        f"/api/v1/hostels/{h1_id}",
        json={"name": "New Name"},
        headers=warden_headers,
    )
    assert resp_warden.status_code == 403

    # Duplicate code
    resp_dup = await client.patch(
        f"/api/v1/hostels/{h2_id}",
        json={"code": "UPD-01"},
        headers=admin_headers,
    )
    assert resp_dup.status_code == 409
    assert resp_dup.json()["error"]["code"] == "HOSTEL_CODE_EXISTS"

    # Success update
    resp_ok = await client.patch(
        f"/api/v1/hostels/{h1_id}",
        json={"name": "Renamed Hostel 1", "address": "Campus South"},
        headers=admin_headers,
    )
    assert resp_ok.status_code == 200
    assert resp_ok.json()["name"] == "Renamed Hostel 1"
    assert resp_ok.json()["address"] == "Campus South"


@pytest.mark.asyncio
async def test_soft_delete_hostel(
    client: AsyncClient,
    admin_headers: dict[str, str],
    student_headers: dict[str, str],
) -> None:
    """Verify soft delete marks is_deleted and hides hostel from list and get queries."""
    created = await client.post(
        "/api/v1/hostels",
        json={"name": "Delete Me Hall", "code": "DEL-01", "gender_type": "mixed"},
        headers=admin_headers,
    )
    hostel_id = created.json()["id"]

    # Student cannot delete
    resp_forbid = await client.delete(f"/api/v1/hostels/{hostel_id}", headers=student_headers)
    assert resp_forbid.status_code == 403

    # Admin deletes
    resp_del = await client.delete(f"/api/v1/hostels/{hostel_id}", headers=admin_headers)
    assert resp_del.status_code == 204

    # Subsequent GET returns 404
    resp_get = await client.get(f"/api/v1/hostels/{hostel_id}", headers=student_headers)
    assert resp_get.status_code == 404
    assert resp_get.json()["error"]["code"] == "HOSTEL_NOT_FOUND"

    # Excluded from list
    resp_list = await client.get(
        "/api/v1/hostels?search=DEL-01",
        headers=student_headers,
    )
    assert resp_list.status_code == 200
    assert resp_list.json()["total"] == 0
    assert len(resp_list.json()["items"]) == 0
