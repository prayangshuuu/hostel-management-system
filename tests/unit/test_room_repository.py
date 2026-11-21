"""Unit tests for Room and Bed repositories."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hostel import Block, GenderType, Hostel
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.repositories.hostel_repository import BlockRepository, HostelRepository
from app.repositories.room_repository import BedRepository, RoomRepository
from app.schemas.common import PaginationParams


@pytest.mark.asyncio
async def test_room_repository_crud(db_session: AsyncSession) -> None:
    """Verify RoomRepository basic CRUD and soft deletion operations."""
    hostel_repo = HostelRepository(db_session)
    block_repo = BlockRepository(db_session)
    room_repo = RoomRepository(db_session)

    hostel = await hostel_repo.create(
        Hostel(name="Repo Hostel", code="RH-01", gender_type=GenderType.MIXED)
    )
    block = await block_repo.create(Block(hostel_id=hostel.id, name="Block R", floor_count=3))

    room = Room(
        block_id=block.id,
        number="101",
        floor=1,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("3500.00"),
        status=RoomStatus.AVAILABLE,
    )
    created = await room_repo.create(room)
    assert created.id is not None

    # get_by_id
    fetched = await room_repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.number == "101"

    # get_by_number
    by_num = await room_repo.get_by_number(block.id, "101")
    assert by_num is not None
    assert by_num.id == created.id

    # update
    created.floor = 2
    updated = await room_repo.update(created)
    assert updated.floor == 2

    # soft_delete
    deleted = await room_repo.soft_delete(created)
    assert deleted.is_deleted is True

    # get_by_id with include_deleted=False -> None
    assert await room_repo.get_by_id(created.id, include_deleted=False) is None
    # get_by_id with include_deleted=True -> found
    assert await room_repo.get_by_id(created.id, include_deleted=True) is not None


@pytest.mark.asyncio
async def test_room_repository_list_and_total_capacity(db_session: AsyncSession) -> None:
    """Verify list_by_block and get_total_capacity_for_hostel methods."""
    hostel_repo = HostelRepository(db_session)
    block_repo = BlockRepository(db_session)
    room_repo = RoomRepository(db_session)

    hostel = await hostel_repo.create(
        Hostel(name="Capacity Hostel", code="CH-01", gender_type=GenderType.MALE)
    )
    block = await block_repo.create(Block(hostel_id=hostel.id, name="Block C", floor_count=2))

    # Total capacity when empty -> 0
    cap_zero = await room_repo.get_total_capacity_for_hostel(hostel.id)
    assert cap_zero == 0

    await room_repo.create(
        Room(
            block_id=block.id,
            number="101",
            floor=1,
            room_type=RoomType.DOUBLE,
            capacity=2,
            monthly_rent=Decimal("4000.00"),
        )
    )
    room2 = await room_repo.create(
        Room(
            block_id=block.id,
            number="102",
            floor=1,
            room_type=RoomType.TRIPLE,
            capacity=3,
            monthly_rent=Decimal("3000.00"),
        )
    )

    cap_total = await room_repo.get_total_capacity_for_hostel(hostel.id)
    assert cap_total == 5

    # list_by_block
    params = PaginationParams(page=1, size=10)
    rooms, count = await room_repo.list_by_block(block.id, params)
    assert count == 2
    assert len(rooms) == 2

    # Soft delete room2 -> capacity decreases
    await room_repo.soft_delete(room2)
    assert await room_repo.get_total_capacity_for_hostel(hostel.id) == 2


@pytest.mark.asyncio
async def test_room_repository_search_available(db_session: AsyncSession) -> None:
    """Verify search_available filters and maintenance exclusion."""
    hostel_repo = HostelRepository(db_session)
    block_repo = BlockRepository(db_session)
    room_repo = RoomRepository(db_session)
    bed_repo = BedRepository(db_session)

    hostel = await hostel_repo.create(
        Hostel(name="Search Hostel", code="SH-01", gender_type=GenderType.MIXED)
    )
    block = await block_repo.create(Block(hostel_id=hostel.id, name="Block S", floor_count=3))

    # Room 1: available with free bed
    r1 = await room_repo.create(
        Room(
            block_id=block.id,
            number="101",
            floor=1,
            room_type=RoomType.SINGLE,
            capacity=1,
            monthly_rent=Decimal("5000.00"),
            status=RoomStatus.AVAILABLE,
        )
    )
    await bed_repo.create(Bed(room_id=r1.id, label="A", is_occupied=False))

    # Room 2: in maintenance (should be excluded)
    r2 = await room_repo.create(
        Room(
            block_id=block.id,
            number="102",
            floor=1,
            room_type=RoomType.DOUBLE,
            capacity=2,
            monthly_rent=Decimal("4000.00"),
            status=RoomStatus.MAINTENANCE,
        )
    )
    await bed_repo.create(Bed(room_id=r2.id, label="A", is_occupied=False))

    # Room 3: all beds occupied (should be excluded)
    r3 = await room_repo.create(
        Room(
            block_id=block.id,
            number="201",
            floor=2,
            room_type=RoomType.SINGLE,
            capacity=1,
            monthly_rent=Decimal("6000.00"),
            status=RoomStatus.FULL,
        )
    )
    await bed_repo.create(Bed(room_id=r3.id, label="A", is_occupied=True))

    # Search without filters
    results, total = await room_repo.search_available()
    assert total == 1
    assert results[0].id == r1.id

    # Filter by hostel_id
    res_h, _ = await room_repo.search_available(hostel_id=hostel.id)
    assert len(res_h) == 1

    # Filter by room_type
    res_type, _ = await room_repo.search_available(room_type=RoomType.SINGLE)
    assert len(res_type) == 1

    res_no_match, _ = await room_repo.search_available(room_type=RoomType.DORM)
    assert len(res_no_match) == 0

    # Filter by floor
    res_floor, _ = await room_repo.search_available(floor=1)
    assert len(res_floor) == 1

    # Filter by max_rent
    res_rent_low, _ = await room_repo.search_available(max_rent=Decimal("4000.00"))
    assert len(res_rent_low) == 0

    res_rent_ok, _ = await room_repo.search_available(max_rent=Decimal("5000.00"))
    assert len(res_rent_ok) == 1


@pytest.mark.asyncio
async def test_bed_repository_operations(db_session: AsyncSession) -> None:
    """Verify BedRepository methods."""
    hostel_repo = HostelRepository(db_session)
    block_repo = BlockRepository(db_session)
    room_repo = RoomRepository(db_session)
    bed_repo = BedRepository(db_session)

    hostel = await hostel_repo.create(
        Hostel(name="Bed Hostel", code="BH-01", gender_type=GenderType.FEMALE)
    )
    block = await block_repo.create(Block(hostel_id=hostel.id, name="Block B", floor_count=1))
    room = await room_repo.create(
        Room(
            block_id=block.id,
            number="101",
            floor=1,
            room_type=RoomType.DOUBLE,
            capacity=2,
            monthly_rent=Decimal("3000.00"),
        )
    )

    beds = [
        Bed(room_id=room.id, label="B", is_occupied=False),
        Bed(room_id=room.id, label="A", is_occupied=False),
    ]
    created_beds = await bed_repo.create_many(beds)
    assert len(created_beds) == 2

    # list_by_room ordered by label
    room_beds = await bed_repo.list_by_room(room.id)
    assert [b.label for b in room_beds] == ["A", "B"]

    # get_by_id
    b0 = await bed_repo.get_by_id(room_beds[0].id)
    assert b0 is not None
    assert b0.label == "A"

    # delete_beds
    await bed_repo.delete_beds([room_beds[1]])
    remaining = await bed_repo.list_by_room(room.id)
    assert len(remaining) == 1
    assert remaining[0].label == "A"
