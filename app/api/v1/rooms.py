"""Room and Bed API endpoints."""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db, require_role
from app.models.room import RoomType
from app.models.user import User
from app.schemas.common import Page, PaginationParams
from app.schemas.room import (
    BedRead,
    RoomCreate,
    RoomRead,
    RoomUpdate,
    RoomWithBedsRead,
)
from app.services.room_service import RoomService

router = APIRouter(tags=["rooms"])


@router.get(
    "/rooms/available",
    response_model=Page[RoomRead],
    summary="Search available rooms (authenticated)",
)
async def search_available_rooms(
    params: Annotated[PaginationParams, Depends()],
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    hostel_id: Annotated[UUID | None, Query(description="Filter by hostel ID")] = None,
    room_type: Annotated[RoomType | None, Query(description="Filter by room type")] = None,
    floor: Annotated[int | None, Query(description="Filter by floor number")] = None,
    max_rent: Annotated[Decimal | None, Query(description="Maximum monthly rent")] = None,
) -> Page[RoomRead]:
    """Retrieve paginated list of available rooms matching optional search criteria."""
    service = RoomService(session)
    return await service.search_available_rooms(
        hostel_id=hostel_id,
        room_type=room_type,
        floor=floor,
        max_rent=max_rent,
        params=params,
    )


@router.post(
    "/blocks/{id}/rooms",
    response_model=RoomWithBedsRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a room in a block (admin or assigned warden)",
)
async def create_room(
    id: UUID,
    body: RoomCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role("admin", "warden"))],
) -> RoomWithBedsRead:
    """Create a new room in the specified block and generate labeled beds."""
    service = RoomService(session)
    room = await service.create_room(block_id=id, data=body, current_user=current_user)
    return RoomWithBedsRead.model_validate(room)


@router.get(
    "/blocks/{id}/rooms",
    response_model=Page[RoomRead],
    summary="List rooms in a block (admin or assigned warden)",
)
async def list_rooms(
    id: UUID,
    params: Annotated[PaginationParams, Depends()],
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Page[RoomRead]:
    """Retrieve paginated list of rooms within the specified block."""
    service = RoomService(session)
    return await service.list_rooms(block_id=id, params=params, current_user=current_user)


@router.get(
    "/rooms/{id}",
    response_model=RoomWithBedsRead,
    summary="Get room details by ID (admin or assigned warden)",
)
async def get_room(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> RoomWithBedsRead:
    """Retrieve details and beds of a single room."""
    service = RoomService(session)
    room = await service.get_room(room_id=id, current_user=current_user)
    return RoomWithBedsRead.model_validate(room)


@router.patch(
    "/rooms/{id}",
    response_model=RoomWithBedsRead,
    summary="Update room details (admin or assigned warden)",
)
async def update_room(
    id: UUID,
    body: RoomUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role("admin", "warden"))],
) -> RoomWithBedsRead:
    """Update room fields, adjusting beds if capacity changes."""
    service = RoomService(session)
    room = await service.update_room(room_id=id, data=body, current_user=current_user)
    return RoomWithBedsRead.model_validate(room)


@router.delete(
    "/rooms/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a room (admin or assigned warden)",
)
async def delete_room(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role("admin", "warden"))],
) -> None:
    """Soft delete a room record."""
    service = RoomService(session)
    await service.delete_room(room_id=id, current_user=current_user)


@router.post(
    "/rooms/{id}/maintenance",
    response_model=RoomWithBedsRead,
    summary="Set room to maintenance status (admin or assigned warden)",
)
async def set_maintenance(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role("admin", "warden"))],
) -> RoomWithBedsRead:
    """Set room status to MAINTENANCE."""
    service = RoomService(session)
    room = await service.set_maintenance(room_id=id, current_user=current_user)
    return RoomWithBedsRead.model_validate(room)


@router.post(
    "/rooms/{id}/available",
    response_model=RoomWithBedsRead,
    summary="Restore room from maintenance status (admin or assigned warden)",
)
async def set_available(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role("admin", "warden"))],
) -> RoomWithBedsRead:
    """Restore room from maintenance and recalculate operational status."""
    service = RoomService(session)
    room = await service.set_available(room_id=id, current_user=current_user)
    return RoomWithBedsRead.model_validate(room)


@router.get(
    "/rooms/{id}/beds",
    response_model=list[BedRead],
    summary="List beds in a room (admin or assigned warden)",
)
async def list_beds(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role("admin", "warden"))],
) -> list[BedRead]:
    """Retrieve all beds for the specified room."""
    service = RoomService(session)
    beds = await service.list_beds(room_id=id, current_user=current_user)
    return [BedRead.model_validate(b) for b in beds]
