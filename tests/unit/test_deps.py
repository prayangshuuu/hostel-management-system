"""Unit tests for API dependencies."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_current_user, require_role
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import create_access_token
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository


@pytest.mark.asyncio
async def test_get_current_user_valid(db_session: AsyncSession) -> None:
    """Verify get_current_user returns user when token is valid."""
    repo = UserRepository(db_session)
    user = User(
        id=uuid4(),
        email="deps_valid@example.com",
        full_name="Deps User",
        hashed_password="pw",
        role=UserRole.STUDENT,
        is_active=True,
    )
    await repo.create(user)

    token = create_access_token(user_id=user.id, role="student")
    fetched = await get_current_user(token=token, session=db_session)
    assert fetched.id == user.id


@pytest.mark.asyncio
async def test_get_current_user_invalid_uuid(db_session: AsyncSession) -> None:
    """Verify get_current_user raises UnauthorizedError if sub is not a valid UUID."""
    import jwt

    from app.core.config import settings

    token = jwt.encode(
        {"sub": "not-a-uuid", "type": "access", "role": "admin"},
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(UnauthorizedError) as exc_info:
        await get_current_user(token=token, session=db_session)
    assert exc_info.value.code == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_get_current_user_not_found_in_db(db_session: AsyncSession) -> None:
    """Verify get_current_user raises UnauthorizedError if user does not exist in DB."""
    token = create_access_token(user_id=uuid4(), role="student")
    with pytest.raises(UnauthorizedError) as exc_info:
        await get_current_user(token=token, session=db_session)
    assert exc_info.value.code == "USER_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_current_active_user_inactive() -> None:
    """Verify get_current_active_user raises UnauthorizedError for inactive user."""
    user = User(
        id=uuid4(),
        email="inactive_check@example.com",
        full_name="Inactive",
        hashed_password="pw",
        role=UserRole.STUDENT,
        is_active=False,
    )
    with pytest.raises(UnauthorizedError) as exc_info:
        await get_current_active_user(current_user=user)
    assert exc_info.value.code == "INACTIVE_USER"


@pytest.mark.asyncio
async def test_require_role_checker() -> None:
    """Verify require_role allows permitted roles and denies others."""
    admin_checker = require_role(UserRole.ADMIN)

    admin_user = User(
        id=uuid4(),
        email="admin_check@example.com",
        full_name="Admin",
        hashed_password="pw",
        role=UserRole.ADMIN,
        is_active=True,
    )
    student_user = User(
        id=uuid4(),
        email="student_check@example.com",
        full_name="Student",
        hashed_password="pw",
        role=UserRole.STUDENT,
        is_active=True,
    )

    allowed = await admin_checker(current_user=admin_user)
    assert allowed.id == admin_user.id

    with pytest.raises(ForbiddenError) as exc_info:
        await admin_checker(current_user=student_user)
    assert exc_info.value.code == "INSUFFICIENT_PERMISSIONS"
