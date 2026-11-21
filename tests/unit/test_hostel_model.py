"""Unit tests for Hostel, Block, and WardenAssignment database models."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.hostel import Block, GenderType, Hostel, WardenAssignment
from app.models.user import User, UserRole


def test_gender_type_enum_values() -> None:
    """Verify GenderType enum values."""
    assert GenderType.MALE.value == "male"
    assert GenderType.FEMALE.value == "female"
    assert GenderType.MIXED.value == "mixed"


def test_hostel_model_attributes() -> None:
    """Verify Hostel model column attributes and constraints."""
    columns = Hostel.__table__.columns
    assert "id" in columns
    assert "name" in columns
    assert "code" in columns
    assert "gender_type" in columns
    assert "address" in columns
    assert "is_deleted" in columns
    assert "created_at" in columns
    assert "updated_at" in columns

    assert columns["id"].primary_key is True
    assert columns["name"].nullable is False
    assert columns["code"].nullable is False
    assert columns["code"].unique is True
    assert columns["gender_type"].nullable is False
    assert columns["address"].nullable is True
    assert columns["is_deleted"].nullable is False


def test_block_model_attributes() -> None:
    """Verify Block model column attributes and constraints."""
    columns = Block.__table__.columns
    assert "id" in columns
    assert "hostel_id" in columns
    assert "name" in columns
    assert "floor_count" in columns
    assert "created_at" in columns
    assert "updated_at" in columns

    assert columns["id"].primary_key is True
    assert columns["hostel_id"].nullable is False
    assert columns["name"].nullable is False
    assert columns["floor_count"].nullable is False


def test_warden_assignment_model_attributes() -> None:
    """Verify WardenAssignment model column attributes and constraints."""
    columns = WardenAssignment.__table__.columns
    assert "id" in columns
    assert "user_id" in columns
    assert "hostel_id" in columns
    assert "created_at" in columns
    assert "updated_at" in columns

    assert columns["id"].primary_key is True
    assert columns["user_id"].nullable is False
    assert columns["hostel_id"].nullable is False


@pytest.mark.asyncio
async def test_hostel_and_block_crud_in_memory() -> None:
    """Verify Hostel, Block, and WardenAssignment persistence and relationships in SQLite."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    hostel_id = uuid.uuid4()
    user_id = uuid.uuid4()
    block_id = uuid.uuid4()
    assignment_id = uuid.uuid4()

    async with session_maker() as session:
        user = User(
            id=user_id,
            email="warden@example.com",
            full_name="Hostel Warden",
            hashed_password="pw",
            role=UserRole.WARDEN,
        )
        hostel = Hostel(
            id=hostel_id,
            name="Nelson Mandela Hall",
            code="NMH-01",
            gender_type=GenderType.MALE,
            address="123 University Road",
        )
        block = Block(
            id=block_id,
            hostel_id=hostel_id,
            name="Block A",
            floor_count=4,
        )
        assignment = WardenAssignment(
            id=assignment_id,
            user_id=user_id,
            hostel_id=hostel_id,
        )
        session.add_all([user, hostel, block, assignment])
        await session.commit()

    async with session_maker() as session:
        result = await session.execute(select(Hostel).where(Hostel.id == hostel_id))
        fetched_hostel = result.scalar_one()
        assert fetched_hostel.code == "NMH-01"
        assert fetched_hostel.name == "Nelson Mandela Hall"
        assert fetched_hostel.gender_type == GenderType.MALE
        assert fetched_hostel.is_deleted is False
        expected_hostel_repr = f"<Hostel id={hostel_id} code=NMH-01 name=Nelson Mandela Hall>"
        assert repr(fetched_hostel) == expected_hostel_repr

        result = await session.execute(select(Block).where(Block.id == block_id))
        fetched_block = result.scalar_one()
        assert fetched_block.name == "Block A"
        assert fetched_block.floor_count == 4
        assert repr(fetched_block) == f"<Block id={block_id} hostel_id={hostel_id} name=Block A>"

        result = await session.execute(
            select(WardenAssignment).where(WardenAssignment.id == assignment_id)
        )
        fetched_assignment = result.scalar_one()
        assert fetched_assignment.user_id == user_id
        assert fetched_assignment.hostel_id == hostel_id
        expected_assignment_repr = (
            f"<WardenAssignment id={assignment_id} user_id={user_id} hostel_id={hostel_id}>"
        )
        assert repr(fetched_assignment) == expected_assignment_repr

    await engine.dispose()


@pytest.mark.asyncio
async def test_block_unique_constraint_in_memory() -> None:
    """Verify unique constraint on (hostel_id, name) for blocks."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    hostel_id = uuid.uuid4()
    async with session_maker() as session:
        hostel = Hostel(
            id=hostel_id,
            name="Alpha Hall",
            code="AH-01",
        )
        block1 = Block(
            hostel_id=hostel_id,
            name="Block A",
        )
        block2 = Block(
            hostel_id=hostel_id,
            name="Block A",
        )
        session.add_all([hostel, block1, block2])
        with pytest.raises(IntegrityError):
            await session.commit()

    await engine.dispose()


@pytest.mark.asyncio
async def test_warden_assignment_unique_constraint_in_memory() -> None:
    """Verify unique constraint on (user_id, hostel_id) for warden assignments."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    hostel_id = uuid.uuid4()
    user_id = uuid.uuid4()
    async with session_maker() as session:
        user = User(
            id=user_id,
            email="warden2@example.com",
            full_name="Hostel Warden 2",
            hashed_password="pw",
            role=UserRole.WARDEN,
        )
        hostel = Hostel(
            id=hostel_id,
            name="Beta Hall",
            code="BH-01",
        )
        assign1 = WardenAssignment(
            user_id=user_id,
            hostel_id=hostel_id,
        )
        assign2 = WardenAssignment(
            user_id=user_id,
            hostel_id=hostel_id,
        )
        session.add_all([user, hostel, assign1, assign2])
        with pytest.raises(IntegrityError):
            await session.commit()

    await engine.dispose()
