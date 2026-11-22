"""Attendance check-in, check-out, and presence tracking REST endpoints."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.operations import AttendanceType
from app.models.user import User, UserRole
from app.schemas.common import Page, PaginationParams
from app.schemas.operations import (
    AttendanceActionRequest,
    AttendanceRead,
    PresentStudentRead,
)
from app.services.operations_service import OperationsService

router = APIRouter(tags=["attendance"])


@router.post(
    "/attendance/check-in",
    response_model=AttendanceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record student check-in (Admin or Warden)",
)
async def check_in_student(
    body: AttendanceActionRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
) -> AttendanceRead:
    """Record student entry into the hostel."""
    service = OperationsService(session)
    log = await service.check_in(data=body, current_user=current_user)
    return AttendanceRead.model_validate(log)


@router.post(
    "/attendance/check-out",
    response_model=AttendanceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record student check-out (Admin or Warden)",
)
async def check_out_student(
    body: AttendanceActionRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
) -> AttendanceRead:
    """Record student exit from the hostel."""
    service = OperationsService(session)
    log = await service.check_out(data=body, current_user=current_user)
    return AttendanceRead.model_validate(log)


@router.get(
    "/attendance/present",
    response_model=list[PresentStudentRead],
    summary="List students currently present inside the hostel (Admin or Warden)",
)
async def get_present_students(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
    hostel_id: Annotated[
        UUID | None,
        Query(description="Filter by hostel UUID"),
    ] = None,
) -> list[PresentStudentRead]:
    """Retrieve students whose latest attendance event is check-in."""
    service = OperationsService(session)
    return await service.get_present_students(current_user=current_user, hostel_id=hostel_id)


@router.get(
    "/attendance",
    response_model=Page[AttendanceRead],
    summary="List attendance logs with filters (Admin or Warden)",
)
async def list_attendance(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
    params: Annotated[PaginationParams, Depends()],
    student_id: Annotated[UUID | None, Query(description="Filter by student UUID")] = None,
    hostel_id: Annotated[UUID | None, Query(description="Filter by hostel UUID")] = None,
    date_from: Annotated[date | None, Query(description="Start date filter (YYYY-MM-DD)")] = None,
    date_to: Annotated[date | None, Query(description="End date filter (YYYY-MM-DD)")] = None,
    type: Annotated[AttendanceType | None, Query(description="Attendance event type")] = None,
) -> Page[AttendanceRead]:
    """List paginated attendance logs enforcing warden scoping."""
    service = OperationsService(session)
    items, total = await service.list_attendance(
        params=params,
        current_user=current_user,
        student_id=student_id,
        hostel_id=hostel_id,
        date_from=date_from,
        date_to=date_to,
        type=type,
    )
    read_items = [AttendanceRead.model_validate(it) for it in items]
    return Page.create(items=read_items, total=total, params=params)


@router.get(
    "/students/me/attendance",
    response_model=Page[AttendanceRead],
    summary="Get current student attendance logs (Student self-service)",
)
async def get_my_attendance(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.STUDENT))],
    params: Annotated[PaginationParams, Depends()],
    date_from: Annotated[date | None, Query(description="Start date filter (YYYY-MM-DD)")] = None,
    date_to: Annotated[date | None, Query(description="End date filter (YYYY-MM-DD)")] = None,
    type: Annotated[AttendanceType | None, Query(description="Attendance event type")] = None,
) -> Page[AttendanceRead]:
    """Retrieve attendance history for the authenticated student."""
    service = OperationsService(session)
    items, total = await service.get_my_attendance(
        current_user=current_user,
        params=params,
        date_from=date_from,
        date_to=date_to,
        type=type,
    )
    read_items = [AttendanceRead.model_validate(it) for it in items]
    return Page.create(items=read_items, total=total, params=params)
