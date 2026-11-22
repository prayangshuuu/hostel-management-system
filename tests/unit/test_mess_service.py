"""Unit tests for MessService business logic, cutoff enforcement, and headcount."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    ForbiddenError,
)
from app.models.allocation import Allocation, AllocationStatus
from app.models.hostel import Block, GenderType, Hostel, WardenAssignment
from app.models.mess import MealOptOut, MealType
from app.models.operations import LeaveRequest, LeaveStatus
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.schemas.mess import (
    MealOptOutCreate,
    MessMenuBulkUpdateRequest,
    MessMenuItemCreate,
)
from app.services.mess_service import MEAL_DEFAULT_TIMES, MessService

type FixtureData = tuple[Hostel, Hostel, User, User, User, StudentProfile, StudentProfile]


@pytest.fixture
async def setup_data(db_session: AsyncSession) -> FixtureData:
    """Setup hostels, warden, admin, and two students with allocations."""
    uid = uuid.uuid4().hex[:6]

    # Hostels
    h1 = Hostel(name=f"Hostel 1 {uid}", code=f"H1-{uid}", gender_type=GenderType.MIXED)
    h2 = Hostel(name=f"Hostel 2 {uid}", code=f"H2-{uid}", gender_type=GenderType.MIXED)
    db_session.add_all([h1, h2])
    await db_session.flush()

    # Blocks & Rooms for H1
    b1 = Block(hostel_id=h1.id, name="Block A", floor_count=1)
    db_session.add(b1)
    await db_session.flush()

    r1 = Room(
        block_id=b1.id,
        number="101",
        floor=1,
        room_type=RoomType.DOUBLE,
        capacity=2,
        monthly_rent=Decimal("2000.00"),
        status=RoomStatus.AVAILABLE,
    )
    db_session.add(r1)
    await db_session.flush()

    bed1 = Bed(room_id=r1.id, label="B1", is_occupied=True)
    bed2 = Bed(room_id=r1.id, label="B2", is_occupied=True)
    db_session.add_all([bed1, bed2])
    await db_session.flush()

    # Blocks & Rooms for H2
    b2 = Block(hostel_id=h2.id, name="Block B", floor_count=1)
    db_session.add(b2)
    await db_session.flush()

    r2 = Room(
        block_id=b2.id,
        number="201",
        floor=1,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("3000.00"),
        status=RoomStatus.AVAILABLE,
    )
    db_session.add(r2)
    await db_session.flush()

    bed3 = Bed(room_id=r2.id, label="B1", is_occupied=True)
    db_session.add(bed3)
    await db_session.flush()

    # Admin User
    admin_user = User(
        email=f"admin_{uid}@example.com",
        full_name="Admin User",
        hashed_password="hash",
        role=UserRole.ADMIN,
        is_active=True,
    )
    # Warden assigned to H1 only
    warden_user = User(
        email=f"warden_{uid}@example.com",
        full_name="Warden One",
        hashed_password="hash",
        role=UserRole.WARDEN,
        is_active=True,
    )
    # Student 1 in H1
    stu1_user = User(
        email=f"stu1_{uid}@example.com",
        full_name="Student One",
        hashed_password="hash",
        role=UserRole.STUDENT,
        is_active=True,
    )
    # Student 2 in H2
    stu2_user = User(
        email=f"stu2_{uid}@example.com",
        full_name="Student Two",
        hashed_password="hash",
        role=UserRole.STUDENT,
        is_active=True,
    )
    db_session.add_all([admin_user, warden_user, stu1_user, stu2_user])
    await db_session.flush()

    # Warden assignment to H1
    assignment = WardenAssignment(user_id=warden_user.id, hostel_id=h1.id)
    db_session.add(assignment)

    # Student 1 profile & allocation in H1
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
    db_session.add_all([p1, p2])
    await db_session.flush()

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
    db_session.add_all([alloc1, alloc2])
    await db_session.flush()

    return h1, h2, admin_user, warden_user, stu1_user, p1, p2


async def test_update_and_get_hostel_menu_scoping(
    db_session: AsyncSession, setup_data: FixtureData
) -> None:
    """Verify hostel menu PUT/GET permission and scoping checks."""
    h1, h2, _admin_user, warden_user, stu1_user, _p1, _p2 = setup_data
    service = MessService(db_session)

    # Warden can update assigned hostel (H1)
    req = MessMenuBulkUpdateRequest(
        entries=[
            MessMenuItemCreate(
                day_of_week=0, meal_type=MealType.BREAKFAST, items=["Cereal", "Milk"]
            ),
            MessMenuItemCreate(day_of_week=0, meal_type=MealType.LUNCH, items=["Sandwich"]),
        ]
    )
    menu_h1 = await service.update_hostel_menu(h1.id, req, warden_user)
    assert len(menu_h1.items) == 2
    assert 0 in menu_h1.schedule

    # Warden cannot update unassigned hostel (H2) -> ForbiddenError
    with pytest.raises(ForbiddenError):
        await service.update_hostel_menu(h2.id, req, warden_user)

    # Student 1 (in H1) can view H1 menu
    view_h1 = await service.get_hostel_menu(h1.id, stu1_user)
    assert len(view_h1.items) == 2

    # Student 1 cannot view H2 menu -> ForbiddenError
    with pytest.raises(ForbiddenError) as exc:
        await service.get_hostel_menu(h2.id, stu1_user)
    assert exc.value.code == "FORBIDDEN"


async def test_get_student_today_menu(db_session: AsyncSession, setup_data: FixtureData) -> None:
    """Verify today's menu for authenticated student."""
    h1, _h2, admin_user, _warden_user, stu1_user, _p1, _p2 = setup_data
    service = MessService(db_session)

    today = datetime.now(UTC).date()
    day_of_week = today.weekday()

    # Add menu for today
    req = MessMenuBulkUpdateRequest(
        entries=[
            MessMenuItemCreate(
                day_of_week=day_of_week, meal_type=MealType.BREAKFAST, items=["Toast", "Coffee"]
            ),
            MessMenuItemCreate(
                day_of_week=day_of_week, meal_type=MealType.DINNER, items=["Pasta", "Salad"]
            ),
        ]
    )
    await service.update_hostel_menu(h1.id, req, admin_user)

    daily = await service.get_student_today_menu(stu1_user)
    assert daily.hostel_id == h1.id
    assert daily.day_of_week == day_of_week
    assert "breakfast" in daily.meals
    assert "dinner" in daily.meals


