"""Admin portal audit log viewer with expandable JSON payload inspections."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.schemas.common import PaginationParams
from app.services.audit_service import AuditService
from app.web.deps import render_template, require_admin_web

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/audit", tags=["admin-audit"])


@router.get("", response_class=HTMLResponse)
async def audit_logs_screen(
    request: Request,
    entity: str | None = Query(None),
    action: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=100),
    admin: User = Depends(require_admin_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Superuser Audit Log inspection screen with filter and JSON payload previews."""
    audit_service = AuditService(db)
    params = PaginationParams(page=page, size=size)

    logs_page = await audit_service.list_audit_logs(
        params=params,
        current_user=admin,
        entity=entity if entity else None,
        action=action if action else None,
        date_from=date_from,
        date_to=date_to,
    )

    formatted_logs: list[dict[str, Any]] = []
    for log in logs_page.items:
        details_json = None
        if log.payload:
            details_json = json.dumps(log.payload, indent=2, default=str)
        formatted_logs.append(
            {
                "log": log,
                "details_json": details_json,
            }
        )

    return render_template(
        request,
        "admin/audit/index.html",
        {
            "active_nav": "audit",
            "entity": entity or "",
            "action": action or "",
            "date_from": date_from.isoformat() if date_from else "",
            "date_to": date_to.isoformat() if date_to else "",
            "logs": formatted_logs,
            "total": logs_page.total,
            "page": page,
            "pages": logs_page.pages,
            "size": size,
        },
    )
