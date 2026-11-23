"""Admin portal complaint management, assignment, resolution, and comments."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csrf import verify_csrf
from app.db.session import get_db
from app.models.complaint import ComplaintCategory, ComplaintPriority, ComplaintStatus
from app.models.user import User, UserRole
from app.repositories.hostel_repository import HostelRepository
from app.schemas.common import PaginationParams
from app.schemas.complaint import (
    ComplaintAssignRequest,
    ComplaintCommentCreate,
    ComplaintStatusUpdateRequest,
)
from app.services.complaint_service import ComplaintService
from app.web.deps import render_template, require_staff_web

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/complaints", tags=["admin-complaints"])


@router.get("", response_class=HTMLResponse)
async def list_complaints_screen(
    request: Request,
    status_tab: str = Query("all"),
    priority: str | None = Query(None),
    category: str | None = Query(None),
    hostel_id: UUID | None = Query(None),
    assigned_to_me: bool = Query(False),
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=100),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Complaints queue with tabs and multi-criteria filters."""
    staff, assigned_hostels = current_staff
    complaint_service = ComplaintService(db)
    hostel_repo = HostelRepository(db)

    all_hostels, _ = await hostel_repo.list(params=PaginationParams(page=1, size=100))
    if staff.role == UserRole.WARDEN:
        hostels = [h for h in all_hostels if h.id in assigned_hostels]
    else:
        hostels = all_hostels

    c_status = None
    if status_tab != "all":
        try:
            c_status = ComplaintStatus(status_tab.lower())
        except ValueError:
            c_status = None

    c_priority = None
    if priority:
        try:
            c_priority = ComplaintPriority(priority.lower())
        except ValueError:
            c_priority = None

    c_category = None
    if category:
        try:
            c_category = ComplaintCategory(category.lower())
        except ValueError:
            c_category = None

    assigned_to_id = staff.id if assigned_to_me else None

    params = PaginationParams(page=page, size=size)
    complaints, total = await complaint_service.list_complaints(
        params=params,
        current_user=staff,
        status=c_status,
        priority=c_priority,
        category=c_category,
        hostel_id=hostel_id,
        assigned_to=assigned_to_id,
    )
    pages = (total + size - 1) // size if total > 0 else 1

    return render_template(
        request,
        "admin/complaints/index.html",
        {
            "active_nav": "complaints",
            "hostels": hostels,
            "selected_hostel_id": hostel_id,
            "status_tab": status_tab.lower(),
            "priority": priority or "",
            "category": category or "",
            "assigned_to_me": assigned_to_me,
            "complaints": complaints,
            "total": total,
            "page": page,
            "pages": pages,
            "size": size,
            "categories": list(ComplaintCategory),
            "priorities": list(ComplaintPriority),
        },
    )


@router.get("/{id}", response_class=HTMLResponse)
async def complaint_detail_screen(
    request: Request,
    id: UUID,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Complaint detail view with allowed status transitions and comments thread."""
    staff, _ = current_staff
    complaint_service = ComplaintService(db)
    complaint = await complaint_service.get_complaint(id, current_user=staff)

    allowed_transitions_map = {
        ComplaintStatus.OPEN: [ComplaintStatus.IN_PROGRESS, ComplaintStatus.CLOSED],
        ComplaintStatus.IN_PROGRESS: [ComplaintStatus.RESOLVED, ComplaintStatus.CLOSED],
        ComplaintStatus.RESOLVED: [ComplaintStatus.CLOSED, ComplaintStatus.OPEN],
        ComplaintStatus.CLOSED: [],
    }
    allowed_transitions = allowed_transitions_map.get(complaint.status, [])

    stmt = (
        select(User)
        .where(User.role.in_([UserRole.ADMIN, UserRole.WARDEN]))
        .where(User.is_active.is_(True))
        .order_by(User.full_name.asc())
    )
    res = await db.execute(stmt)
    staff_members = list(res.scalars().all())

    resolution_time_str = None
    if complaint.resolved_at and complaint.created_at:
        diff = complaint.resolved_at - complaint.created_at
        hours = int(diff.total_seconds() // 3600)
        minutes = int((diff.total_seconds() % 3600) // 60)
        resolution_time_str = f"{hours}h {minutes}m"

    return render_template(
        request,
        "admin/complaints/detail.html",
        {
            "active_nav": "complaints",
            "complaint": complaint,
            "allowed_transitions": allowed_transitions,
            "staff_members": staff_members,
            "resolution_time_str": resolution_time_str,
        },
    )


@router.post("/{id}/status")
async def update_complaint_status_submit(
    request: Request,
    id: UUID,
    status_val: str = Form(..., alias="status"),
    resolution_notes: str | None = Form(None),
    mark_room_maintenance: bool = Form(False),
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Update complaint status enforcing state machine."""
    staff, _ = current_staff
    verify_csrf(request, form_csrf=csrf_token)
    complaint_service = ComplaintService(db)
    target_status = ComplaintStatus(status_val.lower())

    payload = ComplaintStatusUpdateRequest(
        status=target_status,
        resolution_notes=resolution_notes.strip() if resolution_notes else None,
        mark_room_maintenance=mark_room_maintenance,
    )
    await complaint_service.update_status(id, payload, current_user=staff)

    if request.headers.get("HX-Request") == "true":
        response = Response(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = f"/admin/complaints/{id}"
        return response

    return RedirectResponse(
        url=f"/admin/complaints/{id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{id}/assign")
async def assign_complaint_submit(
    request: Request,
    id: UUID,
    assigned_to: UUID = Form(...),
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Assign complaint to a staff member."""
    staff, _ = current_staff
    verify_csrf(request, form_csrf=csrf_token)
    complaint_service = ComplaintService(db)
    payload = ComplaintAssignRequest(assigned_to=assigned_to)
    await complaint_service.assign_complaint(id, payload, current_user=staff)

    if request.headers.get("HX-Request") == "true":
        response = Response(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = f"/admin/complaints/{id}"
        return response

    return RedirectResponse(
        url=f"/admin/complaints/{id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{id}/comment")
async def add_complaint_comment_submit(
    request: Request,
    id: UUID,
    comment: str = Form(...),
    is_internal: bool = Form(False),
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Add a staff comment or internal note to complaint thread."""
    staff, _ = current_staff
    verify_csrf(request, form_csrf=csrf_token)
    complaint_service = ComplaintService(db)
    payload = ComplaintCommentCreate(body=comment.strip(), is_internal=is_internal)
    await complaint_service.add_comment(id, payload, current_user=staff)

    if request.headers.get("HX-Request") == "true":
        response = Response(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = f"/admin/complaints/{id}"
        return response

    return RedirectResponse(
        url=f"/admin/complaints/{id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
