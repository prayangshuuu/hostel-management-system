"""Repositories for mess menu persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mess import MealType, MessMenu
from app.schemas.mess import MessMenuItemCreate

__all__ = [
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
