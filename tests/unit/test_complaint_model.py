"""Unit tests for Complaint and ComplaintComment database models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.complaint import (
    Complaint,
    ComplaintCategory,
    ComplaintComment,
    ComplaintPriority,
    ComplaintStatus,
)
from app.models.hostel import Block, GenderType, Hostel
from app.models.room import Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole


def test_complaint_enums_values() -> None:
    """Verify complaint-related enum members and values."""
    assert ComplaintCategory.ELECTRICAL.value == "electrical"
    assert ComplaintCategory.PLUMBING.value == "plumbing"
    assert ComplaintCategory.FURNITURE.value == "furniture"
    assert ComplaintCategory.CLEANING.value == "cleaning"
    assert ComplaintCategory.INTERNET.value == "internet"
    assert ComplaintCategory.OTHER.value == "other"

    assert ComplaintPriority.LOW.value == "low"
    assert ComplaintPriority.MEDIUM.value == "medium"
    assert ComplaintPriority.HIGH.value == "high"
    assert ComplaintPriority.URGENT.value == "urgent"

    assert ComplaintStatus.OPEN.value == "open"
    assert ComplaintStatus.IN_PROGRESS.value == "in_progress"
    assert ComplaintStatus.RESOLVED.value == "resolved"
    assert ComplaintStatus.CLOSED.value == "closed"


def test_complaint_model_attributes() -> None:
    """Verify Complaint model columns, constraints, and indexes."""
    table = Complaint.__table__
    assert isinstance(table, Table)
    columns = table.columns
    assert "id" in columns
    assert "student_id" in columns
    assert "room_id" in columns
    assert "title" in columns
    assert "description" in columns
    assert "category" in columns
    assert "priority" in columns
    assert "status" in columns
    assert "assigned_to" in columns
    assert "resolved_at" in columns
    assert "created_at" in columns
    assert "updated_at" in columns

    assert columns["id"].primary_key is True
    assert columns["student_id"].nullable is False
    assert columns["room_id"].nullable is False
    assert columns["title"].nullable is False
    assert columns["description"].nullable is False
    assert columns["category"].nullable is False
    assert columns["priority"].nullable is False
    assert columns["status"].nullable is False
    assert columns["assigned_to"].nullable is True
    assert columns["resolved_at"].nullable is True

    index_names = {idx.name for idx in table.indexes}
    assert "ix_complaints_student_id" in index_names
    assert "ix_complaints_room_id" in index_names
    assert "ix_complaints_status" in index_names
    assert "ix_complaints_assigned_to" in index_names


def test_complaint_comment_model_attributes() -> None:
    """Verify ComplaintComment model columns, constraints, and indexes."""
    table = ComplaintComment.__table__
    assert isinstance(table, Table)
    columns = table.columns
    assert "id" in columns
    assert "complaint_id" in columns
    assert "author_id" in columns
    assert "body" in columns
    assert "is_internal" in columns
    assert "created_at" in columns
    assert "updated_at" in columns

    assert columns["id"].primary_key is True
    assert columns["complaint_id"].nullable is False
    assert columns["author_id"].nullable is False
    assert columns["body"].nullable is False
    assert columns["is_internal"].nullable is False

    index_names = {idx.name for idx in table.indexes}
    assert "ix_complaint_comments_complaint_id" in index_names
    assert "ix_complaint_comments_is_internal" in index_names


def test_complaint_models_repr() -> None:
    """Verify __repr__ strings for Complaint and ComplaintComment."""
    complaint_id = uuid.uuid4()
    student_id = uuid.uuid4()
    complaint = Complaint(
        id=complaint_id,
        student_id=student_id,
        room_id=uuid.uuid4(),
        title="Leaky tap",
        description="Bathroom faucet is leaking constantly.",
        category=ComplaintCategory.PLUMBING,
        priority=ComplaintPriority.HIGH,
        status=ComplaintStatus.OPEN,
    )
    assert f"<Complaint id={complaint_id}" in repr(complaint)
    assert "category=ComplaintCategory.PLUMBING" in repr(complaint) or "plumbing" in repr(complaint)

    comment_id = uuid.uuid4()
    comment = ComplaintComment(
        id=comment_id,
        complaint_id=complaint_id,
        author_id=uuid.uuid4(),
        body="Plumber assigned to inspect today.",
        is_internal=True,
    )
    assert f"<ComplaintComment id={comment_id}" in repr(comment)
    assert "is_internal=True" in repr(comment)


async def _create_test_environment(
    db_session: AsyncSession,
) -> tuple[StudentProfile, Room, User]:
    """Helper to create student profile, room, and warden user."""
    uid = uuid.uuid4().hex[:8]

    # Student user and profile
    student_user = User(
        email=f"student_{uid}@example.com",
        full_name=f"Student {uid}",
        hashed_password="hash",
        role=UserRole.STUDENT,
    )
    db_session.add(student_user)
    await db_session.flush()

    student = StudentProfile(
        user_id=student_user.id,
        student_no=f"STU-{uid}",
        gender=GenderType.MALE,
        department="Computer Science",
        year=2,
        guardian_name="Guardian Smith",
        guardian_phone="+1234567890",
        emergency_contact="+1987654321",
    )
    db_session.add(student)
    await db_session.flush()

    # Hostel, Block, Room
    hostel = Hostel(
        name=f"Hostel {uid}",
        code=f"H-{uid[:4]}",
        gender_type=GenderType.MALE,
    )
    db_session.add(hostel)
    await db_session.flush()

    block = Block(
        hostel_id=hostel.id,
        name="A",
        floor_count=2,
    )
    db_session.add(block)
    await db_session.flush()

    room = Room(
        block_id=block.id,
        number="201",
        floor=2,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("5000.00"),
        status=RoomStatus.AVAILABLE,
    )
    db_session.add(room)
    await db_session.flush()

    # Warden user
    warden = User(
        email=f"warden_{uid}@example.com",
        full_name=f"Warden {uid}",
        hashed_password="hash",
        role=UserRole.WARDEN,
    )
    db_session.add(warden)
    await db_session.flush()

    return student, room, warden


@pytest.mark.asyncio
async def test_complaint_and_comment_lifecycle_and_relationships(
    db_session: AsyncSession,
) -> None:
    """Verify full persistence lifecycle, defaults, and relationships for complaints."""
    student, room, warden = await _create_test_environment(db_session)

    complaint = Complaint(
        student_id=student.id,
        room_id=room.id,
        title="Ceiling fan not working",
        description="Speed regulator is broken and fan does not turn on.",
        category=ComplaintCategory.ELECTRICAL,
    )
    db_session.add(complaint)
    await db_session.flush()

    assert complaint.id is not None
    assert complaint.priority == ComplaintPriority.MEDIUM
    assert complaint.status == ComplaintStatus.OPEN
    assert complaint.assigned_to is None
    assert complaint.resolved_at is None
    assert complaint.created_at is not None
    assert complaint.updated_at is not None

    # Add comments (one public from student user, one internal from warden)
    comment_1 = ComplaintComment(
        complaint_id=complaint.id,
        author_id=student.user_id,
        body="It stopped working yesterday evening.",
        is_internal=False,
    )
    db_session.add(comment_1)
    await db_session.flush()

    comment_2 = ComplaintComment(
        complaint_id=complaint.id,
        author_id=warden.id,
        body="Electrician dispatched to check.",
        is_internal=True,
    )
    db_session.add(comment_2)
    await db_session.flush()

    # Assign and update complaint status
    now = datetime.now(UTC)
    complaint.assigned_to = warden.id
    complaint.status = ComplaintStatus.RESOLVED
    complaint.resolved_at = now
    await db_session.flush()

    # Query back with relationships
    stmt = (
        select(Complaint)
        .where(Complaint.id == complaint.id)
        .options(
            selectinload(Complaint.student),
            selectinload(Complaint.room),
            selectinload(Complaint.assignee),
            selectinload(Complaint.comments).selectinload(ComplaintComment.author),
        )
    )
    res = await db_session.execute(stmt)
    loaded_complaint = res.scalar_one()

    assert loaded_complaint.student.id == student.id
    assert loaded_complaint.room.id == room.id
    assert loaded_complaint.assignee is not None
    assert loaded_complaint.assignee.id == warden.id
    assert loaded_complaint.status == ComplaintStatus.RESOLVED
    assert loaded_complaint.resolved_at == now
    assert len(loaded_complaint.comments) == 2
    assert loaded_complaint.comments[0].is_internal is False
    assert loaded_complaint.comments[0].author.id == student.user_id
    assert loaded_complaint.comments[1].is_internal is True
    assert loaded_complaint.comments[1].author.id == warden.id

    # Verify student back_populates complaints
    stmt_student = (
        select(StudentProfile)
        .where(StudentProfile.id == student.id)
        .options(selectinload(StudentProfile.complaints))
    )
    res_student = await db_session.execute(stmt_student)
    loaded_student = res_student.scalar_one()
    assert len(loaded_student.complaints) == 1
    assert loaded_student.complaints[0].id == complaint.id


@pytest.mark.asyncio
async def test_complaint_cascade_delete(
    db_session: AsyncSession,
) -> None:
    """Verify cascade deletion for complaint comments and student complaints."""
    student, room, warden = await _create_test_environment(db_session)

    complaint = Complaint(
        student_id=student.id,
        room_id=room.id,
        title="Broken chair",
        description="One leg is loose.",
        category=ComplaintCategory.FURNITURE,
    )
    db_session.add(complaint)
    await db_session.flush()

    comment = ComplaintComment(
        complaint_id=complaint.id,
        author_id=warden.id,
        body="Will replace chair tomorrow.",
    )
    db_session.add(comment)
    await db_session.flush()

    comment_id = comment.id

    # Deleting complaint should cascade to comments
    await db_session.delete(complaint)
    await db_session.flush()

    deleted_comment = await db_session.get(ComplaintComment, comment_id)
    assert deleted_comment is None

    # Create another complaint and test deleting student_profile
    complaint_2 = Complaint(
        student_id=student.id,
        room_id=room.id,
        title="Wifi issue",
        description="Signal drops constantly.",
        category=ComplaintCategory.INTERNET,
    )
    db_session.add(complaint_2)
    await db_session.flush()
    complaint_2_id = complaint_2.id

    await db_session.delete(student)
    await db_session.flush()

    deleted_complaint = await db_session.get(Complaint, complaint_2_id)
    assert deleted_complaint is None
