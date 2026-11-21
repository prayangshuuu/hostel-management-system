"""Authentication service providing login, token refresh, and password management."""

from uuid import UUID

from app.core.exceptions import UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    validate_password_policy,
    verify_password,
)
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import TokenResponse


class AuthService:
    """Service handling user authentication and token issuance."""

    def __init__(self, user_repo: UserRepository) -> None:
        self.user_repo = user_repo

    async def authenticate(self, email: str, password: str) -> TokenResponse:
        """Authenticate user credentials and issue access + refresh tokens."""
        user = await self.user_repo.get_by_email(email)
        if user is None or not verify_password(password, user.hashed_password):
            raise UnauthorizedError("Invalid email or password", code="INVALID_CREDENTIALS")

        if not user.is_active:
            raise UnauthorizedError("User account is inactive", code="INACTIVE_USER")

        role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
        access_token = create_access_token(user_id=user.id, role=role_str)
        refresh_token = create_refresh_token(user_id=user.id, role=role_str)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",  # noqa: S106
        )

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """Validate a refresh token and issue a new token pair."""
        payload = decode_token(refresh_token, expected_type="refresh")
        sub = payload.get("sub")
        if not sub:
            raise UnauthorizedError("Invalid token subject", code="INVALID_TOKEN")

        try:
            user_id = UUID(sub)
        except (ValueError, TypeError) as err:
            raise UnauthorizedError("Invalid user ID in token", code="INVALID_TOKEN") from err

        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise UnauthorizedError("User not found", code="USER_NOT_FOUND")

        if not user.is_active:
            raise UnauthorizedError("User account is inactive", code="INACTIVE_USER")

        role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
        access_token = create_access_token(user_id=user.id, role=role_str)
        new_refresh_token = create_refresh_token(user_id=user.id, role=role_str)

        return TokenResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",  # noqa: S106
        )

    async def change_password(
        self,
        user: User,
        current_password: str,
        new_password: str,
    ) -> None:
        """Verify the current password, validate policy, and update user password."""
        if not verify_password(current_password, user.hashed_password):
            raise UnauthorizedError("Invalid current password", code="INVALID_CURRENT_PASSWORD")

        validate_password_policy(new_password)
        user.hashed_password = hash_password(new_password)
        await self.user_repo.update(user)
