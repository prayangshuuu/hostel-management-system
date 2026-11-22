"""Unit tests for Mess menu and Meal opt-out Pydantic v2 schemas."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.models.mess import MealType
from app.schemas.mess import (
    DailyMenuRead,
    HostelDailyHeadcountResponse,
    MealHeadcountItem,
    MealOptOutCreate,
    MealOptOutRead,
    MessMenuBulkUpdateRequest,
    MessMenuItemCreate,
    MessMenuItemRead,
    WeeklyMenuRead,
)


def test_mess_menu_item_create_valid() -> None:
    """Verify MessMenuItemCreate schema with valid attributes."""
    schema = MessMenuItemCreate(
        day_of_week=0,
        meal_type=MealType.BREAKFAST,
        items=["Pancakes", "Syrup", "Orange Juice"],
    )
    assert schema.day_of_week == 0
    assert schema.meal_type == MealType.BREAKFAST
    assert schema.items == ["Pancakes", "Syrup", "Orange Juice"]


@pytest.mark.parametrize("invalid_day", [-1, 7, 10])
def test_mess_menu_item_create_invalid_day(invalid_day: int) -> None:
    """Verify day_of_week must be between 0 and 6."""
    with pytest.raises(ValidationError) as exc:
        MessMenuItemCreate(
            day_of_week=invalid_day,
            meal_type=MealType.LUNCH,
            items=["Rice", "Dal"],
        )
    assert "day_of_week" in str(exc.value)


def test_mess_menu_item_create_empty_items() -> None:
    """Verify items cannot be empty."""
    with pytest.raises(ValidationError) as exc:
        MessMenuItemCreate(
            day_of_week=2,
            meal_type=MealType.DINNER,
            items=[],
        )
    assert "items" in str(exc.value)


def test_mess_menu_bulk_update_request() -> None:
    """Verify MessMenuBulkUpdateRequest holds a list of entries."""
    entry1 = MessMenuItemCreate(day_of_week=0, meal_type=MealType.BREAKFAST, items=["Eggs"])
    entry2 = MessMenuItemCreate(day_of_week=0, meal_type=MealType.LUNCH, items=["Curry"])
    req = MessMenuBulkUpdateRequest(entries=[entry1, entry2])
    assert len(req.entries) == 2
    assert req.entries[0].meal_type == MealType.BREAKFAST


def test_weekly_menu_read_schedule_auto_populated() -> None:
    """Verify WeeklyMenuRead automatically aggregates items into schedule dict."""
    hostel_id = uuid.uuid4()
    now = datetime.now(UTC)
    items = [
        MessMenuItemRead(
            id=uuid.uuid4(),
            hostel_id=hostel_id,
            day_of_week=0,
            meal_type=MealType.BREAKFAST,
            items=["Oats", "Milk"],
            created_at=now,
            updated_at=now,
        ),
        MessMenuItemRead(
            id=uuid.uuid4(),
            hostel_id=hostel_id,
            day_of_week=0,
            meal_type=MealType.LUNCH,
            items=["Rice", "Beans"],
            created_at=now,
            updated_at=now,
        ),
        MessMenuItemRead(
            id=uuid.uuid4(),
            hostel_id=hostel_id,
            day_of_week=1,
            meal_type=MealType.DINNER,
            items=["Salad", "Soup"],
            created_at=now,
            updated_at=now,
        ),
    ]

    weekly = WeeklyMenuRead(hostel_id=hostel_id, items=items)
    assert weekly.hostel_id == hostel_id
    assert len(weekly.items) == 3
    assert 0 in weekly.schedule
    assert weekly.schedule[0]["breakfast"] == ["Oats", "Milk"]
    assert weekly.schedule[0]["lunch"] == ["Rice", "Beans"]
    assert 1 in weekly.schedule
    assert weekly.schedule[1]["dinner"] == ["Salad", "Soup"]


def test_daily_menu_read() -> None:
    """Verify DailyMenuRead schema initialization."""
    hostel_id = uuid.uuid4()
    today = date(2026, 11, 22)
    daily = DailyMenuRead(
        hostel_id=hostel_id,
        date=today,
        day_of_week=6,
        meals={"breakfast": ["Pancakes"], "dinner": ["Pasta"]},
    )
    assert daily.hostel_id == hostel_id
    assert daily.date == today
    assert daily.day_of_week == 6
    assert "breakfast" in daily.meals


def test_meal_opt_out_schemas() -> None:
    """Verify MealOptOutCreate and MealOptOutRead schemas."""
    create = MealOptOutCreate(date=date(2026, 11, 25), meal_type=MealType.DINNER)
    assert create.date == date(2026, 11, 25)
    assert create.meal_type == MealType.DINNER

    read = MealOptOutRead(
        id=uuid.uuid4(),
        student_id=uuid.uuid4(),
        date=date(2026, 11, 25),
        meal_type=MealType.DINNER,
        created_at=datetime.now(UTC),
    )
    assert read.meal_type == MealType.DINNER


def test_headcount_schemas() -> None:
    """Verify MealHeadcountItem and HostelDailyHeadcountResponse."""
    item = MealHeadcountItem(
        meal_type=MealType.LUNCH,
        allocated_count=50,
        opted_out_count=5,
        on_leave_count=3,
        expected_count=43,
    )
    assert item.allocated_count == 50
    assert item.expected_count == 43

    resp = HostelDailyHeadcountResponse(
        hostel_id=uuid.uuid4(),
        date=date(2026, 11, 22),
        meals=[item],
    )
    assert len(resp.meals) == 1
    assert resp.meals[0].meal_type == MealType.LUNCH
