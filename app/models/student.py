"""Student profile database model."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPkMixin
from app.models.hostel import GenderType

if TYPE_CHECKING:
    from app.models.allocation import Allocation
    from app.models.billing import Invoice
    from app.models.complaint import Complaint
    from app.models.operations import AttendanceLog, LeaveRequest, Visitor
    from app.models.user import User


class StudentProfile(Base, UUIDPkMixin, TimestampMixin, SoftDeleteMixin):
    """Student profile entity linked one-to-one with User."""

    __tablename__ = "student_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    student_no: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
    )
    gender: Mapped[GenderType] = mapped_column(
        Enum(GenderType, native_enum=False, length=20),
        nullable=False,
    )
    department: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    year: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    guardian_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    guardian_phone: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    emergency_contact: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    user: Mapped[User] = relationship(
        "User",
        back_populates="student_profile",
    )
    allocations: Mapped[list[Allocation]] = relationship(
        "Allocation",
        back_populates="student",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    invoices: Mapped[list[Invoice]] = relationship(
        "Invoice",
        back_populates="student",
    )
    attendance_logs: Mapped[list[AttendanceLog]] = relationship(
        "AttendanceLog",
        back_populates="student",
        cascade="all, delete-orphan",
    )
    leave_requests: Mapped[list[LeaveRequest]] = relationship(
        "LeaveRequest",
        back_populates="student",
        cascade="all, delete-orphan",
    )
    visitors: Mapped[list[Visitor]] = relationship(
        "Visitor",
        back_populates="student",
        cascade="all, delete-orphan",
    )
    complaints: Mapped[list[Complaint]] = relationship(
        "Complaint",
        back_populates="student",
        cascade="all, delete-orphan",
    )

    @property
    def current_allocation(self) -> Allocation | None:
        """Active allocation for this student profile, if populated."""
        return getattr(self, "_current_allocation", None)

    @current_allocation.setter
    def current_allocation(self, value: Allocation | None) -> None:
        self._current_allocation = value

    def __repr__(self) -> str:
        return f"<StudentProfile id={self.id} student_no={self.student_no} user_id={self.user_id}>"
