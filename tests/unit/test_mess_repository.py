"""Unit tests for MessMenuRepository and MealOptOutRepository."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hostel import GenderType, Hostel
from app.models.mess import MealOptOut, MealType
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.repositories.mess_repository import MealOptOutRepository, MessMenuRepository
from app.schemas.common import PaginationParams
from app.schemas.mess import MessMenuItemCreate


@pytest.fixture
async def sample_hostel(db_session: AsyncSession) -> Hostel:
    """Create a sample hostel for mess tests."""
    hostel = Hostel(
        name=f"Hostel {uuid.uuid4().hex[:6]}",
        code=f"H-{uuid.uuid4().hex[:4]}",
        gender_type=GenderType.MIXED,
    )
    db_session.add(hostel)
    await db_session.flush()
    return hostel


@pytest.fixture
async def sample_student(db_session: AsyncSession) -> StudentProfile:
    """Create a sample student profile for opt-out tests."""
    user = User(
        email=f"stu_{uuid.uuid4().hex[:6]}@example.com",
        full_name="Test Student",
        hashed_password="hash",
        role=UserRole.STUDENT,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    profile = StudentProfile(
        user_id=user.id,
        student_no=f"STU-{uuid.uuid4().hex[:6]}",
        gender=GenderType.MALE,
        department="Computer Science",
        year=1,
        guardian_name="Guardian",
        guardian_phone="1234567890",
        emergency_contact="0987654321",
    )
    db_session.add(profile)
    await db_session.flush()
    return profile


async def test_mess_menu_bulk_upsert_and_fetch(
    db_session: AsyncSession, sample_hostel: Hostel
) -> None:
    """Verify bulk upsert replaces, handles updates, deletes unmentioned, and is idempotent."""
    repo = MessMenuRepository(db_session)

    # Initial upsert: 3 entries
    entries_v1 = [
        MessMenuItemCreate(day_of_week=0, meal_type=MealType.BREAKFAST, items=["Bread", "Butter"]),
        MessMenuItemCreate(day_of_week=0, meal_type=MealType.LUNCH, items=["Rice", "Dal"]),
        MessMenuItemCreate(day_of_week=1, meal_type=MealType.DINNER, items=["Roti", "Paneer"]),
    ]
    items_v1 = await repo.bulk_upsert(sample_hostel.id, entries_v1)
    assert len(items_v1) == 3

    # Idempotent upsert with same entries retains same items
    items_v1_repeat = await repo.bulk_upsert(sample_hostel.id, entries_v1)
    assert len(items_v1_repeat) == 3
    assert {m.meal_type for m in items_v1_repeat} == {
        MealType.BREAKFAST,
        MealType.LUNCH,
        MealType.DINNER,
    }

    # Second upsert: update day 0 breakfast, remove day 0 lunch, add day 0 dinner
    entries_v2 = [
        MessMenuItemCreate(
            day_of_week=0, meal_type=MealType.BREAKFAST, items=["Pancakes", "Syrup"]
        ),
        MessMenuItemCreate(day_of_week=0, meal_type=MealType.DINNER, items=["Soup", "Bread"]),
        MessMenuItemCreate(day_of_week=1, meal_type=MealType.DINNER, items=["Roti", "Paneer"]),
    ]
    items_v2 = await repo.bulk_upsert(sample_hostel.id, entries_v2)
    assert len(items_v2) == 3

    day0_items = await repo.get_by_hostel_and_day(sample_hostel.id, 0)
    assert len(day0_items) == 2
    day0_meals = {m.meal_type: m.items for m in day0_items}
    assert day0_meals[MealType.BREAKFAST] == ["Pancakes", "Syrup"]
    assert day0_meals[MealType.DINNER] == ["Soup", "Bread"]
    assert MealType.LUNCH not in day0_meals


async def test_meal_opt_out_crud(db_session: AsyncSession, sample_student: StudentProfile) -> None:
    """Verify CRUD methods on MealOptOutRepository."""
    repo = MealOptOutRepository(db_session)

    target_date = date(2026, 11, 25)
    opt_out = MealOptOut(
        student_id=sample_student.id,
        date=target_date,
        meal_type=MealType.DINNER,
    )
    created = await repo.create(opt_out)
    assert created.id is not None
    assert created.date == target_date

    fetched = await repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.student_id == sample_student.id

    by_date_meal = await repo.get_by_student_date_meal(
        sample_student.id, target_date, MealType.DINNER
    )
    assert by_date_meal is not None
    assert by_date_meal.id == created.id

    # Pagination list
    items, total = await repo.list_by_student(
        sample_student.id,
        PaginationParams(page=1, size=10),
    )
    assert total == 1
    assert len(items) == 1

    # Date filtered list
    items_filtered, total_filtered = await repo.list_by_student(
        sample_student.id,
        PaginationParams(page=1, size=10),
        date_from=date(2026, 12, 1),
    )
    assert total_filtered == 0
    assert len(items_filtered) == 0

    # Delete
    await repo.delete(created)
    assert await repo.get_by_id(created.id) is None
