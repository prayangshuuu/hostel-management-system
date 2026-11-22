"""User management endpoints for administrative operations."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.common import Page, PaginationParams
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.user_service import UserService

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user (admin only)",
)
async def create_user(
    body: UserCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> UserRead:
    """Create a user with specified role and details."""
    user_service = UserService(UserRepository(session))
    user = await user_service.create_user(body, current_user=current_user)
    return UserRead.model_validate(user)


@router.get(
    "",
    response_model=Page[UserRead],
    summary="List users (admin only)",
)
async def list_users(
    params: Annotated[PaginationParams, Depends()],
    session: Annotated[AsyncSession, Depends(get_db)],
    role: Annotated[UserRole | None, Query(description="Filter by user role")] = None,
    is_active: Annotated[bool | None, Query(description="Filter by active status")] = None,
    search: Annotated[str | None, Query(description="Search by name or email")] = None,
) -> Page[UserRead]:
    """Retrieve paginated list of users with optional filtering and search."""
    user_service = UserService(UserRepository(session))
    return await user_service.list_users(
        params=params,
        role=role,
        is_active=is_active,
        search=search,
    )


@router.get(
    "/{id}",
    response_model=UserRead,
    summary="Get user details by ID (admin only)",
)
async def get_user(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserRead:
    """Retrieve details of a single user by primary key."""
    user_service = UserService(UserRepository(session))
    user = await user_service.get_user(id)
    return UserRead.model_validate(user)


@router.patch(
    "/{id}",
    response_model=UserRead,
    summary="Update user details (admin only)",
)
async def update_user(
    id: UUID,
    body: UserUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserRead:
    """Update profile and role fields of an existing user."""
    user_service = UserService(UserRepository(session))
    user = await user_service.update_user(user_id=id, user_update=body)
    return UserRead.model_validate(user)


@router.post(
    "/{id}/deactivate",
    response_model=UserRead,
    summary="Deactivate a user account (admin only)",
)
async def deactivate_user(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> UserRead:
    """Set user account active status to false."""
    user_service = UserService(UserRepository(session))
    user = await user_service.deactivate_user(id, current_user=current_user)
    return UserRead.model_validate(user)
