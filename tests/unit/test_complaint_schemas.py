"""Unit tests for complaint request and response Pydantic v2 schemas."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.complaint import ComplaintCategory, ComplaintPriority, ComplaintStatus
from app.models.user import UserRole
from app.schemas.complaint import (
    ComplaintAssignRequest,
    ComplaintCommentCreate,
    ComplaintCommentRead,
    ComplaintCreate,
    ComplaintDetailRead,
    ComplaintRead,
    ComplaintStatusUpdateRequest,
)


def test_complaint_create_valid() -> None:
    """Validate valid complaint creation schema with defaults."""
    req = ComplaintCreate(
        title="Leaking faucet in washroom",
        description="The bathroom faucet continues dripping even when tightly shut.",
        category=ComplaintCategory.PLUMBING,
    )
    assert req.title == "Leaking faucet in washroom"
    assert req.category == ComplaintCategory.PLUMBING
    assert req.priority == ComplaintPriority.MEDIUM


def test_complaint_create_validation_errors() -> None:
    """Validate min/max boundaries and invalid enums for ComplaintCreate."""
    with pytest.raises(ValidationError) as exc:
        ComplaintCreate(
            title="",  # min_length 1
            description="Valid description",
            category=ComplaintCategory.ELECTRICAL,
        )
    assert "title" in str(exc.value)

    with pytest.raises(ValidationError) as exc:
        ComplaintCreate(
            title="A" * 151,  # max_length 150
            description="Valid description",
            category=ComplaintCategory.ELECTRICAL,
        )
    assert "title" in str(exc.value)

    with pytest.raises(ValidationError) as exc:
        ComplaintCreate(
            title="Valid title",
            description="",  # min_length 1
            category=ComplaintCategory.ELECTRICAL,
        )
    assert "description" in str(exc.value)

    with pytest.raises(ValidationError) as exc:
        ComplaintCreate(
            title="Valid title",
            description="B" * 1001,  # max_length 1000
            category=ComplaintCategory.ELECTRICAL,
        )
    assert "description" in str(exc.value)


def test_complaint_status_update_request_validation() -> None:
    """Validate ComplaintStatusUpdateRequest fields and boundary rules."""
    req = ComplaintStatusUpdateRequest(status=ComplaintStatus.RESOLVED)
    assert req.status == ComplaintStatus.RESOLVED
    assert req.resolution_notes is None
    assert req.mark_room_maintenance is False

    req_with_notes = ComplaintStatusUpdateRequest(
        status=ComplaintStatus.IN_PROGRESS,
        resolution_notes="Plumber dispatched to inspect valve.",
        mark_room_maintenance=True,
    )
    assert req_with_notes.mark_room_maintenance is True
    assert req_with_notes.resolution_notes == "Plumber dispatched to inspect valve."

    with pytest.raises(ValidationError):
        ComplaintStatusUpdateRequest(
            status=ComplaintStatus.RESOLVED,
            resolution_notes="C" * 501,  # max 500
        )


def test_complaint_assign_request_validation() -> None:
    """Validate ComplaintAssignRequest schema."""
    assigned_id = uuid.uuid4()
    req = ComplaintAssignRequest(assigned_to=assigned_id)
    assert req.assigned_to == assigned_id

    with pytest.raises(ValidationError):
        ComplaintAssignRequest(assigned_to="invalid-uuid")  # type: ignore[arg-type]


def test_complaint_comment_schemas() -> None:
    """Validate ComplaintCommentCreate and ComplaintCommentRead serialization."""
    comment_create = ComplaintCommentCreate(body="Inspection completed.", is_internal=True)
    assert comment_create.body == "Inspection completed."
    assert comment_create.is_internal is True

    with pytest.raises(ValidationError):
        ComplaintCommentCreate(body="")

    with pytest.raises(ValidationError):
        ComplaintCommentCreate(body="D" * 1001)

    c_id = uuid.uuid4()
    u_id = uuid.uuid4()
    now = datetime.now(UTC)

    # From mock ORM object with author
    mock_author = SimpleNamespace(full_name="Chief Warden", role=UserRole.WARDEN)
    mock_comment_orm = SimpleNamespace(
        id=c_id,
        complaint_id=uuid.uuid4(),
        author_id=u_id,
        body="Internal technician note",
        is_internal=True,
        created_at=now,
        updated_at=now,
        author=mock_author,
    )
    read_from_orm = ComplaintCommentRead.model_validate(mock_comment_orm)
    assert read_from_orm.id == c_id
    assert read_from_orm.author_name == "Chief Warden"
    assert read_from_orm.author_role == "warden"
    assert read_from_orm.is_internal is True


def test_complaint_read_enrichment_and_resolution_time() -> None:
    """Validate ORM relation enrichment and resolution time calculation."""
    comp_id = uuid.uuid4()
    s_id = uuid.uuid4()
    r_id = uuid.uuid4()
    h_id = uuid.uuid4()
    u_id = uuid.uuid4()
    created = datetime(2026, 11, 22, 10, 0, 0, tzinfo=UTC)
    resolved = created + timedelta(hours=3, minutes=30)

    user = SimpleNamespace(full_name="Alice Student")
    student = SimpleNamespace(id=s_id, student_no="STU-001", user=user)
    hostel = SimpleNamespace(id=h_id, name="Mandela Hall")
    block = SimpleNamespace(hostel=hostel)
    room = SimpleNamespace(id=r_id, number="A-101", block=block)
    assignee = SimpleNamespace(full_name="Bob Handyman")

    mock_comp = SimpleNamespace(
        id=comp_id,
        student_id=s_id,
        room_id=r_id,
        title="Heater failure",
        description="Room heater not working",
        category=ComplaintCategory.ELECTRICAL,
        priority=ComplaintPriority.HIGH,
        status=ComplaintStatus.RESOLVED,
        assigned_to=u_id,
        resolved_at=resolved,
        created_at=created,
        updated_at=resolved,
        student=student,
        room=room,
        assignee=assignee,
        comments=[],
    )

    read = ComplaintRead.model_validate(mock_comp)
    assert read.id == comp_id
    assert read.student_name == "Alice Student"
    assert read.student_no == "STU-001"
    assert read.room_number == "A-101"
    assert read.hostel_name == "Mandela Hall"
    assert read.hostel_id == h_id
    assert read.assigned_to_name == "Bob Handyman"
    assert read.resolution_time_hours == 3.5

    # Detail read includes comments
    detail_read = ComplaintDetailRead.model_validate(mock_comp)
    assert detail_read.id == comp_id
    assert detail_read.comments == []
