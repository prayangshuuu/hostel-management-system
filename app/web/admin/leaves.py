"""Admin portal leave request review and history routes."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csrf import verify_csrf
from app.db.session import get_db
from app.models.operations import LeaveStatus
from app.models.user import User, UserRole
from app.repositories.hostel_repository import HostelRepository
from app.schemas.common import PaginationParams
from app.schemas.operations import LeaveReviewRequest
from app.services.operations_service import OperationsService
from app.web.deps import render_template, require_staff_web

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/leaves", tags=["admin-leaves"])


@router.get("", response_class=HTMLResponse)
async def list_leaves_screen(
    request: Request,
    status_tab: str = Query("pending"),
    hostel_id: UUID | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=100),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Leaves list with Pending queue default tab and filters."""
    staff, assigned_hostels = current_staff
    ops_service = OperationsService(db)
    hostel_repo = HostelRepository(db)

    all_hostels, _ = await hostel_repo.list(params=PaginationParams(page=1, size=100))
    if staff.role == UserRole.WARDEN:
        hostels = [h for h in all_hostels if h.id in assigned_hostels]
    else:
        hostels = all_hostels

    leave_status = None
    if status_tab != "all":
        try:
            leave_status = LeaveStatus(status_tab.lower())
        except ValueError:
            leave_status = LeaveStatus.PENDING

    params = PaginationParams(page=page, size=size)
    leaves, total = await ops_service.list_leaves(
        params=params,
        current_user=staff,
        status=leave_status,
        hostel_id=hostel_id,
    )
    pages = (total + size - 1) // size if total > 0 else 1

    return render_template(
        request,
        "admin/leaves/index.html",
        {
            "active_nav": "leaves",
            "hostels": hostels,
            "selected_hostel_id": hostel_id,
            "status_tab": status_tab.lower(),
            "leaves": leaves,
            "total": total,
            "page": page,
            "pages": pages,
            "size": size,
        },
    )


@router.get("/{id}/modal/review", response_class=HTMLResponse)
async def leave_review_modal(
    request: Request,
    id: UUID,
    action: str = Query("approve"),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render leave review dialog modal."""
    staff, _ = current_staff
    ops_service = OperationsService(db)
    leave = await ops_service.get_leave_by_id(id, current_user=staff)
    return render_template(
        request,
        "admin/leaves/review_modal.html",
        {
            "leave": leave,
            "action": action,
            "error": None,
        },
    )


@router.post("/{id}/approve")
async def approve_leave_submit(
    request: Request,
    id: UUID,
    remarks: str | None = Form(None),
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Approve a student leave request with optional remarks."""
    staff, _ = current_staff
    verify_csrf(request, form_csrf=csrf_token)
    ops_service = OperationsService(db)
    review = LeaveReviewRequest(review_notes=remarks.strip() if remarks else None)
    await ops_service.approve_leave_request(id, current_user=staff, review=review)

    if request.headers.get("HX-Request") == "true":
        response = Response(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = "/admin/leaves"
        return response

    return RedirectResponse(
        url="/admin/leaves",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{id}/reject")
async def reject_leave_submit(
    request: Request,
    id: UUID,
    remarks: str | None = Form(None),
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Reject a student leave request with optional remarks."""
    staff, _ = current_staff
    verify_csrf(request, form_csrf=csrf_token)
    ops_service = OperationsService(db)
    review = LeaveReviewRequest(review_notes=remarks.strip() if remarks else None)
    await ops_service.reject_leave_request(id, current_user=staff, review=review)

    if request.headers.get("HX-Request") == "true":
        response = Response(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = "/admin/leaves"
        return response

    return RedirectResponse(
        url="/admin/leaves",
        status_code=status.HTTP_303_SEE_OTHER,
    )
