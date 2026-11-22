"""Mess menu service."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BusinessRuleError,
    ForbiddenError,
    NotFoundError,
)
from app.models.user import User, UserRole
from app.repositories.allocation_repository import AllocationRepository
from app.repositories.hostel_repository import HostelRepository
from app.repositories.mess_repository import MessMenuRepository
from app.repositories.student_repository import StudentRepository
from app.schemas.mess import (
    DailyMenuRead,
    MessMenuBulkUpdateRequest,
    WeeklyMenuRead,
)
from app.services.hostel_service import HostelService

__all__ = [
    "MessService",
]


class MessService:
    """Business logic coordinator for hostel mess menus."""

    def __init__(
        self,
        session: AsyncSession,
        mess_menu_repo: MessMenuRepository | None = None,
        hostel_repo: HostelRepository | None = None,
        student_repo: StudentRepository | None = None,
        allocation_repo: AllocationRepository | None = None,
        hostel_service: HostelService | None = None,
    ) -> None:
        self.session = session
        self.mess_menu_repo = mess_menu_repo or MessMenuRepository(session)
        self.hostel_repo = hostel_repo or HostelRepository(session)
        self.student_repo = student_repo or StudentRepository(session)
        self.allocation_repo = allocation_repo or AllocationRepository(session)
        self.hostel_service = hostel_service or HostelService(session)

    async def update_hostel_menu(
        self,
        hostel_id: UUID,
        data: MessMenuBulkUpdateRequest,
        current_user: User,
    ) -> WeeklyMenuRead:
        """Bulk upsert weekly mess menu entries for a hostel (Admin or assigned Warden)."""
        hostel = await self.hostel_repo.get_by_id(hostel_id)
        if hostel is None or hostel.is_deleted:
            raise NotFoundError("Hostel not found", code="HOSTEL_NOT_FOUND")

        await self.hostel_service.ensure_hostel_access(current_user, hostel_id)

        items = await self.mess_menu_repo.bulk_upsert(hostel_id, data.entries)
        return WeeklyMenuRead(hostel_id=hostel_id, items=items)

    async def get_hostel_menu(
        self,
        hostel_id: UUID,
        current_user: User,
    ) -> WeeklyMenuRead:
        """Fetch weekly mess menu with role and hostel scoping."""
        hostel = await self.hostel_repo.get_by_id(hostel_id)
        if hostel is None or hostel.is_deleted:
            raise NotFoundError("Hostel not found", code="HOSTEL_NOT_FOUND")

        role = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if role == UserRole.ADMIN.value:
            pass
        elif role == UserRole.WARDEN.value:
            await self.hostel_service.ensure_hostel_access(current_user, hostel_id)
        elif role == UserRole.STUDENT.value:
            profile = await self.student_repo.get_by_user_id(current_user.id)
            if profile is None or profile.is_deleted:
                raise ForbiddenError(
                    "You are not allocated to this hostel",
                    code="FORBIDDEN",
                )
            allocation = await self.allocation_repo.get_active_by_student_id(profile.id)
            if (
                allocation is None
                or allocation.bed is None
                or allocation.bed.room is None
                or allocation.bed.room.block is None
                or allocation.bed.room.block.hostel_id != hostel_id
            ):
                raise ForbiddenError(
                    "You are not allocated to this hostel",
                    code="FORBIDDEN",
                )
        else:
            raise ForbiddenError(
                "Insufficient permissions to view hostel menu",
                code="FORBIDDEN",
            )

        items = await self.mess_menu_repo.get_by_hostel(hostel_id)
        return WeeklyMenuRead(hostel_id=hostel_id, items=items)

    async def get_student_today_menu(self, student_user: User) -> DailyMenuRead:
        """Fetch today's mess menu for the actively allocated student."""
        profile = await self.student_repo.get_by_user_id(student_user.id)
        if profile is None or profile.is_deleted:
            raise NotFoundError("Student profile not found", code="STUDENT_NOT_FOUND")

        allocation = await self.allocation_repo.get_active_by_student_id(profile.id)
        if (
            allocation is None
            or allocation.bed is None
            or allocation.bed.room is None
            or allocation.bed.room.block is None
        ):
            raise BusinessRuleError(
                "Student does not have an active allocation",
                code="NO_ACTIVE_ALLOCATION",
                status_code=400,
            )

        hostel_id = allocation.bed.room.block.hostel_id
        today = datetime.now(UTC).date()
        day_of_week = today.weekday()

        items = await self.mess_menu_repo.get_by_hostel_and_day(hostel_id, day_of_week)
        meals: dict[str, list[str]] = {
            (it.meal_type.value if hasattr(it.meal_type, "value") else str(it.meal_type)): it.items
            for it in items
        }
        return DailyMenuRead(
            hostel_id=hostel_id,
            date=today,
            day_of_week=day_of_week,
            meals=meals,
        )
