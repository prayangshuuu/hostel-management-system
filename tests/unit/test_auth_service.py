"""Unit tests for AuthService business logic."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnauthorizedError, ValidationAppError
from app.core.security import create_access_token, create_refresh_token, hash_password
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_auth_service_authenticate_success(db_session: AsyncSession) -> None:
    """Verify successful authentication returns token response."""
    repo = UserRepository(db_session)
    user = User(
        id=uuid4(),
        email="auth_success@example.com",
        full_name="Auth Success",
        hashed_password=hash_password("ValidPassword123"),
        role=UserRole.STUDENT,
        is_active=True,
    )
    await repo.create(user)

    service = AuthService(repo)
    token_resp = await service.authenticate("auth_success@example.com", "ValidPassword123")

    assert token_resp.access_token is not None
    assert token_resp.refresh_token is not None
    assert token_resp.token_type == "bearer"


@pytest.mark.asyncio
async def test_auth_service_authenticate_wrong_password(db_session: AsyncSession) -> None:
    """Verify wrong password raises UnauthorizedError with INVALID_CREDENTIALS."""
    repo = UserRepository(db_session)
    user = User(
        id=uuid4(),
        email="wrong_pw@example.com",
        full_name="Wrong PW",
        hashed_password=hash_password("ValidPassword123"),
        role=UserRole.STUDENT,
        is_active=True,
    )
    await repo.create(user)

    service = AuthService(repo)
    with pytest.raises(UnauthorizedError) as exc_info:
        await service.authenticate("wrong_pw@example.com", "WrongPassword999")
    assert exc_info.value.code == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_auth_service_authenticate_user_not_found(db_session: AsyncSession) -> None:
    """Verify non-existent user raises UnauthorizedError with INVALID_CREDENTIALS."""
    repo = UserRepository(db_session)
    service = AuthService(repo)

    with pytest.raises(UnauthorizedError) as exc_info:
        await service.authenticate("nonexistent@example.com", "Password123")
    assert exc_info.value.code == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_auth_service_authenticate_inactive_user(db_session: AsyncSession) -> None:
    """Verify inactive user raises UnauthorizedError with INACTIVE_USER."""
    repo = UserRepository(db_session)
    user = User(
        id=uuid4(),
        email="inactive@example.com",
        full_name="Inactive User",
        hashed_password=hash_password("ValidPassword123"),
        role=UserRole.STUDENT,
        is_active=False,
    )
    await repo.create(user)

    service = AuthService(repo)
    with pytest.raises(UnauthorizedError) as exc_info:
        await service.authenticate("inactive@example.com", "ValidPassword123")
    assert exc_info.value.code == "INACTIVE_USER"


@pytest.mark.asyncio
async def test_auth_service_refresh_token_flow(db_session: AsyncSession) -> None:
    """Verify refresh token exchange for active user."""
    repo = UserRepository(db_session)
    user = User(
        id=uuid4(),
        email="refresh_flow@example.com",
        full_name="Refresh Flow",
        hashed_password=hash_password("ValidPassword123"),
        role=UserRole.WARDEN,
        is_active=True,
    )
    await repo.create(user)

    refresh_token = create_refresh_token(user_id=user.id, role="warden")
    service = AuthService(repo)
    new_tokens = await service.refresh_token(refresh_token)

    assert new_tokens.access_token is not None
    assert new_tokens.refresh_token is not None


@pytest.mark.asyncio
async def test_auth_service_refresh_token_with_access_token_fails(db_session: AsyncSession) -> None:
    """Verify presenting an access token to refresh flow is rejected."""
    repo = UserRepository(db_session)
    user = User(
        id=uuid4(),
        email="wrong_token_type@example.com",
        full_name="Wrong Token",
        hashed_password=hash_password("ValidPassword123"),
        role=UserRole.WARDEN,
        is_active=True,
    )
    await repo.create(user)

    access_token = create_access_token(user_id=user.id, role="warden")
    service = AuthService(repo)
    with pytest.raises(UnauthorizedError) as exc_info:
        await service.refresh_token(access_token)
    assert exc_info.value.code == "INVALID_TOKEN_TYPE"


@pytest.mark.asyncio
async def test_auth_service_change_password(db_session: AsyncSession) -> None:
    """Verify change_password validates current password and updates hash."""
    repo = UserRepository(db_session)
    user = User(
        id=uuid4(),
        email="change_pw@example.com",
        full_name="Change PW",
        hashed_password=hash_password("OldPassword123"),
        role=UserRole.STUDENT,
        is_active=True,
    )
    await repo.create(user)

    service = AuthService(repo)

    # Wrong current password
    with pytest.raises(UnauthorizedError) as exc_info:
        await service.change_password(user, "IncorrectOld123", "NewPassword123")
    assert exc_info.value.code == "INVALID_CURRENT_PASSWORD"

    # Weak new password
    with pytest.raises(ValidationAppError) as exc_info_weak:
        await service.change_password(user, "OldPassword123", "weak")
    assert exc_info_weak.value.code == "WEAK_PASSWORD"

    # Successful change
    await service.change_password(user, "OldPassword123", "BrandNewPassword123")
    assert user.hashed_password != "OldPassword123"

    # Authenticate with new password
    auth_resp = await service.authenticate("change_pw@example.com", "BrandNewPassword123")
    assert auth_resp.access_token is not None


@pytest.mark.asyncio
async def test_auth_service_refresh_token_edge_cases(db_session: AsyncSession) -> None:
    """Verify refresh_token edge cases: non-uuid sub, missing user, inactive user."""
    import jwt

    from app.core.config import settings

    repo = UserRepository(db_session)
    service = AuthService(repo)

    # Invalid UUID sub
    bad_uuid_token = jwt.encode(
        {"sub": "invalid-uuid", "type": "refresh"},
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(UnauthorizedError) as exc_info:
        await service.refresh_token(bad_uuid_token)
    assert exc_info.value.code == "INVALID_TOKEN"

    # User not found
    unknown_user_token = create_refresh_token(user_id=uuid4(), role="student")
    with pytest.raises(UnauthorizedError) as exc_not_found:
        await service.refresh_token(unknown_user_token)
    assert exc_not_found.value.code == "USER_NOT_FOUND"

    # Inactive user
    inactive_user = User(
        id=uuid4(),
        email="inactive_refresh@example.com",
        full_name="Inactive Refresh",
        hashed_password="pw",
        role=UserRole.STUDENT,
        is_active=False,
    )
    await repo.create(inactive_user)

    inactive_token = create_refresh_token(user_id=inactive_user.id, role="student")
    with pytest.raises(UnauthorizedError) as exc_inactive:
        await service.refresh_token(inactive_token)
    assert exc_inactive.value.code == "INACTIVE_USER"
