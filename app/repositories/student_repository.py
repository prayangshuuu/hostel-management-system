"""Student repository for persistence and query operations."""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.db.base import Base
from app.models.hostel import GenderType
from app.models.student import StudentProfile
from app.models.user import User
from app.schemas.common import PaginationParams


class StudentRepository:
    """Repository handling database operations for the StudentProfile entity."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, id: UUID, include_deleted: bool = False) -> StudentProfile | None:
        """Fetch a student profile by ID with user eager-loaded."""
        stmt = (
            select(StudentProfile)
            .options(selectinload(StudentProfile.user))
            .where(StudentProfile.id == id)
        )
        if not include_deleted:
            stmt = stmt.where(StudentProfile.is_deleted.is_(False))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_user_id(
        self, user_id: UUID, include_deleted: bool = False
    ) -> StudentProfile | None:
        """Fetch a student profile by user ID with user eager-loaded."""
        stmt = (
            select(StudentProfile)
            .options(selectinload(StudentProfile.user))
            .where(StudentProfile.user_id == user_id)
        )
        if not include_deleted:
            stmt = stmt.where(StudentProfile.is_deleted.is_(False))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_student_no(
        self, student_no: str, include_deleted: bool = False
    ) -> StudentProfile | None:
        """Fetch a student profile by student number (case-insensitive) with user eager-loaded."""
        stmt = (
            select(StudentProfile)
            .options(selectinload(StudentProfile.user))
            .where(func.lower(StudentProfile.student_no) == student_no.strip().lower())
        )
        if not include_deleted:
            stmt = stmt.where(StudentProfile.is_deleted.is_(False))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, profile: StudentProfile) -> StudentProfile:
        """Add and flush a new student profile."""
        self.session.add(profile)
        await self.session.flush()
        await self.session.refresh(profile)
        return profile

    async def update(self, profile: StudentProfile) -> StudentProfile:
        """Flush changes to an existing student profile."""
        await self.session.flush()
        await self.session.refresh(profile)
        return profile

    async def soft_delete(self, profile: StudentProfile) -> StudentProfile:
        """Mark student profile as deleted."""
        profile.is_deleted = True
        await self.session.flush()
        await self.session.refresh(profile)
        return profile

    async def list(
        self,
        params: PaginationParams,
        department: str | None = None,
        year: int | None = None,
        gender: GenderType | None = None,
        has_allocation: bool | None = None,
        search: str | None = None,
        warden_hostel_ids: list[UUID] | None = None,
    ) -> tuple[list[StudentProfile], int]:
        """Fetch a paginated list of non-deleted students matching filters and search."""
        stmt = (
            select(StudentProfile)
            .join(StudentProfile.user)
            .options(joinedload(StudentProfile.user))
            .where(StudentProfile.is_deleted.is_(False))
        )
        count_stmt = (
            select(func.count(StudentProfile.id))
            .join(StudentProfile.user)
            .where(StudentProfile.is_deleted.is_(False))
        )

        if department:
            dept_pattern = department.strip().lower()
            stmt = stmt.where(func.lower(StudentProfile.department) == dept_pattern)
            count_stmt = count_stmt.where(func.lower(StudentProfile.department) == dept_pattern)

        if year is not None:
            stmt = stmt.where(StudentProfile.year == year)
            count_stmt = count_stmt.where(StudentProfile.year == year)

        if gender is not None:
            stmt = stmt.where(StudentProfile.gender == gender)
            count_stmt = count_stmt.where(StudentProfile.gender == gender)

        if search:
            search_pattern = f"%{search.strip().lower()}%"
            search_filter = or_(
                func.lower(StudentProfile.student_no).like(search_pattern),
                func.lower(User.full_name).like(search_pattern),
                func.lower(User.email).like(search_pattern),
            )
            stmt = stmt.where(search_filter)
            count_stmt = count_stmt.where(search_filter)

        if "allocations" in Base.metadata.tables:
            alloc_table = Base.metadata.tables["allocations"]
            active_alloc_subq = select(alloc_table.c.student_id).where(
                alloc_table.c.status == "active"
            )
            if has_allocation is True:
                stmt = stmt.where(StudentProfile.id.in_(active_alloc_subq))
                count_stmt = count_stmt.where(StudentProfile.id.in_(active_alloc_subq))
            elif has_allocation is False:
                stmt = stmt.where(StudentProfile.id.not_in(active_alloc_subq))
                count_stmt = count_stmt.where(StudentProfile.id.not_in(active_alloc_subq))

            if (
                warden_hostel_ids is not None
                and "beds" in Base.metadata.tables
                and "rooms" in Base.metadata.tables
                and "blocks" in Base.metadata.tables
            ):
                bed_table = Base.metadata.tables["beds"]
                room_table = Base.metadata.tables["rooms"]
                block_table = Base.metadata.tables["blocks"]
                warden_alloc_subq = (
                    select(alloc_table.c.student_id)
                    .select_from(
                        alloc_table.join(bed_table, alloc_table.c.bed_id == bed_table.c.id)
                        .join(room_table, bed_table.c.room_id == room_table.c.id)
                        .join(block_table, room_table.c.block_id == block_table.c.id)
                    )
                    .where(
                        alloc_table.c.status == "active",
                        block_table.c.hostel_id.in_(warden_hostel_ids),
                    )
                )
                warden_filter = or_(
                    StudentProfile.id.in_(warden_alloc_subq),
                    StudentProfile.id.not_in(active_alloc_subq),
                )
                stmt = stmt.where(warden_filter)
                count_stmt = count_stmt.where(warden_filter)
        else:
            if has_allocation is True:
                stmt = stmt.where(sa.false())
                count_stmt = count_stmt.where(sa.false())

        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        stmt = (
            stmt.order_by(StudentProfile.created_at.desc())
            .offset(params.offset)
            .limit(params.limit)
        )
        items_result = await self.session.execute(stmt)
        profiles = list(items_result.scalars().all())

        return profiles, total
