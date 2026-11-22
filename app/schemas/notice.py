"""Notice request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.notice import NoticeAudience

__all__ = [
    "NoticeAudience",
    "NoticeCreate",
    "NoticeRead",
    "NoticeUnreadCount",
    "NoticeUpdate",
]


class NoticeCreate(BaseModel):
    """Payload to create a new notice announcement."""

    model_config = ConfigDict(extra="forbid")

    hostel_id: UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    audience: NoticeAudience = NoticeAudience.ALL
    is_pinned: bool = False
    published_at: datetime | None = None
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        """Ensure expiration date is strictly after published date when both are supplied."""
        if (
            self.published_at is not None
            and self.expires_at is not None
            and self.expires_at <= self.published_at
        ):
            raise ValueError("expires_at must be strictly after published_at")
        return self


class NoticeUpdate(BaseModel):
    """Payload to update an existing notice announcement."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    body: str | None = Field(default=None, min_length=1)
    audience: NoticeAudience | None = None
    is_pinned: bool | None = None
    published_at: datetime | None = None
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        """Ensure expiration date is strictly after published date when both are supplied."""
        if (
            self.published_at is not None
            and self.expires_at is not None
            and self.expires_at <= self.published_at
        ):
            raise ValueError("expires_at must be strictly after published_at")
        return self


class NoticeRead(BaseModel):
    """Public representation of a notice announcement."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    hostel_id: UUID | None = None
    title: str
    body: str
    audience: NoticeAudience
    is_pinned: bool
    published_at: datetime
    expires_at: datetime | None = None
    created_by_id: UUID | None = None
    is_read: bool = False
    created_at: datetime
    updated_at: datetime
    hostel_name: str | None = None
    created_by_name: str | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_enriched_fields(cls, data: Any) -> Any:
        """Extract enriched contextual details from related ORM attributes if available."""
        if isinstance(data, dict):
            return data

        hostel = getattr(data, "hostel", None)
        created_by = getattr(data, "created_by", None)

        return {
            "id": getattr(data, "id", None),
            "hostel_id": getattr(data, "hostel_id", None),
            "title": getattr(data, "title", None),
            "body": getattr(data, "body", None),
            "audience": getattr(data, "audience", None),
            "is_pinned": getattr(data, "is_pinned", False),
            "published_at": getattr(data, "published_at", None),
            "expires_at": getattr(data, "expires_at", None),
            "created_by_id": getattr(data, "created_by_id", None),
            "is_read": getattr(data, "is_read", False),
            "created_at": getattr(data, "created_at", None),
            "updated_at": getattr(data, "updated_at", None),
            "hostel_name": getattr(hostel, "name", getattr(data, "hostel_name", None)),
            "created_by_name": getattr(
                created_by, "full_name", getattr(data, "created_by_name", None)
            ),
        }


class NoticeUnreadCount(BaseModel):
    """Payload representing count of visible unread notices."""

    unread_count: int
