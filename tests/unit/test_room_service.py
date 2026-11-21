"""Unit tests for RoomService business logic and access control."""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.models.hostel import Block, GenderType, Hostel, WardenAssignment
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.user import User
from app.repositories.hostel_repository import BlockRepository, HostelRepository
from app.schemas.common import PaginationParams
from app.schemas.room import RoomCreate, RoomUpdate
from app.services.hostel_service import HostelService
from app.services.room_service import (
    RoomService,
    generate_bed_labels,
    index_to_label,
    label_to_index,
)


def test_label_generation_and_conversion() -> None:
    """Verify bed label generator and bidirectional index conversions."""
    labels = generate_bed_labels(4)
    assert labels == ["A", "B", "C", "D"]

    labels_28 = generate_bed_labels(28)
    assert labels_28[0] == "A"
    assert labels_28[25] == "Z"
    assert labels_28[26] == "AA"
    assert labels_28[27] == "AB"

    # Bidirectional conversions
    for i in [0, 1, 25, 26, 27, 51, 52]:
        lbl = index_to_label(i)
        assert label_to_index(lbl) == i


def test_recalculate_status() -> None:
    """Verify room status calculation preserves maintenance and handles occupancy."""
    room = Room(status=RoomStatus.MAINTENANCE, capacity=2)
    room.beds = [
        Bed(label="A", is_occupied=False),
        Bed(label="B", is_occupied=False),
    ]
    assert RoomService.recalculate_status(room) == RoomStatus.MAINTENANCE

    # All beds occupied -> FULL
    room_full = Room(status=RoomStatus.AVAILABLE, capacity=2)
    room_full.beds = [
        Bed(label="A", is_occupied=True),
        Bed(label="B", is_occupied=True),
    ]
    assert RoomService.recalculate_status(room_full) == RoomStatus.FULL

    # Partial occupancy -> AVAILABLE
    room_avail = Room(status=RoomStatus.FULL, capacity=2)
    room_avail.beds = [
        Bed(label="A", is_occupied=True),
        Bed(label="B", is_occupied=False),
    ]
    assert RoomService.recalculate_status(room_avail) == RoomStatus.AVAILABLE


