"""Complaints and maintenance REST endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db, require_role
from app.models.complaint import ComplaintCategory, ComplaintPriority, ComplaintStatus
from app.models.user import User, UserRole
from app.schemas.common import Page, PaginationParams
from app.schemas.complaint import (
    ComplaintAssignRequest,
    ComplaintCommentCreate,
    ComplaintCommentRead,
    ComplaintCreate,
    ComplaintDetailRead,
    ComplaintRead,
    ComplaintStatusUpdateRequest,
)
from app.services.complaint_service import ComplaintService

router = APIRouter(tags=["complaints"])


@router.post(
    "/complaints",
    response_model=ComplaintRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new complaint (Student only)",
)
async def create_complaint(
    body: ComplaintCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.STUDENT))],
) -> ComplaintRead:
    """Lodge a complaint auto-bound to the student's active room allocation."""
    service = ComplaintService(session)
    complaint = await service.create_complaint(data=body, current_user=current_user)
    return ComplaintRead.model_validate(complaint)


@router.get(
    "/complaints",
    response_model=Page[ComplaintRead],
    summary="List complaints with filters and role-based scoping",
)
async def list_complaints(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    params: Annotated[PaginationParams, Depends()],
    status_filter: Annotated[
        ComplaintStatus | None,
        Query(alias="status", description="Filter by complaint status"),
    ] = None,
    priority: Annotated[
        ComplaintPriority | None,
        Query(description="Filter by complaint priority"),
    ] = None,
    category: Annotated[
        ComplaintCategory | None,
        Query(description="Filter by complaint category"),
    ] = None,
    hostel_id: Annotated[
        UUID | None,
        Query(description="Filter by hostel UUID"),
    ] = None,
    assigned_to: Annotated[
        UUID | None,
        Query(description="Filter by assigned user UUID"),
    ] = None,
) -> Page[ComplaintRead]:
    """Retrieve paginated complaints filtered by status, priority, category, hostel, or assignee."""
    service = ComplaintService(session)
    items, total = await service.list_complaints(
        params=params,
        current_user=current_user,
        status=status_filter,
        priority=priority,
        category=category,
        hostel_id=hostel_id,
        assigned_to=assigned_to,
    )
    read_items = [ComplaintRead.model_validate(it) for it in items]
    return Page.create(items=read_items, total=total, params=params)


@router.get(
    "/complaints/{id}",
    response_model=ComplaintDetailRead,
    summary="Get complaint details with comments",
)
async def get_complaint(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ComplaintDetailRead:
    """Retrieve detailed complaint with comments (internal comments hidden from students)."""
    service = ComplaintService(session)
    return await service.get_complaint(id=id, current_user=current_user)


@router.post(
    "/complaints/{id}/assign",
    response_model=ComplaintRead,
    summary="Assign complaint to user (Admin or Warden)",
)
async def assign_complaint(
    id: UUID,
    body: ComplaintAssignRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
) -> ComplaintRead:
    """Assign a complaint to a staff user, transitioning OPEN complaints to IN_PROGRESS."""
    service = ComplaintService(session)
    complaint = await service.assign_complaint(id=id, data=body, current_user=current_user)
    return ComplaintRead.model_validate(complaint)


@router.post(
    "/complaints/{id}/status",
    response_model=ComplaintRead,
    summary="Update complaint status (Admin, Warden, or Student for reopen/close)",
)
async def update_complaint_status(
    id: UUID,
    body: ComplaintStatusUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ComplaintRead:
    """Transition complaint lifecycle status according to domain state machine rules."""
    service = ComplaintService(session)
    complaint = await service.update_status(id=id, data=body, current_user=current_user)
    return ComplaintRead.model_validate(complaint)


@router.post(
    "/complaints/{id}/comments",
    response_model=ComplaintCommentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add comment to a complaint",
)
async def add_comment(
    id: UUID,
    body: ComplaintCommentCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ComplaintCommentRead:
    """Post a comment to a complaint thread."""
    service = ComplaintService(session)
    comment = await service.add_comment(id=id, data=body, current_user=current_user)
    return ComplaintCommentRead.model_validate(comment)
