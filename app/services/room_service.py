"""Room and Bed domain service managing lifecycle, capacity, and bed allocations."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
)
from app.models.room import Bed, Room, RoomStatus
from app.models.user import User
from app.repositories.hostel_repository import BlockRepository
from app.repositories.room_repository import BedRepository, RoomRepository
from app.schemas.common import Page, PaginationParams
from app.schemas.room import (
    RoomCreate,
    RoomRead,
    RoomUpdate,
    validate_capacity_for_room_type,
)
from app.services.hostel_service import ensure_hostel_access


def index_to_label(index: int) -> str:
    """Convert a 0-based integer index to an alphabetical label (A, B... Z, AA, AB...)."""
    chars: list[str] = []
    n = index + 1
    while n > 0:
        n -= 1
        chars.append(chr(ord("A") + (n % 26)))
        n //= 26
    return "".join(reversed(chars))


def label_to_index(label: str) -> int:
    """Convert an alphabetical label (A, B... Z, AA, AB...) back to a 0-based index."""
    result = 0
    for ch in label.strip().upper():
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result - 1


def generate_bed_labels(count: int) -> list[str]:
    """Generate sequential bed labels of requested count (e.g., A, B, C... Z, AA, AB...)."""
    return [index_to_label(i) for i in range(max(0, count))]


class RoomService:
    """Service handling room creation, bed management, status calculation, and searches."""

    def __init__(
        self,
        session: AsyncSession,
        room_repo: RoomRepository | None = None,
        bed_repo: BedRepository | None = None,
        block_repo: BlockRepository | None = None,
    ) -> None:
        self.session = session
        self.room_repo = room_repo or RoomRepository(session)
        self.bed_repo = bed_repo or BedRepository(session)
        self.block_repo = block_repo or BlockRepository(session)

    @staticmethod
    def recalculate_status(room: Room) -> RoomStatus:
        """Recalculate room status based on maintenance and bed occupancy."""
        if room.status == RoomStatus.MAINTENANCE:
            return RoomStatus.MAINTENANCE

        occupied_count = sum(1 for b in room.beds if b.is_occupied)
        if len(room.beds) > 0 and occupied_count >= len(room.beds):
            room.status = RoomStatus.FULL
        else:
            room.status = RoomStatus.AVAILABLE
        return room.status

    async def create_room(self, block_id: UUID, data: RoomCreate, current_user: User) -> Room:
        """Create a room inside a block and auto-generate labeled beds."""
        block = await self.block_repo.get_by_id(block_id)
        if block is None:
            raise NotFoundError("Block not found", code="BLOCK_NOT_FOUND")

        await ensure_hostel_access(self.session, current_user, block.hostel_id)

        existing = await self.room_repo.get_by_number(block_id, data.number, include_deleted=True)
        if existing is not None:
            raise ConflictError(
                "Room number already exists in this block",
                code="ROOM_NUMBER_EXISTS",
            )

        validate_capacity_for_room_type(data.room_type, data.capacity)

        room = Room(
            block_id=block_id,
            number=data.number,
            floor=data.floor,
            room_type=data.room_type,
            capacity=data.capacity,
            monthly_rent=data.monthly_rent,
            status=RoomStatus.AVAILABLE,
        )
        labels = generate_bed_labels(data.capacity)
        room.beds = [Bed(label=label, is_occupied=False) for label in labels]
        room = await self.room_repo.create(room)
        self.recalculate_status(room)
        return room

    async def update_room(self, room_id: UUID, data: RoomUpdate, current_user: User) -> Room:
        """Update room details and adjust beds if capacity changes."""
        room = await self.get_room(room_id, current_user)

        if data.number is not None and data.number.strip().lower() != room.number.strip().lower():
            existing = await self.room_repo.get_by_number(
                room.block_id, data.number, include_deleted=True
            )
            if existing is not None and existing.id != room.id:
                raise ConflictError(
                    "Room number already exists in this block",
                    code="ROOM_NUMBER_EXISTS",
                )
            room.number = data.number

        if data.floor is not None:
            room.floor = data.floor

        if data.monthly_rent is not None:
            room.monthly_rent = data.monthly_rent

        target_type = data.room_type if data.room_type is not None else room.room_type
        target_capacity = data.capacity if data.capacity is not None else room.capacity
        if data.room_type is not None or data.capacity is not None:
            validate_capacity_for_room_type(target_type, target_capacity)
            room.room_type = target_type

        if data.capacity is not None and data.capacity != room.capacity:
            sorted_beds = sorted(room.beds, key=lambda b: label_to_index(b.label))
            if data.capacity > room.capacity:
                new_labels = [index_to_label(i) for i in range(len(sorted_beds), data.capacity)]
                for lbl in new_labels:
                    room.beds.append(Bed(room_id=room.id, label=lbl, is_occupied=False))
                room.capacity = data.capacity
            else:
                surplus_beds = sorted_beds[data.capacity :]
                if any(b.is_occupied for b in surplus_beds):
                    raise BusinessRuleError(
                        "Cannot reduce capacity below occupied beds count",
                        code="BEDS_OCCUPIED",
                        status_code=400,
                    )
                for sb in surplus_beds:
                    room.beds.remove(sb)
                await self.bed_repo.delete_beds(surplus_beds)
                room.capacity = data.capacity

        if data.status is not None:
            room.status = data.status

        self.recalculate_status(room)
        return await self.room_repo.update(room)

    async def set_maintenance(self, room_id: UUID, current_user: User) -> Room:
        """Set room status to MAINTENANCE."""
        room = await self.get_room(room_id, current_user)
        room.status = RoomStatus.MAINTENANCE
        return await self.room_repo.update(room)

    async def set_available(self, room_id: UUID, current_user: User) -> Room:
        """Reset room from maintenance and recalculate status."""
        room = await self.get_room(room_id, current_user)
        room.status = RoomStatus.AVAILABLE
        self.recalculate_status(room)
        return await self.room_repo.update(room)

    async def delete_room(self, room_id: UUID, current_user: User) -> Room:
        """Soft delete a room."""
        room = await self.get_room(room_id, current_user)
        return await self.room_repo.soft_delete(room)

    async def get_room(self, room_id: UUID, current_user: User) -> Room:
        """Retrieve room with beds loaded, ensuring hostel access."""
        room = await self.room_repo.get_by_id(room_id, include_deleted=False, load_beds=True)
        if room is None:
            raise NotFoundError("Room not found", code="ROOM_NOT_FOUND")

        block = await self.block_repo.get_by_id(room.block_id)
        if block is None:
            raise NotFoundError("Block not found", code="BLOCK_NOT_FOUND")

        await ensure_hostel_access(self.session, current_user, block.hostel_id)
        return room

    async def list_rooms(
        self, block_id: UUID, params: PaginationParams, current_user: User
    ) -> Page[RoomRead]:
        """List paginated rooms in a block, ensuring hostel access."""
        block = await self.block_repo.get_by_id(block_id)
        if block is None:
            raise NotFoundError("Block not found", code="BLOCK_NOT_FOUND")

        await ensure_hostel_access(self.session, current_user, block.hostel_id)
        rooms, total = await self.room_repo.list_by_block(block_id, params)
        items = [RoomRead.model_validate(r) for r in rooms]
        return Page.create(items=items, total=total, params=params)

    async def list_beds(self, room_id: UUID, current_user: User) -> list[Bed]:
        """List all beds in a room, ensuring hostel access."""
        room = await self.get_room(room_id, current_user)
        return await self.bed_repo.list_by_room(room.id)


__all__ = [
    "RoomService",
    "generate_bed_labels",
    "index_to_label",
    "label_to_index",
]
