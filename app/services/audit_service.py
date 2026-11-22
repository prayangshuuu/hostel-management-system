"""Audit service for logging critical actions and auditing queries."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError
from app.models.audit import AuditLog
from app.models.user import User, UserRole
from app.repositories.audit_repository import AuditLogRepository
from app.schemas.audit import AuditLogRead
from app.schemas.common import Page, PaginationParams

__all__ = [
    "AuditService",
]


class AuditService:
    """Service handling audit trail recording and administrative querying."""

    SENSITIVE_KEYS: frozenset[str] = frozenset(
        {
            "password",
            "hashed_password",
            "token",
            "access_token",
            "refresh_token",
            "secret",
            "authorization",
            "api_key",
            "jwt",
        }
    )

    def __init__(
        self,
        session: AsyncSession,
        audit_repo: AuditLogRepository | None = None,
    ) -> None:
        self.session = session
        self.audit_repo = audit_repo or AuditLogRepository(session)

    @classmethod
    def sanitize_payload(cls, payload: Any) -> Any:
        """Recursively redact sensitive keys (passwords, tokens, secrets) from audit payloads."""
        if isinstance(payload, dict):
            sanitized: dict[str, Any] = {}
            for k, v in payload.items():
                key_str = str(k).lower()
                if key_str in cls.SENSITIVE_KEYS or any(
                    sens in key_str for sens in ("password", "token", "secret", "authorization")
                ):
                    sanitized[str(k)] = "[REDACTED]"
                else:
                    sanitized[str(k)] = cls.sanitize_payload(v)
            return sanitized
        if isinstance(payload, (list, tuple)):
            return [cls.sanitize_payload(item) for item in payload]
        if isinstance(payload, UUID):
            return str(payload)
        if isinstance(payload, datetime):
            return payload.isoformat()
        return payload

    @classmethod
    async def record(
        cls,
        session: AsyncSession,
        actor_id: UUID | None,
        action: str,
        entity: str,
        entity_id: UUID,
        payload: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Record an immutable audit log entry in the SAME session without committing."""
        sanitized = cls.sanitize_payload(payload or {})
        log = AuditLog(
            actor_id=actor_id,
            action=action,
            entity=entity,
            entity_id=entity_id,
            payload=sanitized,
        )
        session.add(log)
        await session.flush()
        return log

    async def list_audit_logs(
        self,
        params: PaginationParams,
        current_user: User,
        actor_id: UUID | None = None,
        entity: str | None = None,
        entity_id: UUID | None = None,
        action: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> Page[AuditLogRead]:
        """Fetch paginated audit logs for administrators with optional filtering."""
        role_str = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if role_str != UserRole.ADMIN.value:
            raise ForbiddenError("Only administrators can view audit logs", code="FORBIDDEN")

        logs, total = await self.audit_repo.list(
            params=params,
            actor_id=actor_id,
            entity=entity,
            entity_id=entity_id,
            action=action,
            date_from=date_from,
            date_to=date_to,
        )

        items = [AuditLogRead.model_validate(log) for log in logs]
        return Page.create(items=items, total=total, params=params)
