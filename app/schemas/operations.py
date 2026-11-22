"""Operations schemas for attendance, leave requests, and visitors."""

from datetime import date, datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.operations import AttendanceType, LeaveStatus

__all__ = [
    "AttendanceActionRequest",
    "AttendanceRead",
    "AttendanceType",
    "LeaveRequestCreate",
    "LeaveRequestRead",
    "LeaveReviewRequest",
    "LeaveStatus",
    "PresentStudentRead",
    "VisitorCheckOutRequest",
    "VisitorCreate",
    "VisitorRead",
]


# =============================================================================
# Attendance Schemas
# =============================================================================


class AttendanceActionRequest(BaseModel):
    """Payload for student hostel check-in and check-out recording."""

    student_id: UUID
    remarks: str | None = None
    timestamp: datetime | None = None


class AttendanceRead(BaseModel):
    """Public representation of an attendance check-in/out log record."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_id: UUID
    type: AttendanceType
    timestamp: datetime
    recorded_by: UUID
    remarks: str | None
    created_at: datetime

    student_name: str | None = None
    student_no: str | None = None
    hostel_name: str | None = None
    room_number: str | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_enriched_fields(cls, data: Any) -> Any:
        """Extract enriched contextual details from related ORM attributes if available."""
        if isinstance(data, dict):
            return data

        d = getattr(data, "__dict__", {})
        student = d.get("student")
        user = getattr(student, "__dict__", {}).get("user") if student else None
        allocations = getattr(student, "allocations", []) if student else []
        active_alloc = next(
            (a for a in allocations if getattr(a, "status", None) == "active"),
            None,
        )
        bed = getattr(active_alloc, "__dict__", {}).get("bed") if active_alloc else None
        room = getattr(bed, "__dict__", {}).get("room") if bed else None
        block = getattr(room, "__dict__", {}).get("block") if room else None
        hostel = getattr(block, "__dict__", {}).get("hostel") if block else None

        return {
            "id": getattr(data, "id", None),
            "student_id": getattr(data, "student_id", None),
            "type": getattr(data, "type", None),
            "timestamp": getattr(data, "timestamp", None),
            "recorded_by": getattr(data, "recorded_by", None),
            "remarks": getattr(data, "remarks", None),
            "created_at": getattr(data, "created_at", None),
            "student_name": getattr(user, "full_name", getattr(data, "student_name", None)),
            "student_no": getattr(student, "student_no", getattr(data, "student_no", None)),
            "hostel_name": getattr(hostel, "name", getattr(data, "hostel_name", None)),
            "room_number": getattr(room, "number", getattr(data, "room_number", None)),
        }


class PresentStudentRead(BaseModel):
    """Details of a student currently present inside the hostel."""

    model_config = ConfigDict(from_attributes=True)

    student_id: UUID
    student_name: str
    student_no: str
    hostel_id: UUID
    hostel_name: str
    room_number: str
    bed_label: str
    last_check_in: datetime


# =============================================================================
# Leave Schemas
# =============================================================================


class LeaveRequestCreate(BaseModel):
    """Payload for submitting a new hostel leave request."""

    from_date: date
    to_date: date
    reason: str = Field(min_length=1, max_length=500)
    student_id: UUID | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        """Enforce chronological validity: to_date >= from_date."""
        if self.to_date < self.from_date:
            raise ValueError("to_date must be greater than or equal to from_date")
        return self


class LeaveReviewRequest(BaseModel):
    """Payload for approving or rejecting a leave request."""

    review_notes: str | None = Field(default=None, max_length=500)


class LeaveRequestRead(BaseModel):
    """Public representation of a student leave request."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_id: UUID
    from_date: date
    to_date: date
    reason: str
    status: LeaveStatus
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    review_notes: str | None
    created_at: datetime
    updated_at: datetime

    student_name: str | None = None
    student_no: str | None = None
    hostel_name: str | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_enriched_fields(cls, data: Any) -> Any:
        """Extract enriched contextual details from related ORM attributes if available."""
        if isinstance(data, dict):
            return data

        d = getattr(data, "__dict__", {})
        student = d.get("student")
        user = getattr(student, "__dict__", {}).get("user") if student else None
        allocations = getattr(student, "allocations", []) if student else []
        active_alloc = next(
            (a for a in allocations if getattr(a, "status", None) == "active"),
            None,
        )
        bed = getattr(active_alloc, "__dict__", {}).get("bed") if active_alloc else None
        room = getattr(bed, "__dict__", {}).get("room") if bed else None
        block = getattr(room, "__dict__", {}).get("block") if room else None
        hostel = getattr(block, "__dict__", {}).get("hostel") if block else None

        return {
            "id": getattr(data, "id", None),
            "student_id": getattr(data, "student_id", None),
            "from_date": getattr(data, "from_date", None),
            "to_date": getattr(data, "to_date", None),
            "reason": getattr(data, "reason", None),
            "status": getattr(data, "status", None),
            "reviewed_by": getattr(data, "reviewed_by", None),
            "reviewed_at": getattr(data, "reviewed_at", None),
            "review_notes": getattr(data, "review_notes", None),
            "created_at": getattr(data, "created_at", None),
            "updated_at": getattr(data, "updated_at", None),
            "student_name": getattr(user, "full_name", getattr(data, "student_name", None)),
            "student_no": getattr(student, "student_no", getattr(data, "student_no", None)),
            "hostel_name": getattr(hostel, "name", getattr(data, "hostel_name", None)),
        }


# =============================================================================
# Visitor Schemas
# =============================================================================


class VisitorCreate(BaseModel):
    """Payload for logging a visitor check-in to visit a hostel resident."""

    student_id: UUID
    name: str = Field(min_length=1, max_length=100)
    phone: str = Field(min_length=1, max_length=50)
    relation: str = Field(min_length=1, max_length=50)
    id_proof_type: str | None = None
    id_proof_number: str | None = None
    remarks: str | None = None


class VisitorCheckOutRequest(BaseModel):
    """Payload for completing a visitor checkout."""

    remarks: str | None = None


class VisitorRead(BaseModel):
    """Public representation of a visitor entry and exit record."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_id: UUID
    name: str
    phone: str
    relation: str
    check_in_at: datetime
    check_out_at: datetime | None
    id_proof_type: str | None
    id_proof_number: str | None
    remarks: str | None
    created_at: datetime
    updated_at: datetime
    is_active: bool
    student_name: str | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_enriched_fields(cls, data: Any) -> Any:
        """Extract enriched contextual details from related ORM attributes if available."""
        if isinstance(data, dict):
            if "is_active" not in data and "check_out_at" in data:
                data["is_active"] = data["check_out_at"] is None
            return data

        d = getattr(data, "__dict__", {})
        student = d.get("student")
        user = getattr(student, "__dict__", {}).get("user") if student else None
        check_out_at = getattr(data, "check_out_at", None)

        return {
            "id": getattr(data, "id", None),
            "student_id": getattr(data, "student_id", None),
            "name": getattr(data, "name", None),
            "phone": getattr(data, "phone", None),
            "relation": getattr(data, "relation", None),
            "check_in_at": getattr(data, "check_in_at", None),
            "check_out_at": check_out_at,
            "id_proof_type": getattr(data, "id_proof_type", None),
            "id_proof_number": getattr(data, "id_proof_number", None),
            "remarks": getattr(data, "remarks", None),
            "created_at": getattr(data, "created_at", None),
            "updated_at": getattr(data, "updated_at", None),
            "is_active": check_out_at is None,
            "student_name": getattr(user, "full_name", getattr(data, "student_name", None)),
        }
