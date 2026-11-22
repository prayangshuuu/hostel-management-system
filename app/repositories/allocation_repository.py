"""Allocation repository for database persistence operations."""

import builtins
from datetime import date
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.base import ExecutableOption

from app.models.allocation import Allocation, AllocationStatus
from app.models.hostel import Block
from app.models.room import Bed, Room
from app.models.student import StudentProfile
from app.models.user import User
from app.schemas.allocation import OccupantRead
from app.schemas.common import PaginationParams


class AllocationRepository:
    """Repository managing queries and mutations for Allocation records."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _eager_load_options(self) -> builtins.list[ExecutableOption]:
        """Return eager loading options for student, user, bed, room, block, and hostel."""
        return [
            selectinload(Allocation.student).selectinload(StudentProfile.user),
            selectinload(Allocation.bed)
            .selectinload(Bed.room)
            .selectinload(Room.block)
            .selectinload(Block.hostel),
        ]

    async def get_by_id(self, id: UUID) -> Allocation | None:
        """Fetch allocation by ID with all related entities eagerly loaded."""
        stmt = select(Allocation).options(*self._eager_load_options()).where(Allocation.id == id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_active_by_student_id(self, student_id: UUID) -> Allocation | None:
        """Fetch active allocation for a student profile with relations loaded."""
        stmt = (
            select(Allocation)
            .options(*self._eager_load_options())
            .where(
                Allocation.student_id == student_id,
                Allocation.status == AllocationStatus.ACTIVE,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_active_by_bed_id(self, bed_id: UUID) -> Allocation | None:
        """Fetch active allocation for a bed with relations loaded."""
        stmt = (
            select(Allocation)
            .options(*self._eager_load_options())
            .where(
                Allocation.bed_id == bed_id,
                Allocation.status == AllocationStatus.ACTIVE,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def has_active_allocations_for_hostel(self, hostel_id: UUID) -> bool:
        """Check if any active allocation exists for the given hostel."""
        stmt = (
            select(func.count(Allocation.id))
            .join(Bed, Allocation.bed_id == Bed.id)
            .join(Room, Bed.room_id == Room.id)
            .join(Block, Room.block_id == Block.id)
            .where(
                Block.hostel_id == hostel_id,
                Allocation.status == AllocationStatus.ACTIVE,
            )
        )
        result = await self.session.execute(stmt)
        count = result.scalar() or 0
        return count > 0

    async def get_overlapping_for_hostel(
        self, hostel_id: UUID, period_start: date, period_end: date
    ) -> builtins.list[Allocation]:
        """Fetch allocations in a hostel overlapping the given date range."""
        stmt = (
            select(Allocation)
            .options(*self._eager_load_options())
            .join(Bed, Allocation.bed_id == Bed.id)
            .join(Room, Bed.room_id == Room.id)
            .join(Block, Room.block_id == Block.id)
            .where(
                Block.hostel_id == hostel_id,
                Allocation.status.in_([AllocationStatus.ACTIVE, AllocationStatus.ENDED]),
                Allocation.start_date <= period_end,
                or_(Allocation.end_date.is_(None), Allocation.end_date >= period_start),
            )
            .order_by(Allocation.start_date.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_student_ids_for_hostel_on_date(
        self, hostel_id: UUID, target_date: date
    ) -> builtins.list[UUID]:
        """Fetch active allocated student IDs in a hostel on a specific date."""
        stmt = (
            select(Allocation.student_id)
            .join(Bed, Allocation.bed_id == Bed.id)
            .join(Room, Bed.room_id == Room.id)
            .join(Block, Room.block_id == Block.id)
            .join(StudentProfile, Allocation.student_id == StudentProfile.id)
            .where(
                Block.hostel_id == hostel_id,
                Allocation.status == AllocationStatus.ACTIVE,
                Allocation.start_date <= target_date,
                or_(Allocation.end_date.is_(None), Allocation.end_date >= target_date),
                StudentProfile.is_deleted.is_(False),
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def has_active_allocations_for_room(self, room_id: UUID) -> bool:
        """Check if any active allocation exists for the given room."""
        stmt = (
            select(func.count(Allocation.id))
            .join(Bed, Allocation.bed_id == Bed.id)
            .where(
                Bed.room_id == room_id,
                Allocation.status == AllocationStatus.ACTIVE,
            )
        )
        result = await self.session.execute(stmt)
        count = result.scalar() or 0
        return count > 0

    async def create(self, allocation: Allocation) -> Allocation:
        """Persist a new allocation record."""
        self.session.add(allocation)
        await self.session.flush()
        return allocation

    async def update(self, allocation: Allocation) -> Allocation:
        """Flush changes to an existing allocation record."""
        await self.session.flush()
        return allocation

    async def list(
        self,
        params: PaginationParams,
        hostel_id: UUID | None = None,
        room_id: UUID | None = None,
        student_id: UUID | None = None,
        status: AllocationStatus | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        warden_hostel_ids: builtins.list[UUID] | None = None,
    ) -> tuple[builtins.list[Allocation], int]:
        """Query paginated allocations with optional filters and warden scoping."""
        stmt = select(Allocation).options(*self._eager_load_options())
        count_stmt = select(func.count(Allocation.id))

        needs_bed = room_id is not None or hostel_id is not None or warden_hostel_ids is not None
        needs_room = hostel_id is not None or warden_hostel_ids is not None
        needs_block = hostel_id is not None or warden_hostel_ids is not None

        if needs_bed:
            stmt = stmt.join(Bed, Allocation.bed_id == Bed.id)
            count_stmt = count_stmt.join(Bed, Allocation.bed_id == Bed.id)
        if needs_room:
            stmt = stmt.join(Room, Bed.room_id == Room.id)
            count_stmt = count_stmt.join(Room, Bed.room_id == Room.id)
        if needs_block:
            stmt = stmt.join(Block, Room.block_id == Block.id)
            count_stmt = count_stmt.join(Block, Room.block_id == Block.id)

        if hostel_id is not None:
            stmt = stmt.where(Block.hostel_id == hostel_id)
            count_stmt = count_stmt.where(Block.hostel_id == hostel_id)

        if warden_hostel_ids is not None:
            stmt = stmt.where(Block.hostel_id.in_(warden_hostel_ids))
            count_stmt = count_stmt.where(Block.hostel_id.in_(warden_hostel_ids))

        if room_id is not None:
            stmt = stmt.where(Bed.room_id == room_id)
            count_stmt = count_stmt.where(Bed.room_id == room_id)

        if student_id is not None:
            stmt = stmt.where(Allocation.student_id == student_id)
            count_stmt = count_stmt.where(Allocation.student_id == student_id)

        if status is not None:
            stmt = stmt.where(Allocation.status == status)
            count_stmt = count_stmt.where(Allocation.status == status)

        if start_date is not None:
            stmt = stmt.where(Allocation.start_date >= start_date)
            count_stmt = count_stmt.where(Allocation.start_date >= start_date)

        if end_date is not None:
            stmt = stmt.where(Allocation.start_date <= end_date)
            count_stmt = count_stmt.where(Allocation.start_date <= end_date)

        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        stmt = stmt.order_by(Allocation.created_at.desc()).offset(params.offset).limit(params.limit)
        result = await self.session.execute(stmt)
        allocations = list(result.scalars().all())

        return allocations, total

    async def get_room_occupants(self, room_id: UUID) -> builtins.list[OccupantRead]:
        """Fetch list of occupants currently having active allocations in the given room."""
        stmt = (
            select(
                Bed.id.label("bed_id"),
                Bed.label.label("bed_label"),
                StudentProfile.id.label("student_id"),
                StudentProfile.student_no.label("student_no"),
                User.full_name.label("student_name"),
                Allocation.id.label("allocation_id"),
                Allocation.start_date.label("start_date"),
            )
            .join(Bed, Allocation.bed_id == Bed.id)
            .join(StudentProfile, Allocation.student_id == StudentProfile.id)
            .join(User, StudentProfile.user_id == User.id)
            .where(
                Bed.room_id == room_id,
                Allocation.status == AllocationStatus.ACTIVE,
            )
            .order_by(Bed.label.asc())
        )
        result = await self.session.execute(stmt)
        rows = result.all()
        return [
            OccupantRead(
                bed_id=row.bed_id,
                bed_label=row.bed_label,
                student_id=row.student_id,
                student_no=row.student_no,
                student_name=row.student_name,
                allocation_id=row.allocation_id,
                start_date=row.start_date,
            )
            for row in rows
        ]


__all__ = ["AllocationRepository"]
