"""Mess menu and meal opt-out database models."""

from __future__ import annotations

import enum
import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Date, Enum, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.hostel import Hostel
    from app.models.student import StudentProfile


class MealType(enum.StrEnum):
    """Meal types available in hostel mess."""

    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    SNACKS = "snacks"
    DINNER = "dinner"


class MessMenu(Base, UUIDPkMixin, TimestampMixin):
    """Weekly mess menu schedule per hostel."""

    __tablename__ = "mess_menus"
    __table_args__ = (
        UniqueConstraint(
            "hostel_id",
            "day_of_week",
            "meal_type",
            name="uq_mess_menus_hostel_day_meal",
        ),
    )

    hostel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("hostels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    day_of_week: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )  # 0=Monday, 6=Sunday
    meal_type: Mapped[MealType] = mapped_column(
        Enum(MealType, native_enum=False, length=20),
        nullable=False,
    )
    items: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    hostel: Mapped[Hostel] = relationship(
        "Hostel",
        back_populates="mess_menus",
    )

    def __repr__(self) -> str:
        return (
            f"<MessMenu id={self.id} hostel_id={self.hostel_id} "
            f"day_of_week={self.day_of_week} meal_type={self.meal_type}>"
        )


class MealOptOut(Base, UUIDPkMixin, TimestampMixin):
    """Meal opt-out entry for a student on a specific date."""

    __tablename__ = "meal_opt_outs"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "date",
            "meal_type",
            name="uq_meal_opt_outs_student_date_meal",
        ),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )
    meal_type: Mapped[MealType] = mapped_column(
        Enum(MealType, native_enum=False, length=20),
        nullable=False,
    )

    student: Mapped[StudentProfile] = relationship(
        "StudentProfile",
        back_populates="meal_opt_outs",
    )

    def __repr__(self) -> str:
        return (
            f"<MealOptOut id={self.id} student_id={self.student_id} "
            f"date={self.date} meal_type={self.meal_type}>"
        )
