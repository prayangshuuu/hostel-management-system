"""Attendance log, leave request, and visitor database models."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.student import StudentProfile
    from app.models.user import User


class AttendanceType(enum.StrEnum):
    """Hostel attendance event type."""

    CHECK_IN = "check_in"
    CHECK_OUT = "check_out"


class LeaveStatus(enum.StrEnum):
    """Leave request workflow status."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class AttendanceLog(Base, UUIDPkMixin, TimestampMixin):
    """Hostel check-in and check-out attendance record."""

    __tablename__ = "attendance_logs"
    __table_args__ = (Index("ix_attendance_logs_student_id_timestamp", "student_id", "timestamp"),)

    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[AttendanceType] = mapped_column(
        Enum(AttendanceType, native_enum=False, length=20),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )
    recorded_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    remarks: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    student: Mapped[StudentProfile] = relationship(
        "StudentProfile",
        back_populates="attendance_logs",
    )
    recorder: Mapped[User] = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<AttendanceLog id={self.id} student_id={self.student_id} "
            f"type={self.type} timestamp={self.timestamp}>"
        )


class LeaveRequest(Base, UUIDPkMixin, TimestampMixin):
    """Student hostel leave request and approval record."""

    __tablename__ = "leave_requests"
    __table_args__ = (
        Index(
            "ix_leave_requests_student_status_dates",
            "student_id",
            "status",
            "from_date",
            "to_date",
        ),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    to_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    status: Mapped[LeaveStatus] = mapped_column(
        Enum(LeaveStatus, native_enum=False, length=20),
        nullable=False,
        default=LeaveStatus.PENDING,
        index=True,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    review_notes: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    student: Mapped[StudentProfile] = relationship(
        "StudentProfile",
        back_populates="leave_requests",
    )
    reviewer: Mapped[User | None] = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<LeaveRequest id={self.id} student_id={self.student_id} "
            f"status={self.status} from_date={self.from_date} to_date={self.to_date}>"
        )


class Visitor(Base, UUIDPkMixin, TimestampMixin):
    """Hostel visitor entry and exit record."""

    __tablename__ = "visitors"
    __table_args__ = (
        Index("ix_visitors_student_active", "student_id", "check_out_at"),
        Index("ix_visitors_check_in_at", "check_in_at"),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    phone: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    relation: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    check_in_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )
    check_out_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    id_proof_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    id_proof_number: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    remarks: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    student: Mapped[StudentProfile] = relationship(
        "StudentProfile",
        back_populates="visitors",
    )

    @property
    def is_active(self) -> bool:
        """Return whether the visitor is currently checked in and on premise."""
        return self.check_out_at is None

    def __repr__(self) -> str:
        return (
            f"<Visitor id={self.id} student_id={self.student_id} "
            f"name={self.name} check_in_at={self.check_in_at}>"
        )
