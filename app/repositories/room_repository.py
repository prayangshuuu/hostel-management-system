"""Room and Bed repositories for persistence operations."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.hostel import Block
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.schemas.common import PaginationParams


class RoomRepository:
    """Repository handling database operations for Room entity."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(
        self, id: UUID, include_deleted: bool = False, load_beds: bool = True
    ) -> Room | None:
        """Fetch a single room by primary key UUID."""
        stmt = select(Room).where(Room.id == id)
        if not include_deleted:
            stmt = stmt.where(Room.is_deleted.is_(False))
        if load_beds:
            stmt = stmt.options(selectinload(Room.beds))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_number(
        self, block_id: UUID, number: str, include_deleted: bool = False
    ) -> Room | None:
        """Fetch a room in a block by room number (case-insensitive)."""
        stmt = select(Room).where(
            Room.block_id == block_id,
            func.lower(Room.number) == number.strip().lower(),
        )
        if not include_deleted:
            stmt = stmt.where(Room.is_deleted.is_(False))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, room: Room) -> Room:
        """Add and flush a new room record."""
        self.session.add(room)
        await self.session.flush()
        await self.session.refresh(
            room,
            attribute_names=[
                "id",
                "number",
                "floor",
                "room_type",
                "capacity",
                "monthly_rent",
                "status",
                "is_deleted",
                "created_at",
                "updated_at",
            ],
        )
        return room

    async def update(self, room: Room) -> Room:
        """Flush changes to an existing room record."""
        await self.session.flush()
        await self.session.refresh(
            room,
            attribute_names=[
                "number",
                "floor",
                "room_type",
                "capacity",
                "monthly_rent",
                "status",
                "is_deleted",
                "created_at",
                "updated_at",
            ],
        )
        return room

    async def soft_delete(self, room: Room) -> Room:
        """Mark a room as deleted without physical row removal."""
        room.is_deleted = True
        await self.session.flush()
        await self.session.refresh(
            room,
            attribute_names=[
                "number",
                "floor",
                "room_type",
                "capacity",
                "monthly_rent",
                "status",
                "is_deleted",
                "created_at",
                "updated_at",
            ],
        )
        return room

    async def list_by_block(
        self, block_id: UUID, params: PaginationParams
    ) -> tuple[list[Room], int]:
        """Fetch a paginated list of non-deleted rooms for a given block."""
        stmt = (
            select(Room)
            .options(selectinload(Room.beds))
            .where(
                Room.block_id == block_id,
                Room.is_deleted.is_(False),
            )
        )
        count_stmt = select(func.count(Room.id)).where(
            Room.block_id == block_id,
            Room.is_deleted.is_(False),
        )

        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        stmt = stmt.order_by(Room.number.asc()).offset(params.offset).limit(params.limit)
        items_result = await self.session.execute(stmt)
        rooms = list(items_result.scalars().all())

        return rooms, total

    async def search_available(
        self,
        hostel_id: UUID | None = None,
        room_type: RoomType | None = None,
        floor: int | None = None,
        max_rent: Decimal | None = None,
        params: PaginationParams | None = None,
    ) -> tuple[list[Room], int]:
        """Search available rooms (not deleted, not maintenance, >=1 free bed)."""
        stmt = (
            select(Room)
            .options(selectinload(Room.beds))
            .where(
                Room.is_deleted.is_(False),
                Room.status != RoomStatus.MAINTENANCE,
                Room.beds.any(Bed.is_occupied.is_(False)),
            )
        )
        count_stmt = select(func.count(Room.id)).where(
            Room.is_deleted.is_(False),
            Room.status != RoomStatus.MAINTENANCE,
            Room.beds.any(Bed.is_occupied.is_(False)),
        )

        if hostel_id is not None:
            stmt = stmt.join(Block, Room.block_id == Block.id).where(Block.hostel_id == hostel_id)
            count_stmt = count_stmt.join(Block, Room.block_id == Block.id).where(
                Block.hostel_id == hostel_id
            )

        if room_type is not None:
            stmt = stmt.where(Room.room_type == room_type)
            count_stmt = count_stmt.where(Room.room_type == room_type)

        if floor is not None:
            stmt = stmt.where(Room.floor == floor)
            count_stmt = count_stmt.where(Room.floor == floor)

        if max_rent is not None:
            stmt = stmt.where(Room.monthly_rent <= max_rent)
            count_stmt = count_stmt.where(Room.monthly_rent <= max_rent)

        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        stmt = stmt.order_by(Room.created_at.desc())
        if params is not None:
            stmt = stmt.offset(params.offset).limit(params.limit)

        items_result = await self.session.execute(stmt)
        rooms = list(items_result.scalars().all())

        return rooms, total

    async def get_total_capacity_for_hostel(self, hostel_id: UUID) -> int:
        """Compute sum of capacities for active non-deleted rooms across all blocks of a hostel."""
        stmt = (
            select(func.coalesce(func.sum(Room.capacity), 0))
            .select_from(Room)
            .join(Block, Room.block_id == Block.id)
            .where(
                Block.hostel_id == hostel_id,
                Room.is_deleted.is_(False),
            )
        )
        result = await self.session.execute(stmt)
        return int(result.scalar() or 0)


class BedRepository:
    """Repository handling database operations for Bed entity."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, bed: Bed) -> Bed:
        """Add and flush a new bed record."""
        self.session.add(bed)
        await self.session.flush()
        return bed

    async def create_many(self, beds: list[Bed]) -> list[Bed]:
        """Add and flush multiple bed records."""
        self.session.add_all(beds)
        await self.session.flush()
        return beds

    async def get_by_id(self, id: UUID) -> Bed | None:
        """Fetch a single bed by primary key UUID."""
        stmt = select(Bed).where(Bed.id == id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, id: UUID) -> Bed | None:
        """Fetch a single bed by primary key UUID, locking the row on PostgreSQL."""
        stmt = select(Bed).where(Bed.id == id)
        bind = self.session.bind
        if bind and getattr(bind.dialect, "name", "") == "postgresql":
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update(self, bed: Bed) -> Bed:
        """Flush changes to an existing bed record."""
        await self.session.flush()
        return bed

    async def list_by_room(self, room_id: UUID) -> list[Bed]:
        """Fetch all beds for a given room ordered by label."""
        stmt = select(Bed).where(Bed.room_id == room_id).order_by(Bed.label.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_beds(self, beds: list[Bed]) -> None:
        """Delete multiple bed records."""
        for bed in beds:
            await self.session.delete(bed)
        await self.session.flush()
