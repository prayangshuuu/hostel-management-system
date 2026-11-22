"""Unit tests for OperationsService business logic."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationAppError,
)
from app.models.allocation import Allocation, AllocationStatus
from app.models.hostel import Block, GenderType, Hostel, WardenAssignment
from app.models.operations import AttendanceType, LeaveStatus
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.schemas.common import PaginationParams
from app.schemas.operations import (
    AttendanceActionRequest,
    LeaveRequestCreate,
    LeaveReviewRequest,
    VisitorCheckOutRequest,
    VisitorCreate,
)
from app.services.operations_service import OperationsService


async def _setup_service_fixtures(
    session: AsyncSession,
) -> tuple[
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
]:
    """Helper setting up hostels, warden assignments, and students."""
    uid = uuid.uuid4().hex[:6]

    # Hostel 1
    h1 = Hostel(name=f"Hostel 1 {uid}", code=f"H1-{uid}", gender_type=GenderType.MIXED)
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
        monthly_rent=Decimal("2000.00"),
        status=RoomStatus.AVAILABLE,
    )
    session.add(r1)
    await session.flush()

    bed1 = Bed(room_id=r1.id, label="101-A")
    session.add(bed1)
    await session.flush()

    # Hostel 2
    h2 = Hostel(name=f"Hostel 2 {uid}", code=f"H2-{uid}", gender_type=GenderType.MIXED)
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
        monthly_rent=Decimal("2000.00"),
        status=RoomStatus.AVAILABLE,
    )
    session.add(r2)
    await session.flush()

    bed2 = Bed(room_id=r2.id, label="201-A")
    session.add(bed2)
    await session.flush()

    # Admin
    admin = User(
        email=f"admin_{uid}@example.com",
        full_name="Admin",
        hashed_password="hash",
        role=UserRole.ADMIN,
    )
    # Warden assigned to H1 only
    warden = User(
        email=f"warden_{uid}@example.com",
        full_name="Warden",
        hashed_password="hash",
        role=UserRole.WARDEN,
    )
    # Student 1 in H1
    stu_user1 = User(
        email=f"stu1_{uid}@example.com",
        full_name="Student One",
        hashed_password="hash",
        role=UserRole.STUDENT,
    )
    # Student 2 in H2
    stu_user2 = User(
        email=f"stu2_{uid}@example.com",
        full_name="Student Two",
        hashed_password="hash",
        role=UserRole.STUDENT,
    )
    session.add_all([admin, warden, stu_user1, stu_user2])
    await session.flush()

    # Assign warden to H1
    assign = WardenAssignment(user_id=warden.id, hostel_id=h1.id)
    session.add(assign)
    await session.flush()

    prof1 = StudentProfile(
        user_id=stu_user1.id,
        student_no=f"STU1-{uid}",
        gender=GenderType.MALE,
        department="CS",
        year=1,
        guardian_name="Guardian",
        guardian_phone="+111",
        emergency_contact="+222",
    )
    prof2 = StudentProfile(
        user_id=stu_user2.id,
        student_no=f"STU2-{uid}",
        gender=GenderType.FEMALE,
        department="EE",
        year=1,
        guardian_name="Guardian",
        guardian_phone="+333",
        emergency_contact="+444",
    )
    session.add_all([prof1, prof2])
    await session.flush()

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
    await session.flush()

    return h1, h2, admin, warden, stu_user1, prof1, alloc1, stu_user2, prof2, alloc2


# =============================================================================
# Attendance Tests
# =============================================================================


@pytest.mark.asyncio
async def test_attendance_check_in_and_out_lifecycle(db_session: AsyncSession) -> None:
    """Verify check-in and check-out sequential state transitions."""
    _h1, _h2, admin, _warden, _u1, prof1, _a1, _u2, _p2, _a2 = await _setup_service_fixtures(
        db_session
    )
    service = OperationsService(db_session)

    # Cannot check out before check in
    with pytest.raises(ConflictError) as exc_co:
        await service.check_out(AttendanceActionRequest(student_id=prof1.id), current_user=admin)
    assert exc_co.value.code == "ALREADY_CHECKED_OUT"

    # Valid check in
    in_log = await service.check_in(
        AttendanceActionRequest(student_id=prof1.id, remarks="First entry"),
        current_user=admin,
    )
    assert in_log.type == AttendanceType.CHECK_IN
    assert in_log.remarks == "First entry"

    # Double check-in blocked
    with pytest.raises(ConflictError) as exc_ci:
        await service.check_in(AttendanceActionRequest(student_id=prof1.id), current_user=admin)
    assert exc_ci.value.code == "ALREADY_CHECKED_IN"

    # Valid check out
    out_log = await service.check_out(
        AttendanceActionRequest(student_id=prof1.id, remarks="Leaving"),
        current_user=admin,
    )
    assert out_log.type == AttendanceType.CHECK_OUT

    # Double check out blocked
    with pytest.raises(ConflictError):
        await service.check_out(AttendanceActionRequest(student_id=prof1.id), current_user=admin)


@pytest.mark.asyncio
async def test_attendance_no_active_allocation_and_warden_scoping(
    db_session: AsyncSession,
) -> None:
    """Verify check-in blocks students without allocation and enforces warden scoping."""
    _h1, _h2, _admin, warden, _u1, prof1, _a1, _u2, prof2, alloc2 = await _setup_service_fixtures(
        db_session
    )
    service = OperationsService(db_session)

    # Student 2 is in H2; warden is only assigned to H1 -> Forbidden
    with pytest.raises(ForbiddenError):
        await service.check_in(AttendanceActionRequest(student_id=prof2.id), current_user=warden)

    # Student 1 in H1 -> Warden succeeds
    log = await service.check_in(AttendanceActionRequest(student_id=prof1.id), current_user=warden)
    assert log.student_id == prof1.id

    # End allocation 2 -> Student 2 has no active allocation
    alloc2.status = AllocationStatus.ENDED
    await db_session.flush()

    admin = User(email="ad@ex.com", full_name="A", hashed_password="h", role=UserRole.ADMIN)
    db_session.add(admin)
    await db_session.flush()

    with pytest.raises(BusinessRuleError) as exc_alloc:
        await service.check_in(AttendanceActionRequest(student_id=prof2.id), current_user=admin)
    assert exc_alloc.value.code == "NO_ACTIVE_ALLOCATION"


@pytest.mark.asyncio
async def test_attendance_present_students_and_my_attendance(
    db_session: AsyncSession,
) -> None:
    """Verify present students list and student self-service attendance."""
    h1, _h2, admin, warden, u1, prof1, _a1, _u2, prof2, _a2 = await _setup_service_fixtures(
        db_session
    )
    service = OperationsService(db_session)

    # Check in student 1 (in H1) and student 2 (in H2)
    await service.check_in(AttendanceActionRequest(student_id=prof1.id), current_user=admin)
    await service.check_in(AttendanceActionRequest(student_id=prof2.id), current_user=admin)

    # Admin sees both
    present_admin = await service.get_present_students(current_user=admin)
    assert len(present_admin) == 2

    # Warden of H1 sees only student 1
    present_warden = await service.get_present_students(current_user=warden)
    assert len(present_warden) == 1
    assert present_warden[0].student_id == prof1.id

    # Filter by H1 explicitly
    present_h1 = await service.get_present_students(current_user=admin, hostel_id=h1.id)
    assert len(present_h1) == 1
    assert present_h1[0].student_id == prof1.id

    # Student 1 fetches own attendance
    params = PaginationParams(page=1, size=10)
    my_logs, total = await service.get_my_attendance(current_user=u1, params=params)
    assert total == 1
    assert my_logs[0].student_id == prof1.id


# =============================================================================
# Leave Request Tests
# =============================================================================


@pytest.mark.asyncio
async def test_leave_creation_rules_and_overlapping(db_session: AsyncSession) -> None:
    """Verify leave request validation, past dates rejection, and overlapping conflict."""
    _h1, _h2, _admin, warden, u1, prof1, _a1, _u2, prof2, _a2 = await _setup_service_fixtures(
        db_session
    )
    service = OperationsService(db_session)

    today = date(2026, 12, 1)

    # 1. Past date rejected
    with pytest.raises(BusinessRuleError) as exc_past:
        await service.create_leave_request(
            LeaveRequestCreate(
                from_date=date(2026, 11, 20),
                to_date=date(2026, 11, 25),
                reason="Past leave",
            ),
            current_user=u1,
            current_date=today,
        )
    assert exc_past.value.code == "PAST_LEAVE_DATE"

    # 2. Student self creation
    req1 = await service.create_leave_request(
        LeaveRequestCreate(
            from_date=date(2026, 12, 5),
            to_date=date(2026, 12, 10),
            reason="Going home",
        ),
        current_user=u1,
        current_date=today,
    )
    assert req1.status == LeaveStatus.PENDING
    assert req1.student_id == prof1.id

    # 3. Overlapping leave rejected
    with pytest.raises(ConflictError) as exc_ov:
        await service.create_leave_request(
            LeaveRequestCreate(
                from_date=date(2026, 12, 8),
                to_date=date(2026, 12, 12),
                reason="Another trip",
            ),
            current_user=u1,
            current_date=today,
        )
    assert exc_ov.value.code == "OVERLAPPING_LEAVE_REQUEST"

    # 4. Warden cannot create leave for student in another hostel
    with pytest.raises(ForbiddenError):
        await service.create_leave_request(
            LeaveRequestCreate(
                student_id=prof2.id,
                from_date=date(2026, 12, 5),
                to_date=date(2026, 12, 10),
                reason="Warden create",
            ),
            current_user=warden,
            current_date=today,
        )


@pytest.mark.asyncio
async def test_leave_approval_rejection_cancel_workflow(db_session: AsyncSession) -> None:
    """Verify leave state machine: approve, reject, cancel, and invalid transitions."""
    _h1, _h2, admin, warden, u1, _prof1, _a1, u2, _p2, _a2 = await _setup_service_fixtures(
        db_session
    )
    service = OperationsService(db_session)
    today = date(2026, 12, 1)

    # Create leave 1
    leave1 = await service.create_leave_request(
        LeaveRequestCreate(
            from_date=date(2026, 12, 5),
            to_date=date(2026, 12, 10),
            reason="Trip 1",
        ),
        current_user=u1,
        current_date=today,
    )

    # Approve by warden (assigned to H1)
    approved = await service.approve_leave_request(
        leave1.id,
        current_user=warden,
        review=LeaveReviewRequest(review_notes="Permitted"),
    )
    assert approved.status == LeaveStatus.APPROVED
    assert approved.reviewed_by == warden.id
    assert approved.review_notes == "Permitted"

    # Cannot approve again
    with pytest.raises(ConflictError) as exc_app:
        await service.approve_leave_request(leave1.id, current_user=admin)
    assert exc_app.value.code == "LEAVE_ALREADY_PROCESSED"

    # Cannot reject approved leave
    with pytest.raises(ConflictError):
        await service.reject_leave_request(leave1.id, current_user=admin)

    # Create leave 2 for student 1 (non-overlapping)
    leave2 = await service.create_leave_request(
        LeaveRequestCreate(
            from_date=date(2026, 12, 15),
            to_date=date(2026, 12, 20),
            reason="Trip 2",
        ),
        current_user=u1,
        current_date=today,
    )

    # Reject leave 2
    rejected = await service.reject_leave_request(
        leave2.id,
        current_user=admin,
        review=LeaveReviewRequest(review_notes="Exams coming up"),
    )
    assert rejected.status == LeaveStatus.REJECTED

    # Create leave 3 for student 1
    leave3 = await service.create_leave_request(
        LeaveRequestCreate(
            from_date=date(2026, 12, 22),
            to_date=date(2026, 12, 25),
            reason="Trip 3",
        ),
        current_user=u1,
        current_date=today,
    )

    # Another student (u2) cannot cancel leave 3
    with pytest.raises(ForbiddenError):
        await service.cancel_leave_request(leave3.id, current_user=u2)

    # Student 1 cancels own leave 3
    cancelled = await service.cancel_leave_request(leave3.id, current_user=u1)
    assert cancelled.status == LeaveStatus.CANCELLED

    # Cannot cancel already cancelled leave
    with pytest.raises(ConflictError):
        await service.cancel_leave_request(leave3.id, current_user=u1)


# =============================================================================
# Visitor Tests
# =============================================================================


@pytest.mark.asyncio
async def test_visiting_hours_and_visitor_checkin_checkout(
    db_session: AsyncSession,
) -> None:
    """Verify visiting hours enforcement and visitor lifecycle."""
    _h1, _h2, admin, warden, _u1, prof1, _a1, _u2, prof2, _a2 = await _setup_service_fixtures(
        db_session
    )
    service = OperationsService(db_session)

    # Outside visiting hours (e.g. 23:00)
    late_time = datetime(2026, 11, 22, 23, 0, tzinfo=UTC)
    with pytest.raises(BusinessRuleError) as exc_hours:
        await service.check_in_visitor(
            VisitorCreate(
                student_id=prof1.id,
                name="John Sr.",
                phone="+987654321",
                relation="Father",
            ),
            current_user=admin,
            check_in_time=late_time,
        )
    assert exc_hours.value.code == "VISITING_HOURS_CLOSED"

    # Within visiting hours (14:00)
    valid_time = datetime(2026, 11, 22, 14, 0, tzinfo=UTC)
    vis = await service.check_in_visitor(
        VisitorCreate(
            student_id=prof1.id,
            name="John Sr.",
            phone="+987654321",
            relation="Father",
            remarks="Family visit",
        ),
        current_user=admin,
        check_in_time=valid_time,
    )
    assert vis.id is not None
    assert vis.is_active is True

    # Same visitor cannot check in again while active inside
    with pytest.raises(ConflictError) as exc_active:
        await service.check_in_visitor(
            VisitorCreate(
                student_id=prof1.id,
                name="john sr.",  # case insensitive
                phone="+987654321",
                relation="Father",
            ),
            current_user=admin,
            check_in_time=valid_time,
        )
    assert exc_active.value.code == "VISITOR_ALREADY_CHECKED_IN"

    # Warden cannot manage visitor for student in unassigned hostel H2
    with pytest.raises(ForbiddenError):
        await service.check_in_visitor(
            VisitorCreate(
                student_id=prof2.id,
                name="Jane",
                phone="+111222",
                relation="Mother",
            ),
            current_user=warden,
            check_in_time=valid_time,
        )

    # Check out visitor
    out_time = datetime(2026, 11, 22, 15, 30, tzinfo=UTC)
    checked_out = await service.check_out_visitor(
        vis.id,
        current_user=admin,
        data=VisitorCheckOutRequest(remarks="Left on time"),
        check_out_time=out_time,
    )
    assert checked_out.is_active is False
    assert checked_out.check_out_at is not None
    actual_co = (
        checked_out.check_out_at
        if checked_out.check_out_at.tzinfo
        else checked_out.check_out_at.replace(tzinfo=UTC)
    )
    assert actual_co == out_time

    # Cannot check out again
    with pytest.raises(ConflictError) as exc_dup_co:
        await service.check_out_visitor(vis.id, current_user=admin)
    assert exc_dup_co.value.code == "VISITOR_ALREADY_CHECKED_OUT"

    # Now the visitor can check in again after checkout
    vis2 = await service.check_in_visitor(
        VisitorCreate(
            student_id=prof1.id,
            name="John Sr.",
            phone="+987654321",
            relation="Father",
        ),
        current_user=admin,
        check_in_time=datetime(2026, 11, 22, 16, 0, tzinfo=UTC),
    )
    assert vis2.id != vis.id
    assert vis2.is_active is True


@pytest.mark.asyncio
async def test_operations_service_edge_cases_and_scoping(
    db_session: AsyncSession,
) -> None:
    """Verify various error branches, lookups, and warden scoping across service operations."""
    h1, h2, admin, warden, u1, prof1, _a1, u2, _prof2, _a2 = await _setup_service_fixtures(
        db_session
    )
    service = OperationsService(db_session)
    dummy_id = uuid.uuid4()

    # 1. Nonexistent student on check-in / check-out
    with pytest.raises(NotFoundError):
        await service.check_in(AttendanceActionRequest(student_id=dummy_id), current_user=admin)
    with pytest.raises(NotFoundError):
        await service.check_out(AttendanceActionRequest(student_id=dummy_id), current_user=admin)

    # 2. Student without student profile in get_my_attendance
    fake_user = User(
        email="fake@ex.com",
        full_name="Fake",
        hashed_password="h",
        role=UserRole.STUDENT,
    )
    db_session.add(fake_user)
    await db_session.flush()

    params = PaginationParams(page=1, size=10)
    with pytest.raises(NotFoundError):
        await service.get_my_attendance(current_user=fake_user, params=params)

    # 3. Present students warden scoping: unassigned hostel raises Forbidden
    with pytest.raises(ForbiddenError):
        await service.get_present_students(current_user=warden, hostel_id=h2.id)

    # 4. List attendance with warden scoping on assigned vs unassigned hostel
    with pytest.raises(ForbiddenError):
        await service.list_attendance(params=params, current_user=warden, hostel_id=h2.id)
    logs_w, _ = await service.list_attendance(params=params, current_user=warden, hostel_id=h1.id)
    assert isinstance(logs_w, list)

    # 5. Create leave admin edge cases: missing student_id, nonexistent student_id
    today = date(2026, 12, 1)
    with pytest.raises(ValidationAppError):
        await service.create_leave_request(
            LeaveRequestCreate(
                from_date=date(2026, 12, 5),
                to_date=date(2026, 12, 10),
                reason="Trip",
            ),
            current_user=admin,
            current_date=today,
        )

    with pytest.raises(NotFoundError):
        await service.create_leave_request(
            LeaveRequestCreate(
                student_id=dummy_id,
                from_date=date(2026, 12, 5),
                to_date=date(2026, 12, 10),
                reason="Trip",
            ),
            current_user=admin,
            current_date=today,
        )

    # 6. Leave approve / reject nonexistent leave
    with pytest.raises(NotFoundError):
        await service.approve_leave_request(dummy_id, current_user=admin)
    with pytest.raises(NotFoundError):
        await service.reject_leave_request(dummy_id, current_user=admin)
    with pytest.raises(NotFoundError):
        await service.cancel_leave_request(dummy_id, current_user=admin)
    with pytest.raises(NotFoundError):
        await service.get_leave_by_id(dummy_id, current_user=admin)

    # 7. Get leave by id: student forbidden to view another student's leave
    leave = await service.create_leave_request(
        LeaveRequestCreate(
            from_date=date(2026, 12, 5),
            to_date=date(2026, 12, 10),
            reason="Trip S1",
        ),
        current_user=u1,
        current_date=today,
    )
    with pytest.raises(ForbiddenError):
        await service.get_leave_by_id(leave.id, current_user=u2)

    fetched_by_w = await service.get_leave_by_id(leave.id, current_user=warden)
    assert fetched_by_w.id == leave.id

    # 8. List leaves with warden scoping
    with pytest.raises(ForbiddenError):
        await service.list_leaves(params=params, current_user=warden, hostel_id=h2.id)
    leaves_h1, _ = await service.list_leaves(params=params, current_user=warden, hostel_id=h1.id)
    assert isinstance(leaves_h1, list)

    # 9. Get my leaves profile not found
    with pytest.raises(NotFoundError):
        await service.get_my_leaves(current_user=fake_user, params=params)

    # 10. Visitor check in nonexistent student
    valid_time = datetime(2026, 11, 22, 14, 0, tzinfo=UTC)
    with pytest.raises(NotFoundError):
        await service.check_in_visitor(
            VisitorCreate(
                student_id=dummy_id,
                name="Vis",
                phone="+123",
                relation="Friend",
            ),
            current_user=admin,
            check_in_time=valid_time,
        )

    # 11. Visitor checkout nonexistent visitor
    with pytest.raises(NotFoundError):
        await service.check_out_visitor(dummy_id, current_user=admin)
    with pytest.raises(NotFoundError):
        await service.get_visitor_by_id(dummy_id, current_user=admin)

    # 12. Visitor get by id: student forbidden to view another's visitor
    vis = await service.check_in_visitor(
        VisitorCreate(
            student_id=prof1.id,
            name="Vis One",
            phone="+987",
            relation="Cousin",
        ),
        current_user=admin,
        check_in_time=valid_time,
    )
    with pytest.raises(ForbiddenError):
        await service.get_visitor_by_id(vis.id, current_user=u2)
    fetched_vis = await service.get_visitor_by_id(vis.id, current_user=u1)
    assert fetched_vis.id == vis.id

    # 13. List visitors warden scoping
    with pytest.raises(ForbiddenError):
        await service.list_visitors(params=params, current_user=warden, hostel_id=h2.id)
    vis_w, _ = await service.list_visitors(params=params, current_user=warden, hostel_id=h1.id)
    assert isinstance(vis_w, list)

    # 14. Get my visitors profile not found
    with pytest.raises(NotFoundError):
        await service.get_my_visitors(current_user=fake_user, params=params)
