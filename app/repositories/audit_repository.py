"""AuditLog repository layer."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.audit import AuditLog
from app.schemas.common import PaginationParams

__all__ = [
    "AuditLogRepository",
]


class AuditLogRepository:
    """Repository handling database operations for the AuditLog entity."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, log: AuditLog) -> AuditLog:
        """Add and flush an audit log entry."""
        self.session.add(log)
        await self.session.flush()
        await self.session.refresh(log)
        return log

    async def list(
        self,
        params: PaginationParams,
        actor_id: UUID | None = None,
        entity: str | None = None,
        entity_id: UUID | None = None,
        action: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> tuple[list[AuditLog], int]:
        """Fetch paginated audit log entries matching optional filters."""
        stmt = select(AuditLog).options(joinedload(AuditLog.actor))
        count_stmt = select(func.count(AuditLog.id))

        if actor_id is not None:
            stmt = stmt.where(AuditLog.actor_id == actor_id)
            count_stmt = count_stmt.where(AuditLog.actor_id == actor_id)

        if entity is not None:
            stmt = stmt.where(AuditLog.entity == entity)
            count_stmt = count_stmt.where(AuditLog.entity == entity)

        if entity_id is not None:
            stmt = stmt.where(AuditLog.entity_id == entity_id)
            count_stmt = count_stmt.where(AuditLog.entity_id == entity_id)

        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
            count_stmt = count_stmt.where(AuditLog.action == action)

        if date_from is not None:
            stmt = stmt.where(AuditLog.created_at >= date_from)
            count_stmt = count_stmt.where(AuditLog.created_at >= date_from)

        if date_to is not None:
            stmt = stmt.where(AuditLog.created_at <= date_to)
            count_stmt = count_stmt.where(AuditLog.created_at <= date_to)

        stmt = stmt.order_by(AuditLog.created_at.desc())

        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        paginated_stmt = stmt.offset(params.offset).limit(params.limit)
        items_result = await self.session.execute(paginated_stmt)
        items = list(items_result.scalars().all())

        return items, total
