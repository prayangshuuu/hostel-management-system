"""Integration tests for attendance, leave requests, and visitors REST API."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.models.allocation import Allocation, AllocationStatus
from app.models.hostel import Block, GenderType, Hostel, WardenAssignment
from app.models.operations import AttendanceType, LeaveStatus
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole

type SetupResult = tuple[
    Hostel,
    Hostel,
    User,
    User,
    User,
    StudentProfile,
    Allocation,
    User,
    StudentProfile,
    Allocation,
]


async def _create_full_setup(
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
        full_name="Admin",
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
    session.add_all([admin, warden, u1, u2])
    await session.flush()

    # Warden assigned to H1 only
    session.add(WardenAssignment(user_id=warden.id, hostel_id=h1.id))
    await session.flush()

    # Profiles
    prof1 = StudentProfile(
        id=uuid4(),
        user_id=u1.id,
        student_no=f"STU1-{uid}",
        gender=GenderType.MALE,
        department="Engineering",
        year=1,
        guardian_name="Guardian",
        guardian_phone="+111",
        emergency_contact="+222",
    )
    prof2 = StudentProfile(
        id=uuid4(),
        user_id=u2.id,
        student_no=f"STU2-{uid}",
        gender=GenderType.FEMALE,
        department="Medicine",
        year=2,
        guardian_name="Guardian",
        guardian_phone="+333",
        emergency_contact="+444",
    )
    session.add_all([prof1, prof2])
    await session.flush()

    # Allocations
    alloc1 = Allocation(
        student_id=prof1.id,
        bed_id=bed1.id,
        start_date=date(2026, 11, 1),
        status=AllocationStatus.ACTIVE,
    )
    alloc2 = Allocation(
        student_id=prof2.id,
        bed_id=bed2.id,
        start_date=date(2026, 11, 1),
        status=AllocationStatus.ACTIVE,
    )
    session.add_all([alloc1, alloc2])
    await session.commit()

    return h1, h2, admin, warden, u1, prof1, alloc1, u2, prof2, alloc2


def _headers(user: User) -> dict[str, str]:
    """Generate authorization headers for user."""
    role = user.role.value if isinstance(user.role, UserRole) else str(user.role)
    token = create_access_token(user_id=user.id, role=role)
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# Attendance Integration Tests
# =============================================================================


@pytest.mark.asyncio
async def test_attendance_api_lifecycle(client: AsyncClient, db_session: AsyncSession) -> None:
    """Verify attendance check-in, check-out, present list, and student self-service API."""
    h1, _h2, admin, warden, u1, prof1, _a1, u2, prof2, _a2 = await _create_full_setup(db_session)

    admin_hdr = _headers(admin)
    warden_hdr = _headers(warden)
    student1_hdr = _headers(u1)
    _headers(u2)

    # 1. Student cannot record check-in (403)
    resp = await client.post(
        "/api/v1/attendance/check-in",
        headers=student1_hdr,
        json={"student_id": str(prof1.id)},
    )
    assert resp.status_code == 403

    # 2. Check out before check in returns 409 ALREADY_CHECKED_OUT
    resp = await client.post(
        "/api/v1/attendance/check-out",
        headers=warden_hdr,
        json={"student_id": str(prof1.id)},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "ALREADY_CHECKED_OUT"

    # 3. Warden of H1 cannot check in student in H2 (403)
    resp = await client.post(
        "/api/v1/attendance/check-in",
        headers=warden_hdr,
        json={"student_id": str(prof2.id)},
    )
    assert resp.status_code == 403

    # 4. Valid check-in by warden for student 1
    resp = await client.post(
        "/api/v1/attendance/check-in",
        headers=warden_hdr,
        json={"student_id": str(prof1.id), "remarks": "Returned on time"},
    )
    assert resp.status_code == 201
    in_data = resp.json()
    assert in_data["student_id"] == str(prof1.id)
    assert in_data["type"] == AttendanceType.CHECK_IN.value
    assert in_data["remarks"] == "Returned on time"
    assert in_data["student_name"] == "Student Alpha"
    assert in_data["hostel_name"] == h1.name

    # 5. Double check-in returns 409 ALREADY_CHECKED_IN
    resp = await client.post(
        "/api/v1/attendance/check-in",
        headers=admin_hdr,
        json={"student_id": str(prof1.id)},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "ALREADY_CHECKED_IN"

    # 6. Admin checks in student 2 (in H2)
    resp = await client.post(
        "/api/v1/attendance/check-in",
        headers=admin_hdr,
        json={"student_id": str(prof2.id)},
    )
    assert resp.status_code == 201

    # 7. GET /attendance/present
    # Admin sees both students
    resp = await client.get("/api/v1/attendance/present", headers=admin_hdr)
    assert resp.status_code == 200
    present_list = resp.json()
    assert len(present_list) == 2

    # Warden of H1 sees only student 1
    resp = await client.get("/api/v1/attendance/present", headers=warden_hdr)
    assert resp.status_code == 200
    present_warden = resp.json()
    assert len(present_warden) == 1
    assert present_warden[0]["student_id"] == str(prof1.id)

    # Filter present by hostel H1
    resp = await client.get(f"/api/v1/attendance/present?hostel_id={h1.id}", headers=admin_hdr)
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    # 8. Check-out student 1
    resp = await client.post(
        "/api/v1/attendance/check-out",
        headers=warden_hdr,
        json={"student_id": str(prof1.id), "remarks": "Going to library"},
    )
    assert resp.status_code == 201
    assert resp.json()["type"] == AttendanceType.CHECK_OUT.value

    # Present list for H1 is now empty
    resp = await client.get("/api/v1/attendance/present", headers=warden_hdr)
    assert resp.status_code == 200
    assert len(resp.json()) == 0

    # 9. List attendance logs
    resp = await client.get("/api/v1/attendance", headers=warden_hdr)
    assert resp.status_code == 200
    logs_page = resp.json()
    assert logs_page["total"] == 2  # 1 check-in, 1 check-out for student 1

    # 10. Student 1 self-service attendance
    resp = await client.get("/api/v1/students/me/attendance", headers=student1_hdr)
    assert resp.status_code == 200
    my_logs = resp.json()
    assert my_logs["total"] == 2
    assert my_logs["items"][0]["student_id"] == str(prof1.id)


# =============================================================================
# Leave Request Integration Tests
# =============================================================================


@pytest.mark.asyncio
async def test_leaves_api_lifecycle(client: AsyncClient, db_session: AsyncSession) -> None:
    """Verify leave submission, validation, review, and cancellation endpoints."""
    _h1, _h2, admin, warden, u1, prof1, _a1, u2, _prof2, _a2 = await _create_full_setup(db_session)

    admin_hdr = _headers(admin)
    warden_hdr = _headers(warden)
    student1_hdr = _headers(u1)
    student2_hdr = _headers(u2)

    # 1. Validation error: to_date < from_date (422)
    resp = await client.post(
        "/api/v1/leaves",
        headers=student1_hdr,
        json={
            "from_date": "2026-12-10",
            "to_date": "2026-12-05",
            "reason": "Invalid dates",
        },
    )
    assert resp.status_code == 422

    # 2. Student self-submits valid leave request
    resp = await client.post(
        "/api/v1/leaves",
        headers=student1_hdr,
        json={
            "from_date": "2026-12-10",
            "to_date": "2026-12-15",
            "reason": "Family function",
        },
    )
    assert resp.status_code == 201
    leave1 = resp.json()
    leave1_id = leave1["id"]
    assert leave1["status"] == LeaveStatus.PENDING.value
    assert leave1["student_name"] == "Student Alpha"
    assert leave1["student_no"] == prof1.student_no

    # 3. Overlapping leave blocked (409)
    resp = await client.post(
        "/api/v1/leaves",
        headers=student1_hdr,
        json={
            "from_date": "2026-12-12",
            "to_date": "2026-12-18",
            "reason": "Overlap",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "OVERLAPPING_LEAVE_REQUEST"

    # 4. Student 1 fetches /students/me/leaves
    resp = await client.get("/api/v1/students/me/leaves", headers=student1_hdr)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    # 5. GET /leaves/{id} by self and warden
    resp = await client.get(f"/api/v1/leaves/{leave1_id}", headers=student1_hdr)
    assert resp.status_code == 200
    resp = await client.get(f"/api/v1/leaves/{leave1_id}", headers=warden_hdr)
    assert resp.status_code == 200

    # Another student cannot view it (403)
    resp = await client.get(f"/api/v1/leaves/{leave1_id}", headers=student2_hdr)
    assert resp.status_code == 403

    # 6. Warden approves leave 1
    resp = await client.post(
        f"/api/v1/leaves/{leave1_id}/approve",
        headers=warden_hdr,
        json={"review_notes": "Approved by hostel warden"},
    )
    assert resp.status_code == 200
    app_data = resp.json()
    assert app_data["status"] == LeaveStatus.APPROVED.value
    assert app_data["review_notes"] == "Approved by hostel warden"

    # 7. Cannot cancel or re-approve already approved leave
    resp = await client.post(f"/api/v1/leaves/{leave1_id}/cancel", headers=student1_hdr)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "LEAVE_ALREADY_PROCESSED"

    # 8. Submit leave 2 and reject it
    resp = await client.post(
        "/api/v1/leaves",
        headers=student1_hdr,
        json={
            "from_date": "2026-12-20",
            "to_date": "2026-12-22",
            "reason": "Short break",
        },
    )
    assert resp.status_code == 201
    leave2_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/leaves/{leave2_id}/reject",
        headers=admin_hdr,
        json={"review_notes": "Not permitted due to exams"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == LeaveStatus.REJECTED.value

    # 9. Submit leave 3 and cancel it
    resp = await client.post(
        "/api/v1/leaves",
        headers=student1_hdr,
        json={
            "from_date": "2026-12-25",
            "to_date": "2026-12-28",
            "reason": "Holiday",
        },
    )
    assert resp.status_code == 201
    leave3_id = resp.json()["id"]

    # Student cancels own pending leave
    resp = await client.post(f"/api/v1/leaves/{leave3_id}/cancel", headers=student1_hdr)
    assert resp.status_code == 200
    assert resp.json()["status"] == LeaveStatus.CANCELLED.value


# =============================================================================
# Visitor Integration Tests
# =============================================================================


@pytest.mark.asyncio
async def test_visitors_api_lifecycle(client: AsyncClient, db_session: AsyncSession) -> None:
    """Verify visitor entry, checkout, listing, and visiting hours enforcement."""
    _h1, _h2, admin, warden, u1, prof1, _a1, _u2, _prof2, _a2 = await _create_full_setup(db_session)

    admin_hdr = _headers(admin)
    warden_hdr = _headers(warden)
    student1_hdr = _headers(u1)

    # 1. Check in visitor (temporarily set config to 24h for standard run)
    orig_start = settings.VISIT_START
    orig_end = settings.VISIT_END
    settings.VISIT_START = "00:00"
    settings.VISIT_END = "23:59"

    try:
        # Student cannot log visitor check-in (403)
        resp = await client.post(
            "/api/v1/visitors",
            headers=student1_hdr,
            json={
                "student_id": str(prof1.id),
                "name": "Jane Parent",
                "phone": "+1234567890",
                "relation": "Mother",
            },
        )
        assert resp.status_code == 403

        # Valid visitor check-in by warden
        resp = await client.post(
            "/api/v1/visitors",
            headers=warden_hdr,
            json={
                "student_id": str(prof1.id),
                "name": "Jane Parent",
                "phone": "+1234567890",
                "relation": "Mother",
                "id_proof_type": "Passport",
                "id_proof_number": "P-9988",
                "remarks": "Visiting room",
            },
        )
        assert resp.status_code == 201
        vis_data = resp.json()
        vis_id = vis_data["id"]
        assert vis_data["name"] == "Jane Parent"
        assert vis_data["is_active"] is True
        assert vis_data["student_id"] == str(prof1.id)

        # Duplicate active visitor check-in blocked (409)
        resp = await client.post(
            "/api/v1/visitors",
            headers=admin_hdr,
            json={
                "student_id": str(prof1.id),
                "name": "Jane Parent",
                "phone": "+1234567890",
                "relation": "Mother",
            },
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "VISITOR_ALREADY_CHECKED_IN"

        # List visitors (active=true)
        resp = await client.get("/api/v1/visitors?active=true", headers=warden_hdr)
        assert resp.status_code == 200
        active_list = resp.json()
        assert active_list["total"] == 1
        assert active_list["items"][0]["id"] == vis_id

        # Student self-service sees visitor
        resp = await client.get("/api/v1/students/me/visitors", headers=student1_hdr)
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

        # Check out visitor
        resp = await client.post(
            f"/api/v1/visitors/{vis_id}/check-out",
            headers=warden_hdr,
            json={"remarks": "Left campus safely"},
        )
        assert resp.status_code == 200
        co_data = resp.json()
        assert co_data["is_active"] is False
        assert co_data["check_out_at"] is not None

        # Cannot check out already checked-out visitor (409)
        resp = await client.post(
            f"/api/v1/visitors/{vis_id}/check-out",
            headers=warden_hdr,
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "VISITOR_ALREADY_CHECKED_OUT"

        # Now active=true list is empty
        resp = await client.get("/api/v1/visitors?active=true", headers=warden_hdr)
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

        # Now active=false list has 1 item
        resp = await client.get("/api/v1/visitors?active=false", headers=warden_hdr)
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    finally:
        settings.VISIT_START = orig_start
        settings.VISIT_END = orig_end


@pytest.mark.asyncio
async def test_visiting_hours_closed_rejection_api(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Verify that visiting hours outside configured window returns 400 VISITING_HOURS_CLOSED."""
    _h1, _h2, admin, _warden, _u1, prof1, _a1, _u2, _p2, _a2 = await _create_full_setup(db_session)
    admin_hdr = _headers(admin)

    # Set visiting hours to closed window (e.g. 01:00 to 01:01)
    orig_start = settings.VISIT_START
    orig_end = settings.VISIT_END
    settings.VISIT_START = "01:00"
    settings.VISIT_END = "01:01"

    try:
        resp = await client.post(
            "/api/v1/visitors",
            headers=admin_hdr,
            json={
                "student_id": str(prof1.id),
                "name": "Late Visitor",
                "phone": "+999999",
                "relation": "Friend",
            },
        )
        # Assuming current real time is not 01:00
        if datetime.now(UTC).time().hour != 1:
            assert resp.status_code == 400
            assert resp.json()["error"]["code"] == "VISITING_HOURS_CLOSED"
    finally:
        settings.VISIT_START = orig_start
        settings.VISIT_END = orig_end
