"""Integration tests for room bed allocations, lifecycle, business rules, and concurrency."""

import asyncio
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.exceptions import BusinessRuleError, ConflictError
from app.core.security import hash_password
from app.models.allocation import Allocation, AllocationStatus
from app.models.hostel import Block, GenderType, Hostel
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.schemas.allocation import AllocationCreate
from app.services.allocation_service import AllocationService


async def create_hostel_via_api(
    client: AsyncClient,
    admin_headers: dict[str, str],
    name: str = "Test Hostel",
    code: str = "TH-01",
    gender_type: str = "mixed",
) -> str:
    """Helper to create a hostel via API."""
    resp = await client.post(
        "/api/v1/hostels",
        json={"name": name, "code": code, "gender_type": gender_type, "address": "Campus"},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def create_block_via_api(
    client: AsyncClient,
    admin_headers: dict[str, str],
    hostel_id: str,
    name: str = "Block A",
) -> str:
    """Helper to create a block via API."""
    resp = await client.post(
        f"/api/v1/hostels/{hostel_id}/blocks",
        json={"name": name, "floor_count": 2},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def create_room_via_api(
    client: AsyncClient,
    admin_headers: dict[str, str],
    block_id: str,
    number: str = "101",
    capacity: int = 2,
    room_type: str = "double",
    monthly_rent: str = "4000.00",
) -> dict[str, str]:
    """Helper to create a room with beds via API."""
    resp = await client.post(
        f"/api/v1/blocks/{block_id}/rooms",
        json={
            "number": number,
            "floor": 1,
            "room_type": room_type,
            "capacity": capacity,
            "monthly_rent": monthly_rent,
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def create_student_via_api(
    client: AsyncClient,
    admin_headers: dict[str, str],
    email: str = "student1@test.com",
    student_no: str = "STU-001",
    gender: str = "male",
    password: str = "StudentSecret123",  # noqa: S107
) -> dict[str, str]:
    """Helper to create a student profile via API."""
    resp = await client.post(
        "/api/v1/students",
        json={
            "email": email,
            "full_name": f"Student {student_no}",
            "student_no": student_no,
            "gender": gender,
            "department": "Engineering",
            "year": 1,
            "guardian_name": "Parent",
            "guardian_phone": "+1234567890",
            "emergency_contact": "+1987654321",
            "password": password,
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_allocate_happy_path_by_bed_and_room(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Verify bed allocation by bed_id and room_id with enriched response fields."""
    hostel_id = await create_hostel_via_api(client, admin_headers, code="API-HP-H1")
    block_id = await create_block_via_api(client, admin_headers, hostel_id)
    room = await create_room_via_api(client, admin_headers, block_id, number="101", capacity=2)
    s1 = await create_student_via_api(
        client, admin_headers, email="hp1@test.com", student_no="HP-001"
    )
    s2 = await create_student_via_api(
        client, admin_headers, email="hp2@test.com", student_no="HP-002"
    )

    bed_id_1 = room["beds"][0]["id"]
    bed_id_2 = room["beds"][1]["id"]

    # 1. Allocate by bed_id
    resp1 = await client.post(
        "/api/v1/allocations",
        json={
            "student_id": s1["id"],
            "bed_id": bed_id_1,
            "start_date": str(date.today()),
        },
        headers=admin_headers,
    )
    assert resp1.status_code == 201, resp1.text
    data1 = resp1.json()
    assert data1["student_id"] == s1["id"]
    assert data1["bed_id"] == bed_id_1
    assert data1["status"] == "active"
    assert data1["student_no"] == "HP-001"
    assert data1["bed_label"] == "A"
    assert data1["room_number"] == "101"
    assert data1["hostel_id"] == hostel_id

    # 2. Allocate by room_id (picks remaining free bed B)
    resp2 = await client.post(
        "/api/v1/allocations",
        json={
            "student_id": s2["id"],
            "room_id": room["id"],
            "start_date": str(date.today()),
        },
        headers=admin_headers,
    )
    assert resp2.status_code == 201, resp2.text
    data2 = resp2.json()
    assert data2["student_id"] == s2["id"]
    assert data2["bed_id"] == bed_id_2
    assert data2["status"] == "active"
    assert data2["bed_label"] == "B"


@pytest.mark.asyncio
async def test_allocate_rule1_single_active_allocation_per_student(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Core rule 1: Single active allocation per student -> STUDENT_ALREADY_ALLOCATED (400)."""
    hostel_id = await create_hostel_via_api(client, admin_headers, code="API-R1-H1")
    block_id = await create_block_via_api(client, admin_headers, hostel_id)
    room = await create_room_via_api(client, admin_headers, block_id, number="101", capacity=2)
    student = await create_student_via_api(
        client, admin_headers, email="r1_dup@test.com", student_no="R1-001"
    )

    # First allocation succeeds
    resp1 = await client.post(
        "/api/v1/allocations",
        json={"student_id": student["id"], "bed_id": room["beds"][0]["id"]},
        headers=admin_headers,
    )
    assert resp1.status_code == 201

    # Second allocation for same student fails
    resp2 = await client.post(
        "/api/v1/allocations",
        json={"student_id": student["id"], "bed_id": room["beds"][1]["id"]},
        headers=admin_headers,
    )
    assert resp2.status_code == 400
    err = resp2.json()["error"]
    assert err["code"] == "STUDENT_ALREADY_ALLOCATED"


@pytest.mark.asyncio
async def test_allocate_rule2_single_active_allocation_per_bed(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Core rule 2: Single active allocation per bed -> BED_ALREADY_OCCUPIED (400)."""
    hostel_id = await create_hostel_via_api(client, admin_headers, code="API-R2-H1")
    block_id = await create_block_via_api(client, admin_headers, hostel_id)
    room = await create_room_via_api(client, admin_headers, block_id, number="101", capacity=2)
    s1 = await create_student_via_api(
        client, admin_headers, email="r2_s1@test.com", student_no="R2-001"
    )
    s2 = await create_student_via_api(
        client, admin_headers, email="r2_s2@test.com", student_no="R2-002"
    )

    bed_id = room["beds"][0]["id"]

    # Student 1 takes bed
    resp1 = await client.post(
        "/api/v1/allocations",
        json={"student_id": s1["id"], "bed_id": bed_id},
        headers=admin_headers,
    )
    assert resp1.status_code == 201

    # Student 2 tries to take the same bed
    resp2 = await client.post(
        "/api/v1/allocations",
        json={"student_id": s2["id"], "bed_id": bed_id},
        headers=admin_headers,
    )
    assert resp2.status_code == 400
    err = resp2.json()["error"]
    assert err["code"] == "BED_ALREADY_OCCUPIED"


@pytest.mark.asyncio
async def test_allocate_rule3_room_status_transitions(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Core rule 3: Room status auto-updates ('full' on all occupied, 'available' when vacated)."""
    hostel_id = await create_hostel_via_api(client, admin_headers, code="API-R3-H1")
    block_id = await create_block_via_api(client, admin_headers, hostel_id)
    room = await create_room_via_api(client, admin_headers, block_id, number="101", capacity=2)
    s1 = await create_student_via_api(
        client, admin_headers, email="r3_s1@test.com", student_no="R3-001"
    )
    s2 = await create_student_via_api(
        client, admin_headers, email="r3_s2@test.com", student_no="R3-002"
    )

    room_url = f"/api/v1/rooms/{room['id']}"

    # Room is initially available
    r_init = (await client.get(room_url, headers=admin_headers)).json()
    assert r_init["status"] == "available"

    # Allocate bed 1 -> 1/2 occupied -> still available
    alloc1_resp = await client.post(
        "/api/v1/allocations",
        json={"student_id": s1["id"], "bed_id": room["beds"][0]["id"]},
        headers=admin_headers,
    )
    assert alloc1_resp.status_code == 201
    alloc1_id = alloc1_resp.json()["id"]

    r_mid = (await client.get(room_url, headers=admin_headers)).json()
    assert r_mid["status"] == "available"

    # Allocate bed 2 -> 2/2 occupied -> transitions to full
    alloc2_resp = await client.post(
        "/api/v1/allocations",
        json={"student_id": s2["id"], "bed_id": room["beds"][1]["id"]},
        headers=admin_headers,
    )
    assert alloc2_resp.status_code == 201

    r_full = (await client.get(room_url, headers=admin_headers)).json()
    assert r_full["status"] == "full"

    # Vacate bed 1 -> transitions back to available
    vacate_resp = await client.post(
        f"/api/v1/allocations/{alloc1_id}/vacate",
        json={"reason": "Left hostel"},
        headers=admin_headers,
    )
    assert vacate_resp.status_code == 200

    r_avail = (await client.get(room_url, headers=admin_headers)).json()
    assert r_avail["status"] == "available"


@pytest.mark.asyncio
async def test_allocate_rule4_gender_match(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Core rule 4: Gender match rule (mismatch -> GENDER_MISMATCH, 400; mixed allows both)."""
    # 1. Female hostel
    female_h = await create_hostel_via_api(
        client, admin_headers, code="API-G-FEM", gender_type="female"
    )
    b_fem = await create_block_via_api(client, admin_headers, female_h)
    r_fem = await create_room_via_api(
        client, admin_headers, b_fem, number="101", capacity=1, room_type="single"
    )

    male_s = await create_student_via_api(
        client, admin_headers, email="male_g@test.com", student_no="G-MALE", gender="male"
    )

    # Male student into female hostel -> 400 GENDER_MISMATCH
    resp_fem_mismatch = await client.post(
        "/api/v1/allocations",
        json={"student_id": male_s["id"], "bed_id": r_fem["beds"][0]["id"]},
        headers=admin_headers,
    )
    assert resp_fem_mismatch.status_code == 400
    assert resp_fem_mismatch.json()["error"]["code"] == "GENDER_MISMATCH"

    # 2. Male hostel
    male_h = await create_hostel_via_api(
        client, admin_headers, code="API-G-MALE", gender_type="male"
    )
    b_male = await create_block_via_api(client, admin_headers, male_h)
    r_male = await create_room_via_api(
        client, admin_headers, b_male, number="101", capacity=1, room_type="single"
    )

    female_s = await create_student_via_api(
        client, admin_headers, email="female_g@test.com", student_no="G-FEM", gender="female"
    )

    # Female student into male hostel -> 400 GENDER_MISMATCH
    resp_male_mismatch = await client.post(
        "/api/v1/allocations",
        json={"student_id": female_s["id"], "bed_id": r_male["beds"][0]["id"]},
        headers=admin_headers,
    )
    assert resp_male_mismatch.status_code == 400
    assert resp_male_mismatch.json()["error"]["code"] == "GENDER_MISMATCH"

    # 3. Mixed hostel allows both
    mixed_h = await create_hostel_via_api(
        client, admin_headers, code="API-G-MIXED", gender_type="mixed"
    )
    b_mixed = await create_block_via_api(client, admin_headers, mixed_h)
    r_mixed = await create_room_via_api(
        client, admin_headers, b_mixed, number="101", capacity=2, room_type="double"
    )

    resp_m = await client.post(
        "/api/v1/allocations",
        json={"student_id": male_s["id"], "bed_id": r_mixed["beds"][0]["id"]},
        headers=admin_headers,
    )
    assert resp_m.status_code == 201

    resp_f = await client.post(
        "/api/v1/allocations",
        json={"student_id": female_s["id"], "bed_id": r_mixed["beds"][1]["id"]},
        headers=admin_headers,
    )
    assert resp_f.status_code == 201


@pytest.mark.asyncio
async def test_allocate_rule5_room_under_maintenance(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Core rule 5: Room in maintenance cannot receive allocation -> ROOM_UNDER_MAINTENANCE."""
    hostel_id = await create_hostel_via_api(client, admin_headers, code="API-MAINT-H1")
    block_id = await create_block_via_api(client, admin_headers, hostel_id)
    room = await create_room_via_api(
        client, admin_headers, block_id, number="101", capacity=1, room_type="single"
    )
    student = await create_student_via_api(
        client, admin_headers, email="maint_s@test.com", student_no="M-001"
    )

    # Set room to maintenance
    maint_resp = await client.post(f"/api/v1/rooms/{room['id']}/maintenance", headers=admin_headers)
    assert maint_resp.status_code == 200

    # Allocate attempt must fail
    alloc_resp = await client.post(
        "/api/v1/allocations",
        json={"student_id": student["id"], "bed_id": room["beds"][0]["id"]},
        headers=admin_headers,
    )
    assert alloc_resp.status_code == 400
    assert alloc_resp.json()["error"]["code"] == "ROOM_UNDER_MAINTENANCE"


@pytest.mark.asyncio
async def test_allocate_rule7_warden_scoping_and_roles(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_headers: dict[str, str],
    warden_user: User,
    student_headers: dict[str, str],
) -> None:
    """Core rule 7: Wardens scoped to assigned hostels: cannot allocate in other hostels -> 403."""
    # Hostel 1: assigned to warden
    h1_id = await create_hostel_via_api(client, admin_headers, code="API-W-H1")
    b1_id = await create_block_via_api(client, admin_headers, h1_id)
    r1 = await create_room_via_api(
        client, admin_headers, b1_id, number="101", capacity=1, room_type="single"
    )

    # Assign warden to Hostel 1
    assign_resp = await client.post(
        f"/api/v1/hostels/{h1_id}/wardens",
        json={"user_id": str(warden_user.id)},
        headers=admin_headers,
    )
    assert assign_resp.status_code == 201

    # Hostel 2: unassigned
    h2_id = await create_hostel_via_api(client, admin_headers, code="API-W-H2")
    b2_id = await create_block_via_api(client, admin_headers, h2_id)
    r2 = await create_room_via_api(
        client, admin_headers, b2_id, number="101", capacity=1, room_type="single"
    )

    s1 = await create_student_via_api(
        client, admin_headers, email="w_s1@test.com", student_no="WS-001"
    )
    s2 = await create_student_via_api(
        client, admin_headers, email="w_s2@test.com", student_no="WS-002"
    )

    # 1. Warden succeeds in assigned hostel H1
    resp_w_ok = await client.post(
        "/api/v1/allocations",
        json={"student_id": s1["id"], "bed_id": r1["beds"][0]["id"]},
        headers=warden_headers,
    )
    assert resp_w_ok.status_code == 201

    # 2. Warden fails in unassigned hostel H2 -> 403
    resp_w_forbidden = await client.post(
        "/api/v1/allocations",
        json={"student_id": s2["id"], "bed_id": r2["beds"][0]["id"]},
        headers=warden_headers,
    )
    assert resp_w_forbidden.status_code == 403

    # 3. Student role cannot allocate beds -> 403
    resp_student = await client.post(
        "/api/v1/allocations",
        json={"student_id": s2["id"], "bed_id": r2["beds"][0]["id"]},
        headers=student_headers,
    )
    assert resp_student.status_code == 403

    # 4. Unauthenticated -> 401
    resp_noauth = await client.post(
        "/api/v1/allocations",
        json={"student_id": s2["id"], "bed_id": r2["beds"][0]["id"]},
    )
    assert resp_noauth.status_code == 401


@pytest.mark.asyncio
async def test_allocate_by_room_picks_free_bed_and_room_full(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Allocate by room: picks free bed; full room -> ROOM_FULL (400)."""
    hostel_id = await create_hostel_via_api(client, admin_headers, code="API-RFULL-H1")
    block_id = await create_block_via_api(client, admin_headers, hostel_id)
    room = await create_room_via_api(
        client, admin_headers, block_id, number="101", capacity=1, room_type="single"
    )
    s1 = await create_student_via_api(
        client, admin_headers, email="rf1@test.com", student_no="RF-001"
    )
    s2 = await create_student_via_api(
        client, admin_headers, email="rf2@test.com", student_no="RF-002"
    )

    # Pick free bed by room_id
    resp1 = await client.post(
        "/api/v1/allocations",
        json={"student_id": s1["id"], "room_id": room["id"]},
        headers=admin_headers,
    )
    assert resp1.status_code == 201

    # Room is full now -> ROOM_FULL (400)
    resp2 = await client.post(
        "/api/v1/allocations",
        json={"student_id": s2["id"], "room_id": room["id"]},
        headers=admin_headers,
    )
    assert resp2.status_code == 400
    assert resp2.json()["error"]["code"] == "ROOM_FULL"


@pytest.mark.asyncio
async def test_vacate_frees_bed_and_transitions_room_status(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Vacate frees bed and room status transitions full -> available."""
    hostel_id = await create_hostel_via_api(client, admin_headers, code="API-VAC-H1")
    block_id = await create_block_via_api(client, admin_headers, hostel_id)
    room = await create_room_via_api(
        client, admin_headers, block_id, number="101", capacity=1, room_type="single"
    )
    student = await create_student_via_api(
        client, admin_headers, email="vac1@test.com", student_no="VAC-001"
    )

    # Allocate single bed -> room becomes full
    alloc_resp = await client.post(
        "/api/v1/allocations",
        json={"student_id": student["id"], "bed_id": room["beds"][0]["id"]},
        headers=admin_headers,
    )
    alloc_id = alloc_resp.json()["id"]

    r_full = (await client.get(f"/api/v1/rooms/{room['id']}", headers=admin_headers)).json()
    assert r_full["status"] == "full"

    # Vacate
    end_date = str(date.today())
    vac_resp = await client.post(
        f"/api/v1/allocations/{alloc_id}/vacate",
        json={"end_date": end_date, "reason": "Completed term"},
        headers=admin_headers,
    )
    assert vac_resp.status_code == 200
    vac_data = vac_resp.json()
    assert vac_data["status"] == "ended"
    assert vac_data["end_date"] == end_date
    assert vac_data["reason"] == "Completed term"

    # Room transitions back to available
    r_avail = (await client.get(f"/api/v1/rooms/{room['id']}", headers=admin_headers)).json()
    assert r_avail["status"] == "available"


@pytest.mark.asyncio
async def test_transfer_is_atomic_forced_failure_preserves_original(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Transfer is atomic: forced failure on allocate step leaves original allocation intact."""
    hostel_id = await create_hostel_via_api(client, admin_headers, code="API-XFER-ATOMIC")
    block_id = await create_block_via_api(client, admin_headers, hostel_id)
    r1 = await create_room_via_api(
        client, admin_headers, block_id, number="101", capacity=1, room_type="single"
    )
    r2_maint = await create_room_via_api(
        client, admin_headers, block_id, number="102", capacity=1, room_type="single"
    )
    # Put r2 into maintenance
    await client.post(f"/api/v1/rooms/{r2_maint['id']}/maintenance", headers=admin_headers)

    student = await create_student_via_api(
        client, admin_headers, email="xfer_at@test.com", student_no="XFAT-001"
    )

    alloc_resp = await client.post(
        "/api/v1/allocations",
        json={"student_id": student["id"], "bed_id": r1["beds"][0]["id"]},
        headers=admin_headers,
    )
    alloc_id = alloc_resp.json()["id"]

    # Transfer into maintenance room must fail with 400 ROOM_UNDER_MAINTENANCE
    xfer_resp = await client.post(
        f"/api/v1/allocations/{alloc_id}/transfer",
        json={"new_room_id": r2_maint["id"]},
        headers=admin_headers,
    )
    assert xfer_resp.status_code == 400
    assert xfer_resp.json()["error"]["code"] == "ROOM_UNDER_MAINTENANCE"

    # Original allocation must remain ACTIVE
    orig_alloc = (await client.get(f"/api/v1/allocations/{alloc_id}", headers=admin_headers)).json()
    assert orig_alloc["status"] == "active"
    assert orig_alloc["end_date"] is None

    # Original room must still be occupied
    r1_check = (await client.get(f"/api/v1/rooms/{r1['id']}", headers=admin_headers)).json()
    assert r1_check["status"] == "full"


@pytest.mark.asyncio
async def test_transfer_same_bed_fails(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Transfer to same bed returns 400 CANNOT_TRANSFER_TO_SAME_BED."""
    hostel_id = await create_hostel_via_api(client, admin_headers, code="API-XFER-SAME")
    block_id = await create_block_via_api(client, admin_headers, hostel_id)
    r1 = await create_room_via_api(
        client, admin_headers, block_id, number="101", capacity=1, room_type="single"
    )
    student = await create_student_via_api(
        client, admin_headers, email="xfer_same@test.com", student_no="XFSAME-001"
    )

    alloc_resp = await client.post(
        "/api/v1/allocations",
        json={"student_id": student["id"], "bed_id": r1["beds"][0]["id"]},
        headers=admin_headers,
    )
    alloc_id = alloc_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/allocations/{alloc_id}/transfer",
        json={"new_bed_id": r1["beds"][0]["id"]},
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "CANNOT_TRANSFER_TO_SAME_BED"


@pytest.mark.asyncio
async def test_cancel_future_and_past_rules(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Cancel: only allowed if start_date in future; past/today raises error (400)."""
    hostel_id = await create_hostel_via_api(client, admin_headers, code="API-CANC-H1")
    block_id = await create_block_via_api(client, admin_headers, hostel_id)
    r1 = await create_room_via_api(
        client, admin_headers, block_id, number="101", capacity=1, room_type="single"
    )
    r2 = await create_room_via_api(
        client, admin_headers, block_id, number="102", capacity=1, room_type="single"
    )
    s1 = await create_student_via_api(
        client, admin_headers, email="canc1@test.com", student_no="CANC-001"
    )
    s2 = await create_student_via_api(
        client, admin_headers, email="canc2@test.com", student_no="CANC-002"
    )

    # 1. Allocation starting today -> cancel fails (400)
    alloc_today = (
        await client.post(
            "/api/v1/allocations",
            json={
                "student_id": s1["id"],
                "bed_id": r1["beds"][0]["id"],
                "start_date": str(date.today()),
            },
            headers=admin_headers,
        )
    ).json()

    cancel_today = await client.post(
        f"/api/v1/allocations/{alloc_today['id']}/cancel",
        headers=admin_headers,
    )
    assert cancel_today.status_code == 400
    assert cancel_today.json()["error"]["code"] == "CANNOT_CANCEL_ACTIVE_ALLOCATION"

    # 2. Allocation starting tomorrow -> cancel succeeds (200)
    tomorrow = str(date.today() + timedelta(days=1))
    alloc_future = (
        await client.post(
            "/api/v1/allocations",
            json={"student_id": s2["id"], "bed_id": r2["beds"][0]["id"], "start_date": tomorrow},
            headers=admin_headers,
        )
    ).json()

    cancel_future = await client.post(
        f"/api/v1/allocations/{alloc_future['id']}/cancel",
        headers=admin_headers,
    )
    assert cancel_future.status_code == 200
    assert cancel_future.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_hostel_and_room_delete_guards(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Hostel/room delete blocked with active allocations -> 409 ConflictError."""
    hostel_id = await create_hostel_via_api(client, admin_headers, code="API-DELG-H1")
    block_id = await create_block_via_api(client, admin_headers, hostel_id)
    room = await create_room_via_api(
        client, admin_headers, block_id, number="101", capacity=1, room_type="single"
    )
    student = await create_student_via_api(
        client, admin_headers, email="delg@test.com", student_no="DELG-001"
    )

    alloc = (
        await client.post(
            "/api/v1/allocations",
            json={"student_id": student["id"], "bed_id": room["beds"][0]["id"]},
            headers=admin_headers,
        )
    ).json()

    # 1. Delete room blocked -> 409
    del_room = await client.delete(f"/api/v1/rooms/{room['id']}", headers=admin_headers)
    assert del_room.status_code == 409
    assert del_room.json()["error"]["code"] == "ROOM_HAS_ACTIVE_ALLOCATIONS"

    # 2. Delete hostel blocked -> 409
    del_hostel = await client.delete(f"/api/v1/hostels/{hostel_id}", headers=admin_headers)
    assert del_hostel.status_code == 409
    assert del_hostel.json()["error"]["code"] == "HOSTEL_HAS_ACTIVE_ALLOCATIONS"

    # 3. Vacate allocation
    await client.post(f"/api/v1/allocations/{alloc['id']}/vacate", json={}, headers=admin_headers)

    # 4. Now room and hostel delete succeed -> 204
    del_room_ok = await client.delete(f"/api/v1/rooms/{room['id']}", headers=admin_headers)
    assert del_room_ok.status_code == 204

    del_hostel_ok = await client.delete(f"/api/v1/hostels/{hostel_id}", headers=admin_headers)
    assert del_hostel_ok.status_code == 204


@pytest.mark.asyncio
async def test_list_and_detail_allocations_filters_and_scoping(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_headers: dict[str, str],
    warden_user: User,
) -> None:
    """Verify list filtering, pagination, and detail scoping."""
    h1_id = await create_hostel_via_api(client, admin_headers, code="API-LST-H1")
    b1_id = await create_block_via_api(client, admin_headers, h1_id)
    r1 = await create_room_via_api(
        client, admin_headers, b1_id, number="101", capacity=1, room_type="single"
    )

    # Assign warden to H1
    await client.post(
        f"/api/v1/hostels/{h1_id}/wardens",
        json={"user_id": str(warden_user.id)},
        headers=admin_headers,
    )

    h2_id = await create_hostel_via_api(client, admin_headers, code="API-LST-H2")
    b2_id = await create_block_via_api(client, admin_headers, h2_id)
    r2 = await create_room_via_api(
        client, admin_headers, b2_id, number="101", capacity=1, room_type="single"
    )

    s1 = await create_student_via_api(
        client, admin_headers, email="lst1@test.com", student_no="LST-001"
    )
    s2 = await create_student_via_api(
        client, admin_headers, email="lst2@test.com", student_no="LST-002"
    )

    alloc1 = (
        await client.post(
            "/api/v1/allocations",
            json={"student_id": s1["id"], "bed_id": r1["beds"][0]["id"]},
            headers=admin_headers,
        )
    ).json()

    alloc2 = (
        await client.post(
            "/api/v1/allocations",
            json={"student_id": s2["id"], "bed_id": r2["beds"][0]["id"]},
            headers=admin_headers,
        )
    ).json()

    # 1. Admin lists allocations with filters
    list_resp = await client.get(
        f"/api/v1/allocations?hostel_id={h1_id}&status=active",
        headers=admin_headers,
    )
    assert list_resp.status_code == 200
    page_data = list_resp.json()
    assert page_data["total"] >= 1
    assert all(item["hostel_id"] == h1_id for item in page_data["items"])

    # 2. Warden lists allocations (scoped to assigned hostel H1)
    w_list_resp = await client.get("/api/v1/allocations", headers=warden_headers)
    assert w_list_resp.status_code == 200
    w_items = w_list_resp.json()["items"]
    assert any(item["id"] == alloc1["id"] for item in w_items)
    assert all(item["id"] != alloc2["id"] for item in w_items)

    # 3. Warden querying unassigned hostel -> 403
    w_h2_resp = await client.get(
        f"/api/v1/allocations?hostel_id={h2_id}",
        headers=warden_headers,
    )
    assert w_h2_resp.status_code == 403

    # 4. Detail endpoint scoping
    # Warden views H1 alloc -> 200
    assert (
        await client.get(f"/api/v1/allocations/{alloc1['id']}", headers=warden_headers)
    ).status_code == 200
    # Warden views H2 alloc -> 403
    assert (
        await client.get(f"/api/v1/allocations/{alloc2['id']}", headers=warden_headers)
    ).status_code == 403


@pytest.mark.asyncio
async def test_student_self_service_and_room_occupants(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Verify /students/me/allocation, enriched student profile, and /rooms/{id}/occupants."""
    hostel_id = await create_hostel_via_api(client, admin_headers, code="API-OCC-H1")
    block_id = await create_block_via_api(client, admin_headers, hostel_id)
    room = await create_room_via_api(
        client, admin_headers, block_id, number="101", capacity=2, room_type="double"
    )
    student = await create_student_via_api(
        client,
        admin_headers,
        email="stu_self@test.com",
        student_no="SELF-001",
        password="MySecret1234",
    )

    # Student logs in
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "stu_self@test.com", "password": "MySecret1234"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    stu_headers = {"Authorization": f"Bearer {token}"}

    # Before allocation: /students/me/allocation -> 404
    resp_no_alloc = await client.get("/api/v1/students/me/allocation", headers=stu_headers)
    assert resp_no_alloc.status_code == 404

    # Allocate bed to student
    alloc_resp = await client.post(
        "/api/v1/allocations",
        json={"student_id": student["id"], "bed_id": room["beds"][0]["id"]},
        headers=admin_headers,
    )
    alloc_id = alloc_resp.json()["id"]

    # Now /students/me/allocation -> 200
    my_alloc = await client.get("/api/v1/students/me/allocation", headers=stu_headers)
    assert my_alloc.status_code == 200
    assert my_alloc.json()["id"] == alloc_id

    # /students/me includes current_allocation
    me_resp = await client.get("/api/v1/students/me", headers=stu_headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["current_allocation"] is not None
    assert me_resp.json()["current_allocation"]["id"] == alloc_id

    # /rooms/{id}/occupants returns student details
    occ_resp = await client.get(f"/api/v1/rooms/{room['id']}/occupants", headers=admin_headers)
    assert occ_resp.status_code == 200
    occupants = occ_resp.json()
    assert len(occupants) == 1
    assert occupants[0]["student_no"] == "SELF-001"
    assert occupants[0]["bed_label"] == "A"
    assert occupants[0]["allocation_id"] == alloc_id


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_postgres_concurrent_allocations_to_last_bed(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """PostgreSQL concurrency test: two simultaneous allocations to the last bed via asyncio.gather.

    Exactly one must succeed, while the other fails with ConflictError or BusinessRuleError.
    """
    admin_id = uuid4()
    h_code = f"PG-H-{uuid4().hex[:6]}"
    r_number = f"R-{uuid4().hex[:4]}"

    # 1. Setup entities in Postgres
    async with pg_session_factory() as setup_session:
        admin_user = User(
            id=admin_id,
            email=f"pg_adm_{uuid4().hex[:6]}@example.com",
            full_name="Postgres Admin",
            phone="+1000000001",
            hashed_password=hash_password("Pass1234"),
            role=UserRole.ADMIN,
            is_active=True,
        )
        setup_session.add(admin_user)

        hostel = Hostel(
            id=uuid4(),
            name="PG Concurrency Hostel",
            code=h_code,
            gender_type=GenderType.MIXED,
            address="PG Campus",
        )
        setup_session.add(hostel)

        block = Block(
            id=uuid4(),
            hostel_id=hostel.id,
            name="PG Block",
            floor_count=1,
        )
        setup_session.add(block)

        room = Room(
            id=uuid4(),
            block_id=block.id,
            number=r_number,
            floor=1,
            room_type=RoomType.SINGLE,
            capacity=1,
            monthly_rent=Decimal("3500.00"),
            status=RoomStatus.AVAILABLE,
        )
        setup_session.add(room)

        bed = Bed(
            id=uuid4(),
            room_id=room.id,
            label="A",
            is_occupied=False,
        )
        setup_session.add(bed)

        # Student 1
        u1 = User(
            id=uuid4(),
            email=f"pg_s1_{uuid4().hex[:6]}@example.com",
            full_name="Student One",
            phone="+1000000002",
            hashed_password=hash_password("Pass1234"),
            role=UserRole.STUDENT,
            is_active=True,
        )
        setup_session.add(u1)
        p1 = StudentProfile(
            id=uuid4(),
            user_id=u1.id,
            student_no=f"PGS1-{uuid4().hex[:6]}",
            gender=GenderType.MALE,
            department="CSE",
            year=1,
            guardian_name="G1",
            guardian_phone="+1111111111",
            emergency_contact="+1222222222",
        )
        setup_session.add(p1)

        # Student 2
        u2 = User(
            id=uuid4(),
            email=f"pg_s2_{uuid4().hex[:6]}@example.com",
            full_name="Student Two",
            phone="+1000000003",
            hashed_password=hash_password("Pass1234"),
            role=UserRole.STUDENT,
            is_active=True,
        )
        setup_session.add(u2)
        p2 = StudentProfile(
            id=uuid4(),
            user_id=u2.id,
            student_no=f"PGS2-{uuid4().hex[:6]}",
            gender=GenderType.FEMALE,
            department="ECE",
            year=1,
            guardian_name="G2",
            guardian_phone="+1333333333",
            emergency_contact="+1444444444",
        )
        setup_session.add(p2)

        await setup_session.commit()

        bed_id = bed.id
        s1_id = p1.id
        s2_id = p2.id

    # 2. Concurrently attempt to allocate the single bed
    async def try_allocate(student_id: UUID) -> tuple[bool, str | None]:
        async with pg_session_factory() as session:
            service = AllocationService(session)
            u = await session.get(User, admin_id)
            if u is None:
                return (False, "ADMIN_NOT_FOUND")
            try:
                await service.allocate(
                    AllocationCreate(student_id=student_id, bed_id=bed_id),
                    current_user=u,
                )
                await session.commit()
                return (True, None)
            except (ConflictError, BusinessRuleError) as exc:
                await session.rollback()
                return (False, exc.code)
            except Exception as e:
                await session.rollback()
                return (False, type(e).__name__)

    results = await asyncio.gather(
        try_allocate(s1_id),
        try_allocate(s2_id),
    )

    successes = [r for r in results if r[0] is True]
    failures = [r for r in results if r[0] is False]

    # Exactly one must succeed and one must fail
    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}: {results}"
    assert len(failures) == 1, f"Expected exactly 1 failure, got {len(failures)}: {results}"
    assert failures[0][1] in ("BED_ALREADY_OCCUPIED", "ALLOCATION_CONFLICT")

    # 3. Verify PostgreSQL state
    async with pg_session_factory() as verify_session:
        saved_bed = await verify_session.get(Bed, bed_id)
        assert saved_bed is not None
        assert saved_bed.is_occupied is True

        active_allocs_res = await verify_session.execute(
            select(Allocation).where(
                Allocation.bed_id == bed_id,
                Allocation.status == AllocationStatus.ACTIVE,
            )
        )
        active_allocs = active_allocs_res.scalars().all()
        assert len(active_allocs) == 1
