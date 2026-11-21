"""Integration tests for room endpoints, bed generation, and availability search."""

from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.room import Bed
from app.models.user import User


@pytest.mark.asyncio
async def test_room_crud_and_bed_generation(
    client: AsyncClient,
    admin_headers: dict[str, str],
    student_headers: dict[str, str],
) -> None:
    """Verify room creation auto-generates beds, duplicate numbers 409, and CRUD lifecycle."""
    # Create hostel and block
    h_resp = await client.post(
        "/api/v1/hostels",
        json={"name": "Engineering Hostel", "code": "ENG-R1", "gender_type": "mixed"},
        headers=admin_headers,
    )
    hostel_id = h_resp.json()["id"]

    b_resp = await client.post(
        f"/api/v1/hostels/{hostel_id}/blocks",
        json={"name": "Block R", "floor_count": 3},
        headers=admin_headers,
    )
    block_id = b_resp.json()["id"]

    # Student cannot create room -> 403
    resp_student_create = await client.post(
        f"/api/v1/blocks/{block_id}/rooms",
        json={
            "number": "101",
            "floor": 1,
            "room_type": "double",
            "capacity": 2,
            "monthly_rent": "4500.00",
        },
        headers=student_headers,
    )
    assert resp_student_create.status_code == 403

    # Type / capacity mismatch -> 422
    resp_mismatch = await client.post(
        f"/api/v1/blocks/{block_id}/rooms",
        json={
            "number": "101",
            "floor": 1,
            "room_type": "single",
            "capacity": 2,
            "monthly_rent": "4500.00",
        },
        headers=admin_headers,
    )
    assert resp_mismatch.status_code == 422
    assert resp_mismatch.json()["error"]["code"] == "INVALID_CAPACITY_FOR_ROOM_TYPE"

    # Admin creates valid room -> 201
    resp_create = await client.post(
        f"/api/v1/blocks/{block_id}/rooms",
        json={
            "number": "101",
            "floor": 1,
            "room_type": "double",
            "capacity": 2,
            "monthly_rent": "4500.00",
        },
        headers=admin_headers,
    )
    assert resp_create.status_code == 201
    room = resp_create.json()
    assert room["number"] == "101"
    assert room["capacity"] == 2
    assert room["status"] == "available"
    assert len(room["beds"]) == 2
    assert [b["label"] for b in room["beds"]] == ["A", "B"]
    room_id = room["id"]

    # Duplicate room number in block -> 409
    resp_dup = await client.post(
        f"/api/v1/blocks/{block_id}/rooms",
        json={
            "number": "101",
            "floor": 1,
            "room_type": "double",
            "capacity": 2,
            "monthly_rent": "4500.00",
        },
        headers=admin_headers,
    )
    assert resp_dup.status_code == 409
    assert resp_dup.json()["error"]["code"] == "ROOM_NUMBER_EXISTS"

    # List rooms in block -> 200
    resp_list = await client.get(
        f"/api/v1/blocks/{block_id}/rooms?page=1&size=10",
        headers=admin_headers,
    )
    assert resp_list.status_code == 200
    page_data = resp_list.json()
    assert page_data["total"] == 1
    assert page_data["items"][0]["id"] == room_id

    # Get room details -> 200
    resp_get = await client.get(f"/api/v1/rooms/{room_id}", headers=admin_headers)
    assert resp_get.status_code == 200
    assert resp_get.json()["id"] == room_id
    assert len(resp_get.json()["beds"]) == 2

    # Get beds -> 200
    resp_beds = await client.get(f"/api/v1/rooms/{room_id}/beds", headers=admin_headers)
    assert resp_beds.status_code == 200
    assert len(resp_beds.json()) == 2

    # Update rent
    resp_patch = await client.patch(
        f"/api/v1/rooms/{room_id}",
        json={"monthly_rent": "4800.00"},
        headers=admin_headers,
    )
    assert resp_patch.status_code == 200
    assert resp_patch.json()["monthly_rent"] == "4800.00"

    # Toggle maintenance
    resp_maint = await client.post(f"/api/v1/rooms/{room_id}/maintenance", headers=admin_headers)
    assert resp_maint.status_code == 200
    assert resp_maint.json()["status"] == "maintenance"

    # Toggle available
    resp_avail = await client.post(f"/api/v1/rooms/{room_id}/available", headers=admin_headers)
    assert resp_avail.status_code == 200
    assert resp_avail.json()["status"] == "available"

    # Delete room -> 204
    resp_delete = await client.delete(f"/api/v1/rooms/{room_id}", headers=admin_headers)
    assert resp_delete.status_code == 204

    # Subsequent GET -> 404
    resp_not_found = await client.get(f"/api/v1/rooms/{room_id}", headers=admin_headers)
    assert resp_not_found.status_code == 404


