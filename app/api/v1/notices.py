"""Notices and announcements REST endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db, require_role
from app.models.notice import NoticeAudience
from app.models.user import User, UserRole
from app.schemas.common import Page, PaginationParams
from app.schemas.notice import (
    NoticeCreate,
    NoticeRead,
    NoticeUnreadCount,
    NoticeUpdate,
)
from app.services.notice_service import NoticeService

router = APIRouter(prefix="/notices", tags=["notices"])


@router.post(
    "",
    response_model=NoticeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a notice announcement (admin or assigned warden)",
)
async def create_notice(
    body: NoticeCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_role(UserRole.ADMIN, UserRole.WARDEN)),
    ],
) -> NoticeRead:
    """Create a new notice announcement."""
    service = NoticeService(session)
    return await service.create_notice(current_user=current_user, payload=body)


@router.get(
    "",
    response_model=Page[NoticeRead],
    summary="List notices visible to current user",
)
async def list_notices(
    params: Annotated[PaginationParams, Depends()],
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    include_drafts_expired: Annotated[
        bool,
        Query(description="Include draft and expired notices (admin/warden only)"),
    ] = False,
    hostel_id: Annotated[
        UUID | None,
        Query(description="Filter by target hostel"),
    ] = None,
    audience: Annotated[
        NoticeAudience | None,
        Query(description="Filter by target audience"),
    ] = None,
) -> Page[NoticeRead]:
    """Retrieve paginated notices scoped to current user role and hostel allocation."""
    service = NoticeService(session)
    return await service.list_notices(
        params=params,
        current_user=current_user,
        include_drafts_expired=include_drafts_expired,
        hostel_id=hostel_id,
        audience=audience,
    )


@router.get(
    "/unread-count",
    response_model=NoticeUnreadCount,
    summary="Get count of unread visible notices for current user",
)
async def get_unread_count(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> NoticeUnreadCount:
    """Get count of unread visible notices for current user."""
    service = NoticeService(session)
    return await service.get_unread_count(current_user=current_user)


@router.get(
    "/{id}",
    response_model=NoticeRead,
    summary="Get details of a notice announcement",
)
async def get_notice(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> NoticeRead:
    """Get single notice verifying visibility permissions."""
    service = NoticeService(session)
    return await service.get_notice(current_user=current_user, notice_id=id)


@router.patch(
    "/{id}",
    response_model=NoticeRead,
    summary="Update a notice announcement (admin or assigned warden)",
)
async def update_notice(
    id: UUID,
    body: NoticeUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_role(UserRole.ADMIN, UserRole.WARDEN)),
    ],
) -> NoticeRead:
    """Update fields on an existing notice announcement."""
    service = NoticeService(session)
    return await service.update_notice(
        current_user=current_user,
        notice_id=id,
        payload=body,
    )


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a notice announcement (admin or assigned warden)",
)
async def delete_notice(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[
        User,
        Depends(require_role(UserRole.ADMIN, UserRole.WARDEN)),
    ],
) -> None:
    """Delete an existing notice announcement."""
    service = NoticeService(session)
    await service.delete_notice(current_user=current_user, notice_id=id)


@router.post(
    "/{id}/read",
    response_model=NoticeRead,
    summary="Mark notice as read for authenticated user",
)
async def mark_notice_as_read(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> NoticeRead:
    """Mark a notice as read idempotently."""
    service = NoticeService(session)
    return await service.mark_as_read(current_user=current_user, notice_id=id)
