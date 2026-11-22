"""Unit tests for MessMenu and MealOptOut database models."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import Table, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.hostel import GenderType, Hostel
from app.models.mess import MealOptOut, MealType, MessMenu
from app.models.student import StudentProfile
from app.models.user import User, UserRole


def test_meal_type_enum_values() -> None:
    """Verify MealType enum members and string values."""
    assert MealType.BREAKFAST.value == "breakfast"
    assert MealType.LUNCH.value == "lunch"
    assert MealType.SNACKS.value == "snacks"
    assert MealType.DINNER.value == "dinner"


def test_mess_menu_model_attributes() -> None:
    """Verify MessMenu model table structure, columns, constraints, and indexes."""
    table = MessMenu.__table__
    assert isinstance(table, Table)
    columns = table.columns

    assert "id" in columns
    assert "hostel_id" in columns
    assert "day_of_week" in columns
    assert "meal_type" in columns
    assert "items" in columns
    assert "created_at" in columns
    assert "updated_at" in columns

    assert columns["id"].primary_key is True
    assert columns["hostel_id"].nullable is False
    assert columns["day_of_week"].nullable is False
    assert columns["meal_type"].nullable is False
    assert columns["items"].nullable is False

    index_names = {idx.name for idx in table.indexes}
    assert "ix_mess_menus_hostel_id" in index_names

    uq_names = {uq.name for uq in table.constraints if type(uq).__name__ == "UniqueConstraint"}
    assert "uq_mess_menus_hostel_day_meal" in uq_names


def test_meal_opt_out_model_attributes() -> None:
    """Verify MealOptOut model table structure, columns, constraints, and indexes."""
    table = MealOptOut.__table__
    assert isinstance(table, Table)
    columns = table.columns

    assert "id" in columns
    assert "student_id" in columns
    assert "date" in columns
    assert "meal_type" in columns
    assert "created_at" in columns
    assert "updated_at" in columns

    assert columns["id"].primary_key is True
    assert columns["student_id"].nullable is False
    assert columns["date"].nullable is False
    assert columns["meal_type"].nullable is False

    index_names = {idx.name for idx in table.indexes}
    assert "ix_meal_opt_outs_student_id" in index_names
    assert "ix_meal_opt_outs_date" in index_names

    uq_names = {uq.name for uq in table.constraints if type(uq).__name__ == "UniqueConstraint"}
    assert "uq_meal_opt_outs_student_date_meal" in uq_names


def test_mess_models_repr() -> None:
    """Verify __repr__ implementations for MessMenu and MealOptOut."""
    menu_id = uuid.uuid4()
    hostel_id = uuid.uuid4()
    menu = MessMenu(
        id=menu_id,
        hostel_id=hostel_id,
        day_of_week=0,
        meal_type=MealType.BREAKFAST,
        items=["Oatmeal", "Bananas", "Coffee"],
    )
    menu_repr = repr(menu)
    assert f"<MessMenu id={menu_id}" in menu_repr
    assert f"hostel_id={hostel_id}" in menu_repr
    assert "day_of_week=0" in menu_repr
    assert "meal_type=MealType.BREAKFAST" in menu_repr or "breakfast" in menu_repr

    opt_out_id = uuid.uuid4()
    student_id = uuid.uuid4()
    opt_out = MealOptOut(
        id=opt_out_id,
        student_id=student_id,
        date=date(2026, 11, 23),
        meal_type=MealType.LUNCH,
    )
    opt_out_repr = repr(opt_out)
    assert f"<MealOptOut id={opt_out_id}" in opt_out_repr
    assert f"student_id={student_id}" in opt_out_repr
    assert "date=2026-11-23" in opt_out_repr
    assert "meal_type=MealType.LUNCH" in opt_out_repr or "lunch" in opt_out_repr


async def _create_test_fixtures(
    db_session: AsyncSession,
) -> tuple[Hostel, StudentProfile]:
    """Helper creating a test Hostel and StudentProfile."""
    uid = uuid.uuid4().hex[:8]

    hostel = Hostel(
        name=f"Hostel {uid}",
        code=f"H-{uid[:4]}",
        gender_type=GenderType.MIXED,
    )
    db_session.add(hostel)

    user = User(
        email=f"student_{uid}@example.com",
        full_name=f"Student {uid}",
        hashed_password="hash",
        role=UserRole.STUDENT,
    )
    db_session.add(user)
    await db_session.flush()

    student = StudentProfile(
        user_id=user.id,
        student_no=f"STU-{uid}",
        gender=GenderType.MIXED,
        department="Computer Science",
        year=2,
        guardian_name="Guardian Name",
        guardian_phone="+1234567890",
        emergency_contact="+1987654321",
    )
    db_session.add(student)
    await db_session.flush()

    return hostel, student


@pytest.mark.asyncio
async def test_mess_menu_crud_and_relationship(db_session: AsyncSession) -> None:
    """Verify MessMenu insertion, retrieval, hostel relationship, and cascade."""
    hostel, _ = await _create_test_fixtures(db_session)

    menu = MessMenu(
        hostel_id=hostel.id,
        day_of_week=0,
        meal_type=MealType.BREAKFAST,
        items=["Pancakes", "Syrup", "Milk"],
    )
    db_session.add(menu)
    await db_session.commit()

    # Query back
    result = await db_session.execute(
        select(Hostel).options(selectinload(Hostel.mess_menus)).where(Hostel.id == hostel.id)
    )
    loaded_hostel = result.scalar_one()
    assert len(loaded_hostel.mess_menus) == 1
    assert loaded_hostel.mess_menus[0].meal_type == MealType.BREAKFAST
    assert loaded_hostel.mess_menus[0].items == ["Pancakes", "Syrup", "Milk"]
    assert loaded_hostel.mess_menus[0].hostel.id == hostel.id

    # Test cascade delete
    await db_session.delete(loaded_hostel)
    await db_session.commit()

    menu_check = await db_session.execute(select(MessMenu).where(MessMenu.id == menu.id))
    assert menu_check.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_mess_menu_unique_constraint(db_session: AsyncSession) -> None:
    """Verify unique constraint on (hostel_id, day_of_week, meal_type)."""
    hostel, _ = await _create_test_fixtures(db_session)

    menu1 = MessMenu(
        hostel_id=hostel.id,
        day_of_week=1,
        meal_type=MealType.LUNCH,
        items=["Rice", "Curry"],
    )
    db_session.add(menu1)
    await db_session.commit()

    menu2 = MessMenu(
        hostel_id=hostel.id,
        day_of_week=1,
        meal_type=MealType.LUNCH,
        items=["Sandwich"],
    )
    db_session.add(menu2)
    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_meal_opt_out_crud_and_relationship(db_session: AsyncSession) -> None:
    """Verify MealOptOut insertion, retrieval, student relationship, and cascade."""
    _, student = await _create_test_fixtures(db_session)

    opt_out = MealOptOut(
        student_id=student.id,
        date=date(2026, 11, 25),
        meal_type=MealType.DINNER,
    )
    db_session.add(opt_out)
    await db_session.commit()

    result = await db_session.execute(
        select(StudentProfile)
        .options(selectinload(StudentProfile.meal_opt_outs))
        .where(StudentProfile.id == student.id)
    )
    loaded_student = result.scalar_one()
    assert len(loaded_student.meal_opt_outs) == 1
    assert loaded_student.meal_opt_outs[0].date == date(2026, 11, 25)
    assert loaded_student.meal_opt_outs[0].meal_type == MealType.DINNER
    assert loaded_student.meal_opt_outs[0].student.id == student.id

    # Test cascade delete
    await db_session.delete(loaded_student)
    await db_session.commit()

    opt_out_check = await db_session.execute(select(MealOptOut).where(MealOptOut.id == opt_out.id))
    assert opt_out_check.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_meal_opt_out_unique_constraint(db_session: AsyncSession) -> None:
    """Verify unique constraint on (student_id, date, meal_type)."""
    _, student = await _create_test_fixtures(db_session)

    opt_out1 = MealOptOut(
        student_id=student.id,
        date=date(2026, 11, 26),
        meal_type=MealType.BREAKFAST,
    )
    db_session.add(opt_out1)
    await db_session.commit()

    opt_out2 = MealOptOut(
        student_id=student.id,
        date=date(2026, 11, 26),
        meal_type=MealType.BREAKFAST,
    )
    db_session.add(opt_out2)
    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()