@pytest.mark.asyncio
async def test_capacity_increase_and_decrease_rules(
    client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Verify capacity increase adds beds and decrease with occupied bed is blocked."""
    # Setup hostel and block
    h_resp = await client.post(
        "/api/v1/hostels",
        json={"name": "Capacity Test Hostel", "code": "CAP-01", "gender_type": "mixed"},
        headers=admin_headers,
    )
    b_resp = await client.post(
        f"/api/v1/hostels/{h_resp.json()['id']}/blocks",
        json={"name": "Block Cap", "floor_count": 2},
        headers=admin_headers,
    )
    block_id = b_resp.json()["id"]

    # Create double room (beds A, B)
    r_resp = await client.post(
        f"/api/v1/blocks/{block_id}/rooms",
        json={
            "number": "201",
            "floor": 2,
            "room_type": "double",
            "capacity": 2,
            "monthly_rent": "3000.00",
        },
        headers=admin_headers,
    )
    room_id = r_resp.json()["id"]
    assert len(r_resp.json()["beds"]) == 2

    # Increase capacity to 4 (room_type=dorm) -> beds C and D added
    inc_resp = await client.patch(
        f"/api/v1/rooms/{room_id}",
        json={"room_type": "dorm", "capacity": 4},
        headers=admin_headers,
    )
    assert inc_resp.status_code == 200
    assert inc_resp.json()["capacity"] == 4
    labels = [b["label"] for b in inc_resp.json()["beds"]]
    assert labels == ["A", "B", "C", "D"]

    # Decrease capacity to 3 (room_type=triple) when unoccupied -> bed D removed
    dec_resp = await client.patch(
        f"/api/v1/rooms/{room_id}",
        json={"room_type": "triple", "capacity": 3},
        headers=admin_headers,
    )
    assert dec_resp.status_code == 200
    assert dec_resp.json()["capacity"] == 3
    assert [b["label"] for b in dec_resp.json()["beds"]] == ["A", "B", "C"]

    # Simulate bed C occupied in database
    beds_res = await db_session.execute(select(Bed).where(Bed.room_id == UUID(room_id)))
    beds = list(beds_res.scalars().all())
    bed_c = next(b for b in beds if b.label == "C")
    bed_c.is_occupied = True
    await db_session.commit()

    # Attempt to reduce capacity to 2 (which would remove occupied bed C) -> 400 BEDS_OCCUPIED
    blocked_resp = await client.patch(
        f"/api/v1/rooms/{room_id}",
        json={"room_type": "double", "capacity": 2},
        headers=admin_headers,
    )
    assert blocked_resp.status_code == 400
    assert blocked_resp.json()["error"]["code"] == "BEDS_OCCUPIED"


@pytest.mark.asyncio
async def test_warden_scoping_on_rooms(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_headers: dict[str, str],
    warden_user: User,
) -> None:
    """Verify assigned warden can access hostel rooms; unassigned gets 403."""
    # Create two hostels
    h1 = (
        await client.post(
            "/api/v1/hostels",
            json={"name": "Hostel One", "code": "H1-SCOPE", "gender_type": "mixed"},
            headers=admin_headers,
        )
    ).json()["id"]

    h2 = (
        await client.post(
            "/api/v1/hostels",
            json={"name": "Hostel Two", "code": "H2-SCOPE", "gender_type": "mixed"},
            headers=admin_headers,
        )
    ).json()["id"]

    # Create blocks in both
    b1 = (
        await client.post(
            f"/api/v1/hostels/{h1}/blocks",
            json={"name": "Block 1", "floor_count": 1},
            headers=admin_headers,
        )
    ).json()["id"]

    b2 = (
        await client.post(
            f"/api/v1/hostels/{h2}/blocks",
            json={"name": "Block 2", "floor_count": 1},
            headers=admin_headers,
        )
    ).json()["id"]

    # Assign warden to hostel 1
    await client.post(
        f"/api/v1/hostels/{h1}/wardens",
        json={"user_id": str(warden_user.id)},
        headers=admin_headers,
    )

    # Assigned warden creates room in block 1 -> 201
    w_create = await client.post(
        f"/api/v1/blocks/{b1}/rooms",
        json={
            "number": "101",
            "floor": 1,
            "room_type": "single",
            "capacity": 1,
            "monthly_rent": "3000.00",
        },
        headers=warden_headers,
    )
    assert w_create.status_code == 201
    room1_id = w_create.json()["id"]

    # Assigned warden can read room1 -> 200
    assert (
        await client.get(f"/api/v1/rooms/{room1_id}", headers=warden_headers)
    ).status_code == 200

    # Admin creates room in block 2 (hostel 2)
    a_create = await client.post(
        f"/api/v1/blocks/{b2}/rooms",
        json={
            "number": "201",
            "floor": 1,
            "room_type": "single",
            "capacity": 1,
            "monthly_rent": "3000.00",
        },
        headers=admin_headers,
    )
    room2_id = a_create.json()["id"]

    # Warden attempts to read room2 in unassigned hostel 2 -> 403
    resp_unassigned = await client.get(f"/api/v1/rooms/{room2_id}", headers=warden_headers)
    assert resp_unassigned.status_code == 403
    assert resp_unassigned.json()["error"]["code"] == "FORBIDDEN"

    # Warden attempts to create room in unassigned block 2 -> 403
    resp_create_unassigned = await client.post(
        f"/api/v1/blocks/{b2}/rooms",
        json={
            "number": "202",
            "floor": 1,
            "room_type": "single",
            "capacity": 1,
            "monthly_rent": "3000.00",
        },
        headers=warden_headers,
    )
    assert resp_create_unassigned.status_code == 403


@pytest.mark.asyncio
async def test_search_available_rooms(
    client: AsyncClient,
    admin_headers: dict[str, str],
    student_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Verify available rooms search filters, maintenance exclusion, and student access."""
    # Create hostel and block
    h_resp = await client.post(
        "/api/v1/hostels",
        json={"name": "Search Test Hostel", "code": "STH-01", "gender_type": "mixed"},
        headers=admin_headers,
    )
    hostel_id = h_resp.json()["id"]

    b_resp = await client.post(
        f"/api/v1/hostels/{hostel_id}/blocks",
        json={"name": "Block Search", "floor_count": 3},
        headers=admin_headers,
    )
    block_id = b_resp.json()["id"]

    # Room 1: available, single, floor 1, rent 5000
    r1 = (
        await client.post(
            f"/api/v1/blocks/{block_id}/rooms",
            json={
                "number": "101",
                "floor": 1,
                "room_type": "single",
                "capacity": 1,
                "monthly_rent": "5000.00",
            },
            headers=admin_headers,
        )
    ).json()

    # Room 2: double, floor 2, rent 4000
    r2 = (
        await client.post(
            f"/api/v1/blocks/{block_id}/rooms",
            json={
                "number": "201",
                "floor": 2,
                "room_type": "double",
                "capacity": 2,
                "monthly_rent": "4000.00",
            },
            headers=admin_headers,
        )
    ).json()

    # Room 3: triple, floor 1, rent 3500 -> set to maintenance
    r3 = (
        await client.post(
            f"/api/v1/blocks/{block_id}/rooms",
            json={
                "number": "102",
                "floor": 1,
                "room_type": "triple",
                "capacity": 3,
                "monthly_rent": "3500.00",
            },
            headers=admin_headers,
        )
    ).json()
    await client.post(f"/api/v1/rooms/{r3['id']}/maintenance", headers=admin_headers)

    # Student can search available rooms -> 200
    s_search = await client.get("/api/v1/rooms/available", headers=student_headers)
    assert s_search.status_code == 200
    items = s_search.json()["items"]
    # Maintenance room r3 is excluded
    item_ids = [item["id"] for item in items]
    assert r1["id"] in item_ids
    assert r2["id"] in item_ids
    assert r3["id"] not in item_ids

    # Filter by hostel_id
    res_hostel = await client.get(
        f"/api/v1/rooms/available?hostel_id={hostel_id}",
        headers=student_headers,
    )
    assert len(res_hostel.json()["items"]) == 2

    # Filter by room_type
    res_type = await client.get(
        "/api/v1/rooms/available?room_type=single",
        headers=student_headers,
    )
    single_ids = [item["id"] for item in res_type.json()["items"]]
    assert r1["id"] in single_ids
    assert r2["id"] not in single_ids

    # Filter by floor
    res_floor = await client.get("/api/v1/rooms/available?floor=2", headers=student_headers)
    floor2_ids = [item["id"] for item in res_floor.json()["items"]]
    assert r2["id"] in floor2_ids
    assert r1["id"] not in floor2_ids

    # Filter by max_rent
    res_rent = await client.get("/api/v1/rooms/available?max_rent=4500", headers=student_headers)
    rent_ids = [item["id"] for item in res_rent.json()["items"]]
    assert r2["id"] in rent_ids
    assert r1["id"] not in rent_ids

    # Combined filters
    res_combined = await client.get(
        f"/api/v1/rooms/available?hostel_id={hostel_id}&room_type=double&floor=2&max_rent=4000",
        headers=student_headers,
    )
    assert len(res_combined.json()["items"]) == 1
    assert res_combined.json()["items"][0]["id"] == r2["id"]
