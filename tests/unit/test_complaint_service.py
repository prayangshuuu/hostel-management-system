"""Unit tests for ComplaintService business rules, transitions, and scoping."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleError, ForbiddenError, NotFoundError
from app.models.allocation import Allocation, AllocationStatus
from app.models.complaint import (
    ComplaintCategory,
    ComplaintPriority,
    ComplaintStatus,
)
from app.models.hostel import Block, GenderType, Hostel, WardenAssignment
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.schemas.common import PaginationParams
from app.schemas.complaint import (
    ComplaintAssignRequest,
    ComplaintCommentCreate,
    ComplaintCreate,
    ComplaintStatusUpdateRequest,
)
from app.services.complaint_service import ComplaintService


@pytest.fixture
async def setup_env(db_session: AsyncSession) -> dict[str, object]:
    """Provide infrastructure, wardens, students, and allocations for complaint service tests."""
    uid = uuid4().hex[:6]

    # Hostels
    h1 = Hostel(name=f"Hostel One {uid}", code=f"H1-{uid}", gender_type=GenderType.MIXED)
    h2 = Hostel(name=f"Hostel Two {uid}", code=f"H2-{uid}", gender_type=GenderType.MIXED)
    db_session.add_all([h1, h2])
    await db_session.flush()

    b1 = Block(hostel_id=h1.id, name="Block 1", floor_count=1)
    b2 = Block(hostel_id=h2.id, name="Block 2", floor_count=1)
    db_session.add_all([b1, b2])
    await db_session.flush()

    r1 = Room(
        block_id=b1.id,
        number="101",
        floor=1,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("2000.00"),
        status=RoomStatus.AVAILABLE,
    )
    r2 = Room(
        block_id=b2.id,
        number="201",
        floor=1,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("2000.00"),
        status=RoomStatus.AVAILABLE,
    )
    db_session.add_all([r1, r2])
    await db_session.flush()

    bed1 = Bed(room_id=r1.id, label="101-A")
    bed2 = Bed(room_id=r2.id, label="201-A")
    db_session.add_all([bed1, bed2])
    await db_session.flush()

    # Users
    admin = User(
        id=uuid4(),
        email=f"admin_{uid}@example.com",
        full_name="Admin Boss",
        hashed_password="hash",
        role=UserRole.ADMIN,
        is_active=True,
    )
    warden_h1 = User(
        id=uuid4(),
        email=f"warden1_{uid}@example.com",
        full_name="Warden Alpha",
        hashed_password="hash",
        role=UserRole.WARDEN,
        is_active=True,
    )
    unassigned_warden = User(
        id=uuid4(),
        email=f"unassigned_{uid}@example.com",
        full_name="Warden Beta",
        hashed_password="hash",
        role=UserRole.WARDEN,
        is_active=True,
    )
    stu1_user = User(
        id=uuid4(),
        email=f"stu1_{uid}@example.com",
        full_name="Student One",
        hashed_password="hash",
        role=UserRole.STUDENT,
        is_active=True,
    )
    stu2_user = User(
        id=uuid4(),
        email=f"stu2_{uid}@example.com",
        full_name="Student Two",
        hashed_password="hash",
        role=UserRole.STUDENT,
        is_active=True,
    )
    unallocated_stu_user = User(
        id=uuid4(),
        email=f"no_alloc_{uid}@example.com",
        full_name="Homeless Student",
        hashed_password="hash",
        role=UserRole.STUDENT,
        is_active=True,
    )
    inactive_user = User(
        id=uuid4(),
        email=f"inactive_{uid}@example.com",
        full_name="Inactive Tech",
        hashed_password="hash",
        role=UserRole.WARDEN,
        is_active=False,
    )
    db_session.add_all(
        [
            admin,
            warden_h1,
            unassigned_warden,
            stu1_user,
            stu2_user,
            unallocated_stu_user,
            inactive_user,
        ]
    )
    await db_session.flush()

    # Warden assignment to H1
    wa1 = WardenAssignment(user_id=warden_h1.id, hostel_id=h1.id)
    db_session.add(wa1)
    await db_session.flush()

    # Student profiles
    p1 = StudentProfile(
        id=uuid4(),
        user_id=stu1_user.id,
        student_no=f"STU1-{uid}",
        gender=GenderType.MALE,
        department="CS",
        year=1,
        guardian_name="G1",
        guardian_phone="123",
        emergency_contact="456",
    )
    p2 = StudentProfile(
        id=uuid4(),
        user_id=stu2_user.id,
        student_no=f"STU2-{uid}",
        gender=GenderType.FEMALE,
        department="IT",
        year=2,
        guardian_name="G2",
        guardian_phone="789",
        emergency_contact="012",
    )
    p_unalloc = StudentProfile(
        id=uuid4(),
        user_id=unallocated_stu_user.id,
        student_no=f"STUN-{uid}",
        gender=GenderType.MALE,
        department="Physics",
        year=1,
        guardian_name="GN",
        guardian_phone="999",
        emergency_contact="888",
    )
    db_session.add_all([p1, p2, p_unalloc])
    await db_session.flush()

    # Allocations
    alloc1 = Allocation(
        student_id=p1.id,
        bed_id=bed1.id,
        start_date=date(2026, 1, 1),
        status=AllocationStatus.ACTIVE,
    )
    alloc2 = Allocation(
        student_id=p2.id,
        bed_id=bed2.id,
        start_date=date(2026, 1, 1),
        status=AllocationStatus.ACTIVE,
    )
    db_session.add_all([alloc1, alloc2])
    await db_session.flush()

    return {
        "h1": h1,
        "h2": h2,
        "r1": r1,
        "r2": r2,
        "admin": admin,
        "warden_h1": warden_h1,
        "unassigned_warden": unassigned_warden,
        "stu1_user": stu1_user,
        "stu2_user": stu2_user,
        "unallocated_stu_user": unallocated_stu_user,
        "inactive_user": inactive_user,
        "p1": p1,
        "p2": p2,
        "p_unalloc": p_unalloc,
    }


@pytest.mark.asyncio
async def test_create_complaint_workflow_and_errors(
    db_session: AsyncSession, setup_env: dict[str, object]
) -> None:
    """Test complaint creation rules, auto-room binding, and allocation check."""
    service = ComplaintService(db_session)
    stu1_user = setup_env["stu1_user"]
    assert isinstance(stu1_user, User)
    unallocated_stu_user = setup_env["unallocated_stu_user"]
    assert isinstance(unallocated_stu_user, User)
    r1 = setup_env["r1"]
    assert isinstance(r1, Room)

    # 1. Non-existent profile fails
    fake_user = User(
        id=uuid4(),
        email="nobody@example.com",
        full_name="Nobody",
        hashed_password="hash",
        role=UserRole.STUDENT,
    )
    with pytest.raises(NotFoundError) as exc:
        await service.create_complaint(
            ComplaintCreate(
                title="Tap broken",
                description="Water leaking",
                category=ComplaintCategory.PLUMBING,
            ),
            fake_user,
        )
    assert exc.value.code == "STUDENT_NOT_FOUND"

    # 2. Student without active allocation fails with NO_ACTIVE_ALLOCATION
    with pytest.raises(BusinessRuleError) as exc_alloc:
        await service.create_complaint(
            ComplaintCreate(
                title="Window stuck",
                description="Cannot open window",
                category=ComplaintCategory.FURNITURE,
            ),
            unallocated_stu_user,
        )
    assert exc_alloc.value.code == "NO_ACTIVE_ALLOCATION"
    assert exc_alloc.value.status_code == 400

    # 3. Successful complaint creation with auto-filled room_id
    data = ComplaintCreate(
        title="Ceiling fan issue",
        description="Fan not rotating smoothly",
        category=ComplaintCategory.ELECTRICAL,
        priority=ComplaintPriority.HIGH,
    )
    complaint = await service.create_complaint(data, stu1_user)
    assert complaint.id is not None
    assert complaint.room_id == r1.id
    assert complaint.status == ComplaintStatus.OPEN
    assert complaint.priority == ComplaintPriority.HIGH


@pytest.mark.asyncio
async def test_list_complaints_scoping(
    db_session: AsyncSession, setup_env: dict[str, object]
) -> None:
    """Test role scoping for student, warden, and admin on complaint listing."""
    service = ComplaintService(db_session)
    stu1_user = setup_env["stu1_user"]
    assert isinstance(stu1_user, User)
    stu2_user = setup_env["stu2_user"]
    assert isinstance(stu2_user, User)
    warden_h1 = setup_env["warden_h1"]
    assert isinstance(warden_h1, User)
    unassigned_warden = setup_env["unassigned_warden"]
    assert isinstance(unassigned_warden, User)
    admin = setup_env["admin"]
    assert isinstance(admin, User)
    h2 = setup_env["h2"]
    assert isinstance(h2, Hostel)

    # File complaints for stu1 (Hostel 1) and stu2 (Hostel 2)
    c1 = await service.create_complaint(
        ComplaintCreate(
            title="Fan broken",
            description="Loud noise",
            category=ComplaintCategory.ELECTRICAL,
        ),
        stu1_user,
    )
    await service.create_complaint(
        ComplaintCreate(
            title="Desk broken",
            description="Leg is loose",
            category=ComplaintCategory.FURNITURE,
        ),
        stu2_user,
    )

    params = PaginationParams(page=1, size=20)

    # Student 1 only sees c1
    items, total = await service.list_complaints(params, current_user=stu1_user)
    assert total == 1
    assert items[0].id == c1.id

    # Warden H1 only sees c1 (hostel 1), not c2 (hostel 2)
    items, total = await service.list_complaints(params, current_user=warden_h1)
    assert total == 1
    assert items[0].id == c1.id

    # Warden H1 requesting unassigned hostel 2 raises ForbiddenError
    with pytest.raises(ForbiddenError):
        await service.list_complaints(params, current_user=warden_h1, hostel_id=h2.id)

    # Unassigned warden gets 0
    items, total = await service.list_complaints(params, current_user=unassigned_warden)
    assert items == []
    assert total == 0

    # Admin sees both c1 and c2
    items, total = await service.list_complaints(params, current_user=admin)
    assert total == 2


@pytest.mark.asyncio
async def test_get_complaint_and_internal_comments_visibility(
    db_session: AsyncSession, setup_env: dict[str, object]
) -> None:
    """Test get_complaint access scoping and hiding internal comments from students."""
    service = ComplaintService(db_session)
    stu1_user = setup_env["stu1_user"]
    assert isinstance(stu1_user, User)
    stu2_user = setup_env["stu2_user"]
    assert isinstance(stu2_user, User)
    warden_h1 = setup_env["warden_h1"]
    assert isinstance(warden_h1, User)

    complaint = await service.create_complaint(
        ComplaintCreate(
            title="Bathroom leak",
            description="Dripping tap",
            category=ComplaintCategory.PLUMBING,
        ),
        stu1_user,
    )

    # Add public and internal comments
    await service.add_comment(
        complaint.id,
        ComplaintCommentCreate(body="When can this be fixed?", is_internal=False),
        stu1_user,
    )
    await service.add_comment(
        complaint.id,
        ComplaintCommentCreate(
            body="Internal: Plumber ordered replacement valve.",
            is_internal=True,
        ),
        warden_h1,
    )

    # Non-existent complaint
    with pytest.raises(NotFoundError):
        await service.get_complaint(uuid4(), stu1_user)

    # Foreign student cannot view
    with pytest.raises(ForbiddenError):
        await service.get_complaint(complaint.id, stu2_user)

    # Owner student views complaint: internal comment is hidden!
    detail_stu = await service.get_complaint(complaint.id, stu1_user)
    assert len(detail_stu.comments) == 1
    assert detail_stu.comments[0].body == "When can this be fixed?"
    assert detail_stu.comments[0].is_internal is False

    # Warden views complaint: all comments visible
    detail_warden = await service.get_complaint(complaint.id, warden_h1)
    assert len(detail_warden.comments) == 2


@pytest.mark.asyncio
async def test_assign_complaint_workflow(
    db_session: AsyncSession, setup_env: dict[str, object]
) -> None:
    """Test assigning complaint, transitioning OPEN to IN_PROGRESS, and validation."""
    service = ComplaintService(db_session)
    stu1_user = setup_env["stu1_user"]
    assert isinstance(stu1_user, User)
    warden_h1 = setup_env["warden_h1"]
    assert isinstance(warden_h1, User)
    admin = setup_env["admin"]
    assert isinstance(admin, User)
    inactive_user = setup_env["inactive_user"]
    assert isinstance(inactive_user, User)

    complaint = await service.create_complaint(
        ComplaintCreate(
            title="Broken chair",
            description="Armrest broken",
            category=ComplaintCategory.FURNITURE,
        ),
        stu1_user,
    )
    assert complaint.status == ComplaintStatus.OPEN

    # Inactive user raises NotFoundError
    with pytest.raises(NotFoundError) as exc_inactive:
        await service.assign_complaint(
            complaint.id,
            ComplaintAssignRequest(assigned_to=inactive_user.id),
            warden_h1,
        )
    assert exc_inactive.value.code == "USER_NOT_FOUND"

    # Non-existent user raises NotFoundError
    with pytest.raises(NotFoundError):
        await service.assign_complaint(
            complaint.id,
            ComplaintAssignRequest(assigned_to=uuid4()),
            warden_h1,
        )

    # Assigning to warden transitions status to IN_PROGRESS
    assigned = await service.assign_complaint(
        complaint.id,
        ComplaintAssignRequest(assigned_to=warden_h1.id),
        admin,
    )
    assert assigned.assigned_to == warden_h1.id
    assert assigned.status == ComplaintStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_status_machine_and_reopen_window(
    db_session: AsyncSession, setup_env: dict[str, object]
) -> None:
    """Test full status state machine, 7-day reopen window, and invalid transitions."""
    service = ComplaintService(db_session)
    stu1_user = setup_env["stu1_user"]
    assert isinstance(stu1_user, User)
    warden_h1 = setup_env["warden_h1"]
    assert isinstance(warden_h1, User)
    r1 = setup_env["r1"]
    assert isinstance(r1, Room)

    complaint = await service.create_complaint(
        ComplaintCreate(
            title="Electric shock from switch",
            description="Dangerous spark",
            category=ComplaintCategory.ELECTRICAL,
            priority=ComplaintPriority.URGENT,
        ),
        stu1_user,
    )
    assert complaint.status == ComplaintStatus.OPEN

    # Invalid transition: OPEN -> RESOLVED is disallowed
    with pytest.raises(BusinessRuleError) as exc_trans:
        await service.update_status(
            complaint.id,
            ComplaintStatusUpdateRequest(status=ComplaintStatus.RESOLVED),
            warden_h1,
        )
    assert exc_trans.value.code == "INVALID_STATUS_TRANSITION"

    # Transition: OPEN -> IN_PROGRESS with room maintenance flag
    in_prog = await service.update_status(
        complaint.id,
        ComplaintStatusUpdateRequest(
            status=ComplaintStatus.IN_PROGRESS,
            mark_room_maintenance=True,
        ),
        warden_h1,
    )
    assert in_prog.status == ComplaintStatus.IN_PROGRESS
    assert r1.status == RoomStatus.MAINTENANCE

    # Transition: IN_PROGRESS -> RESOLVED (sets resolved_at and notes comment)
    resolved = await service.update_status(
        complaint.id,
        ComplaintStatusUpdateRequest(
            status=ComplaintStatus.RESOLVED,
            resolution_notes="Electrician replaced the faulty switchboard.",
        ),
        warden_h1,
    )
    assert resolved.status == ComplaintStatus.RESOLVED
    assert resolved.resolved_at is not None

    # Check resolution_time_hours exposed
    detail = await service.get_complaint(complaint.id, warden_h1)
    assert detail.resolution_time_hours is not None
    assert detail.resolution_time_hours >= 0.0
    # Comment was created for resolution notes
    assert any(c.body == "Electrician replaced the faulty switchboard." for c in detail.comments)

    # Student cannot transition RESOLVED to IN_PROGRESS
    with pytest.raises(ForbiddenError):
        await service.update_status(
            complaint.id,
            ComplaintStatusUpdateRequest(status=ComplaintStatus.IN_PROGRESS),
            stu1_user,
        )

    # Student cannot set mark_room_maintenance
    with pytest.raises(ForbiddenError):
        await service.update_status(
            complaint.id,
            ComplaintStatusUpdateRequest(
                status=ComplaintStatus.OPEN,
                mark_room_maintenance=True,
            ),
            stu1_user,
        )

    # Student can reopen within 7 days: RESOLVED -> OPEN
    reopened = await service.update_status(
        complaint.id,
        ComplaintStatusUpdateRequest(
            status=ComplaintStatus.OPEN,
            resolution_notes="Switch is still sparking intermittently.",
        ),
        stu1_user,
    )
    assert reopened.status == ComplaintStatus.OPEN
    assert reopened.resolved_at is None

    # Re-resolve it
    await service.update_status(
        complaint.id,
        ComplaintStatusUpdateRequest(status=ComplaintStatus.IN_PROGRESS),
        warden_h1,
    )
    await service.update_status(
        complaint.id,
        ComplaintStatusUpdateRequest(status=ComplaintStatus.RESOLVED),
        warden_h1,
    )

    # Simulate resolved_at expired (> 7 days ago)
    complaint.resolved_at = datetime.now(UTC) - timedelta(days=8)
    await db_session.flush()

    with pytest.raises(BusinessRuleError) as exc_expired:
        await service.update_status(
            complaint.id,
            ComplaintStatusUpdateRequest(status=ComplaintStatus.OPEN),
            stu1_user,
        )
    assert exc_expired.value.code == "REOPEN_WINDOW_EXPIRED"

    # Close the complaint: RESOLVED -> CLOSED
    closed = await service.update_status(
        complaint.id,
        ComplaintStatusUpdateRequest(status=ComplaintStatus.CLOSED),
        warden_h1,
    )
    assert closed.status == ComplaintStatus.CLOSED

    # Terminal state CLOSED cannot transition anywhere
    with pytest.raises(BusinessRuleError):
        await service.update_status(
            complaint.id,
            ComplaintStatusUpdateRequest(status=ComplaintStatus.OPEN),
            warden_h1,
        )
