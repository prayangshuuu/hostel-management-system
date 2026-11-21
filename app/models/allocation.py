"""Allocation database model."""

from __future__ import annotations

import enum
import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, Enum, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.room import Bed
    from app.models.student import StudentProfile


class AllocationStatus(enum.StrEnum):
    """Allocation lifecycle statuses."""

    ACTIVE = "active"
    ENDED = "ended"
    CANCELLED = "cancelled"


class Allocation(Base, UUIDPkMixin, TimestampMixin):
    """Room bed allocation entity for a student."""

    __tablename__ = "allocations"
    __table_args__ = (
        Index(
            "uq_allocations_active_student",
            "student_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "uq_allocations_active_bed",
            "bed_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bed_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("beds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[AllocationStatus] = mapped_column(
        Enum(
            AllocationStatus,
            values_callable=lambda x: [str(e.value) for e in x],
            native_enum=False,
            length=20,
        ),
        nullable=False,
        default=AllocationStatus.ACTIVE,
        index=True,
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    student: Mapped[StudentProfile] = relationship(
        "StudentProfile",
        back_populates="allocations",
    )
    bed: Mapped[Bed] = relationship(
        "Bed",
        back_populates="allocations",
    )

    def __repr__(self) -> str:
        return (
            f"<Allocation id={self.id} student_id={self.student_id} "
            f"bed_id={self.bed_id} status={self.status}>"
        )
