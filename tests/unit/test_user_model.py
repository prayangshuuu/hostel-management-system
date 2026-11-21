"""Unit tests for User model and UserRole enum."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.user import User, UserRole


def test_user_role_enum_values() -> None:
    """Verify UserRole enum values."""
    assert UserRole.ADMIN.value == "admin"
    assert UserRole.WARDEN.value == "warden"
    assert UserRole.STUDENT.value == "student"


def test_user_model_attributes() -> None:
    """Verify User model column attributes and constraints."""
    columns = User.__table__.columns
    assert "id" in columns
    assert "email" in columns
    assert "full_name" in columns
    assert "phone" in columns
    assert "hashed_password" in columns
    assert "role" in columns
    assert "is_active" in columns
    assert "created_at" in columns
    assert "updated_at" in columns
    # Soft delete should not be on user
    assert "is_deleted" not in columns

    assert columns["id"].primary_key is True
    assert columns["email"].unique is True
    assert columns["email"].nullable is False
    assert columns["full_name"].nullable is False
    assert columns["hashed_password"].nullable is False
    assert columns["role"].nullable is False
    assert columns["is_active"].nullable is False


@pytest.mark.asyncio
async def test_user_crud_in_memory() -> None:
    """Verify User model persistence and defaults in SQLite."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    user_id = uuid.uuid4()
    async with session_maker() as session:
        user = User(
            id=user_id,
            email="warden@hostel.example.com",
            full_name="John Doe",
            phone="+1234567890",
            hashed_password="hashed_placeholder_pw",  # noqa: S106
            role=UserRole.WARDEN,
        )
        session.add(user)
        await session.commit()

    async with session_maker() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        fetched = result.scalar_one()
        assert fetched.id == user_id
        assert fetched.email == "warden@hostel.example.com"
        assert fetched.full_name == "John Doe"
        assert fetched.phone == "+1234567890"
        assert fetched.role == UserRole.WARDEN
        assert fetched.is_active is True
        assert fetched.created_at is not None
        assert fetched.updated_at is not None
        assert repr(fetched) == f"<User id={user_id} email=warden@hostel.example.com role=warden>"

    await engine.dispose()
