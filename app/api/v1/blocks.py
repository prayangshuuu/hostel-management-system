"""Block management endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db, require_role
from app.models.user import User, UserRole
from app.schemas.hostel import BlockRead, BlockUpdate
from app.services.hostel_service import HostelService

router = APIRouter(prefix="/blocks", tags=["blocks"])


@router.get(
    "/{id}",
    response_model=BlockRead,
    summary="Get block details by ID (admin or assigned warden)",
)
async def get_block(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> BlockRead:
    """Retrieve details of a single block, enforcing hostel access for wardens."""
    service = HostelService(session)
    block = await service.get_block(id)
    await service.ensure_hostel_access(current_user, block.hostel_id)
    return BlockRead.model_validate(block)


@router.patch(
    "/{id}",
    response_model=BlockRead,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
    summary="Update block details (admin only)",
)
async def update_block(
    id: UUID,
    body: BlockUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> BlockRead:
    """Update block name or floor count."""
    service = HostelService(session)
    block = await service.update_block(block_id=id, data=body)
    return BlockRead.model_validate(block)


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
    summary="Delete a block (admin only)",
)
async def delete_block(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete a block record."""
    service = HostelService(session)
    await service.delete_block(id)
