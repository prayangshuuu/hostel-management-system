"""Complaint and complaint comment database models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.room import Room
    from app.models.student import StudentProfile
    from app.models.user import User


class ComplaintCategory(enum.StrEnum):
    """Category classification for a hostel complaint."""

    ELECTRICAL = "electrical"
    PLUMBING = "plumbing"
    FURNITURE = "furniture"
    CLEANING = "cleaning"
    INTERNET = "internet"
    OTHER = "other"


class ComplaintPriority(enum.StrEnum):
    """Urgency level of a hostel complaint."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class ComplaintStatus(enum.StrEnum):
    """Lifecycle status of a hostel complaint."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class Complaint(Base, UUIDPkMixin, TimestampMixin):
    """Student complaint record."""

    __tablename__ = "complaints"
    __table_args__ = (
        Index("ix_complaints_status_category_priority", "status", "category", "priority"),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    room_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rooms.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
    )
    category: Mapped[ComplaintCategory] = mapped_column(
        Enum(ComplaintCategory, native_enum=False, length=20),
        nullable=False,
    )
    priority: Mapped[ComplaintPriority] = mapped_column(
        Enum(ComplaintPriority, native_enum=False, length=20),
        nullable=False,
        default=ComplaintPriority.MEDIUM,
    )
    status: Mapped[ComplaintStatus] = mapped_column(
        Enum(ComplaintStatus, native_enum=False, length=20),
        nullable=False,
        default=ComplaintStatus.OPEN,
        index=True,
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    student: Mapped[StudentProfile] = relationship(
        "StudentProfile",
        back_populates="complaints",
    )
    room: Mapped[Room] = relationship("Room")
    assignee: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[assigned_to],
    )
    comments: Mapped[list[ComplaintComment]] = relationship(
        "ComplaintComment",
        back_populates="complaint",
        cascade="all, delete-orphan",
        order_by="ComplaintComment.created_at",
    )

    def __repr__(self) -> str:
        return (
            f"<Complaint id={self.id} student_id={self.student_id} "
            f"category={self.category} status={self.status}>"
        )


class ComplaintComment(Base, UUIDPkMixin, TimestampMixin):
    """Comment thread entry for a complaint."""

    __tablename__ = "complaint_comments"

    complaint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("complaints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
    )
    is_internal: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        index=True,
    )

    complaint: Mapped[Complaint] = relationship(
        "Complaint",
        back_populates="comments",
    )
    author: Mapped[User] = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<ComplaintComment id={self.id} complaint_id={self.complaint_id} "
            f"author_id={self.author_id} is_internal={self.is_internal}>"
        )
