"""Unit tests for attendance, leave request, and visitor Pydantic schemas."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.operations import AttendanceType, LeaveStatus
from app.schemas.operations import (
    AttendanceActionRequest,
    AttendanceRead,
    LeaveRequestCreate,
    LeaveRequestRead,
    LeaveReviewRequest,
    PresentStudentRead,
    VisitorCheckOutRequest,
    VisitorCreate,
    VisitorRead,
)


def test_attendance_action_request_schema() -> None:
    """Verify AttendanceActionRequest schema parsing and defaults."""
    stu_id = uuid4()
    req = AttendanceActionRequest(student_id=stu_id)
    assert req.student_id == stu_id
    assert req.remarks is None
    assert req.timestamp is None

    now = datetime.now(UTC)
    req2 = AttendanceActionRequest(student_id=stu_id, remarks="Gate 1 entry", timestamp=now)
    assert req2.remarks == "Gate 1 entry"
    assert req2.timestamp == now


def test_attendance_read_schema_enrichment() -> None:
    """Verify AttendanceRead schema parses dictionaries and enriched fields."""
    stu_id = uuid4()
    log_id = uuid4()
    rec_id = uuid4()
    now = datetime.now(UTC)

    data = {
        "id": log_id,
        "student_id": stu_id,
        "type": AttendanceType.CHECK_IN,
        "timestamp": now,
        "recorded_by": rec_id,
        "remarks": "On time",
        "created_at": now,
        "student_name": "Alice Smith",
        "student_no": "STU-001",
        "hostel_name": "Hostel Alpha",
        "room_number": "101",
    }
    read_obj = AttendanceRead.model_validate(data)
    assert read_obj.id == log_id
    assert read_obj.student_name == "Alice Smith"
    assert read_obj.room_number == "101"
    assert read_obj.type == AttendanceType.CHECK_IN


def test_present_student_read_schema() -> None:
    """Verify PresentStudentRead schema fields."""
    stu_id = uuid4()
    hostel_id = uuid4()
    now = datetime.now(UTC)

    read_obj = PresentStudentRead(
        student_id=stu_id,
        student_name="Bob Jones",
        student_no="STU-002",
        hostel_id=hostel_id,
        hostel_name="Hostel Beta",
        room_number="202",
        bed_label="202-B",
        last_check_in=now,
    )
    assert read_obj.student_id == stu_id
    assert read_obj.bed_label == "202-B"


def test_leave_request_create_validation() -> None:
    """Verify LeaveRequestCreate validation: to_date >= from_date."""
    # Valid chronological
    valid = LeaveRequestCreate(
        from_date=date(2026, 12, 1),
        to_date=date(2026, 12, 5),
        reason="Family event",
    )
    assert valid.from_date == date(2026, 12, 1)
    assert valid.to_date == date(2026, 12, 5)

    # Valid same-day
    same_day = LeaveRequestCreate(
        from_date=date(2026, 12, 1),
        to_date=date(2026, 12, 1),
        reason="Day trip",
    )
    assert same_day.from_date == same_day.to_date

    # Invalid: to_date < from_date
    with pytest.raises(ValidationError) as exc:
        LeaveRequestCreate(
            from_date=date(2026, 12, 5),
            to_date=date(2026, 12, 1),
            reason="Backwards trip",
        )
    assert "to_date must be greater than or equal to from_date" in str(exc.value)

    # Invalid: empty reason
    with pytest.raises(ValidationError):
        LeaveRequestCreate(
            from_date=date(2026, 12, 1),
            to_date=date(2026, 12, 5),
            reason="",
        )


def test_leave_review_request() -> None:
    """Verify LeaveReviewRequest schema optional notes."""
    req1 = LeaveReviewRequest()
    assert req1.review_notes is None

    req2 = LeaveReviewRequest(review_notes="Approved by warden")
    assert req2.review_notes == "Approved by warden"


def test_leave_request_read_schema() -> None:
    """Verify LeaveRequestRead schema fields and enrichment."""
    req_id = uuid4()
    stu_id = uuid4()
    admin_id = uuid4()
    now = datetime.now(UTC)

    data = {
        "id": req_id,
        "student_id": stu_id,
        "from_date": date(2026, 12, 1),
        "to_date": date(2026, 12, 5),
        "reason": "Conference",
        "status": LeaveStatus.APPROVED,
        "reviewed_by": admin_id,
        "reviewed_at": now,
        "review_notes": "All clear",
        "created_at": now,
        "updated_at": now,
        "student_name": "Charlie Brown",
        "student_no": "STU-003",
        "hostel_name": "Hostel Gamma",
    }
    read_obj = LeaveRequestRead.model_validate(data)
    assert read_obj.id == req_id
    assert read_obj.status == LeaveStatus.APPROVED
    assert read_obj.student_name == "Charlie Brown"


def test_visitor_create_validation() -> None:
    """Verify VisitorCreate validation rules."""
    stu_id = uuid4()
    vis = VisitorCreate(
        student_id=stu_id,
        name="John Doe",
        phone="+1234567890",
        relation="Father",
        id_proof_type="Passport",
        id_proof_number="P123456",
        remarks="Visiting",
    )
    assert vis.name == "John Doe"
    assert vis.relation == "Father"

    # Empty name
    with pytest.raises(ValidationError):
        VisitorCreate(
            student_id=stu_id,
            name="",
            phone="+1234567890",
            relation="Father",
        )


def test_visitor_read_and_checkout_schemas() -> None:
    """Verify VisitorRead is_active computation and VisitorCheckOutRequest."""
    chk_req = VisitorCheckOutRequest(remarks="Checked out safely")
    assert chk_req.remarks == "Checked out safely"

    vis_id = uuid4()
    stu_id = uuid4()
    now = datetime.now(UTC)

    # Active visitor (check_out_at is None)
    active_data = {
        "id": vis_id,
        "student_id": stu_id,
        "name": "Jane Doe",
        "phone": "+111222333",
        "relation": "Mother",
        "check_in_at": now,
        "check_out_at": None,
        "id_proof_type": None,
        "id_proof_number": None,
        "remarks": None,
        "created_at": now,
        "updated_at": now,
        "is_active": True,
    }
    active_read = VisitorRead.model_validate(active_data)
    assert active_read.is_active is True

    # Checked out visitor
    inactive_data = {
        **active_data,
        "check_out_at": now,
        "is_active": False,
    }
    inactive_read = VisitorRead.model_validate(inactive_data)
    assert inactive_read.is_active is False
