"""Hostel management and warden assignment endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db, require_role
from app.models.hostel import GenderType
from app.models.user import User, UserRole
from app.schemas.common import Page, PaginationParams
from app.schemas.hostel import (
    BlockCreate,
    BlockRead,
    HostelCreate,
    HostelRead,
    HostelUpdate,
    WardenAssignmentRead,
    WardenAssignRequest,
)
from app.services.hostel_service import HostelService

router = APIRouter(prefix="/hostels", tags=["hostels"])


@router.post(
    "",
    response_model=HostelRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
    summary="Create a new hostel (admin only)",
)
async def create_hostel(
    body: HostelCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> HostelRead:
    """Create a new hostel record."""
    service = HostelService(session)
    hostel = await service.create_hostel(body)
    return HostelRead.model_validate(hostel)


@router.get(
    "",
    response_model=Page[HostelRead],
    summary="List hostels (authenticated)",
)
async def list_hostels(
    params: Annotated[PaginationParams, Depends()],
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    gender_type: Annotated[
        GenderType | None, Query(description="Filter by gender segregation type")
    ] = None,
    search: Annotated[str | None, Query(description="Search by name, code, or address")] = None,
) -> Page[HostelRead]:
    """Retrieve paginated list of non-deleted hostels with optional filters."""
    service = HostelService(session)
    return await service.list_hostels(params=params, gender_type=gender_type, search=search)


@router.get(
    "/{id}",
    response_model=HostelRead,
    summary="Get hostel details by ID (authenticated)",
)
async def get_hostel(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HostelRead:
    """Retrieve details of a single hostel by primary key."""
    service = HostelService(session)
    hostel = await service.get_hostel(id)
    return HostelRead.model_validate(hostel)


@router.patch(
    "/{id}",
    response_model=HostelRead,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
    summary="Update hostel details (admin only)",
)
async def update_hostel(
    id: UUID,
    body: HostelUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> HostelRead:
    """Update name, code, gender type, or address of an existing hostel."""
    service = HostelService(session)
    hostel = await service.update_hostel(hostel_id=id, data=body)
    return HostelRead.model_validate(hostel)


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
    summary="Soft delete a hostel (admin only)",
)
async def delete_hostel(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Soft delete a hostel record."""
    service = HostelService(session)
    await service.delete_hostel(id)


@router.post(
    "/{id}/blocks",
    response_model=BlockRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
    summary="Create a block in a hostel (admin only)",
)
async def create_block(
    id: UUID,
    body: BlockCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BlockRead:
    """Create a new block within the specified hostel."""
    service = HostelService(session)
    block = await service.create_block(hostel_id=id, data=body)
    return BlockRead.model_validate(block)


@router.get(
    "/{id}/blocks",
    response_model=list[BlockRead],
    summary="List blocks in a hostel (admin or assigned warden)",
)
async def list_blocks(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[BlockRead]:
    """Retrieve all blocks for a hostel, enforcing warden assignment access."""
    service = HostelService(session)
    await service.ensure_hostel_access(current_user, id)
    blocks = await service.list_blocks(id)
    return [BlockRead.model_validate(b) for b in blocks]


@router.post(
    "/{id}/wardens",
    response_model=WardenAssignmentRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
    summary="Assign a warden to a hostel (admin only)",
)
async def assign_warden(
    id: UUID,
    body: WardenAssignRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> WardenAssignmentRead:
    """Assign a warden to manage the specified hostel."""
    service = HostelService(session)
    assignment = await service.assign_warden(hostel_id=id, user_id=body.user_id)
    return WardenAssignmentRead.model_validate(assignment)


@router.delete(
    "/{id}/wardens/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
    summary="Remove a warden assignment (admin only)",
)
async def remove_warden(
    id: UUID,
    user_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Remove warden assignment from the specified hostel."""
    service = HostelService(session)
    await service.remove_warden(hostel_id=id, user_id=user_id)


@router.get(
    "/{id}/wardens",
    response_model=list[WardenAssignmentRead],
    summary="List wardens assigned to a hostel (admin or assigned warden)",
)
async def list_wardens(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> list[WardenAssignmentRead]:
    """Retrieve all warden assignments for a hostel, enforcing warden assignment access."""
    service = HostelService(session)
    await service.ensure_hostel_access(current_user, id)
    assignments = await service.list_wardens(id)
    return [WardenAssignmentRead.model_validate(a) for a in assignments]