async def test_opt_out_date_in_past(db_session: AsyncSession, setup_data: FixtureData) -> None:
    """Verify opt-out fails if date is in the past."""
    _h1, _h2, _admin_user, _warden_user, stu1_user, _p1, _p2 = setup_data
    service = MessService(db_session)

    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    with pytest.raises(BusinessRuleError) as exc:
        await service.opt_out_meal(
            MealOptOutCreate(date=yesterday, meal_type=MealType.LUNCH),
            stu1_user,
        )
    assert exc.value.code == "DATE_IN_PAST"


async def test_opt_out_cutoff_expired(db_session: AsyncSession, setup_data: FixtureData) -> None:
    """Verify opt-out fails when current time is past the cutoff window."""
    _h1, _h2, _admin_user, _warden_user, stu1_user, _p1, _p2 = setup_data
    service = MessService(db_session)

    target_date = datetime.now(UTC).date() + timedelta(days=1)
    # Default breakfast is 08:00 UTC. 12 hours cutoff means cutoff is 20:00 the day before.
    meal_time = MEAL_DEFAULT_TIMES[MealType.BREAKFAST]
    meal_dt = datetime.combine(target_date, meal_time, tzinfo=UTC)
    cutoff_time = meal_dt - timedelta(hours=12)

    # Freeze current time to 1 second AFTER cutoff
    frozen_now = cutoff_time + timedelta(seconds=1)
    with patch("app.services.mess_service.datetime") as mock_dt:
        mock_dt.now.return_value = frozen_now
        mock_dt.combine = datetime.combine
        with pytest.raises(BusinessRuleError) as exc:
            await service.opt_out_meal(
                MealOptOutCreate(date=target_date, meal_type=MealType.BREAKFAST),
                stu1_user,
            )
        assert exc.value.code == "CUTOFF_EXPIRED"


async def test_opt_out_duplicate_conflict(
    db_session: AsyncSession, setup_data: FixtureData
) -> None:
    """Verify duplicate meal opt-out raises 409 ConflictError."""
    _h1, _h2, _admin_user, _warden_user, stu1_user, _p1, _p2 = setup_data
    service = MessService(db_session)

    future_date = datetime.now(UTC).date() + timedelta(days=3)
    # First opt out
    opt = await service.opt_out_meal(
        MealOptOutCreate(date=future_date, meal_type=MealType.LUNCH),
        stu1_user,
    )
    assert opt.id is not None

    # Duplicate opt out -> ConflictError
    with pytest.raises(ConflictError) as exc:
        await service.opt_out_meal(
            MealOptOutCreate(date=future_date, meal_type=MealType.LUNCH),
            stu1_user,
        )
    assert exc.value.code == "ALREADY_OPTED_OUT"


