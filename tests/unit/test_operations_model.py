"""Unit tests for AttendanceLog, LeaveRequest, and Visitor database models."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.hostel import GenderType
from app.models.operations import (
    AttendanceLog,
    AttendanceType,
    LeaveRequest,
    LeaveStatus,
    Visitor,
)
from app.models.student import StudentProfile
from app.models.user import User, UserRole


def test_attendance_log_model_attributes() -> None:
    """Verify AttendanceLog model columns, constraints, and indexes."""
    columns = AttendanceLog.__table__.columns
    assert "id" in columns
    assert "student_id" in columns
    assert "type" in columns
    assert "timestamp" in columns
    assert "recorded_by" in columns
    assert "remarks" in columns
    assert "created_at" in columns
    assert "updated_at" in columns

    assert columns["id"].primary_key is True
    assert columns["student_id"].nullable is False
    assert columns["type"].nullable is False
    assert columns["timestamp"].nullable is False
    assert columns["recorded_by"].nullable is False
    assert columns["remarks"].nullable is True

    index_names = {idx.name for idx in AttendanceLog.__table__.indexes}
    assert "ix_attendance_logs_student_id" in index_names
    assert "ix_attendance_logs_student_id_timestamp" in index_names


def test_leave_request_model_attributes() -> None:
    """Verify LeaveRequest model columns, constraints, and indexes."""
    columns = LeaveRequest.__table__.columns
    assert "id" in columns
    assert "student_id" in columns
    assert "from_date" in columns
    assert "to_date" in columns
    assert "reason" in columns
    assert "status" in columns
    assert "reviewed_by" in columns
    assert "reviewed_at" in columns
    assert "review_notes" in columns
    assert "created_at" in columns
    assert "updated_at" in columns

    assert columns["id"].primary_key is True
    assert columns["student_id"].nullable is False
    assert columns["from_date"].nullable is False
    assert columns["to_date"].nullable is False
    assert columns["reason"].nullable is False
    assert columns["status"].nullable is False
    assert columns["reviewed_by"].nullable is True
    assert columns["reviewed_at"].nullable is True
    assert columns["review_notes"].nullable is True

    index_names = {idx.name for idx in LeaveRequest.__table__.indexes}
    assert "ix_leave_requests_student_id" in index_names
    assert "ix_leave_requests_status" in index_names
    assert "ix_leave_requests_student_status_dates" in index_names


def test_visitor_model_attributes() -> None:
    """Verify Visitor model columns, constraints, and indexes."""
    columns = Visitor.__table__.columns
    assert "id" in columns
    assert "student_id" in columns
    assert "name" in columns
    assert "phone" in columns
    assert "relation" in columns
    assert "check_in_at" in columns
    assert "check_out_at" in columns
    assert "id_proof_type" in columns
    assert "id_proof_number" in columns
    assert "remarks" in columns
    assert "created_at" in columns
    assert "updated_at" in columns

    assert columns["id"].primary_key is True
    assert columns["student_id"].nullable is False
    assert columns["name"].nullable is False
    assert columns["phone"].nullable is False
    assert columns["relation"].nullable is False
    assert columns["check_in_at"].nullable is False
    assert columns["check_out_at"].nullable is True
    assert columns["id_proof_type"].nullable is True
    assert columns["id_proof_number"].nullable is True
    assert columns["remarks"].nullable is True

    index_names = {idx.name for idx in Visitor.__table__.indexes}
    assert "ix_visitors_student_id" in index_names
    assert "ix_visitors_student_active" in index_names
    assert "ix_visitors_check_in_at" in index_names


def test_enums_values() -> None:
    """Verify enum members and values."""
    assert AttendanceType.CHECK_IN == "check_in"
    assert AttendanceType.CHECK_OUT == "check_out"

    assert LeaveStatus.PENDING == "pending"
    assert LeaveStatus.APPROVED == "approved"
    assert LeaveStatus.REJECTED == "rejected"
    assert LeaveStatus.CANCELLED == "cancelled"


def test_operations_models_repr() -> None:
    """Verify __repr__ outputs for operations models."""
    log_id = uuid.uuid4()
    student_id = uuid.uuid4()
    now = datetime.now(UTC)

    log = AttendanceLog(
        id=log_id,
        student_id=student_id,
        type=AttendanceType.CHECK_IN,
        timestamp=now,
        recorded_by=uuid.uuid4(),
    )
    assert f"<AttendanceLog id={log_id}" in repr(log)
    assert "type=AttendanceType.CHECK_IN" in repr(log) or "check_in" in repr(log)

    leave_id = uuid.uuid4()
    leave = LeaveRequest(
        id=leave_id,
        student_id=student_id,
        from_date=date(2026, 12, 1),
        to_date=date(2026, 12, 5),
        reason="Family function",
        status=LeaveStatus.PENDING,
    )
    assert f"<LeaveRequest id={leave_id}" in repr(leave)
    assert "status=LeaveStatus.PENDING" in repr(leave) or "pending" in repr(leave)

    visitor_id = uuid.uuid4()
    visitor = Visitor(
        id=visitor_id,
        student_id=student_id,
        name="Jane Parent",
        phone="+1234567890",
        relation="Mother",
        check_in_at=now,
    )
    assert f"<Visitor id={visitor_id}" in repr(visitor)
    assert "Jane Parent" in repr(visitor)


async def _create_test_student(db_session: AsyncSession) -> tuple[User, StudentProfile]:
    """Helper to create a student user and student profile."""
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"student_{uid}@example.com",
        full_name=f"Student {uid}",
        hashed_password="hash",
        role=UserRole.STUDENT,
    )
    db_session.add(user)
    await db_session.flush()

    profile = StudentProfile(
        user_id=user.id,
        student_no=f"STU-{uid}",
        gender=GenderType.FEMALE,
        department="Engineering",
        year=1,
        guardian_name="Guardian Name",
        guardian_phone="+1112223334",
        emergency_contact="+1112223335",
    )
    db_session.add(profile)
    await db_session.flush()
    return user, profile


@pytest.mark.asyncio
async def test_attendance_log_lifecycle_and_relationships(
    db_session: AsyncSession,
) -> None:
    """Verify AttendanceLog persistence, defaults, and relationships."""
    _student_user, student_profile = await _create_test_student(db_session)

    warden = User(
        email=f"warden_{uuid.uuid4().hex[:8]}@example.com",
        full_name="Warden Bob",
        hashed_password="hash",
        role=UserRole.WARDEN,
    )
    db_session.add(warden)
    await db_session.flush()

    log = AttendanceLog(
        student_id=student_profile.id,
        type=AttendanceType.CHECK_IN,
        recorded_by=warden.id,
        remarks="Returned on time",
    )
    db_session.add(log)
    await db_session.flush()

    assert log.id is not None
    assert log.type == AttendanceType.CHECK_IN
    assert log.remarks == "Returned on time"
    assert log.timestamp is not None

    stmt = (
        select(AttendanceLog)
        .options(
            selectinload(AttendanceLog.student),
            selectinload(AttendanceLog.recorder),
        )
        .where(AttendanceLog.id == log.id)
    )
    res = await db_session.execute(stmt)
    loaded_log = res.scalar_one()

    assert loaded_log.student.id == student_profile.id
    assert loaded_log.recorder.id == warden.id

    # Verify back-populate on StudentProfile
    stmt_student = (
        select(StudentProfile)
        .options(selectinload(StudentProfile.attendance_logs))
        .where(StudentProfile.id == student_profile.id)
    )
    res_student = await db_session.execute(stmt_student)
    loaded_student = res_student.scalar_one()
    assert len(loaded_student.attendance_logs) == 1
    assert loaded_student.attendance_logs[0].id == log.id


@pytest.mark.asyncio
async def test_leave_request_lifecycle_and_relationships(
    db_session: AsyncSession,
) -> None:
    """Verify LeaveRequest persistence, defaults, reviewer assignment, and relationships."""
    _student_user, student_profile = await _create_test_student(db_session)

    leave = LeaveRequest(
        student_id=student_profile.id,
        from_date=date(2026, 12, 10),
        to_date=date(2026, 12, 15),
        reason="Medical emergency at home",
    )
    db_session.add(leave)
    await db_session.flush()

    assert leave.id is not None
    assert leave.status == LeaveStatus.PENDING
    assert leave.reviewed_by is None
    assert leave.reviewed_at is None
    assert leave.review_notes is None

    # Review the leave
    admin = User(
        email=f"admin_{uuid.uuid4().hex[:8]}@example.com",
        full_name="Admin Alice",
        hashed_password="hash",
        role=UserRole.ADMIN,
    )
    db_session.add(admin)
    await db_session.flush()

    now = datetime.now(UTC)
    leave.status = LeaveStatus.APPROVED
    leave.reviewed_by = admin.id
    leave.reviewed_at = now
    leave.review_notes = "Approved with parental consent"
    await db_session.flush()

    stmt = (
        select(LeaveRequest)
        .options(
            selectinload(LeaveRequest.student),
            selectinload(LeaveRequest.reviewer),
        )
        .where(LeaveRequest.id == leave.id)
    )
    res = await db_session.execute(stmt)
    loaded_leave = res.scalar_one()

    assert loaded_leave.status == LeaveStatus.APPROVED
    assert loaded_leave.reviewer is not None
    assert loaded_leave.reviewer.id == admin.id
    assert loaded_leave.review_notes == "Approved with parental consent"
    assert loaded_leave.student.id == student_profile.id

    # Verify back-populate on StudentProfile
    stmt_student = (
        select(StudentProfile)
        .options(selectinload(StudentProfile.leave_requests))
        .where(StudentProfile.id == student_profile.id)
    )
    res_student = await db_session.execute(stmt_student)
    loaded_student = res_student.scalar_one()
    assert len(loaded_student.leave_requests) == 1
    assert loaded_student.leave_requests[0].id == leave.id


@pytest.mark.asyncio
async def test_visitor_lifecycle_and_relationships(
    db_session: AsyncSession,
) -> None:
    """Verify Visitor persistence, checkout update, and relationships."""
    _student_user, student_profile = await _create_test_student(db_session)

    visitor = Visitor(
        student_id=student_profile.id,
        name="John Doe Sr.",
        phone="+9876543210",
        relation="Father",
        id_proof_type="National ID",
        id_proof_number="NID-998877",
        remarks="Visiting for the weekend",
    )
    db_session.add(visitor)
    await db_session.flush()

    assert visitor.id is not None
    assert visitor.check_in_at is not None
    assert visitor.check_out_at is None

    # Check out the visitor
    out_time = datetime.now(UTC)
    visitor.check_out_at = out_time
    await db_session.flush()

    stmt = select(Visitor).options(selectinload(Visitor.student)).where(Visitor.id == visitor.id)
    res = await db_session.execute(stmt)
    loaded_visitor = res.scalar_one()

    assert loaded_visitor.check_out_at is not None
    assert loaded_visitor.student.id == student_profile.id
    assert loaded_visitor.id_proof_type == "National ID"

    # Verify back-populate on StudentProfile
    stmt_student = (
        select(StudentProfile)
        .options(selectinload(StudentProfile.visitors))
        .where(StudentProfile.id == student_profile.id)
    )
    res_student = await db_session.execute(stmt_student)
    loaded_student = res_student.scalar_one()
    assert len(loaded_student.visitors) == 1
    assert loaded_student.visitors[0].id == visitor.id


@pytest.mark.asyncio
async def test_student_profile_cascade_delete_operations(
    db_session: AsyncSession,
) -> None:
    """Verify that deleting a StudentProfile cascade deletes operations records."""
    _student_user, student_profile = await _create_test_student(db_session)

    warden = User(
        email=f"warden_del_{uuid.uuid4().hex[:8]}@example.com",
        full_name="Warden Cascade",
        hashed_password="hash",
        role=UserRole.WARDEN,
    )
    db_session.add(warden)
    await db_session.flush()

    log = AttendanceLog(
        student_id=student_profile.id,
        type=AttendanceType.CHECK_IN,
        recorded_by=warden.id,
    )
    leave = LeaveRequest(
        student_id=student_profile.id,
        from_date=date(2026, 12, 10),
        to_date=date(2026, 12, 12),
        reason="Trip",
    )
    visitor = Visitor(
        student_id=student_profile.id,
        name="Aunt Mary",
        phone="+1234445555",
        relation="Aunt",
    )
    db_session.add_all([log, leave, visitor])
    await db_session.flush()

    # Delete StudentProfile
    await db_session.delete(student_profile)
    await db_session.flush()

    # Verify child records were deleted
    res_log = await db_session.execute(select(AttendanceLog).where(AttendanceLog.id == log.id))
    assert res_log.scalar_one_or_none() is None

    res_leave = await db_session.execute(select(LeaveRequest).where(LeaveRequest.id == leave.id))
    assert res_leave.scalar_one_or_none() is None

    res_visitor = await db_session.execute(select(Visitor).where(Visitor.id == visitor.id))
    assert res_visitor.scalar_one_or_none() is None
