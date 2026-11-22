"""Student leave requests and approvals REST endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.operations import LeaveStatus
from app.models.user import User, UserRole
from app.schemas.common import Page, PaginationParams
from app.schemas.operations import (
    LeaveRequestCreate,
    LeaveRequestRead,
    LeaveReviewRequest,
)
from app.services.operations_service import OperationsService

router = APIRouter(tags=["leaves"])


@router.post(
    "/leaves",
    response_model=LeaveRequestRead,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a new leave request (Student, Admin, or Warden)",
)
async def create_leave_request(
    body: LeaveRequestCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_role(UserRole.STUDENT, UserRole.ADMIN, UserRole.WARDEN)),
    ],
) -> LeaveRequestRead:
    """Submit a hostel leave request enforcing future dates and active allocation."""
    service = OperationsService(session)
    leave = await service.create_leave_request(data=body, current_user=current_user)
    return LeaveRequestRead.model_validate(leave)


@router.get(
    "/leaves",
    response_model=Page[LeaveRequestRead],
    summary="List leave requests with filters (Admin or Warden)",
)
async def list_leaves(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
    params: Annotated[PaginationParams, Depends()],
    student_id: Annotated[UUID | None, Query(description="Filter by student UUID")] = None,
    status_filter: Annotated[
        LeaveStatus | None,
        Query(alias="status", description="Filter by leave workflow status"),
    ] = None,
    hostel_id: Annotated[UUID | None, Query(description="Filter by hostel UUID")] = None,
) -> Page[LeaveRequestRead]:
    """List paginated leave requests enforcing warden scoping."""
    service = OperationsService(session)
    items, total = await service.list_leaves(
        params=params,
        current_user=current_user,
        student_id=student_id,
        status=status_filter,
        hostel_id=hostel_id,
    )
    read_items = [LeaveRequestRead.model_validate(it) for it in items]
    return Page.create(items=read_items, total=total, params=params)


@router.get(
    "/students/me/leaves",
    response_model=Page[LeaveRequestRead],
    summary="Get current student leave requests (Student self-service)",
)
async def get_my_leaves(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.STUDENT))],
    params: Annotated[PaginationParams, Depends()],
    status_filter: Annotated[
        LeaveStatus | None,
        Query(alias="status", description="Filter by leave workflow status"),
    ] = None,
) -> Page[LeaveRequestRead]:
    """Retrieve submitted leave requests for authenticated student."""
    service = OperationsService(session)
    items, total = await service.get_my_leaves(
        current_user=current_user,
        params=params,
        status=status_filter,
    )
    read_items = [LeaveRequestRead.model_validate(it) for it in items]
    return Page.create(items=read_items, total=total, params=params)


@router.get(
    "/leaves/{id}",
    response_model=LeaveRequestRead,
    summary="Get leave request by ID (Admin, Warden, or student self)",
)
async def get_leave_by_id(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_role(UserRole.ADMIN, UserRole.WARDEN, UserRole.STUDENT)),
    ],
) -> LeaveRequestRead:
    """Retrieve details of a specific leave request record."""
    service = OperationsService(session)
    leave = await service.get_leave_by_id(leave_id=id, current_user=current_user)
    return LeaveRequestRead.model_validate(leave)


@router.post(
    "/leaves/{id}/approve",
    response_model=LeaveRequestRead,
    summary="Approve a pending leave request (Admin or Warden)",
)
async def approve_leave(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
    body: LeaveReviewRequest | None = None,
) -> LeaveRequestRead:
    """Transition a pending leave request to approved status."""
    service = OperationsService(session)
    leave = await service.approve_leave_request(
        leave_id=id,
        current_user=current_user,
        review=body,
    )
    return LeaveRequestRead.model_validate(leave)


@router.post(
    "/leaves/{id}/reject",
    response_model=LeaveRequestRead,
    summary="Reject a pending leave request (Admin or Warden)",
)
async def reject_leave(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
    body: LeaveReviewRequest | None = None,
) -> LeaveRequestRead:
    """Transition a pending leave request to rejected status."""
    service = OperationsService(session)
    leave = await service.reject_leave_request(
        leave_id=id,
        current_user=current_user,
        review=body,
    )
    return LeaveRequestRead.model_validate(leave)


@router.post(
    "/leaves/{id}/cancel",
    response_model=LeaveRequestRead,
    summary="Cancel a pending leave request (Student self or Admin)",
)
async def cancel_leave(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_role(UserRole.ADMIN, UserRole.STUDENT)),
    ],
) -> LeaveRequestRead:
    """Cancel a pending leave request record."""
    service = OperationsService(session)
    leave = await service.cancel_leave_request(leave_id=id, current_user=current_user)
    return LeaveRequestRead.model_validate(leave)
