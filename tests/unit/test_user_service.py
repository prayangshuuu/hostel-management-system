"""Unit tests for UserService business logic."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models.user import UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.common import PaginationParams
from app.schemas.user import UserCreate, UserUpdate
from app.services.user_service import UserService


@pytest.mark.asyncio
async def test_user_service_create_user_success(db_session: AsyncSession) -> None:
    """Verify UserService creates user, lowercases email, and hashes password."""
    repo = UserRepository(db_session)
    service = UserService(repo)

    create_data = UserCreate(
        email="NewUser@example.com",
        full_name="New User",
        phone="+123456",
        password="SecurePassword123",
        role=UserRole.STUDENT,
    )
    user = await service.create_user(create_data)

    assert user.id is not None
    assert user.email == "newuser@example.com"
    assert user.full_name == "New User"
    assert user.hashed_password != "SecurePassword123"
    assert user.role == UserRole.STUDENT
    assert user.is_active is True


@pytest.mark.asyncio
async def test_user_service_create_user_duplicate_email(db_session: AsyncSession) -> None:
    """Verify duplicate email raises ConflictError with EMAIL_EXISTS."""
    repo = UserRepository(db_session)
    service = UserService(repo)

    create_data = UserCreate(
        email="duplicate@example.com",
        full_name="User 1",
        password="Password123",
        role=UserRole.STUDENT,
    )
    await service.create_user(create_data)

    with pytest.raises(ConflictError) as exc_info:
        await service.create_user(create_data)
    assert exc_info.value.code == "EMAIL_EXISTS"


@pytest.mark.asyncio
async def test_user_service_create_user_weak_password(db_session: AsyncSession) -> None:
    """Verify weak password raises ValidationAppError."""
    repo = UserRepository(db_session)
    service = UserService(repo)

    # Bypass Pydantic schema validation to test service-layer validation
    create_data = UserCreate.model_construct(
        email="weak_pw@example.com",
        full_name="Weak PW",
        phone=None,
        password="short",
        role=UserRole.STUDENT,
    )
    with pytest.raises(ValidationAppError) as exc_info:
        await service.create_user(create_data)
    assert exc_info.value.code == "WEAK_PASSWORD"


@pytest.mark.asyncio
async def test_user_service_get_user(db_session: AsyncSession) -> None:
    """Verify get_user retrieval and NotFoundError on missing user."""
    repo = UserRepository(db_session)
    service = UserService(repo)

    create_data = UserCreate(
        email="get_target@example.com",
        full_name="Get Target",
        password="Password123",
        role=UserRole.STUDENT,
    )
    user = await service.create_user(create_data)

    fetched = await service.get_user(user.id)
    assert fetched.id == user.id

    with pytest.raises(NotFoundError) as exc_info:
        await service.get_user(uuid4())
    assert exc_info.value.code == "USER_NOT_FOUND"


@pytest.mark.asyncio
async def test_user_service_update_and_deactivate(db_session: AsyncSession) -> None:
    """Verify update_user and deactivate_user."""
    repo = UserRepository(db_session)
    service = UserService(repo)

    user = await service.create_user(
        UserCreate(
            email="lifecycle@example.com",
            full_name="Original Name",
            password="Password123",
            role=UserRole.STUDENT,
        )
    )

    updated = await service.update_user(
        user.id,
        UserUpdate(full_name="Updated Name", role=UserRole.WARDEN),
    )
    assert updated.full_name == "Updated Name"
    assert updated.role == UserRole.WARDEN

    deactivated = await service.deactivate_user(user.id)
    assert deactivated.is_active is False


@pytest.mark.asyncio
async def test_user_service_list_users(db_session: AsyncSession) -> None:
    """Verify list_users returns Page[UserRead]."""
    repo = UserRepository(db_session)
    service = UserService(repo)

    for i in range(3):
        await service.create_user(
            UserCreate(
                email=f"list_user_{i}@example.com",
                full_name=f"List User {i}",
                password="Password123",
                role=UserRole.STUDENT,
            )
        )

    params = PaginationParams(page=1, size=2)
    page = await service.list_users(params)

    assert page.total == 3
    assert len(page.items) == 2
    assert page.pages == 2
    assert page.page == 1
