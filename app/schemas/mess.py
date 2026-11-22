"""Mess menu and meal opt-out Pydantic schemas."""

from __future__ import annotations

from datetime import date, datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.mess import MealType

__all__ = [
    "DailyMenuRead",
    "HostelDailyHeadcountResponse",
    "MealHeadcountItem",
    "MealOptOutCreate",
    "MealOptOutRead",
    "MealType",
    "MessMenuBulkUpdateRequest",
    "MessMenuItemCreate",
    "MessMenuItemRead",
    "WeeklyMenuRead",
]


class MessMenuItemCreate(BaseModel):
    """Payload to create or replace a mess menu item."""

    day_of_week: int = Field(ge=0, le=6, description="Day of week (0=Monday, 6=Sunday)")
    meal_type: MealType
    items: list[str] = Field(min_length=1, description="List of food items served")


class MessMenuBulkUpdateRequest(BaseModel):
    """Payload for bulk updating or replacing a hostel's weekly menu."""

    entries: list[MessMenuItemCreate] = Field(default_factory=list)


class MessMenuItemRead(BaseModel):
    """Representation of an individual mess menu item."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    hostel_id: UUID
    day_of_week: int
    meal_type: MealType
    items: list[str]
    created_at: datetime
    updated_at: datetime


class WeeklyMenuRead(BaseModel):
    """Full weekly mess menu schedule for a hostel."""

    model_config = ConfigDict(from_attributes=True)

    hostel_id: UUID
    items: list[MessMenuItemRead] = Field(default_factory=list)
    schedule: dict[int, dict[str, list[str]]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def populate_schedule(self) -> Self:
        """Populate schedule mapping if not provided."""
        if not self.schedule and self.items:
            sched: dict[int, dict[str, list[str]]] = {}
            for item in self.items:
                meal_key = (
                    item.meal_type.value
                    if hasattr(item.meal_type, "value")
                    else str(item.meal_type)
                )
                sched.setdefault(item.day_of_week, {})[meal_key] = item.items
            self.schedule = sched
        return self


class DailyMenuRead(BaseModel):
    """Mess menu schedule for a hostel on a specific day."""

    model_config = ConfigDict(from_attributes=True)

    hostel_id: UUID
    date: date
    day_of_week: int
    meals: dict[str, list[str]] = Field(default_factory=dict)


class MealOptOutCreate(BaseModel):
    """Payload for opting out of a specific meal."""

    date: date
    meal_type: MealType


class MealOptOutRead(BaseModel):
    """Representation of a student meal opt-out."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_id: UUID
    date: date
    meal_type: MealType
    created_at: datetime


class MealHeadcountItem(BaseModel):
    """Headcount breakdown for a specific meal."""

    meal_type: MealType
    allocated_count: int
    opted_out_count: int
    on_leave_count: int
    expected_count: int


class HostelDailyHeadcountResponse(BaseModel):
    """Daily expected meal headcount for a hostel."""

    hostel_id: UUID
    date: date
    meals: list[MealHeadcountItem] = Field(default_factory=list)
