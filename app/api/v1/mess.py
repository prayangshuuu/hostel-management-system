"""Mess menu REST endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.user import User, UserRole
from app.schemas.mess import (
    DailyMenuRead,
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
