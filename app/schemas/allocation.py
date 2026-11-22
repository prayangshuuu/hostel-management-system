"""Room bed allocation request and response schemas."""

from datetime import date, datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.allocation import AllocationStatus


class AllocationCreate(BaseModel):
    """Payload for allocating a bed/room to a student."""

    model_config = ConfigDict(extra="forbid")

    student_id: UUID
    bed_id: UUID | None = None
    room_id: UUID | None = None
    start_date: date = Field(default_factory=date.today)

    @model_validator(mode="after")
    def validate_bed_or_room(self) -> Self:
        """Validate that at least one of bed_id or room_id is specified."""
        if self.bed_id is None and self.room_id is None:
            raise ValueError("At least one of bed_id or room_id must be provided")
        return self


class AllocationVacateRequest(BaseModel):
    """Payload for ending/vacating an active room bed allocation."""

    model_config = ConfigDict(extra="forbid")

    end_date: date | None = None
    reason: str | None = Field(default=None, max_length=500)


class AllocationTransferRequest(BaseModel):
    """Payload for transferring a student allocation to a new bed or room."""

    model_config = ConfigDict(extra="forbid")

    new_bed_id: UUID | None = None
    new_room_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_new_bed_or_room(self) -> Self:
        """Validate that at least one of new_bed_id or new_room_id is specified."""
        if self.new_bed_id is None and self.new_room_id is None:
            raise ValueError("At least one of new_bed_id or new_room_id must be provided")
        return self


class AllocationRead(BaseModel):
    """Public room bed allocation response schema with enriched location and student details."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_id: UUID
    bed_id: UUID
    start_date: date
    end_date: date | None = None
    status: AllocationStatus
    reason: str | None = None
    created_at: datetime
    updated_at: datetime

    # Enriched contextual fields
    student_no: str | None = None
    student_name: str | None = None
    bed_label: str | None = None
    room_number: str | None = None
    room_id: UUID | None = None
    hostel_name: str | None = None
    hostel_id: UUID | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_enriched_fields(cls, data: Any) -> Any:
        """Extract enriched contextual details from related ORM attributes if available."""
        if isinstance(data, dict):
            return data

        student = getattr(data, "student", None)
        user = getattr(student, "user", None) if student else None
        bed = getattr(data, "bed", None)
        room = getattr(bed, "room", None) if bed else None
        block = getattr(room, "block", None) if room else None
        hostel = getattr(block, "hostel", None) if block else None

        return {
            "id": getattr(data, "id", None),
            "student_id": getattr(data, "student_id", None),
            "bed_id": getattr(data, "bed_id", None),
            "start_date": getattr(data, "start_date", None),
            "end_date": getattr(data, "end_date", None),
            "status": getattr(data, "status", None),
            "reason": getattr(data, "reason", None),
            "created_at": getattr(data, "created_at", None),
            "updated_at": getattr(data, "updated_at", None),
            "student_no": getattr(student, "student_no", getattr(data, "student_no", None)),
            "student_name": getattr(user, "full_name", getattr(data, "student_name", None)),
            "bed_label": getattr(bed, "label", getattr(data, "bed_label", None)),
            "room_number": getattr(room, "number", getattr(data, "room_number", None)),
            "room_id": getattr(room, "id", getattr(data, "room_id", None)),
            "hostel_name": getattr(hostel, "name", getattr(data, "hostel_name", None)),
            "hostel_id": getattr(hostel, "id", getattr(data, "hostel_id", None)),
        }


class OccupantRead(BaseModel):
    """Details of a student currently occupying a bed in a room."""

    model_config = ConfigDict(from_attributes=True)

    bed_id: UUID
    bed_label: str
    student_id: UUID
    student_no: str
    student_name: str
    allocation_id: UUID
    start_date: date


__all__ = [
    "AllocationCreate",
    "AllocationRead",
    "AllocationStatus",
    "AllocationTransferRequest",
    "AllocationVacateRequest",
    "OccupantRead",
]