@pytest.mark.asyncio
async def test_room_service_create_and_bed_generation(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Verify room creation auto-creates labeled beds matching capacity."""
    hostel_repo = HostelRepository(db_session)
    block_repo = BlockRepository(db_session)
    room_service = RoomService(db_session)

    hostel = await hostel_repo.create(
        Hostel(name="Svc Hostel", code="SVCH-01", gender_type=GenderType.MIXED)
    )
    block = await block_repo.create(Block(hostel_id=hostel.id, name="Block A", floor_count=2))

    data = RoomCreate(
        number="101",
        floor=1,
        room_type=RoomType.DOUBLE,
        capacity=2,
        monthly_rent=Decimal("4000.00"),
    )
    room = await room_service.create_room(block.id, data, admin_user)

    assert room.number == "101"
    assert room.capacity == 2
    assert len(room.beds) == 2
    assert [b.label for b in room.beds] == ["A", "B"]
    assert all(b.is_occupied is False for b in room.beds)

    # Duplicate room number in same block -> ConflictError
    with pytest.raises(ConflictError) as exc:
        await room_service.create_room(block.id, data, admin_user)
    assert exc.value.code == "ROOM_NUMBER_EXISTS"


@pytest.mark.asyncio
async def test_room_service_capacity_change_rules(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Verify increasing and decreasing room capacity rules."""
    hostel_repo = HostelRepository(db_session)
    block_repo = BlockRepository(db_session)
    room_service = RoomService(db_session)

    hostel = await hostel_repo.create(
        Hostel(name="Capacity Rule Hostel", code="CRH-01", gender_type=GenderType.MIXED)
    )
    block = await block_repo.create(Block(hostel_id=hostel.id, name="Block B", floor_count=2))

    # Create double room (beds A, B)
    room = await room_service.create_room(
        block.id,
        RoomCreate(
            number="201",
            floor=2,
            room_type=RoomType.DOUBLE,
            capacity=2,
            monthly_rent=Decimal("4000.00"),
        ),
        admin_user,
    )
    assert len(room.beds) == 2

    # Increase capacity to 4 (room_type=DORM) -> beds C, D added
    updated_dorm = await room_service.update_room(
        room.id,
        RoomUpdate(room_type=RoomType.DORM, capacity=4),
        admin_user,
    )
    assert updated_dorm.capacity == 4
    assert len(updated_dorm.beds) == 4
    assert [b.label for b in updated_dorm.beds] == ["A", "B", "C", "D"]

    # Decrease capacity to 3 (room_type=TRIPLE) when unoccupied -> bed D removed
    updated_triple = await room_service.update_room(
        room.id,
        RoomUpdate(room_type=RoomType.TRIPLE, capacity=3),
        admin_user,
    )
    assert updated_triple.capacity == 3
    assert len(updated_triple.beds) == 3
    assert [b.label for b in updated_triple.beds] == ["A", "B", "C"]

    # Mark bed C as occupied directly
    bed_c = next(b for b in updated_triple.beds if b.label == "C")
    bed_c.is_occupied = True
    await db_session.flush()

    # Attempt to decrease capacity to 2 (which would remove occupied bed C) -> BusinessRuleError
    with pytest.raises(BusinessRuleError) as exc:
        await room_service.update_room(
            room.id,
            RoomUpdate(room_type=RoomType.DOUBLE, capacity=2),
            admin_user,
        )
    assert exc.value.code == "BEDS_OCCUPIED"
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_room_service_maintenance_and_available(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Verify toggling room maintenance and available status."""
    hostel_repo = HostelRepository(db_session)
    block_repo = BlockRepository(db_session)
    room_service = RoomService(db_session)

    hostel = await hostel_repo.create(
        Hostel(name="Toggle Hostel", code="TH-01", gender_type=GenderType.MIXED)
    )
    block = await block_repo.create(Block(hostel_id=hostel.id, name="Block T", floor_count=1))
    room = await room_service.create_room(
        block.id,
        RoomCreate(
            number="301",
            floor=1,
            room_type=RoomType.SINGLE,
            capacity=1,
            monthly_rent=Decimal("3000.00"),
        ),
        admin_user,
    )
    assert room.status == RoomStatus.AVAILABLE

    # Set maintenance
    m_room = await room_service.set_maintenance(room.id, admin_user)
    assert m_room.status == RoomStatus.MAINTENANCE

    # Restore to available
    a_room = await room_service.set_available(room.id, admin_user)
    assert a_room.status == RoomStatus.AVAILABLE


@pytest.mark.asyncio
async def test_room_service_scoping(
    db_session: AsyncSession, warden_user: User, student_user: User
) -> None:
    """Verify warden scoping: assigned warden can manage, unassigned or student cannot."""
    hostel_repo = HostelRepository(db_session)
    block_repo = BlockRepository(db_session)
    room_service = RoomService(db_session)

    hostel1 = await hostel_repo.create(
        Hostel(name="Assigned Hostel", code="AH-01", gender_type=GenderType.MIXED)
    )
    hostel2 = await hostel_repo.create(
        Hostel(name="Other Hostel", code="OH-01", gender_type=GenderType.MIXED)
    )

    block1 = await block_repo.create(Block(hostel_id=hostel1.id, name="Block 1", floor_count=1))
    block2 = await block_repo.create(Block(hostel_id=hostel2.id, name="Block 2", floor_count=1))

    # Assign warden to hostel1
    db_session.add(WardenAssignment(hostel_id=hostel1.id, user_id=warden_user.id))
    await db_session.flush()

    # Assigned warden creates room in hostel1 -> ok
    room1 = await room_service.create_room(
        block1.id,
        RoomCreate(
            number="101",
            floor=1,
            room_type=RoomType.SINGLE,
            capacity=1,
            monthly_rent=Decimal("3000.00"),
        ),
        warden_user,
    )
    assert room1.number == "101"

    # Assigned warden attempts to create room in unassigned hostel2 -> ForbiddenError
    with pytest.raises(ForbiddenError):
        await room_service.create_room(
            block2.id,
            RoomCreate(
                number="101",
                floor=1,
                room_type=RoomType.SINGLE,
                capacity=1,
                monthly_rent=Decimal("3000.00"),
            ),
            warden_user,
        )

    # Student attempts to create room -> ForbiddenError
    with pytest.raises(ForbiddenError):
        await room_service.create_room(
            block1.id,
            RoomCreate(
                number="102",
                floor=1,
                room_type=RoomType.SINGLE,
                capacity=1,
                monthly_rent=Decimal("3000.00"),
            ),
            student_user,
        )


@pytest.mark.asyncio
async def test_hostel_service_computes_real_total_capacity(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Verify HostelService.get_hostel and list_hostels compute real room capacity."""
    hostel_service = HostelService(db_session)
    room_service = RoomService(db_session)

    from app.schemas.hostel import BlockCreate, HostelCreate

    hostel = await hostel_service.create_hostel(
        HostelCreate(name="Real Cap Hostel", code="RCH-01", gender_type=GenderType.MIXED)
    )
    block = await hostel_service.create_block(
        hostel.id,
        BlockCreate(name="Main Block", floor_count=2),
    )

    # Initially total_capacity is 0
    h_init = await hostel_service.get_hostel(hostel.id)
    assert h_init.total_capacity == 0

    # Add room of capacity 2
    await room_service.create_room(
        block.id,
        RoomCreate(
            number="101",
            floor=1,
            room_type=RoomType.DOUBLE,
            capacity=2,
            monthly_rent=Decimal("4000.00"),
        ),
        admin_user,
    )

    # Add room of capacity 3
    await room_service.create_room(
        block.id,
        RoomCreate(
            number="102",
            floor=1,
            room_type=RoomType.TRIPLE,
            capacity=3,
            monthly_rent=Decimal("3500.00"),
        ),
        admin_user,
    )

    # get_hostel now returns total_capacity == 5
    h_updated = await hostel_service.get_hostel(hostel.id)
    assert h_updated.total_capacity == 5

    # list_hostels also returns total_capacity == 5
    page = await hostel_service.list_hostels(PaginationParams(page=1, size=10))
    matching = next(h for h in page.items if h.id == hostel.id)
    assert matching.total_capacity == 5


@pytest.mark.asyncio
async def test_room_service_edge_cases_and_queries(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Verify edge cases: missing block/room, duplicate update, and field updates."""
    from app.schemas.hostel import BlockCreate, HostelCreate

    hostel_service = HostelService(db_session)
    room_service = RoomService(db_session)

    hostel = await hostel_service.create_hostel(
        HostelCreate(name="Edge Hostel", code="EH-01", gender_type=GenderType.MIXED)
    )
    block = await hostel_service.create_block(
        hostel.id,
        BlockCreate(name="Block Edge", floor_count=3),
    )

    # create_room with nonexistent block -> NotFoundError
    with pytest.raises(NotFoundError) as exc_b:
        await room_service.create_room(
            uuid4(),
            RoomCreate(
                number="999",
                floor=1,
                room_type=RoomType.SINGLE,
                capacity=1,
                monthly_rent=Decimal("2000.00"),
            ),
            admin_user,
        )
    assert exc_b.value.code == "BLOCK_NOT_FOUND"

    # Create two rooms
    r1 = await room_service.create_room(
        block.id,
        RoomCreate(
            number="101",
            floor=1,
            room_type=RoomType.SINGLE,
            capacity=1,
            monthly_rent=Decimal("2000.00"),
        ),
        admin_user,
    )
    r2 = await room_service.create_room(
        block.id,
        RoomCreate(
            number="102",
            floor=1,
            room_type=RoomType.DOUBLE,
            capacity=2,
            monthly_rent=Decimal("3000.00"),
        ),
        admin_user,
    )

    # Update r2 number to existing r1 number -> ConflictError
    with pytest.raises(ConflictError) as exc_dup:
        await room_service.update_room(r2.id, RoomUpdate(number="101"), admin_user)
    assert exc_dup.value.code == "ROOM_NUMBER_EXISTS"

    # Update r1 floor, rent, status
    r1_updated = await room_service.update_room(
        r1.id,
        RoomUpdate(
            floor=2,
            monthly_rent=Decimal("2500.00"),
            status=RoomStatus.MAINTENANCE,
        ),
        admin_user,
    )
    assert r1_updated.floor == 2
    assert r1_updated.monthly_rent == Decimal("2500.00")
    assert r1_updated.status == RoomStatus.MAINTENANCE

    # get_room nonexistent -> NotFoundError
    with pytest.raises(NotFoundError) as exc_r:
        await room_service.get_room(uuid4(), admin_user)
    assert exc_r.value.code == "ROOM_NOT_FOUND"

    # list_rooms
    room_page = await room_service.list_rooms(
        block.id, PaginationParams(page=1, size=10), admin_user
    )
    assert room_page.total == 2

    # list_rooms nonexistent block -> NotFoundError
    with pytest.raises(NotFoundError):
        await room_service.list_rooms(uuid4(), PaginationParams(page=1, size=10), admin_user)

    # list_beds
    beds = await room_service.list_beds(r2.id, admin_user)
    assert len(beds) == 2

    # search_available_rooms
    search_page = await room_service.search_available_rooms(hostel_id=hostel.id)
    assert search_page.total >= 1

    # delete_room
    await room_service.delete_room(r1.id, admin_user)
    with pytest.raises(NotFoundError):
        await room_service.get_room(r1.id, admin_user)
