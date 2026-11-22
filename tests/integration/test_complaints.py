"""Integration tests for complaint and maintenance REST API endpoints."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.allocation import Allocation, AllocationStatus
from app.models.complaint import Complaint, ComplaintStatus
from app.models.hostel import Block, GenderType, Hostel, WardenAssignment
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole

type SetupResult = tuple[
    Hostel,
    Hostel,
    Room,
    User,
    User,
    User,
    StudentProfile,
    User,
    StudentProfile,
    User,
]


async def _create_test_data(
    session: AsyncSession,
) -> SetupResult:
    """Helper setting up 2 hostels, 1 warden assigned to H1, and 2 students."""
    uid = uuid4().hex[:6]

    # Hostel 1
    h1 = Hostel(name=f"Alpha {uid}", code=f"ALP-{uid}", gender_type=GenderType.MIXED)
    session.add(h1)
    await session.flush()

    b1 = Block(hostel_id=h1.id, name="Block A", floor_count=1)
    session.add(b1)
    await session.flush()

    r1 = Room(
        block_id=b1.id,
        number="101",
        floor=1,
        room_type=RoomType.DOUBLE,
        capacity=2,
        monthly_rent=Decimal("2500.00"),
        status=RoomStatus.AVAILABLE,
    )
    session.add(r1)
    await session.flush()

    bed1 = Bed(room_id=r1.id, label="101-A")
    session.add(bed1)
    await session.flush()

    # Hostel 2
    h2 = Hostel(name=f"Beta {uid}", code=f"BET-{uid}", gender_type=GenderType.MIXED)
    session.add(h2)
    await session.flush()

    b2 = Block(hostel_id=h2.id, name="Block B", floor_count=1)
    session.add(b2)
    await session.flush()

    r2 = Room(
        block_id=b2.id,
        number="201",
        floor=1,
        room_type=RoomType.DOUBLE,
        capacity=2,
        monthly_rent=Decimal("2500.00"),
        status=RoomStatus.AVAILABLE,
    )
    session.add(r2)
    await session.flush()

    bed2 = Bed(room_id=r2.id, label="201-A")
    session.add(bed2)
    await session.flush()

    # Users
    admin = User(
        id=uuid4(),
        email=f"admin_{uid}@example.com",
        full_name="Admin Boss",
        hashed_password=hash_password("Pass123"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    warden = User(
        id=uuid4(),
        email=f"warden_{uid}@example.com",
        full_name="Warden Alpha",
        hashed_password=hash_password("Pass123"),
        role=UserRole.WARDEN,
        is_active=True,
    )
    u1 = User(
        id=uuid4(),
        email=f"stu1_{uid}@example.com",
        full_name="Student Alpha",
        hashed_password=hash_password("Pass123"),
        role=UserRole.STUDENT,
        is_active=True,
    )
    u2 = User(
        id=uuid4(),
        email=f"stu2_{uid}@example.com",
        full_name="Student Beta",
        hashed_password=hash_password("Pass123"),
        role=UserRole.STUDENT,
        is_active=True,
    )
    u_unalloc = User(
        id=uuid4(),
        email=f"noalloc_{uid}@example.com",
        full_name="Student Homeless",
        hashed_password=hash_password("Pass123"),
        role=UserRole.STUDENT,
        is_active=True,
    )
    session.add_all([admin, warden, u1, u2, u_unalloc])
    await session.flush()

    wa = WardenAssignment(user_id=warden.id, hostel_id=h1.id)
    session.add(wa)
    await session.flush()

    p1 = StudentProfile(
        id=uuid4(),
        user_id=u1.id,
        student_no=f"STU-ALP-{uid}",
        gender=GenderType.MALE,
        department="CS",
        year=1,
        guardian_name="Guardian 1",
        guardian_phone="1234567890",
        emergency_contact="0987654321",
    )
    p2 = StudentProfile(
        id=uuid4(),
        user_id=u2.id,
        student_no=f"STU-BET-{uid}",
        gender=GenderType.FEMALE,
        department="ECE",
        year=2,
        guardian_name="Guardian 2",
        guardian_phone="1234567890",
        emergency_contact="0987654321",
    )
    p_unalloc = StudentProfile(
        id=uuid4(),
        user_id=u_unalloc.id,
        student_no=f"STU-NO-{uid}",
        gender=GenderType.MALE,
        department="Civil",
        year=1,
        guardian_name="Guardian 3",
        guardian_phone="1234567890",
        emergency_contact="0987654321",
    )
    session.add_all([p1, p2, p_unalloc])
    await session.flush()

    a1 = Allocation(
        student_id=p1.id,
        bed_id=bed1.id,
        start_date=date(2026, 1, 1),
        status=AllocationStatus.ACTIVE,
    )
    a2 = Allocation(
        student_id=p2.id,
        bed_id=bed2.id,
        start_date=date(2026, 1, 1),
        status=AllocationStatus.ACTIVE,
    )
    session.add_all([a1, a2])
    await session.commit()

    return h1, h2, r1, admin, warden, u1, p1, u2, p2, u_unalloc


def _headers(user: User) -> dict[str, str]:
    """Generate authorization headers for user."""
    role = user.role.value if isinstance(user.role, UserRole) else str(user.role)
    token = create_access_token(user_id=user.id, role=role)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_complaint_creation_and_authorization(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Test POST /api/v1/complaints authorization and active allocation validation."""
    h1, _, r1, _admin, warden, u1, _, _, _, u_unalloc = await _create_test_data(db_session)

    # 1. Unauthenticated gets 401
    resp = await client.post("/api/v1/complaints", json={"title": "test", "description": "desc"})
    assert resp.status_code == 401

    # 2. Non-student gets 403
    resp = await client.post(
        "/api/v1/complaints",
        json={
            "title": "Broken light",
            "description": "Flickering constantly",
            "category": "electrical",
        },
        headers=_headers(warden),
    )
    assert resp.status_code == 403

    # 3. Student without active allocation gets 400 NO_ACTIVE_ALLOCATION
    resp = await client.post(
        "/api/v1/complaints",
        json={
            "title": "Broken desk",
            "description": "Leg cracked",
            "category": "furniture",
        },
        headers=_headers(u_unalloc),
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "NO_ACTIVE_ALLOCATION"

    # 4. Student with active allocation succeeds: 201 Created and room auto-filled
    payload = {
        "title": "Water leakage in washroom",
        "description": "Pipe leaking under sink",
        "category": "plumbing",
        "priority": "high",
    }
    resp = await client.post("/api/v1/complaints", json=payload, headers=_headers(u1))
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == payload["title"]
    assert data["room_id"] == str(r1.id)
    assert data["room_number"] == "101"
    assert data["hostel_name"] == h1.name
    assert data["status"] == "open"
    assert data["priority"] == "high"


@pytest.mark.asyncio
async def test_complaint_listing_and_filtering(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Test GET /api/v1/complaints scoping and query filters."""
    _h1, _h2, _, admin, warden, u1, _, u2, _, _ = await _create_test_data(db_session)

    # u1 files plumbing complaint in H1
    r_c1 = await client.post(
        "/api/v1/complaints",
        json={
            "title": "Water leak H1",
            "description": "Pipe dripping",
            "category": "plumbing",
            "priority": "low",
        },
        headers=_headers(u1),
    )
    assert r_c1.status_code == 201
    c1_id = r_c1.json()["id"]

    # u2 files internet complaint in H2
    r_c2 = await client.post(
        "/api/v1/complaints",
        json={
            "title": "WiFi issue H2",
            "description": "No signal",
            "category": "internet",
            "priority": "urgent",
        },
        headers=_headers(u2),
    )
    assert r_c2.status_code == 201

    # Student 1 lists complaints: only sees own (c1)
    resp = await client.get("/api/v1/complaints", headers=_headers(u1))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == c1_id

    # Warden (assigned only to H1) lists complaints: sees c1, but not c2
    resp = await client.get("/api/v1/complaints", headers=_headers(warden))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == c1_id

    # Warden filtering by priority
    resp = await client.get("/api/v1/complaints?priority=urgent", headers=_headers(warden))
    assert resp.status_code == 200
    assert resp.json()["total"] == 0

    # Admin sees both complaints
    resp = await client.get("/api/v1/complaints", headers=_headers(admin))
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


@pytest.mark.asyncio
async def test_complaint_detail_and_internal_comments(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Test GET /api/v1/complaints/{id} hiding internal comments from student."""
    _, _, _, _admin, warden, u1, _, u2, _, _ = await _create_test_data(db_session)

    # Student 1 files complaint
    r_c = await client.post(
        "/api/v1/complaints",
        json={
            "title": "Door lock jammed",
            "description": "Key gets stuck",
            "category": "other",
        },
        headers=_headers(u1),
    )
    comp_id = r_c.json()["id"]

    # Student posts public comment
    resp = await client.post(
        f"/api/v1/complaints/{comp_id}/comments",
        json={"body": "Please hurry, cannot lock door.", "is_internal": False},
        headers=_headers(u1),
    )
    assert resp.status_code == 201
    assert resp.json()["body"] == "Please hurry, cannot lock door."
    assert resp.json()["is_internal"] is False
    assert resp.json()["author_name"] == u1.full_name

    # Student posting with is_internal=True is forced to False!
    resp = await client.post(
        f"/api/v1/complaints/{comp_id}/comments",
        json={"body": "Sneaky comment", "is_internal": True},
        headers=_headers(u1),
    )
    assert resp.status_code == 201
    assert resp.json()["is_internal"] is False

    # Warden posts internal comment
    resp = await client.post(
        f"/api/v1/complaints/{comp_id}/comments",
        json={"body": "Internal: Locksmith called, ETA 2pm", "is_internal": True},
        headers=_headers(warden),
    )
    assert resp.status_code == 201
    assert resp.json()["is_internal"] is True

    # Foreign student u2 cannot view complaint (403)
    resp = await client.get(f"/api/v1/complaints/{comp_id}", headers=_headers(u2))
    assert resp.status_code == 403

    # Student 1 views detail: internal comment is omitted!
    resp = await client.get(f"/api/v1/complaints/{comp_id}", headers=_headers(u1))
    assert resp.status_code == 200
    comments = resp.json()["comments"]
    assert len(comments) == 2
    assert all(not c["is_internal"] for c in comments)

    # Warden views detail: internal comment is included!
    resp = await client.get(f"/api/v1/complaints/{comp_id}", headers=_headers(warden))
    assert resp.status_code == 200
    comments = resp.json()["comments"]
    assert len(comments) == 3
    assert any(c["is_internal"] for c in comments)


@pytest.mark.asyncio
async def test_complaint_assignment_and_status_transitions(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Test assign, status lifecycle, 7-day reopen window, and room maintenance flag."""
    _, _, r1, admin, warden, u1, _, _, _, _ = await _create_test_data(db_session)

    # Create complaint
    r_c = await client.post(
        "/api/v1/complaints",
        json={
            "title": "Severe ceiling plaster collapse",
            "description": "Plaster falling from ceiling above bed",
            "category": "other",
            "priority": "urgent",
        },
        headers=_headers(u1),
    )
    comp_id = r_c.json()["id"]

    # Student cannot assign staff (403)
    resp = await client.post(
        f"/api/v1/complaints/{comp_id}/assign",
        json={"assigned_to": str(warden.id)},
        headers=_headers(u1),
    )
    assert resp.status_code == 403

    # Warden assigns staff: transitions OPEN -> IN_PROGRESS
    resp = await client.post(
        f"/api/v1/complaints/{comp_id}/assign",
        json={"assigned_to": str(warden.id)},
        headers=_headers(warden),
    )
    assert resp.status_code == 200
    assert resp.json()["assigned_to"] == str(warden.id)
    assert resp.json()["assigned_to_name"] == warden.full_name
    assert resp.json()["status"] == "in_progress"

    # Warden resolves complaint with resolution_notes and sets mark_room_maintenance=True
    resp = await client.post(
        f"/api/v1/complaints/{comp_id}/status",
        json={
            "status": "resolved",
            "resolution_notes": "Plaster cleared, room marked for maintenance repair.",
            "mark_room_maintenance": True,
        },
        headers=_headers(warden),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"
    assert resp.json()["resolved_at"] is not None

    # Verify room status was changed to MAINTENANCE
    room_resp = await client.get(f"/api/v1/rooms/{r1.id}", headers=_headers(admin))
    assert room_resp.status_code == 200
    assert room_resp.json()["status"] == "maintenance"

    # Student reopens complaint within 7 days
    resp = await client.post(
        f"/api/v1/complaints/{comp_id}/status",
        json={
            "status": "open",
            "resolution_notes": "Ceiling is still flaking debris.",
        },
        headers=_headers(u1),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "open"
    assert resp.json()["resolved_at"] is None

    # Simulate resolved_at expired by directly updating DB to 8 days ago
    complaint_obj = await db_session.get(Complaint, UUID(comp_id))
    assert complaint_obj is not None
    complaint_obj.status = ComplaintStatus.RESOLVED
    complaint_obj.resolved_at = datetime.now(UTC) - timedelta(days=8)
    await db_session.commit()

    # Student attempts to reopen expired complaint -> 400 REOPEN_WINDOW_EXPIRED
    resp = await client.post(
        f"/api/v1/complaints/{comp_id}/status",
        json={"status": "open"},
        headers=_headers(u1),
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "REOPEN_WINDOW_EXPIRED"

    # Student closes complaint -> 200 OK
    resp = await client.post(
        f"/api/v1/complaints/{comp_id}/status",
        json={"status": "closed"},
        headers=_headers(u1),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"

    # Closed complaint cannot transition anywhere -> 400 INVALID_STATUS_TRANSITION
    resp = await client.post(
        f"/api/v1/complaints/{comp_id}/status",
        json={"status": "open"},
        headers=_headers(warden),
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
