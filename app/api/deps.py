"""Common API dependencies."""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Validate access token and return the associated user."""
    payload = decode_token(token, expected_type="access")
    sub = payload.get("sub")
    if not sub:
        raise UnauthorizedError("Token missing subject claim", code="INVALID_TOKEN")

    try:
        user_id = UUID(sub)
    except (ValueError, TypeError) as err:
        raise UnauthorizedError("Invalid user ID in token", code="INVALID_TOKEN") from err

    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(user_id)
    if user is None:
        raise UnauthorizedError("User not found", code="USER_NOT_FOUND")

    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Ensure the authenticated user account is active."""
    if not current_user.is_active:
        raise UnauthorizedError("User account is inactive", code="INACTIVE_USER")
    return current_user


def require_role(
    *roles: str | UserRole,
) -> Callable[..., Coroutine[Any, Any, User]]:
    """Return a dependency enforcing that current user holds at least one of the specified roles."""
    allowed_roles = {r.value if isinstance(r, UserRole) else str(r) for r in roles}

    async def role_dependency(
        current_user: Annotated[User, Depends(get_current_active_user)],
    ) -> User:
        user_role_str = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if user_role_str not in allowed_roles:
            raise ForbiddenError(
                "Insufficient permissions for requested resource",
                code="INSUFFICIENT_PERMISSIONS",
            )
        return current_user

    return role_dependency


__all__ = [
    "get_current_active_user",
    "get_current_user",
    "get_db",
    "oauth2_scheme",
    "require_role",
]
