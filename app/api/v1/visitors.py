"""Hostel visitor check-in, check-out, and logs REST endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.user import User, UserRole
from app.schemas.common import Page, PaginationParams
from app.schemas.operations import (
    VisitorCheckOutRequest,
    VisitorCreate,
    VisitorRead,
)
from app.services.operations_service import OperationsService

router = APIRouter(tags=["visitors"])


@router.post(
    "/visitors",
    response_model=VisitorRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record visitor check-in (Admin or Warden)",
)
async def check_in_visitor(
    body: VisitorCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
) -> VisitorRead:
    """Register visitor entry during authorized visiting hours."""
    service = OperationsService(session)
    visitor = await service.check_in_visitor(data=body, current_user=current_user)
    return VisitorRead.model_validate(visitor)


@router.post(
    "/visitors/{id}/check-out",
    response_model=VisitorRead,
    summary="Record visitor check-out (Admin or Warden)",
)
async def check_out_visitor(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
    body: VisitorCheckOutRequest | None = None,
) -> VisitorRead:
    """Record visitor departure from the hostel."""
    service = OperationsService(session)
    visitor = await service.check_out_visitor(
        visitor_id=id,
        current_user=current_user,
        data=body,
    )
    return VisitorRead.model_validate(visitor)


@router.get(
    "/visitors",
    response_model=Page[VisitorRead],
    summary="List visitor records with filters (Admin or Warden)",
)
async def list_visitors(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
    params: Annotated[PaginationParams, Depends()],
    student_id: Annotated[UUID | None, Query(description="Filter by student UUID")] = None,
    active: Annotated[
        bool | None,
        Query(description="Filter by active status (true: currently inside, false: checked out)"),
    ] = None,
    hostel_id: Annotated[UUID | None, Query(description="Filter by hostel UUID")] = None,
) -> Page[VisitorRead]:
    """Fetch paginated visitor logs enforcing warden scoping."""
    service = OperationsService(session)
    items, total = await service.list_visitors(
        params=params,
        current_user=current_user,
        student_id=student_id,
        active=active,
        hostel_id=hostel_id,
    )
    read_items = [VisitorRead.model_validate(it) for it in items]
    return Page.create(items=read_items, total=total, params=params)


@router.get(
    "/students/me/visitors",
    response_model=Page[VisitorRead],
    summary="Get current student visitor logs (Student self-service)",
)
async def get_my_visitors(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.STUDENT))],
    params: Annotated[PaginationParams, Depends()],
    active: Annotated[
        bool | None,
        Query(description="Filter by active status"),
    ] = None,
) -> Page[VisitorRead]:
    """Retrieve visitor logs for the authenticated student."""
    service = OperationsService(session)
    items, total = await service.get_my_visitors(
        current_user=current_user,
        params=params,
        active=active,
    )
    read_items = [VisitorRead.model_validate(it) for it in items]
    return Page.create(items=read_items, total=total, params=params)


@router.get(
    "/visitors/{id}",
    response_model=VisitorRead,
    summary="Get visitor record by ID (Admin, Warden, or student self)",
)
async def get_visitor_by_id(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_role(UserRole.ADMIN, UserRole.WARDEN, UserRole.STUDENT)),
    ],
) -> VisitorRead:
    """Retrieve details of a specific visitor record."""
    service = OperationsService(session)
    visitor = await service.get_visitor_by_id(visitor_id=id, current_user=current_user)
    return VisitorRead.model_validate(visitor)
