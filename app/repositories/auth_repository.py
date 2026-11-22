"""Authentication and refresh token repository for database operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import RefreshToken


class RefreshTokenRepository:
    """Repository handling database operations for the RefreshToken entity."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        token: RefreshToken | None = None,
        *,
        user_id: UUID | None = None,
        jti: str | None = None,
        family_id: UUID | None = None,
        expires_at: datetime | None = None,
    ) -> RefreshToken:
        """Create and persist a new refresh token entity."""
        if token is None:
            if user_id is None or jti is None or family_id is None or expires_at is None:
                raise ValueError(
                    "Must provide either a RefreshToken instance or all required attributes."
                )
            token = RefreshToken(
                user_id=user_id,
                jti=jti,
                family_id=family_id,
                expires_at=expires_at,
                is_revoked=False,
            )
        self.session.add(token)
        await self.session.flush()
        await self.session.refresh(token)
        return token

    async def get_by_jti(self, jti: str) -> RefreshToken | None:
        """Fetch a single refresh token by its unique JWT ID."""
        stmt = select(RefreshToken).where(RefreshToken.jti == jti)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke_family(self, family_id: UUID) -> int:
        """Revoke all tokens in a family."""
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.is_revoked.is_(False))
            .values(is_revoked=True)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        cursor_result = cast(CursorResult[Any], result)
        return int(cursor_result.rowcount)

    async def revoke_token(self, jti: str) -> bool:
        """Revoke a single refresh token by its unique JWT ID."""
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.jti == jti, RefreshToken.is_revoked.is_(False))
            .values(is_revoked=True)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        cursor_result = cast(CursorResult[Any], result)
        return bool(cursor_result.rowcount > 0)

    async def revoke_by_user_id(self, user_id: UUID) -> int:
        """Revoke all active refresh tokens belonging to a specific user."""
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.is_revoked.is_(False))
            .values(is_revoked=True)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        cursor_result = cast(CursorResult[Any], result)
        return int(cursor_result.rowcount)
