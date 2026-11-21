"""Unit tests for StudentProfile database model and user relationship."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.db.base import Base
from app.models.hostel import GenderType
from app.models.student import StudentProfile
from app.models.user import User, UserRole


def test_student_profile_model_attributes() -> None:
    """Verify StudentProfile model column attributes and constraints."""
    columns = StudentProfile.__table__.columns
    assert "id" in columns
    assert "user_id" in columns
    assert "student_no" in columns
    assert "gender" in columns
    assert "department" in columns
    assert "year" in columns
    assert "guardian_name" in columns
    assert "guardian_phone" in columns
    assert "emergency_contact" in columns
    assert "is_deleted" in columns
    assert "created_at" in columns
    assert "updated_at" in columns

    assert columns["id"].primary_key is True
    assert columns["user_id"].nullable is False
    assert columns["user_id"].unique is True
    assert columns["student_no"].nullable is False
    assert columns["student_no"].unique is True
    assert columns["gender"].nullable is False
    assert columns["department"].nullable is False
    assert columns["year"].nullable is False
    assert columns["guardian_name"].nullable is False
    assert columns["guardian_phone"].nullable is False
    assert columns["emergency_contact"].nullable is False
    assert columns["is_deleted"].nullable is False


def test_student_profile_repr() -> None:
    """Verify StudentProfile __repr__ formatting."""
    profile_id = uuid.uuid4()
    user_id = uuid.uuid4()
    profile = StudentProfile(
        id=profile_id,
        user_id=user_id,
        student_no="STU-2026-001",
        gender=GenderType.MALE,
        department="Computer Science",
        year=2,
        guardian_name="Parent Doe",
        guardian_phone="+1234567890",
        emergency_contact="+1987654321",
    )
    r = repr(profile)
    assert str(profile_id) in r
    assert "STU-2026-001" in r
    assert str(user_id) in r


@pytest.mark.asyncio
async def test_student_profile_crud_in_memory() -> None:
    """Verify StudentProfile model persistence and defaults in SQLite."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_maker() as session:
        user = User(
            email="student1@hostel.example.com",
            full_name="Alice Student",
            phone="+1112223333",
            hashed_password="hashed_pw_xyz",
            role=UserRole.STUDENT,
        )
        session.add(user)
        await session.flush()

        profile = StudentProfile(
            user_id=user.id,
            student_no="CS-2026-001",
            gender=GenderType.FEMALE,
            department="Computer Science",
            year=1,
            guardian_name="Eve Student",
            guardian_phone="+1112224444",
            emergency_contact="+1112225555",
        )
        session.add(profile)
        await session.commit()

        profile_id = profile.id
        user_id = user.id

    async with session_maker() as session:
        stmt = (
            select(StudentProfile)
            .where(StudentProfile.id == profile_id)
            .options(selectinload(StudentProfile.user))
        )
        result = await session.execute(stmt)
        fetched_profile = result.scalar_one()

        assert fetched_profile.student_no == "CS-2026-001"
        assert fetched_profile.gender == GenderType.FEMALE
        assert fetched_profile.department == "Computer Science"
        assert fetched_profile.year == 1
        assert fetched_profile.guardian_name == "Eve Student"
        assert fetched_profile.guardian_phone == "+1112224444"
        assert fetched_profile.emergency_contact == "+1112225555"
        assert fetched_profile.is_deleted is False
        assert fetched_profile.created_at is not None
        assert fetched_profile.updated_at is not None
        assert fetched_profile.user.id == user_id
        assert fetched_profile.user.email == "student1@hostel.example.com"

    # Verify bidirectional relationship from User
    async with session_maker() as session:
        user_stmt = (
            select(User).where(User.id == user_id).options(selectinload(User.student_profile))
        )
        u_res = await session.execute(user_stmt)
        fetched_user = u_res.scalar_one()
        assert fetched_user.student_profile is not None
        assert fetched_user.student_profile.student_no == "CS-2026-001"

    await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_student_no_rejected() -> None:
    """Verify unique constraint on student_no."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_maker() as session:
        u1 = User(
            email="u1@hostel.example.com",
            full_name="User 1",
            hashed_password="pw1",
            role=UserRole.STUDENT,
        )
        u2 = User(
            email="u2@hostel.example.com",
            full_name="User 2",
            hashed_password="pw2",
            role=UserRole.STUDENT,
        )
        session.add_all([u1, u2])
        await session.flush()

        p1 = StudentProfile(
            user_id=u1.id,
            student_no="STU-UNIQUE",
            gender=GenderType.MALE,
            department="Electrical",
            year=2,
            guardian_name="G1",
            guardian_phone="123",
            emergency_contact="456",
        )
        p2 = StudentProfile(
            user_id=u2.id,
            student_no="STU-UNIQUE",
            gender=GenderType.FEMALE,
            department="Mechanical",
            year=3,
            guardian_name="G2",
            guardian_phone="789",
            emergency_contact="012",
        )
        session.add(p1)
        await session.flush()

        session.add(p2)
        with pytest.raises(IntegrityError):
            await session.flush()

    await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_user_id_rejected() -> None:
    """Verify unique constraint on user_id (1-to-1 profile)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_maker() as session:
        u = User(
            email="one@hostel.example.com",
            full_name="User One",
            hashed_password="pw",
            role=UserRole.STUDENT,
        )
        session.add(u)
        await session.flush()

        p1 = StudentProfile(
            user_id=u.id,
            student_no="STU-001",
            gender=GenderType.MALE,
            department="Electrical",
            year=1,
            guardian_name="G1",
            guardian_phone="123",
            emergency_contact="456",
        )
        p2 = StudentProfile(
            user_id=u.id,
            student_no="STU-002",
            gender=GenderType.FEMALE,
            department="Civil",
            year=1,
            guardian_name="G2",
            guardian_phone="789",
            emergency_contact="012",
        )
        session.add(p1)
        await session.flush()

        session.add(p2)
        with pytest.raises(IntegrityError):
            await session.flush()

    await engine.dispose()


@pytest.mark.asyncio
async def test_user_deletion_cascades_to_student_profile() -> None:
    """Verify deleting a User deletes the associated StudentProfile."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_maker() as session:
        user = User(
            email="delete_me@hostel.example.com",
            full_name="Temporary User",
            hashed_password="pw",
            role=UserRole.STUDENT,
        )
        session.add(user)
        await session.flush()

        profile = StudentProfile(
            user_id=user.id,
            student_no="STU-DEL-01",
            gender=GenderType.MALE,
            department="Physics",
            year=4,
            guardian_name="G",
            guardian_phone="123",
            emergency_contact="456",
        )
        session.add(profile)
        await session.commit()

        # Delete user
        await session.delete(user)
        await session.commit()

        # Check profile is also deleted
        res = await session.execute(
            select(StudentProfile).where(StudentProfile.student_no == "STU-DEL-01")
        )
        assert res.scalar_one_or_none() is None

    await engine.dispose()
