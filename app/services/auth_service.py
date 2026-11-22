"""Authentication service providing login, token refresh, lockout, and session management."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.core.config import settings
from app.core.exceptions import AuthenticationError, UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    validate_password_policy,
    verify_password,
)
from app.models.user import User
from app.repositories.auth_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import TokenResponse

logger = logging.getLogger(__name__)


class AuthService:
    """Service handling user authentication, account lockout, token issuance and rotation."""

    def __init__(
        self,
        user_repo: UserRepository,
        refresh_token_repo: RefreshTokenRepository | None = None,
    ) -> None:
        self.user_repo = user_repo
        self.refresh_token_repo = (
            refresh_token_repo
            if refresh_token_repo is not None
            else RefreshTokenRepository(user_repo.session)
        )

    async def authenticate(self, email: str, password: str) -> TokenResponse:
        """Authenticate user credentials, enforce account lockout, and issue token pair."""
        user = await self.user_repo.get_by_email(email)
        now = datetime.now(UTC)

        if user is None:
            raise AuthenticationError("Invalid email or password", code="INVALID_CREDENTIALS")

        # Account lockout verification
        if user.locked_until is not None:
            locked_until = (
                user.locked_until
                if user.locked_until.tzinfo is not None
                else user.locked_until.replace(tzinfo=UTC)
            )
            if locked_until > now:
                raise AuthenticationError(
                    "Account temporarily locked due to multiple failed logins",
                    code="ACCOUNT_LOCKED",
                    status_code=401,
                )
            # Lockout cooldown elapsed: reset attempts and unlock
            user.failed_login_attempts = 0
            user.locked_until = None
            await self.user_repo.update(user)

        # Password verification
        if not verify_password(password, user.hashed_password):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.FAILED_LOGIN_LIMIT:
                user.locked_until = now + timedelta(minutes=settings.LOCKOUT_DURATION_MINUTES)
            await self.user_repo.update(user)
            await self.user_repo.session.commit()
            raise AuthenticationError("Invalid email or password", code="INVALID_CREDENTIALS")

        if not user.is_active:
            raise AuthenticationError("User account is inactive", code="INACTIVE_USER")

        # Reset failed attempts on successful login
        if user.failed_login_attempts > 0 or user.locked_until is not None:
            user.failed_login_attempts = 0
            user.locked_until = None
            await self.user_repo.update(user)

        role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
        access_token = create_access_token(user_id=user.id, role=role_str)

        token_jti = uuid4().hex
        token_family = uuid4()
        refresh_token = create_refresh_token(
            user_id=user.id,
            role=role_str,
            jti=token_jti,
            family_id=token_family,
        )
        expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        await self.refresh_token_repo.create(
            user_id=user.id,
            jti=token_jti,
            family_id=token_family,
            expires_at=expires_at,
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",  # noqa: S106 # nosec B106
        )

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """Validate a refresh token, check family revocation, rotate token, and issue new pair."""
        payload = decode_token(refresh_token, expected_type="refresh")
        sub = payload.get("sub")
        jti = payload.get("jti")

        if not sub or not jti:
            raise AuthenticationError(
                "Invalid token payload or missing identifier",
                code="INVALID_TOKEN",
            )

        try:
            user_id = UUID(sub)
        except (ValueError, TypeError) as err:
            raise AuthenticationError("Invalid user ID in token", code="INVALID_TOKEN") from err

        token_record = await self.refresh_token_repo.get_by_jti(jti)
        if token_record is None:
            raise AuthenticationError(
                "Refresh token not found or already invalidated",
                code="INVALID_TOKEN",
                status_code=401,
            )

        # Theft detection: if a revoked token is reused, revoke the entire family
        if token_record.is_revoked:
            await self.refresh_token_repo.revoke_family(token_record.family_id)
            await self.user_repo.session.commit()
            raise AuthenticationError(
                "Refresh token reuse detected; session revoked",
                code="TOKEN_REVOKED",
                status_code=401,
            )

        now = datetime.now(UTC)
        expires_at = (
            token_record.expires_at
            if token_record.expires_at.tzinfo is not None
            else token_record.expires_at.replace(tzinfo=UTC)
        )
        if expires_at <= now:
            raise AuthenticationError("Refresh token has expired", code="TOKEN_EXPIRED")

        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise AuthenticationError("User not found", code="USER_NOT_FOUND")

        if not user.is_active:
            raise AuthenticationError("User account is inactive", code="INACTIVE_USER")

        # Invalidate the consumed refresh token
        await self.refresh_token_repo.revoke_token(jti)

        # Issue rotated refresh token with a new JTI within the same token family
        role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
        new_jti = uuid4().hex
        family_id = token_record.family_id
        new_refresh_token = create_refresh_token(
            user_id=user.id,
            role=role_str,
            jti=new_jti,
            family_id=family_id,
        )
        new_expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        await self.refresh_token_repo.create(
            user_id=user.id,
            jti=new_jti,
            family_id=family_id,
            expires_at=new_expires_at,
        )

        access_token = create_access_token(user_id=user.id, role=role_str)
        return TokenResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",  # noqa: S106 # nosec B106
        )

    async def logout(
        self,
        refresh_token: str | None = None,
        user_id: UUID | None = None,
        current_user_id: UUID | None = None,
    ) -> None:
        """Revoke refresh token family via token or user identity."""
        target_user_id = user_id or current_user_id
        if refresh_token:
            try:
                payload = decode_token(refresh_token, expected_type="refresh")
                jti = payload.get("jti")
                family_id_claim = payload.get("family_id")
                if jti:
                    token_record = await self.refresh_token_repo.get_by_jti(jti)
                    if token_record:
                        await self.refresh_token_repo.revoke_family(token_record.family_id)
                        return
                if family_id_claim:
                    await self.refresh_token_repo.revoke_family(UUID(family_id_claim))
                    return
            except Exception as exc:
                logger.debug("Failed decoding refresh token during logout: %s", exc)

        if target_user_id is not None:
            await self.refresh_token_repo.revoke_by_user_id(target_user_id)

    async def change_password(
        self,
        user: User,
        current_password: str,
        new_password: str,
    ) -> None:
        """Verify current password, validate policy, update password, and revoke user sessions."""
        if not verify_password(current_password, user.hashed_password):
            raise UnauthorizedError("Invalid current password", code="INVALID_CURRENT_PASSWORD")

        validate_password_policy(new_password)
        user.hashed_password = hash_password(new_password)
        await self.user_repo.update(user)
        # Security hardening: revoke active refresh tokens on password rotation
        await self.refresh_token_repo.revoke_by_user_id(user.id)
