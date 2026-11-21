"""Room bed allocation API endpoints."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db, require_role
from app.models.allocation import AllocationStatus
from app.models.user import User, UserRole
from app.schemas.allocation import (
    AllocationCreate,
    AllocationRead,
    AllocationTransferRequest,
    AllocationVacateRequest,
    OccupantRead,
)
from app.schemas.common import Page, PaginationParams
from app.services.allocation_service import AllocationService

router = APIRouter(tags=["allocations"])


@router.post(
    "/allocations",
    response_model=AllocationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Allocate bed or room to a student (admin or warden)",
)
async def allocate_bed(
    body: AllocationCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
) -> AllocationRead:
    """Assign a student to a room/bed enforcing capacity, gender, and maintenance invariants."""
    service = AllocationService(session)
    allocation = await service.allocate(data=body, current_user=current_user)
    return AllocationRead.model_validate(allocation)


@router.get(
    "/allocations",
    response_model=Page[AllocationRead],
    summary="List allocations with filters and warden scoping (admin or warden)",
)
async def list_allocations(
    params: Annotated[PaginationParams, Depends()],
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
    hostel_id: Annotated[UUID | None, Query(description="Filter by hostel ID")] = None,
    room_id: Annotated[UUID | None, Query(description="Filter by room ID")] = None,
    student_id: Annotated[UUID | None, Query(description="Filter by student profile ID")] = None,
    allocation_status: Annotated[
        AllocationStatus | None,
        Query(alias="status", description="Filter by allocation status"),
    ] = None,
    start_date: Annotated[
        date | None,
        Query(description="Filter allocations starting on or after"),
    ] = None,
    end_date: Annotated[
        date | None,
        Query(description="Filter allocations starting on or before"),
    ] = None,
) -> Page[AllocationRead]:
    """Retrieve paginated allocations matching query criteria with warden access restrictions."""
    service = AllocationService(session)
    return await service.list_allocations(
        params=params,
        current_user=current_user,
        hostel_id=hostel_id,
        room_id=room_id,
        student_id=student_id,
        status=allocation_status,
        start_date=start_date,
        end_date=end_date,
    )


@router.get(
    "/students/me/allocation",
    response_model=AllocationRead,
    summary="Get active allocation of the current student (student self-service)",
)
async def get_my_allocation(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.STUDENT))],
) -> AllocationRead:
    """Retrieve active room and bed allocation details for the authenticated student."""
    service = AllocationService(session)
    allocation = await service.get_my_active_allocation(current_user=current_user)
    return AllocationRead.model_validate(allocation)


@router.get(
    "/rooms/{id}/occupants",
    response_model=list[OccupantRead],
    summary="List current occupants of a room (admin or warden)",
)
async def get_room_occupants(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
) -> list[OccupantRead]:
    """Retrieve list of students currently occupying beds in the specified room."""
    service = AllocationService(session)
    return await service.get_room_occupants(room_id=id, current_user=current_user)


@router.get(
    "/allocations/{id}",
    response_model=AllocationRead,
    summary="Get allocation by ID (admin, assigned warden, or student themselves)",
)
async def get_allocation(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> AllocationRead:
    """Retrieve detailed allocation record enforcing ownership or warden access."""
    service = AllocationService(session)
    allocation = await service.get_allocation(id=id, current_user=current_user)
    return AllocationRead.model_validate(allocation)


@router.post(
    "/allocations/{id}/vacate",
    response_model=AllocationRead,
    summary="Vacate an active allocation (admin or warden)",
)
async def vacate_allocation(
    id: UUID,
    body: AllocationVacateRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
) -> AllocationRead:
    """Vacate an active allocation, mark bed available, and update room status."""
    service = AllocationService(session)
    allocation = await service.vacate(allocation_id=id, data=body, current_user=current_user)
    return AllocationRead.model_validate(allocation)


@router.post(
    "/allocations/{id}/transfer",
    response_model=AllocationRead,
    summary="Transfer student to a new bed or room atomically (admin or warden)",
)
async def transfer_allocation(
    id: UUID,
    body: AllocationTransferRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
) -> AllocationRead:
    """Atomically vacate existing bed and assign student to new bed in a single transaction."""
    service = AllocationService(session)
    allocation = await service.transfer(allocation_id=id, data=body, current_user=current_user)
    return AllocationRead.model_validate(allocation)


@router.post(
    "/allocations/{id}/cancel",
    response_model=AllocationRead,
    summary="Cancel future allocation (admin or warden)",
)
async def cancel_allocation(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
) -> AllocationRead:
    """Cancel an allocation starting in the future, freeing the reserved bed."""
    service = AllocationService(session)
    allocation = await service.cancel(allocation_id=id, current_user=current_user)
    return AllocationRead.model_validate(allocation)
