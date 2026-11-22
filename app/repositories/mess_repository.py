"""Repositories for mess menu and meal opt-out persistence."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mess import MealOptOut, MealType, MessMenu
from app.schemas.common import PaginationParams
from app.schemas.mess import MessMenuItemCreate

__all__ = [
    "MealOptOutRepository",
    "MessMenuRepository",
]


class MessMenuRepository:
    """Repository handling persistence and queries for MessMenu entities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_hostel(self, hostel_id: UUID) -> list[MessMenu]:
        """Fetch all mess menu entries for a hostel, ordered by day of week and meal type."""
        stmt = (
            select(MessMenu)
            .where(MessMenu.hostel_id == hostel_id)
            .order_by(MessMenu.day_of_week.asc(), MessMenu.meal_type.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_hostel_and_day(self, hostel_id: UUID, day_of_week: int) -> list[MessMenu]:
        """Fetch mess menu entries for a specific day of the week in a hostel."""
        stmt = (
            select(MessMenu)
            .where(MessMenu.hostel_id == hostel_id, MessMenu.day_of_week == day_of_week)
            .order_by(MessMenu.meal_type.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def bulk_upsert(
        self, hostel_id: UUID, entries: list[MessMenuItemCreate]
    ) -> list[MessMenu]:
        """Replace and upsert all weekly mess menu entries for a hostel."""
        # De-duplicate entries within the input (last specified wins)
        unique_entries: dict[tuple[int, MealType], list[str]] = {}
        for entry in entries:
            unique_entries[(entry.day_of_week, entry.meal_type)] = entry.items

        existing = await self.get_by_hostel(hostel_id)
        existing_map = {(m.day_of_week, m.meal_type): m for m in existing}

        # Remove existing menu items that are not in the new payload
        for key, old_item in existing_map.items():
            if key not in unique_entries:
                await self.session.delete(old_item)

        # Update existing items or insert new ones
        for (day, meal), items in unique_entries.items():
            if (day, meal) in existing_map:
                existing_map[(day, meal)].items = items
            else:
                new_item = MessMenu(
                    hostel_id=hostel_id,
                    day_of_week=day,
                    meal_type=meal,
                    items=items,
                )
                self.session.add(new_item)

        await self.session.flush()
        return await self.get_by_hostel(hostel_id)


class MealOptOutRepository:
    """Repository handling persistence and queries for MealOptOut entities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, opt_out: MealOptOut) -> MealOptOut:
        """Add and flush a new meal opt-out record."""
        self.session.add(opt_out)
        await self.session.flush()
        await self.session.refresh(opt_out)
        return opt_out

    async def get_by_id(self, id: UUID) -> MealOptOut | None:
        """Fetch a single meal opt-out by UUID."""
        stmt = select(MealOptOut).where(MealOptOut.id == id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_student_date_meal(
        self, student_id: UUID, date: date, meal_type: MealType
    ) -> MealOptOut | None:
        """Find an existing opt-out for a student, date, and meal type."""
        stmt = select(MealOptOut).where(
            MealOptOut.student_id == student_id,
            MealOptOut.date == date,
            MealOptOut.meal_type == meal_type,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_student(
        self,
        student_id: UUID,
        params: PaginationParams,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> tuple[list[MealOptOut], int]:
        """Fetch paginated meal opt-out records for a student."""
        stmt = select(MealOptOut).where(MealOptOut.student_id == student_id)
        count_stmt = select(func.count(MealOptOut.id)).where(MealOptOut.student_id == student_id)

        if date_from is not None:
            stmt = stmt.where(MealOptOut.date >= date_from)
            count_stmt = count_stmt.where(MealOptOut.date >= date_from)
        if date_to is not None:
            stmt = stmt.where(MealOptOut.date <= date_to)
            count_stmt = count_stmt.where(MealOptOut.date <= date_to)

        total = (await self.session.execute(count_stmt)).scalar() or 0
        stmt = (
            stmt.order_by(MealOptOut.date.desc(), MealOptOut.created_at.desc())
            .offset(params.offset)
            .limit(params.limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def delete(self, opt_out: MealOptOut) -> None:
        """Delete a meal opt-out record."""
        await self.session.delete(opt_out)
        await self.session.flush()

    async def get_opt_outs_for_students_on_date(
        self, student_ids: list[UUID], target_date: date
    ) -> list[MealOptOut]:
        """Fetch all opt-out records for a collection of students on a specific date."""
        if not student_ids:
            return []
        stmt = select(MealOptOut).where(
            MealOptOut.student_id.in_(student_ids),
            MealOptOut.date == target_date,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
