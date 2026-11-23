"""Admin portal notice board management with live preview and status badges."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csrf import verify_csrf
from app.db.session import get_db
from app.models.notice import NoticeAudience
from app.models.user import User, UserRole
from app.repositories.hostel_repository import HostelRepository
from app.schemas.common import PaginationParams
from app.schemas.notice import NoticeCreate, NoticeUpdate
from app.services.notice_service import NoticeService
from app.web.deps import render_template, require_staff_web

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/notices", tags=["admin-notices"])


def compute_notice_status(notice: Any) -> str:
    """Compute notice operational status: scheduled, live, or expired."""
    now = datetime.now(UTC)
    pub = notice.published_at
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=UTC)
    if pub > now:
        return "scheduled"

    if notice.expires_at:
        exp = notice.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        if exp < now:
            return "expired"

    return "live"


@router.get("", response_class=HTMLResponse)
async def list_notices_screen(
    request: Request,
    hostel_id: UUID | None = Query(None),
    audience: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=100),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """List administrative notices with status badge and scope info."""
    staff, assigned_hostels = current_staff
    notice_service = NoticeService(db)
    hostel_repo = HostelRepository(db)

    all_hostels, _ = await hostel_repo.list(params=PaginationParams(page=1, size=100))
    if staff.role == UserRole.WARDEN:
        hostels = [h for h in all_hostels if h.id in assigned_hostels]
    else:
        hostels = all_hostels

    n_audience = None
    if audience:
        try:
            n_audience = NoticeAudience(audience.lower())
        except ValueError:
            n_audience = None

    params = PaginationParams(page=page, size=size)
    notices_page = await notice_service.list_notices(
        params=params,
        current_user=staff,
        include_drafts_expired=True,
        hostel_id=hostel_id,
        audience=n_audience,
    )

    notices_with_status = [
        {"notice": n, "status": compute_notice_status(n)} for n in notices_page.items
    ]

    return render_template(
        request,
        "admin/notices/index.html",
        {
            "active_nav": "notices",
            "hostels": hostels,
            "selected_hostel_id": hostel_id,
            "selected_audience": audience or "",
            "notices": notices_with_status,
            "total": notices_page.total,
            "page": page,
            "pages": notices_page.pages,
            "size": size,
            "audiences": list(NoticeAudience),
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_notice_form(
    request: Request,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render notice creation form."""
    staff, assigned_hostels = current_staff
    hostel_repo = HostelRepository(db)

    all_hostels, _ = await hostel_repo.list(params=PaginationParams(page=1, size=100))
    if staff.role == UserRole.WARDEN:
        hostels = [h for h in all_hostels if h.id in assigned_hostels]
    else:
        hostels = all_hostels

    return render_template(
        request,
        "admin/notices/form.html",
        {
            "active_nav": "notices",
            "is_edit": False,
            "notice": None,
            "hostels": hostels,
            "audiences": list(NoticeAudience),
            "is_admin": staff.role == UserRole.ADMIN,
        },
    )


@router.post("")
async def create_notice_submit(
    request: Request,
    title: str = Form(...),
    body: str = Form(...),
    audience: str = Form(...),
    hostel_id: UUID | None = Form(None),
    is_pinned: bool = Form(False),
    published_at: datetime | None = Form(None),
    expires_at: datetime | None = Form(None),
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Submit new notice announcement."""
    staff, _ = current_staff
    verify_csrf(request, form_csrf=csrf_token)
    notice_service = NoticeService(db)

    payload = NoticeCreate(
        title=title.strip(),
        body=body.strip(),
        audience=NoticeAudience(audience.lower()),
        hostel_id=hostel_id if hostel_id else None,
        is_pinned=is_pinned,
        published_at=published_at,
        expires_at=expires_at,
    )
    await notice_service.create_notice(current_user=staff, payload=payload)

    return RedirectResponse(
        url="/admin/notices",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/{id}/edit", response_class=HTMLResponse)
async def edit_notice_form(
    request: Request,
    id: UUID,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render notice edit form."""
    staff, assigned_hostels = current_staff
    notice_service = NoticeService(db)
    notice = await notice_service.get_notice(current_user=staff, notice_id=id)

    hostel_repo = HostelRepository(db)
    all_hostels, _ = await hostel_repo.list(params=PaginationParams(page=1, size=100))
    if staff.role == UserRole.WARDEN:
        hostels = [h for h in all_hostels if h.id in assigned_hostels]
    else:
        hostels = all_hostels

    return render_template(
        request,
        "admin/notices/form.html",
        {
            "active_nav": "notices",
            "is_edit": True,
            "notice": notice,
            "hostels": hostels,
            "audiences": list(NoticeAudience),
            "is_admin": staff.role == UserRole.ADMIN,
        },
    )


@router.post("/{id}/edit")
async def edit_notice_submit(
    request: Request,
    id: UUID,
    title: str = Form(...),
    body: str = Form(...),
    audience: str = Form(...),
    is_pinned: bool = Form(False),
    published_at: datetime | None = Form(None),
    expires_at: datetime | None = Form(None),
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Submit notice modifications."""
    staff, _ = current_staff
    verify_csrf(request, form_csrf=csrf_token)
    notice_service = NoticeService(db)

    update_data: dict[str, Any] = {
        "title": title.strip(),
        "body": body.strip(),
        "audience": NoticeAudience(audience.lower()),
        "is_pinned": is_pinned,
    }
    if published_at is not None:
        update_data["published_at"] = published_at
    if expires_at is not None:
        update_data["expires_at"] = expires_at

    payload = NoticeUpdate(**update_data)
    await notice_service.update_notice(current_user=staff, notice_id=id, payload=payload)

    return RedirectResponse(
        url="/admin/notices",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{id}/delete")
async def delete_notice_submit(
    request: Request,
    id: UUID,
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a notice."""
    staff, _ = current_staff
    verify_csrf(request, form_csrf=csrf_token)
    notice_service = NoticeService(db)
    await notice_service.delete_notice(current_user=staff, notice_id=id)

    return RedirectResponse(
        url="/admin/notices",
        status_code=status.HTTP_303_SEE_OTHER,
    )