async def test_cancel_opt_out_permissions_and_cutoff(
    db_session: AsyncSession, setup_data: FixtureData
) -> None:
    """Verify cancel opt-out ownership check and cutoff enforcement."""
    _h1, _h2, _admin_user, _warden_user, stu1_user, _p1, p2 = setup_data
    service = MessService(db_session)

    # Student 2 user
    stu2_user = await db_session.get(User, p2.user_id)
    assert stu2_user is not None

    future_date = datetime.now(UTC).date() + timedelta(days=5)
    opt = await service.opt_out_meal(
        MealOptOutCreate(date=future_date, meal_type=MealType.DINNER),
        stu1_user,
    )

    # Student 2 cannot cancel Student 1's opt out -> ForbiddenError
    with pytest.raises(ForbiddenError):
        await service.cancel_opt_out(opt.id, stu2_user)

    # Cutoff expiration check on cancel
    meal_time = MEAL_DEFAULT_TIMES[MealType.DINNER]
    meal_dt = datetime.combine(future_date, meal_time, tzinfo=UTC)
    cutoff = meal_dt - timedelta(hours=12)

    with patch("app.services.mess_service.datetime") as mock_dt:
        mock_dt.now.return_value = cutoff + timedelta(minutes=5)
        mock_dt.combine = datetime.combine
        with pytest.raises(BusinessRuleError) as exc:
            await service.cancel_opt_out(opt.id, stu1_user)
        assert exc.value.code == "CUTOFF_EXPIRED"

    # Successful cancellation before cutoff
    await service.cancel_opt_out(opt.id, stu1_user)
    assert await service.meal_opt_out_repo.get_by_id(opt.id) is None


async def test_headcount_with_opt_out_and_leave_deduplication(
    db_session: AsyncSession, setup_data: FixtureData
) -> None:
    """Verify headcount merges opt-outs and leaves without double counting."""
    h1, _h2, admin_user, _warden_user, _stu1_user, p1, _p2 = setup_data
    service = MessService(db_session)

    # Add a second student in H1
    uid = uuid.uuid4().hex[:6]
    extra_user = User(
        email=f"extra_{uid}@example.com",
        full_name="Extra Student",
        hashed_password="hash",
        role=UserRole.STUDENT,
        is_active=True,
    )
    db_session.add(extra_user)
    await db_session.flush()

    extra_p = StudentProfile(
        user_id=extra_user.id,
        student_no=f"STU-EX-{uid}",
        gender=GenderType.MALE,
        department="Mechanical",
        year=1,
        guardian_name="Guardian Extra",
        guardian_phone="1234567890",
        emergency_contact="0987654321",
    )
    db_session.add(extra_p)
    await db_session.flush()

    # Find the second bed in Room 101 of H1
    h1_beds = await db_session.execute(
        Allocation.__table__.select().where(Allocation.student_id == p1.id)
    )
    h1_alloc_row = h1_beds.first()
    assert h1_alloc_row is not None

    today = datetime.now(UTC).date()
    target_date = today + timedelta(days=2)

    # Allocate extra_p to bed2 in H1
    from app.models.room import Bed

    bed2 = (await db_session.execute(Bed.__table__.select().where(Bed.label == "B2"))).first()
    assert bed2 is not None

    extra_alloc = Allocation(
        student_id=extra_p.id,
        bed_id=bed2.id,
        start_date=today - timedelta(days=1),
        status=AllocationStatus.ACTIVE,
    )
    db_session.add(extra_alloc)
    await db_session.flush()

    # Total allocated in H1 = 2 (p1 and extra_p)

    # 1. Student 1 opts out of LUNCH on target_date
    db_session.add(
        MealOptOut(
            student_id=p1.id,
            date=target_date,
            meal_type=MealType.LUNCH,
        )
    )

    # 2. Student 1 is ALSO on approved leave covering target_date
    leave1 = LeaveRequest(
        student_id=p1.id,
        from_date=target_date - timedelta(days=1),
        to_date=target_date + timedelta(days=1),
        reason="Family event",
        status=LeaveStatus.APPROVED,
    )
    db_session.add(leave1)

    # 3. Extra student is NOT on leave and has NOT opted out
    await db_session.flush()

    # Get headcount for H1
    headcount = await service.get_headcount(h1.id, target_date, admin_user)
    assert headcount.hostel_id == h1.id
    assert headcount.date == target_date

    lunch_item = next(m for m in headcount.meals if m.meal_type == MealType.LUNCH)
    assert lunch_item.allocated_count == 2
    assert lunch_item.opted_out_count == 1  # p1 opted out
    assert lunch_item.on_leave_count == 1  # p1 on leave
    # If double counted, expected would be 2 - (1 + 1) = 0.
    # But union set is {p1}, so len(union) = 1 -> expected is 2 - 1 = 1!
    assert lunch_item.expected_count == 1

    # For DINNER:
    # p1 is still on leave, but did not opt out
    dinner_item = next(m for m in headcount.meals if m.meal_type == MealType.DINNER)
    assert dinner_item.allocated_count == 2
    assert dinner_item.opted_out_count == 0
    assert dinner_item.on_leave_count == 1
    assert dinner_item.expected_count == 1
