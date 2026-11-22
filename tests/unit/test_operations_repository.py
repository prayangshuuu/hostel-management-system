"""Unit tests for operations repositories: attendance, leave, and visitors."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.allocation import Allocation, AllocationStatus
from app.models.hostel import Block, GenderType, Hostel
from app.models.operations import (
    AttendanceLog,
    AttendanceType,
    LeaveRequest,
    LeaveStatus,
    Visitor,
)
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.repositories.operations_repository import (
    AttendanceRepository,
    LeaveRepository,
    VisitorRepository,
)
from app.schemas.common import PaginationParams


async def _setup_hostel_and_student(
    session: AsyncSession,
) -> tuple[Hostel, User, StudentProfile, Allocation, User]:
    """Helper creating a hostel, block, room, bed, warden, student, and active allocation."""
    uid = uuid.uuid4().hex[:6]
    hostel = Hostel(
        name=f"Hostel {uid}",
        code=f"H-{uid}",
        gender_type=GenderType.MIXED,
    )
    session.add(hostel)
    await session.flush()

    block = Block(hostel_id=hostel.id, name="Block A", floor_count=2)
    session.add(block)
    await session.flush()

    room = Room(
        block_id=block.id,
        number="101",
        floor=1,
        room_type=RoomType.DOUBLE,
        capacity=2,
        monthly_rent=Decimal("3000.00"),
        status=RoomStatus.AVAILABLE,
    )
    session.add(room)
    await session.flush()

    bed = Bed(room_id=room.id, label="101-A")
    session.add(bed)
    await session.flush()

    warden = User(
        email=f"warden_{uid}@example.com",
        full_name="Warden User",
        hashed_password="hash",
        role=UserRole.WARDEN,
    )
    student_user = User(
        email=f"student_{uid}@example.com",
        full_name="Student User",
        hashed_password="hash",
        role=UserRole.STUDENT,
    )
    session.add_all([warden, student_user])
    await session.flush()

    profile = StudentProfile(
        user_id=student_user.id,
        student_no=f"STU-{uid}",
        gender=GenderType.MALE,
        department="Science",
        year=1,
        guardian_name="Guardian",
        guardian_phone="+1112223334",
        emergency_contact="+1112223335",
    )
    session.add(profile)
    await session.flush()

    allocation = Allocation(
        student_id=profile.id,
        bed_id=bed.id,
        start_date=date(2026, 11, 1),
        status=AllocationStatus.ACTIVE,
    )
    session.add(allocation)
    await session.flush()

    return hostel, warden, profile, allocation, student_user


@pytest.mark.asyncio
async def test_attendance_repository_crud_and_latest(db_session: AsyncSession) -> None:
    """Verify AttendanceRepository creation and get_latest_for_student."""
    _hostel, warden, profile, _alloc, _stu_user = await _setup_hostel_and_student(db_session)
    repo = AttendanceRepository(db_session)

    # Initially None
    latest = await repo.get_latest_for_student(profile.id)
    assert latest is None

    t1 = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    log1 = AttendanceLog(
        student_id=profile.id,
        type=AttendanceType.CHECK_IN,
        timestamp=t1,
        recorded_by=warden.id,
        remarks="First check-in",
    )
    await repo.create(log1)

    latest = await repo.get_latest_for_student(profile.id)
    assert latest is not None
    assert latest.type == AttendanceType.CHECK_IN
    assert latest.id == log1.id

    t2 = datetime(2026, 11, 20, 16, 0, tzinfo=UTC)
    log2 = AttendanceLog(
        student_id=profile.id,
        type=AttendanceType.CHECK_OUT,
        timestamp=t2,
        recorded_by=warden.id,
        remarks="Going home",
    )
    await repo.create(log2)

    latest = await repo.get_latest_for_student(profile.id)
    assert latest is not None
    assert latest.type == AttendanceType.CHECK_OUT
    assert latest.id == log2.id


@pytest.mark.asyncio
async def test_attendance_repository_list_and_present_students(
    db_session: AsyncSession,
) -> None:
    """Verify AttendanceRepository listing filters and get_present_students."""
    hostel, warden, profile, _alloc, _stu_user = await _setup_hostel_and_student(db_session)
    repo = AttendanceRepository(db_session)

    t1 = datetime(2026, 11, 22, 9, 0, tzinfo=UTC)
    log = AttendanceLog(
        student_id=profile.id,
        type=AttendanceType.CHECK_IN,
        timestamp=t1,
        recorded_by=warden.id,
    )
    await repo.create(log)

    params = PaginationParams(page=1, size=10)
    items, total = await repo.list(
        params=params,
        student_id=profile.id,
        hostel_id=hostel.id,
        type=AttendanceType.CHECK_IN,
    )
    assert total == 1
    assert len(items) == 1
    assert items[0].id == log.id

    # get_present_students
    present = await repo.get_present_students(hostel_id=hostel.id)
    assert len(present) == 1
    assert present[0].student_id == profile.id
    assert present[0].student_name == "Student User"
    assert present[0].hostel_name == hostel.name
    assert present[0].room_number == "101"
    assert present[0].bed_label == "101-A"

    # Now student checks out
    t2 = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
    log_out = AttendanceLog(
        student_id=profile.id,
        type=AttendanceType.CHECK_OUT,
        timestamp=t2,
        recorded_by=warden.id,
    )
    await repo.create(log_out)

    present_after = await repo.get_present_students(hostel_id=hostel.id)
    assert len(present_after) == 0


@pytest.mark.asyncio
async def test_leave_repository_crud_and_overlapping(db_session: AsyncSession) -> None:
    """Verify LeaveRepository lifecycle and date overlap detection."""
    hostel, warden, profile, _alloc, _stu_user = await _setup_hostel_and_student(db_session)
    repo = LeaveRepository(db_session)

    leave = LeaveRequest(
        student_id=profile.id,
        from_date=date(2026, 12, 10),
        to_date=date(2026, 12, 15),
        reason="Vacation",
        status=LeaveStatus.PENDING,
    )
    created = await repo.create(leave)
    assert created.id is not None

    fetched = await repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.reason == "Vacation"

    # Overlapping tests:
    # 1. Exact match overlaps
    ov1 = await repo.get_overlapping(profile.id, date(2026, 12, 10), date(2026, 12, 15))
    assert len(ov1) == 1

    # 2. Sub-interval overlaps (12-11 to 12-14)
    ov2 = await repo.get_overlapping(profile.id, date(2026, 12, 11), date(2026, 12, 14))
    assert len(ov2) == 1

    # 3. Super-interval overlaps (12-08 to 12-18)
    ov3 = await repo.get_overlapping(profile.id, date(2026, 12, 8), date(2026, 12, 18))
    assert len(ov3) == 1

    # 4. Partial overlap left (12-08 to 12-11)
    ov4 = await repo.get_overlapping(profile.id, date(2026, 12, 8), date(2026, 12, 11))
    assert len(ov4) == 1

    # 5. Non-overlapping before (12-01 to 12-09)
    nov1 = await repo.get_overlapping(profile.id, date(2026, 12, 1), date(2026, 12, 9))
    assert len(nov1) == 0

    # 6. Non-overlapping after (12-16 to 12-20)
    nov2 = await repo.get_overlapping(profile.id, date(2026, 12, 16), date(2026, 12, 20))
    assert len(nov2) == 0

    # 7. Exclude id
    ov_ex = await repo.get_overlapping(
        profile.id, date(2026, 12, 10), date(2026, 12, 15), exclude_id=created.id
    )
    assert len(ov_ex) == 0

    # Update
    created.status = LeaveStatus.APPROVED
    created.reviewed_by = warden.id
    created.reviewed_at = datetime.now(UTC)
    updated = await repo.update(created)
    assert updated.status == LeaveStatus.APPROVED

    # List
    params = PaginationParams(page=1, size=10)
    items, total = await repo.list(
        params=params,
        student_id=profile.id,
        status=LeaveStatus.APPROVED,
        hostel_id=hostel.id,
    )
    assert total == 1
    assert items[0].id == created.id


@pytest.mark.asyncio
async def test_visitor_repository_crud_and_active(db_session: AsyncSession) -> None:
    """Verify VisitorRepository lifecycle and active visitor query."""
    hostel, _warden, profile, _alloc, _stu_user = await _setup_hostel_and_student(db_session)
    repo = VisitorRepository(db_session)

    vis = Visitor(
        student_id=profile.id,
        name="Mary Doe",
        phone="+999888777",
        relation="Aunt",
    )
    created = await repo.create(vis)
    assert created.id is not None
    assert created.is_active is True

    # Active visitor lookup
    active = await repo.get_active_by_student_and_visitor(
        student_id=profile.id,
        name="mary doe",  # case-insensitive
        phone="+999888777",
    )
    assert active is not None
    assert active.id == created.id

    # List active
    params = PaginationParams(page=1, size=10)
    items, total = await repo.list(params=params, student_id=profile.id, active=True)
    assert total == 1
    assert items[0].id == created.id

    # Check out
    created.check_out_at = datetime.now(UTC)
    await repo.update(created)
    assert created.is_active is False

    # Should no longer be active
    active_after = await repo.get_active_by_student_and_visitor(
        student_id=profile.id,
        name="Mary Doe",
        phone="+999888777",
    )
    assert active_after is None

    # List inactive
    items_in, total_in = await repo.list(
        params=params, student_id=profile.id, active=False, hostel_id=hostel.id
    )
    assert total_in == 1
    assert items_in[0].id == created.id
