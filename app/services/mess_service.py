"""Mess menu, meal opt-out, and kitchen headcount service."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.models.mess import MealOptOut, MealType
from app.models.user import User, UserRole
from app.repositories.allocation_repository import AllocationRepository
from app.repositories.hostel_repository import HostelRepository
from app.repositories.mess_repository import MealOptOutRepository, MessMenuRepository
from app.repositories.operations_repository import LeaveRepository
from app.repositories.student_repository import StudentRepository
from app.schemas.common import PaginationParams
from app.schemas.mess import (
    DailyMenuRead,
    HostelDailyHeadcountResponse,
    MealHeadcountItem,
    MealOptOutCreate,
    MessMenuBulkUpdateRequest,
    WeeklyMenuRead,
)
from app.services.hostel_service import HostelService

__all__ = [
    "MEAL_DEFAULT_TIMES",
    "MessService",
]

MEAL_DEFAULT_TIMES: dict[MealType, time] = {
    MealType.BREAKFAST: time(8, 0),
    MealType.LUNCH: time(12, 0),
    MealType.SNACKS: time(16, 0),
    MealType.DINNER: time(20, 0),
}


class MessService:
    """Business logic coordinator for mess menus, opt-outs, and headcount projections."""

    def __init__(
        self,
        session: AsyncSession,
        mess_menu_repo: MessMenuRepository | None = None,
        meal_opt_out_repo: MealOptOutRepository | None = None,
        hostel_repo: HostelRepository | None = None,
        student_repo: StudentRepository | None = None,
        allocation_repo: AllocationRepository | None = None,
        leave_repo: LeaveRepository | None = None,
        hostel_service: HostelService | None = None,
    ) -> None:
        self.session = session
        self.mess_menu_repo = mess_menu_repo or MessMenuRepository(session)
        self.meal_opt_out_repo = meal_opt_out_repo or MealOptOutRepository(session)
        self.hostel_repo = hostel_repo or HostelRepository(session)
        self.student_repo = student_repo or StudentRepository(session)
        self.allocation_repo = allocation_repo or AllocationRepository(session)
        self.leave_repo = leave_repo or LeaveRepository(session)
        self.hostel_service = hostel_service or HostelService(session)

    def _enforce_cutoff(self, target_date: date, meal_type: MealType) -> None:
        """Enforce opt-out and cancellation cutoff time."""
        meal_time = MEAL_DEFAULT_TIMES.get(meal_type, time(8, 0))
        meal_datetime = datetime.combine(target_date, meal_time, tzinfo=UTC)
        cutoff = meal_datetime - timedelta(hours=settings.MEAL_OPTOUT_CUTOFF_HOURS)
        now = datetime.now(UTC)
        if now >= cutoff:
            raise BusinessRuleError(
                "Opt-out cutoff time has passed for this meal",
                code="CUTOFF_EXPIRED",
                status_code=400,
            )

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

    async def opt_out_meal(
        self,
        data: MealOptOutCreate,
        student_user: User,
    ) -> MealOptOut:
        """Opt out of an upcoming meal enforcing active allocation and cutoff timing."""
        profile = await self.student_repo.get_by_user_id(student_user.id)
        if profile is None or profile.is_deleted:
            raise NotFoundError("Student profile not found", code="STUDENT_NOT_FOUND")

        allocation = await self.allocation_repo.get_active_by_student_id(profile.id)
        if allocation is None:
            raise BusinessRuleError(
                "Student does not have an active allocation",
                code="NO_ACTIVE_ALLOCATION",
                status_code=400,
            )

        today = datetime.now(UTC).date()
        if data.date < today:
            raise BusinessRuleError(
                "Date cannot be in the past",
                code="DATE_IN_PAST",
                status_code=400,
            )

        self._enforce_cutoff(data.date, data.meal_type)

        existing = await self.meal_opt_out_repo.get_by_student_date_meal(
            profile.id, data.date, data.meal_type
        )
        if existing is not None:
            raise ConflictError(
                "Already opted out for this meal",
                code="ALREADY_OPTED_OUT",
            )

        opt_out = MealOptOut(
            student_id=profile.id,
            date=data.date,
            meal_type=data.meal_type,
        )
        return await self.meal_opt_out_repo.create(opt_out)

    async def cancel_opt_out(self, opt_out_id: UUID, student_user: User) -> None:
        """Cancel an existing meal opt-out enforcing ownership and cutoff timing."""
        profile = await self.student_repo.get_by_user_id(student_user.id)
        if profile is None or profile.is_deleted:
            raise NotFoundError("Student profile not found", code="STUDENT_NOT_FOUND")

        opt_out = await self.meal_opt_out_repo.get_by_id(opt_out_id)
        if opt_out is None:
            raise NotFoundError("Meal opt-out not found", code="OPT_OUT_NOT_FOUND")

        if opt_out.student_id != profile.id:
            raise ForbiddenError(
                "You can only cancel your own opt-outs",
                code="FORBIDDEN",
            )

        self._enforce_cutoff(opt_out.date, opt_out.meal_type)

        await self.meal_opt_out_repo.delete(opt_out)

    async def list_student_opt_outs(
        self,
        params: PaginationParams,
        student_user: User,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> tuple[list[MealOptOut], int]:
        """Fetch paginated meal opt-out records for authenticated student."""
        profile = await self.student_repo.get_by_user_id(student_user.id)
        if profile is None or profile.is_deleted:
            raise NotFoundError("Student profile not found", code="STUDENT_NOT_FOUND")

        return await self.meal_opt_out_repo.list_by_student(
            student_id=profile.id,
            params=params,
            date_from=date_from,
            date_to=date_to,
        )

    async def get_headcount(
        self,
        hostel_id: UUID,
        target_date: date,
        current_user: User,
    ) -> HostelDailyHeadcountResponse:
        """Compute expected headcount per meal type with deduplicated leave and opt-out counts."""
        hostel = await self.hostel_repo.get_by_id(hostel_id)
        if hostel is None or hostel.is_deleted:
            raise NotFoundError("Hostel not found", code="HOSTEL_NOT_FOUND")

        await self.hostel_service.ensure_hostel_access(current_user, hostel_id)

        student_ids = await self.allocation_repo.get_active_student_ids_for_hostel_on_date(
            hostel_id, target_date
        )
        total_allocated = len(student_ids)

        opt_outs = await self.meal_opt_out_repo.get_opt_outs_for_students_on_date(
            student_ids, target_date
        )
        opted_out_by_meal: dict[MealType, set[UUID]] = {m: set() for m in MealType}
        for opt in opt_outs:
            opted_out_by_meal[opt.meal_type].add(opt.student_id)

        leaves = await self.leave_repo.get_approved_leaves_for_students_on_date(
            student_ids, target_date
        )
        on_leave_student_ids = {leave.student_id for leave in leaves}

        meal_items: list[MealHeadcountItem] = []
        for meal_type in MealType:
            opted_out_ids = opted_out_by_meal[meal_type]
            union_set = opted_out_ids | on_leave_student_ids
            expected = total_allocated - len(union_set)
            meal_items.append(
                MealHeadcountItem(
                    meal_type=meal_type,
                    allocated_count=total_allocated,
                    opted_out_count=len(opted_out_ids),
                    on_leave_count=len(on_leave_student_ids),
                    expected_count=max(0, expected),
                )
            )

        return HostelDailyHeadcountResponse(
            hostel_id=hostel_id,
            date=target_date,
            meals=meal_items,
        )
