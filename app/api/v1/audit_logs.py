"""Audit log querying REST endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.user import User, UserRole
from app.schemas.audit import AuditLogRead
from app.schemas.common import Page, PaginationParams
from app.services.audit_service import AuditService

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.get(
    "",
    response_model=Page[AuditLogRead],
    summary="List audit log entries (admin only)",
)
async def list_audit_logs(
    params: Annotated[PaginationParams, Depends()],
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN))],
    actor_id: Annotated[
        UUID | None,
        Query(description="Filter by actor UUID"),
    ] = None,
    entity: Annotated[
        str | None,
        Query(description="Filter by aggregate entity name"),
    ] = None,
    entity_id: Annotated[
        UUID | None,
        Query(description="Filter by aggregate entity UUID"),
    ] = None,
    action: Annotated[
        str | None,
        Query(description="Filter by action name"),
    ] = None,
    date_from: Annotated[
        datetime | None,
        Query(description="Filter audit logs created on or after this timestamp"),
    ] = None,
    date_to: Annotated[
        datetime | None,
        Query(description="Filter audit logs created on or before this timestamp"),
    ] = None,
) -> Page[AuditLogRead]:
    """Retrieve paginated audit trail logs for administrators."""
    service = AuditService(session)
    return await service.list_audit_logs(
        params=params,
        current_user=current_user,
        actor_id=actor_id,
        entity=entity,
        entity_id=entity_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
    )
