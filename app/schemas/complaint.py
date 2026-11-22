"""Complaint request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.complaint import ComplaintCategory, ComplaintPriority, ComplaintStatus

__all__ = [
    "ComplaintAssignRequest",
    "ComplaintCategory",
    "ComplaintCommentCreate",
    "ComplaintCommentRead",
    "ComplaintCreate",
    "ComplaintDetailRead",
    "ComplaintPriority",
    "ComplaintRead",
    "ComplaintStatus",
    "ComplaintStatusUpdateRequest",
]


class ComplaintCreate(BaseModel):
    """Payload to lodge a new student complaint."""

    title: str = Field(min_length=1, max_length=150)
    description: str = Field(min_length=1, max_length=1000)
    category: ComplaintCategory
    priority: ComplaintPriority = ComplaintPriority.MEDIUM


class ComplaintStatusUpdateRequest(BaseModel):
    """Payload to transition complaint lifecycle status."""

    status: ComplaintStatus
    resolution_notes: str | None = Field(default=None, max_length=500)
    mark_room_maintenance: bool = False


class ComplaintAssignRequest(BaseModel):
    """Payload to assign a complaint to staff / user."""

    assigned_to: UUID


class ComplaintCommentCreate(BaseModel):
    """Payload to post a comment to an existing complaint."""

    body: str = Field(min_length=1, max_length=1000)
    is_internal: bool = False


class ComplaintCommentRead(BaseModel):
    """Representation of a complaint comment."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    complaint_id: UUID
    author_id: UUID
    author_name: str | None = None
    author_role: str | None = None
    body: str
    is_internal: bool
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def populate_author_details(cls, data: Any) -> Any:
        """Extract author metadata when serializing ORM instance."""
        if isinstance(data, dict):
            return data

        author = getattr(data, "author", None)
        author_name = author.full_name if author else None
        role_val = getattr(author, "role", None)
        author_role: str | None = None
        if role_val is not None:
            author_role = str(role_val.value) if hasattr(role_val, "value") else str(role_val)

        return {
            "id": getattr(data, "id", None),
            "complaint_id": getattr(data, "complaint_id", None),
            "author_id": getattr(data, "author_id", None),
            "author_name": author_name,
            "author_role": author_role,
            "body": getattr(data, "body", None),
            "is_internal": getattr(data, "is_internal", False),
            "created_at": getattr(data, "created_at", None),
            "updated_at": getattr(data, "updated_at", None),
        }


class ComplaintRead(BaseModel):
    """Public representation of a complaint."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_id: UUID
    room_id: UUID
    title: str
    description: str
    category: ComplaintCategory
    priority: ComplaintPriority
    status: ComplaintStatus
    assigned_to: UUID | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    student_name: str | None = None
    student_no: str | None = None
    room_number: str | None = None
    hostel_name: str | None = None
    hostel_id: UUID | None = None
    assigned_to_name: str | None = None
    resolution_time_hours: float | None = None

    @classmethod
    def _extract_enriched_fields(cls, data: Any) -> Any:
        """Extract enriched contextual details from related ORM attributes if available."""
        if isinstance(data, dict):
            if (
                data.get("resolution_time_hours") is None
                and data.get("resolved_at")
                and data.get("created_at")
            ):
                res_at = data["resolved_at"]
                cr_at = data["created_at"]
                if isinstance(res_at, datetime) and isinstance(cr_at, datetime):
                    diff = (res_at - cr_at).total_seconds() / 3600.0
                    data["resolution_time_hours"] = round(diff, 2)
            return data

        student = getattr(data, "student", None)
        user = getattr(student, "user", None) if student else None
        room = getattr(data, "room", None)
        block = getattr(room, "block", None) if room else None
        hostel = getattr(block, "hostel", None) if block else None
        assignee = getattr(data, "assignee", None)

        resolved_at = getattr(data, "resolved_at", None)
        created_at = getattr(data, "created_at", None)
        resolution_time_hours: float | None = None
        if resolved_at and created_at:
            resolution_time_hours = round((resolved_at - created_at).total_seconds() / 3600.0, 2)

        return {
            "id": getattr(data, "id", None),
            "student_id": getattr(data, "student_id", None),
            "room_id": getattr(data, "room_id", None),
            "title": getattr(data, "title", None),
            "description": getattr(data, "description", None),
            "category": getattr(data, "category", None),
            "priority": getattr(data, "priority", None),
            "status": getattr(data, "status", None),
            "assigned_to": getattr(data, "assigned_to", None),
            "resolved_at": resolved_at,
            "created_at": created_at,
            "updated_at": getattr(data, "updated_at", None),
            "student_name": user.full_name if user else None,
            "student_no": student.student_no if student else None,
            "room_number": room.number if room else None,
            "hostel_name": hostel.name if hostel else None,
            "hostel_id": hostel.id if hostel else None,
            "assigned_to_name": assignee.full_name if assignee else None,
            "resolution_time_hours": resolution_time_hours,
        }

    @model_validator(mode="before")
    @classmethod
    def populate_enriched_fields(cls, data: Any) -> Any:
        """Validate and enrich complaint fields."""
        return cls._extract_enriched_fields(data)


class ComplaintDetailRead(ComplaintRead):
    """Detailed complaint representation including comment thread."""

    comments: list[ComplaintCommentRead] = []

    @model_validator(mode="before")
    @classmethod
    def populate_detail_fields(cls, data: Any) -> Any:
        """Extract base fields and append comments if present."""
        base_dict = cls._extract_enriched_fields(data)
        if isinstance(base_dict, dict) and "comments" not in base_dict:
            raw_comments = getattr(data, "comments", [])
            base_dict["comments"] = raw_comments
        return base_dict
