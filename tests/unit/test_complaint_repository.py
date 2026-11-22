"""Unit tests for ComplaintRepository and ComplaintCommentRepository."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.allocation import Allocation, AllocationStatus
from app.models.complaint import (
    Complaint,
    ComplaintCategory,
    ComplaintComment,
    ComplaintPriority,
    ComplaintStatus,
)
from app.models.hostel import Block, GenderType, Hostel
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.repositories.complaint_repository import (
    ComplaintCommentRepository,
    ComplaintRepository,
)
from app.schemas.common import PaginationParams


@pytest.mark.asyncio
async def test_complaint_and_comment_repository_crud(db_session: AsyncSession) -> None:
    """Test complaint creation, reading with relationships, and comments listing."""
    uid = uuid4().hex[:6]

    # Infrastructure
    hostel = Hostel(name=f"Hostel {uid}", code=f"H-{uid}", gender_type=GenderType.MIXED)
    db_session.add(hostel)
    await db_session.flush()

    block = Block(hostel_id=hostel.id, name="Block A", floor_count=2)
    db_session.add(block)
    await db_session.flush()

    room = Room(
        block_id=block.id,
        number="101",
        floor=1,
        room_type=RoomType.DOUBLE,
        capacity=2,
        monthly_rent=Decimal("2000.00"),
        status=RoomStatus.AVAILABLE,
    )
    db_session.add(room)
    await db_session.flush()

    bed = Bed(room_id=room.id, label="A")
    db_session.add(bed)
    await db_session.flush()

    # Users
    student_user = User(
        id=uuid4(),
        email=f"stu_{uid}@example.com",
        full_name="Student One",
        hashed_password="hash",
        role=UserRole.STUDENT,
        is_active=True,
    )
    staff_user = User(
        id=uuid4(),
        email=f"staff_{uid}@example.com",
        full_name="Staff Tech",
        hashed_password="hash",
        role=UserRole.WARDEN,
        is_active=True,
    )
    db_session.add_all([student_user, staff_user])
    await db_session.flush()

    profile = StudentProfile(
        id=uuid4(),
        user_id=student_user.id,
        student_no=f"NO-{uid}",
        gender=GenderType.MALE,
        department="CS",
        year=1,
        guardian_name="Parent",
        guardian_phone="123",
        emergency_contact="456",
    )
    db_session.add(profile)
    await db_session.flush()

    allocation = Allocation(
        student_id=profile.id,
        bed_id=bed.id,
        start_date=date(2026, 1, 1),
        status=AllocationStatus.ACTIVE,
    )
    db_session.add(allocation)
    await db_session.flush()

    complaint_repo = ComplaintRepository(db_session)
    comment_repo = ComplaintCommentRepository(db_session)

    # Create complaint
    complaint = Complaint(
        student_id=profile.id,
        room_id=room.id,
        title="Ceiling fan vibration",
        description="Fan is making loud vibrations on speed 3.",
        category=ComplaintCategory.ELECTRICAL,
        priority=ComplaintPriority.MEDIUM,
        status=ComplaintStatus.OPEN,
    )
    created = await complaint_repo.create(complaint)
    assert created.id is not None
    assert created.status == ComplaintStatus.OPEN

    # Get by ID with relationships
    fetched = await complaint_repo.get_by_id(created.id, load_comments=True)
    assert fetched is not None
    assert fetched.student.user.full_name == "Student One"
    assert fetched.room.block.hostel.name == f"Hostel {uid}"
    assert fetched.assignee is None
    assert len(fetched.comments) == 0

    # Non-existent ID returns None
    missing = await complaint_repo.get_by_id(uuid4())
    assert missing is None

    # Add comments
    public_comment = ComplaintComment(
        complaint_id=created.id,
        author_id=student_user.id,
        body="Any update on this?",
        is_internal=False,
    )
    internal_comment = ComplaintComment(
        complaint_id=created.id,
        author_id=staff_user.id,
        body="Electrician scheduled for tomorrow morning.",
        is_internal=True,
    )
    await comment_repo.create(public_comment)
    await comment_repo.create(internal_comment)

    # List comments by complaint
    all_comments = await comment_repo.list_by_complaint(created.id, include_internal=True)
    assert len(all_comments) == 2

    public_only = await comment_repo.list_by_complaint(created.id, include_internal=False)
    assert len(public_only) == 1
    assert public_only[0].body == "Any update on this?"

    # Update complaint
    created.status = ComplaintStatus.IN_PROGRESS
    created.assigned_to = staff_user.id
    updated = await complaint_repo.update(created)
    assert updated.status == ComplaintStatus.IN_PROGRESS
    assert updated.assigned_to == staff_user.id


@pytest.mark.asyncio
async def test_complaint_repository_list_and_filters(db_session: AsyncSession) -> None:
    """Test filtering complaints by category, priority, status, and hostel/warden scope."""
    uid = uuid4().hex[:6]

    h1 = Hostel(name=f"H1 {uid}", code=f"H1-{uid}", gender_type=GenderType.MIXED)
    h2 = Hostel(name=f"H2 {uid}", code=f"H2-{uid}", gender_type=GenderType.MIXED)
    db_session.add_all([h1, h2])
    await db_session.flush()

    b1 = Block(hostel_id=h1.id, name="B1", floor_count=1)
    b2 = Block(hostel_id=h2.id, name="B2", floor_count=1)
    db_session.add_all([b1, b2])
    await db_session.flush()

    r1 = Room(
        block_id=b1.id,
        number="101",
        floor=1,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("1000.00"),
        status=RoomStatus.AVAILABLE,
    )
    r2 = Room(
        block_id=b2.id,
        number="201",
        floor=1,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("1000.00"),
        status=RoomStatus.AVAILABLE,
    )
    db_session.add_all([r1, r2])
    await db_session.flush()

    u1 = User(
        id=uuid4(),
        email=f"u1_{uid}@example.com",
        full_name="U1",
        hashed_password="hash",
        role=UserRole.STUDENT,
        is_active=True,
    )
    u2 = User(
        id=uuid4(),
        email=f"u2_{uid}@example.com",
        full_name="U2",
        hashed_password="hash",
        role=UserRole.STUDENT,
        is_active=True,
    )
    tech = User(
        id=uuid4(),
        email=f"tech_{uid}@example.com",
        full_name="Tech",
        hashed_password="hash",
        role=UserRole.WARDEN,
        is_active=True,
    )
    db_session.add_all([u1, u2, tech])
    await db_session.flush()

    p1 = StudentProfile(
        id=uuid4(),
        user_id=u1.id,
        student_no=f"S1-{uid}",
        gender=GenderType.MALE,
        department="EE",
        year=2,
        guardian_name="G1",
        guardian_phone="1",
        emergency_contact="2",
    )
    p2 = StudentProfile(
        id=uuid4(),
        user_id=u2.id,
        student_no=f"S2-{uid}",
        gender=GenderType.FEMALE,
        department="ME",
        year=3,
        guardian_name="G2",
        guardian_phone="3",
        emergency_contact="4",
    )
    db_session.add_all([p1, p2])
    await db_session.flush()

    complaint_repo = ComplaintRepository(db_session)

    c1 = Complaint(
        student_id=p1.id,
        room_id=r1.id,
        title="Plumbing issue",
        description="Drain blocked",
        category=ComplaintCategory.PLUMBING,
        priority=ComplaintPriority.HIGH,
        status=ComplaintStatus.OPEN,
        assigned_to=tech.id,
    )
    c2 = Complaint(
        student_id=p2.id,
        room_id=r2.id,
        title="WiFi disconnected",
        description="No signal in room 201",
        category=ComplaintCategory.INTERNET,
        priority=ComplaintPriority.LOW,
        status=ComplaintStatus.RESOLVED,
    )
    await complaint_repo.create(c1)
    await complaint_repo.create(c2)

    params = PaginationParams(page=1, size=20)

    # Filter by category
    items, total = await complaint_repo.list(params, category=ComplaintCategory.PLUMBING)
    assert total == 1
    assert items[0].id == c1.id

    # Filter by priority
    items, total = await complaint_repo.list(params, priority=ComplaintPriority.LOW)
    assert total == 1
    assert items[0].id == c2.id

    # Filter by status
    items, total = await complaint_repo.list(params, status=ComplaintStatus.RESOLVED)
    assert total == 1
    assert items[0].id == c2.id

    # Filter by student_id
    items, total = await complaint_repo.list(params, student_id=p1.id)
    assert total == 1
    assert items[0].id == c1.id

    # Filter by assigned_to
    items, total = await complaint_repo.list(params, assigned_to=tech.id)
    assert total == 1
    assert items[0].id == c1.id

    # Filter by hostel_id
    items, total = await complaint_repo.list(params, hostel_id=h2.id)
    assert total == 1
    assert items[0].id == c2.id

    # Filter by warden_hostel_ids
    items, total = await complaint_repo.list(params, warden_hostel_ids=[h1.id])
    assert total == 1
    assert items[0].id == c1.id

    # Empty warden_hostel_ids returns empty list immediately
    items, total = await complaint_repo.list(params, warden_hostel_ids=[])
    assert items == []
    assert total == 0
