"""Repository layer for hostel, block, and warden assignment entities."""

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.hostel import Block, GenderType, Hostel, WardenAssignment
from app.schemas.common import PaginationParams


class HostelRepository:
    """Repository handling database operations for the Hostel entity."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, id: UUID, include_deleted: bool = False) -> Hostel | None:
        """Fetch a single hostel by primary key UUID."""
        stmt = select(Hostel).where(Hostel.id == id)
        if not include_deleted:
            stmt = stmt.where(Hostel.is_deleted.is_(False))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_code(self, code: str, include_deleted: bool = False) -> Hostel | None:
        """Fetch a hostel by code (case-insensitive)."""
        stmt = select(Hostel).where(func.lower(Hostel.code) == code.strip().lower())
        if not include_deleted:
            stmt = stmt.where(Hostel.is_deleted.is_(False))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, hostel: Hostel) -> Hostel:
        """Add and flush a new hostel record."""
        self.session.add(hostel)
        await self.session.flush()
        await self.session.refresh(hostel)
        return hostel

    async def update(self, hostel: Hostel) -> Hostel:
        """Flush changes to an existing hostel record."""
        await self.session.flush()
        await self.session.refresh(hostel)
        return hostel

    async def soft_delete(self, hostel: Hostel) -> Hostel:
        """Mark a hostel as deleted without physical row removal."""
        hostel.is_deleted = True
        await self.session.flush()
        await self.session.refresh(hostel)
        return hostel

    async def list(
        self,
        params: PaginationParams,
        gender_type: GenderType | None = None,
        search: str | None = None,
    ) -> tuple[list[Hostel], int]:
        """Fetch a paginated list of non-deleted hostels matching optional filters."""
        stmt = select(Hostel).where(Hostel.is_deleted.is_(False))
        count_stmt = select(func.count(Hostel.id)).where(Hostel.is_deleted.is_(False))

        if gender_type is not None:
            stmt = stmt.where(Hostel.gender_type == gender_type)
            count_stmt = count_stmt.where(Hostel.gender_type == gender_type)

        if search:
            search_pattern = f"%{search.strip().lower()}%"
            search_filter = or_(
                func.lower(Hostel.name).like(search_pattern),
                func.lower(Hostel.code).like(search_pattern),
                func.lower(Hostel.address).like(search_pattern),
            )
            stmt = stmt.where(search_filter)
            count_stmt = count_stmt.where(search_filter)

        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        stmt = stmt.order_by(Hostel.created_at.desc()).offset(params.offset).limit(params.limit)
        items_result = await self.session.execute(stmt)
        hostels = list(items_result.scalars().all())

        return hostels, total


class BlockRepository:
    """Repository handling database operations for the Block entity."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, id: UUID) -> Block | None:
        """Fetch a block by primary key UUID."""
        stmt = select(Block).where(Block.id == id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name(self, hostel_id: UUID, name: str) -> Block | None:
        """Fetch a block within a hostel by name (case-insensitive)."""
        stmt = select(Block).where(
            Block.hostel_id == hostel_id,
            func.lower(Block.name) == name.strip().lower(),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, block: Block) -> Block:
        """Add and flush a new block record."""
        self.session.add(block)
        await self.session.flush()
        await self.session.refresh(block)
        return block

    async def update(self, block: Block) -> Block:
        """Flush changes to an existing block record."""
        await self.session.flush()
        await self.session.refresh(block)
        return block

    async def delete(self, block: Block) -> None:
        """Hard delete a block record."""
        await self.session.delete(block)
        await self.session.flush()

    async def list_by_hostel(self, hostel_id: UUID) -> list[Block]:
        """Fetch all blocks for a given hostel ordered by name."""
        stmt = select(Block).where(Block.hostel_id == hostel_id).order_by(Block.name.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class WardenAssignmentRepository:
    """Repository handling database operations for WardenAssignment entity."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, hostel_id: UUID, user_id: UUID) -> WardenAssignment | None:
        """Fetch an assignment by hostel_id and user_id with user relationship eager-loaded."""
        stmt = (
            select(WardenAssignment)
            .options(selectinload(WardenAssignment.user))
            .where(
                WardenAssignment.hostel_id == hostel_id,
                WardenAssignment.user_id == user_id,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, id: UUID) -> WardenAssignment | None:
        """Fetch an assignment by primary key UUID with user relationship eager-loaded."""
        stmt = (
            select(WardenAssignment)
            .options(selectinload(WardenAssignment.user))
            .where(WardenAssignment.id == id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, assignment: WardenAssignment) -> WardenAssignment:
        """Add and flush a new warden assignment record."""
        self.session.add(assignment)
        await self.session.flush()
        await self.session.refresh(assignment)
        return assignment

    async def delete(self, assignment: WardenAssignment) -> None:
        """Hard delete a warden assignment record."""
        await self.session.delete(assignment)
        await self.session.flush()

    async def list_by_hostel(self, hostel_id: UUID) -> list[WardenAssignment]:
        """Fetch all warden assignments for a given hostel with user eager-loaded."""
        stmt = (
            select(WardenAssignment)
            .options(selectinload(WardenAssignment.user))
            .where(WardenAssignment.hostel_id == hostel_id)
            .order_by(WardenAssignment.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def is_warden_assigned(self, user_id: UUID, hostel_id: UUID) -> bool:
        """Check whether a warden is assigned to the specified hostel."""
        stmt = select(func.count(WardenAssignment.id)).where(
            WardenAssignment.user_id == user_id,
            WardenAssignment.hostel_id == hostel_id,
        )
        result = await self.session.execute(stmt)
        count = result.scalar() or 0
        return count > 0

    async def list_hostel_ids_for_warden(self, user_id: UUID) -> list[UUID]:
        """Fetch list of hostel IDs assigned to a warden."""
        stmt = select(WardenAssignment.hostel_id).where(WardenAssignment.user_id == user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
