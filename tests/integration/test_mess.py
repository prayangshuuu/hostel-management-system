"""Integration tests for Mess menu, meal opt-out, and headcount REST API endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models.allocation import Allocation, AllocationStatus
from app.models.hostel import Block, GenderType, Hostel, WardenAssignment
from app.models.mess import MealOptOut, MealType
from app.models.operations import LeaveRequest, LeaveStatus
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.services.mess_service import MEAL_DEFAULT_TIMES

type MessSetupResult = tuple[
    Hostel,
    Hostel,
    User,
    User,
    User,
    StudentProfile,
    User,
    StudentProfile,
    User,
    str,
    str,
    str,
    str,
    str,
]


async def _create_test_data(session: AsyncSession) -> MessSetupResult:
    """Helper setting up 2 hostels, 1 warden assigned to H1, 2 students, and tokens."""
    uid = uuid.uuid4().hex[:6]

    # Hostels
    h1 = Hostel(name=f"Hostel Alpha {uid}", code=f"HA-{uid}", gender_type=GenderType.MIXED)
    h2 = Hostel(name=f"Hostel Beta {uid}", code=f"HB-{uid}", gender_type=GenderType.MIXED)
    session.add_all([h1, h2])
    await session.flush()

    # Blocks & Rooms for H1
    b1 = Block(hostel_id=h1.id, name="Block A", floor_count=1)
    session.add(b1)
    await session.flush()

    r1 = Room(
        block_id=b1.id,
        number="101",
        floor=1,
        room_type=RoomType.DOUBLE,
        capacity=2,
        monthly_rent=Decimal("2000.00"),
        status=RoomStatus.AVAILABLE,
    )
    session.add(r1)
    await session.flush()

    bed1 = Bed(room_id=r1.id, label="B1", is_occupied=True)
    bed2 = Bed(room_id=r1.id, label="B2", is_occupied=True)
    session.add_all([bed1, bed2])
    await session.flush()

    # Blocks & Rooms for H2
    b2 = Block(hostel_id=h2.id, name="Block B", floor_count=1)
    session.add(b2)
    await session.flush()

    r2 = Room(
        block_id=b2.id,
        number="201",
        floor=1,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("3000.00"),
        status=RoomStatus.AVAILABLE,
    )
    session.add(r2)
    await session.flush()

    bed3 = Bed(room_id=r2.id, label="B1", is_occupied=True)
    session.add(bed3)
    await session.flush()

    # Users
    admin_user = User(
        email=f"admin_{uid}@example.com",
        full_name="Admin Boss",
        hashed_password=hash_password("adminpass"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    warden_user = User(
        email=f"warden_{uid}@example.com",
        full_name="Warden Alpha",
        hashed_password=hash_password("wardenpass"),
        role=UserRole.WARDEN,
        is_active=True,
    )
    stu1_user = User(
        email=f"stu1_{uid}@example.com",
        full_name="Student One",
        hashed_password=hash_password("stupass1"),
        role=UserRole.STUDENT,
        is_active=True,
    )
    stu2_user = User(
        email=f"stu2_{uid}@example.com",
        full_name="Student Two",
        hashed_password=hash_password("stupass2"),
        role=UserRole.STUDENT,
        is_active=True,
    )
    stu_no_alloc_user = User(
        email=f"noalloc_{uid}@example.com",
        full_name="Student Unallocated",
        hashed_password=hash_password("stupass3"),
        role=UserRole.STUDENT,
        is_active=True,
    )
    session.add_all([admin_user, warden_user, stu1_user, stu2_user, stu_no_alloc_user])
    await session.flush()

    # Warden assignment to H1
    session.add(WardenAssignment(user_id=warden_user.id, hostel_id=h1.id))

    # Student profiles
    p1 = StudentProfile(
        user_id=stu1_user.id,
        student_no=f"STU1-{uid}",
        gender=GenderType.MALE,
        department="Computer Science",
        year=1,
        guardian_name="Guardian 1",
        guardian_phone="1234567890",
        emergency_contact="0987654321",
    )
    p2 = StudentProfile(
        user_id=stu2_user.id,
        student_no=f"STU2-{uid}",
        gender=GenderType.FEMALE,
        department="Electrical",
        year=2,
        guardian_name="Guardian 2",
        guardian_phone="1234567890",
        emergency_contact="0987654321",
    )
    p_no_alloc = StudentProfile(
        user_id=stu_no_alloc_user.id,
        student_no=f"STU3-{uid}",
        gender=GenderType.FEMALE,
        department="Civil",
        year=1,
        guardian_name="Guardian 3",
        guardian_phone="1234567890",
        emergency_contact="0987654321",
    )
    session.add_all([p1, p2, p_no_alloc])
    await session.flush()

    today = datetime.now(UTC).date()
    alloc1 = Allocation(
        student_id=p1.id,
        bed_id=bed1.id,
        start_date=today - timedelta(days=10),
        status=AllocationStatus.ACTIVE,
    )
    alloc2 = Allocation(
        student_id=p2.id,
        bed_id=bed3.id,
        start_date=today - timedelta(days=5),
        status=AllocationStatus.ACTIVE,
    )
    session.add_all([alloc1, alloc2])
    await session.commit()

    # JWT tokens
    admin_token = create_access_token(user_id=admin_user.id, role="admin")
    warden_token = create_access_token(user_id=warden_user.id, role="warden")
    stu1_token = create_access_token(user_id=stu1_user.id, role="student")
    stu2_token = create_access_token(user_id=stu2_user.id, role="student")
    stu_no_alloc_token = create_access_token(user_id=stu_no_alloc_user.id, role="student")

    return (
        h1,
        h2,
        admin_user,
        warden_user,
        stu1_user,
        p1,
        stu2_user,
        p2,
        stu_no_alloc_user,
        admin_token,
        warden_token,
        stu1_token,
        stu2_token,
        stu_no_alloc_token,
    )


async def test_mess_menu_endpoints(client: AsyncClient, db_session: AsyncSession) -> None:
    """Verify PUT and GET menu endpoints, authorization, and student scoping."""
    (
        h1,
        h2,
        _,
        _,
        _,
        _,
        _,
        _,
        _,
        admin_token,
        warden_token,
        stu1_token,
        stu2_token,
        _,
    ) = await _create_test_data(db_session)

    menu_payload = {
        "entries": [
            {"day_of_week": 0, "meal_type": "breakfast", "items": ["Pancakes", "Tea"]},
            {"day_of_week": 0, "meal_type": "lunch", "items": ["Rice", "Curry"]},
            {"day_of_week": 1, "meal_type": "dinner", "items": ["Soup", "Bread"]},
        ]
    }

    # 1. Student cannot PUT menu -> 403
    resp = await client.put(
        f"/api/v1/hostels/{h1.id}/menu",
        json=menu_payload,
        headers={"Authorization": f"Bearer {stu1_token}"},
    )
    assert resp.status_code == 403

    # 2. Warden can PUT menu for assigned hostel H1 -> 200
    resp = await client.put(
        f"/api/v1/hostels/{h1.id}/menu",
        json=menu_payload,
        headers={"Authorization": f"Bearer {warden_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["hostel_id"] == str(h1.id)
    assert len(body["items"]) == 3
    assert "0" in body["schedule"] or 0 in body["schedule"]

    # 3. Warden cannot PUT menu for unassigned hostel H2 -> 403
    resp = await client.put(
        f"/api/v1/hostels/{h2.id}/menu",
        json=menu_payload,
        headers={"Authorization": f"Bearer {warden_token}"},
    )
    assert resp.status_code == 403

    # 4. Student 1 (in H1) can GET H1 menu -> 200
    resp = await client.get(
        f"/api/v1/hostels/{h1.id}/menu",
        headers={"Authorization": f"Bearer {stu1_token}"},
    )
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 3

    # 5. Student 2 (in H2) CANNOT GET H1 menu -> 403
    resp = await client.get(
        f"/api/v1/hostels/{h1.id}/menu",
        headers={"Authorization": f"Bearer {stu2_token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"

    # 6. Admin can GET any hostel menu -> 200
    resp = await client.get(
        f"/api/v1/hostels/{h1.id}/menu",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200


async def test_student_today_menu_endpoint(client: AsyncClient, db_session: AsyncSession) -> None:
    """Verify GET /api/v1/students/me/menu/today for allocated vs unallocated student."""
    (
        h1,
        _,
        _,
        _,
        _,
        _,
        _,
        _,
        _,
        admin_token,
        _,
        stu1_token,
        _,
        stu_no_alloc_token,
    ) = await _create_test_data(db_session)

    today = datetime.now(UTC).date()
    day_of_week = today.weekday()

    # Populate today's menu for H1
    await client.put(
        f"/api/v1/hostels/{h1.id}/menu",
        json={
            "entries": [
                {
                    "day_of_week": day_of_week,
                    "meal_type": "breakfast",
                    "items": ["Eggs", "Toast"],
                },
                {
                    "day_of_week": day_of_week,
                    "meal_type": "lunch",
                    "items": ["Fried Rice"],
                },
            ]
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    # Student 1 fetches today's menu -> 200
    resp = await client.get(
        "/api/v1/students/me/menu/today",
        headers={"Authorization": f"Bearer {stu1_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["hostel_id"] == str(h1.id)
    assert body["day_of_week"] == day_of_week
    assert "breakfast" in body["meals"]
    assert body["meals"]["breakfast"] == ["Eggs", "Toast"]

    # Student without allocation fetches today's menu -> 400 NO_ACTIVE_ALLOCATION
    resp_no = await client.get(
        "/api/v1/students/me/menu/today",
        headers={"Authorization": f"Bearer {stu_no_alloc_token}"},
    )
    assert resp_no.status_code == 400
    assert resp_no.json()["error"]["code"] == "NO_ACTIVE_ALLOCATION"


async def test_meal_opt_out_lifecycle_endpoints(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Verify POST, GET, DELETE meal opt-outs, duplicate prevention, and cutoff check."""
    (
        _,
        _,
        _,
        _,
        _,
        _,
        _,
        _,
        _,
        _,
        _,
        stu1_token,
        stu2_token,
        stu_no_alloc_token,
    ) = await _create_test_data(db_session)

    future_date = (datetime.now(UTC) + timedelta(days=4)).date()

    # 1. Unallocated student cannot opt out -> 400
    resp = await client.post(
        "/api/v1/meals/opt-outs",
        json={"date": str(future_date), "meal_type": "lunch"},
        headers={"Authorization": f"Bearer {stu_no_alloc_token}"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "NO_ACTIVE_ALLOCATION"

    # 2. Date in past -> 400
    yesterday = (datetime.now(UTC) - timedelta(days=1)).date()
    resp = await client.post(
        "/api/v1/meals/opt-outs",
        json={"date": str(yesterday), "meal_type": "lunch"},
        headers={"Authorization": f"Bearer {stu1_token}"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "DATE_IN_PAST"

    # 3. Successful opt-out -> 201
    resp = await client.post(
        "/api/v1/meals/opt-outs",
        json={"date": str(future_date), "meal_type": "dinner"},
        headers={"Authorization": f"Bearer {stu1_token}"},
    )
    assert resp.status_code == 201
    opt_data = resp.json()
    opt_id = opt_data["id"]
    assert opt_data["meal_type"] == "dinner"

    # 4. Duplicate opt-out -> 409
    resp_dup = await client.post(
        "/api/v1/meals/opt-outs",
        json={"date": str(future_date), "meal_type": "dinner"},
        headers={"Authorization": f"Bearer {stu1_token}"},
    )
    assert resp_dup.status_code == 409
    assert resp_dup.json()["error"]["code"] == "ALREADY_OPTED_OUT"

    # 5. List opt-outs
    resp_list = await client.get(
        "/api/v1/students/me/opt-outs",
        headers={"Authorization": f"Bearer {stu1_token}"},
    )
    assert resp_list.status_code == 200
    list_body = resp_list.json()
    assert list_body["total"] == 1
    assert list_body["items"][0]["id"] == opt_id

    # 6. Student 2 cannot cancel Student 1's opt-out -> 403
    resp_del_other = await client.delete(
        f"/api/v1/meals/opt-outs/{opt_id}",
        headers={"Authorization": f"Bearer {stu2_token}"},
    )
    assert resp_del_other.status_code == 403

    # 7. Cancel opt-out past cutoff -> 400
    meal_time = MEAL_DEFAULT_TIMES[MealType.DINNER]
    meal_dt = datetime.combine(future_date, meal_time, tzinfo=UTC)
    cutoff = meal_dt - timedelta(hours=12)

    with patch("app.services.mess_service.datetime") as mock_dt:
        mock_dt.now.return_value = cutoff + timedelta(seconds=10)
        mock_dt.combine = datetime.combine
        resp_late = await client.delete(
            f"/api/v1/meals/opt-outs/{opt_id}",
            headers={"Authorization": f"Bearer {stu1_token}"},
        )
        assert resp_late.status_code == 400
        assert resp_late.json()["error"]["code"] == "CUTOFF_EXPIRED"

    # 8. Successful cancellation -> 204
    resp_del = await client.delete(
        f"/api/v1/meals/opt-outs/{opt_id}",
        headers={"Authorization": f"Bearer {stu1_token}"},
    )
    assert resp_del.status_code == 204

    # 9. List now empty
    resp_list_after = await client.get(
        "/api/v1/students/me/opt-outs",
        headers={"Authorization": f"Bearer {stu1_token}"},
    )
    assert resp_list_after.json()["total"] == 0


async def test_meal_headcount_endpoint(client: AsyncClient, db_session: AsyncSession) -> None:
    """Verify GET /api/v1/meals/headcount with combined leave and opt-out math."""
    (
        h1,
        _,
        _,
        _,
        _stu1_user,
        p1,
        _,
        _,
        _,
        _admin_token,
        warden_token,
        stu1_token,
        _,
        _,
    ) = await _create_test_data(db_session)

    target_date = (datetime.now(UTC) + timedelta(days=3)).date()

    # Student 1 opts out of lunch on target_date
    db_session.add(
        MealOptOut(
            student_id=p1.id,
            date=target_date,
            meal_type=MealType.LUNCH,
        )
    )

    # Student 1 is ALSO on approved leave covering target_date
    db_session.add(
        LeaveRequest(
            student_id=p1.id,
            from_date=target_date,
            to_date=target_date,
            reason="Dentist appointment",
            status=LeaveStatus.APPROVED,
        )
    )
    await db_session.commit()

    # 1. Student cannot access headcount -> 403
    resp_stu = await client.get(
        f"/api/v1/meals/headcount?hostel_id={h1.id}&date={target_date}",
        headers={"Authorization": f"Bearer {stu1_token}"},
    )
    assert resp_stu.status_code == 403

    # 2. Warden can access headcount for assigned hostel H1 -> 200
    resp_warden = await client.get(
        f"/api/v1/meals/headcount?hostel_id={h1.id}&date={target_date}",
        headers={"Authorization": f"Bearer {warden_token}"},
    )
    assert resp_warden.status_code == 200
    data = resp_warden.json()
    assert data["hostel_id"] == str(h1.id)
    assert data["date"] == str(target_date)

    lunch = next(m for m in data["meals"] if m["meal_type"] == "lunch")
    assert lunch["allocated_count"] == 1
    assert lunch["opted_out_count"] == 1
    assert lunch["on_leave_count"] == 1
    # Expected count = 1 - 1 = 0 (deduplicated!)
    assert lunch["expected_count"] == 0

    dinner = next(m for m in data["meals"] if m["meal_type"] == "dinner")
    assert dinner["allocated_count"] == 1
    assert dinner["opted_out_count"] == 0
    assert dinner["on_leave_count"] == 1
    # Expected count = 1 - 1 = 0 (due to leave)
    assert dinner["expected_count"] == 0
