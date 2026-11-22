"""Mess menu and meal opt-out REST endpoints."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.user import User, UserRole
from app.schemas.common import Page, PaginationParams
from app.schemas.mess import (
    DailyMenuRead,
    HostelDailyHeadcountResponse,
    MealOptOutCreate,
    MealOptOutRead,
    MessMenuBulkUpdateRequest,
    WeeklyMenuRead,
)
from app.services.mess_service import MessService

router = APIRouter(tags=["mess"])


@router.put(
    "/hostels/{id}/menu",
    response_model=WeeklyMenuRead,
    summary="Bulk upsert weekly mess menu (Admin or assigned Warden)",
)
async def update_hostel_menu(
    id: UUID,
    body: MessMenuBulkUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_role(UserRole.ADMIN, UserRole.WARDEN)),
    ],
) -> WeeklyMenuRead:
    """Replace and upsert weekly mess menu schedule for a hostel."""
    service = MessService(session)
    return await service.update_hostel_menu(
        hostel_id=id,
        data=body,
        current_user=current_user,
    )


@router.get(
    "/hostels/{id}/menu",
    response_model=WeeklyMenuRead,
    summary="Get weekly mess menu for a hostel",
)
async def get_hostel_menu(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_role(UserRole.ADMIN, UserRole.WARDEN, UserRole.STUDENT)),
    ],
) -> WeeklyMenuRead:
    """Retrieve full weekly mess menu for a hostel enforcing role and allocation scoping."""
    service = MessService(session)
    return await service.get_hostel_menu(
        hostel_id=id,
        current_user=current_user,
    )


@router.get(
    "/students/me/menu/today",
    response_model=DailyMenuRead,
    summary="Get today's mess menu for authenticated student",
)
async def get_student_today_menu(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.STUDENT))],
) -> DailyMenuRead:
    """Fetch today's mess menu for the actively allocated student."""
    service = MessService(session)
    return await service.get_student_today_menu(student_user=current_user)


@router.post(
    "/meals/opt-outs",
    response_model=MealOptOutRead,
    status_code=status.HTTP_201_CREATED,
    summary="Opt out of an upcoming meal (Student only)",
)
async def opt_out_meal(
    body: MealOptOutCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.STUDENT))],
) -> MealOptOutRead:
    """Submit a meal opt-out enforcing active allocation, future date, and cutoff time."""
    service = MessService(session)
    opt_out = await service.opt_out_meal(data=body, student_user=current_user)
    return MealOptOutRead.model_validate(opt_out)


@router.delete(
    "/meals/opt-outs/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel a meal opt-out (Student only)",
)
async def cancel_opt_out(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.STUDENT))],
) -> None:
    """Cancel a previously submitted meal opt-out before the cutoff time."""
    service = MessService(session)
    await service.cancel_opt_out(opt_out_id=id, student_user=current_user)


@router.get(
    "/students/me/opt-outs",
    response_model=Page[MealOptOutRead],
    summary="List meal opt-outs for authenticated student",
)
async def list_my_opt_outs(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.STUDENT))],
    params: Annotated[PaginationParams, Depends()],
    date_from: Annotated[date | None, Query(description="Filter from date")] = None,
    date_to: Annotated[date | None, Query(description="Filter to date")] = None,
) -> Page[MealOptOutRead]:
    """Retrieve paginated meal opt-out history for the authenticated student."""
    service = MessService(session)
    items, total = await service.list_student_opt_outs(
        params=params,
        student_user=current_user,
        date_from=date_from,
        date_to=date_to,
    )
    read_items = [MealOptOutRead.model_validate(it) for it in items]
    return Page.create(items=read_items, total=total, params=params)


@router.get(
    "/meals/headcount",
    response_model=HostelDailyHeadcountResponse,
    summary="Get daily meal headcount projections for a hostel (Admin or assigned Warden)",
)
async def get_meal_headcount(
    hostel_id: Annotated[UUID, Query(description="Hostel UUID")],
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_role(UserRole.ADMIN, UserRole.WARDEN)),
    ],
    target_date: Annotated[
        date | None,
        Query(alias="date", description="Headcount target date"),
    ] = None,
) -> HostelDailyHeadcountResponse:
    """Get expected meal headcount per meal type with deduplicated leave and opt-out counts."""
    service = MessService(session)
    actual_date = target_date or datetime.now(UTC).date()
    return await service.get_headcount(
        hostel_id=hostel_id,
        target_date=actual_date,
        current_user=current_user,
    )
