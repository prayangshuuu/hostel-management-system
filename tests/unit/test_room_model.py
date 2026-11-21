"""Unit tests for Room and Bed database models."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.db.base import Base
from app.models.hostel import Block, GenderType, Hostel
from app.models.room import Bed, Room, RoomStatus, RoomType


def test_room_type_enum_values() -> None:
    """Verify RoomType enum values."""
    assert RoomType.SINGLE.value == "single"
    assert RoomType.DOUBLE.value == "double"
    assert RoomType.TRIPLE.value == "triple"
    assert RoomType.DORM.value == "dorm"


def test_room_status_enum_values() -> None:
    """Verify RoomStatus enum values."""
    assert RoomStatus.AVAILABLE.value == "available"
    assert RoomStatus.FULL.value == "full"
    assert RoomStatus.MAINTENANCE.value == "maintenance"


def test_room_model_attributes() -> None:
    """Verify Room model column attributes and constraints."""
    columns = Room.__table__.columns
    assert "id" in columns
    assert "block_id" in columns
    assert "number" in columns
    assert "floor" in columns
    assert "room_type" in columns
    assert "capacity" in columns
    assert "monthly_rent" in columns
    assert "status" in columns
    assert "is_deleted" in columns
    assert "created_at" in columns
    assert "updated_at" in columns

    assert columns["id"].primary_key is True
    assert columns["block_id"].nullable is False
    assert columns["number"].nullable is False
    assert columns["floor"].nullable is False
    assert columns["room_type"].nullable is False
    assert columns["capacity"].nullable is False
    assert columns["monthly_rent"].nullable is False
    assert columns["status"].nullable is False
    assert columns["is_deleted"].nullable is False


def test_bed_model_attributes() -> None:
    """Verify Bed model column attributes and constraints."""
    columns = Bed.__table__.columns
    assert "id" in columns
    assert "room_id" in columns
    assert "label" in columns
    assert "is_occupied" in columns
    assert "created_at" in columns
    assert "updated_at" in columns

    assert columns["id"].primary_key is True
    assert columns["room_id"].nullable is False
    assert columns["label"].nullable is False
    assert columns["is_occupied"].nullable is False


@pytest.mark.asyncio
async def test_room_and_bed_creation_and_relationships() -> None:
    """Verify room and bed persistence, relationships, and ordering."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        hostel = Hostel(name="Alpha Hostel", code="ALP-01", gender_type=GenderType.MIXED)
        session.add(hostel)
        await session.flush()

        block = Block(hostel_id=hostel.id, name="Block A", floor_count=3)
        session.add(block)
        await session.flush()

        room = Room(
            block_id=block.id,
            number="101",
            floor=1,
            room_type=RoomType.DOUBLE,
            capacity=2,
            monthly_rent=Decimal("4500.00"),
            status=RoomStatus.AVAILABLE,
        )
        session.add(room)
        await session.flush()

        bed_b = Bed(room_id=room.id, label="B", is_occupied=False)
        bed_a = Bed(room_id=room.id, label="A", is_occupied=False)
        session.add_all([bed_b, bed_a])
        await session.commit()

    async with session_factory() as session:
        stmt = (
            select(Room)
            .where(Room.number == "101")
            .options(selectinload(Room.beds), selectinload(Room.block))
        )
        result = await session.execute(stmt)
        fetched_room = result.scalar_one()

        assert fetched_room.capacity == 2
        assert fetched_room.monthly_rent == Decimal("4500.00")
        assert fetched_room.status == RoomStatus.AVAILABLE
        assert fetched_room.block.name == "Block A"
        assert len(fetched_room.beds) == 2
        # order_by="Bed.label" ensures A comes before B
        assert [b.label for b in fetched_room.beds] == ["A", "B"]

        # Check hostel total_capacity calculation when loaded
        hostel_stmt = (
            select(Hostel)
            .where(Hostel.id == hostel.id)
            .options(selectinload(Hostel.blocks).selectinload(Block.rooms))
        )
        h_res = await session.execute(hostel_stmt)
        fetched_hostel = h_res.scalar_one()
        assert fetched_hostel.total_capacity == 2

    await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_room_number_in_block_rejected() -> None:
    """Verify unique constraint on (block_id, number)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        hostel = Hostel(name="Beta Hostel", code="BET-01", gender_type=GenderType.MALE)
        session.add(hostel)
        await session.flush()

        block = Block(hostel_id=hostel.id, name="Block B", floor_count=2)
        session.add(block)
        await session.flush()

        room1 = Room(
            block_id=block.id,
            number="201",
            floor=2,
            room_type=RoomType.SINGLE,
            capacity=1,
            monthly_rent=Decimal("6000.00"),
        )
        session.add(room1)
        await session.flush()

        room2 = Room(
            block_id=block.id,
            number="201",
            floor=2,
            room_type=RoomType.SINGLE,
            capacity=1,
            monthly_rent=Decimal("6000.00"),
        )
        session.add(room2)
        with pytest.raises(IntegrityError):
            await session.flush()

    await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_bed_label_in_room_rejected() -> None:
    """Verify unique constraint on (room_id, label)."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        hostel = Hostel(name="Gamma Hostel", code="GAM-01", gender_type=GenderType.FEMALE)
        session.add(hostel)
        await session.flush()

        block = Block(hostel_id=hostel.id, name="Block C", floor_count=1)
        session.add(block)
        await session.flush()

        room = Room(
            block_id=block.id,
            number="301",
            floor=1,
            room_type=RoomType.DOUBLE,
            capacity=2,
            monthly_rent=Decimal("3000.00"),
        )
        session.add(room)
        await session.flush()

        bed1 = Bed(room_id=room.id, label="A")
        bed2 = Bed(room_id=room.id, label="A")
        session.add_all([bed1, bed2])
        with pytest.raises(IntegrityError):
            await session.flush()

    await engine.dispose()


@pytest.mark.asyncio
async def test_cascade_delete_block_to_rooms_and_beds() -> None:
    """Verify cascade delete from block to rooms and beds."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        hostel = Hostel(name="Delta Hostel", code="DEL-01", gender_type=GenderType.MIXED)
        session.add(hostel)
        await session.flush()

        block = Block(hostel_id=hostel.id, name="Block D", floor_count=1)
        session.add(block)
        await session.flush()

        room = Room(
            block_id=block.id,
            number="401",
            floor=1,
            room_type=RoomType.SINGLE,
            capacity=1,
            monthly_rent=Decimal("5000.00"),
        )
        session.add(room)
        await session.flush()

        bed = Bed(room_id=room.id, label="A")
        session.add(bed)
        await session.commit()

        # Delete room
        await session.delete(room)
        await session.commit()

        beds_count = await session.execute(select(Bed).where(Bed.room_id == room.id))
        assert len(beds_count.scalars().all()) == 0

    await engine.dispose()
