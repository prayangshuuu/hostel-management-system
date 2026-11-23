"""Admin portal visitor registration, checkout, and logs."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.csrf import verify_csrf
from app.core.exceptions import AppException
from app.db.session import get_db
from app.models.allocation import Allocation, AllocationStatus
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.repositories.hostel_repository import HostelRepository
from app.schemas.common import PaginationParams
from app.schemas.operations import VisitorCreate
from app.services.operations_service import OperationsService
from app.web.deps import render_template, require_staff_web

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/visitors", tags=["admin-visitors"])


@router.get("", response_class=HTMLResponse)
async def list_visitors_screen(
    request: Request,
    hostel_id: UUID | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=100),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Visitors dashboard with Active Visitors queue and history table."""
    staff, assigned_hostels = current_staff
    ops_service = OperationsService(db)
    hostel_repo = HostelRepository(db)

    all_hostels, _ = await hostel_repo.list(params=PaginationParams(page=1, size=100))
    if staff.role == UserRole.WARDEN:
        hostels = [h for h in all_hostels if h.id in assigned_hostels]
    else:
        hostels = all_hostels

    # Fetch currently active visitors (active=True)
    active_visitors, _ = await ops_service.list_visitors(
        params=PaginationParams(page=1, size=50),
        current_user=staff,
        active=True,
        hostel_id=hostel_id,
    )

    # Historical logs
    params = PaginationParams(page=page, size=size)
    visitors, total = await ops_service.list_visitors(
        params=params,
        current_user=staff,
        hostel_id=hostel_id,
    )
    pages = (total + size - 1) // size if total > 0 else 1

    return render_template(
        request,
        "admin/visitors/index.html",
        {
            "active_nav": "visitors",
            "hostels": hostels,
            "selected_hostel_id": hostel_id,
            "active_visitors": active_visitors,
            "visitors": visitors,
            "total": total,
            "page": page,
            "pages": pages,
            "size": size,
        },
    )


@router.get("/modal/register", response_class=HTMLResponse)
async def register_visitor_modal(
    request: Request,
    student_id: UUID | None = Query(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render register visitor modal with student selector."""
    # List active students
    stmt = (
        select(StudentProfile)
        .options(selectinload(StudentProfile.user))
        .join(StudentProfile.user)
        .join(
            Allocation,
            (Allocation.student_id == StudentProfile.id)
            & (Allocation.status == AllocationStatus.ACTIVE),
        )
        .where(StudentProfile.is_deleted.is_(False))
        .limit(100)
    )
    res = await db.execute(stmt)
    students = list(res.scalars().all())

    return render_template(
        request,
        "admin/visitors/register_modal.html",
        {
            "students": students,
            "selected_student_id": student_id,
            "error": None,
        },
    )


@router.post("/register")
async def register_visitor_submit(
    request: Request,
    student_id: UUID = Form(...),
    name: str = Form(...),
    phone: str = Form(...),
    relation: str = Form(...),
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Process visitor check-in with visiting hours validation."""
    staff, _ = current_staff
    verify_csrf(request, form_csrf=csrf_token)
    ops_service = OperationsService(db)

    try:
        payload = VisitorCreate(
            student_id=student_id,
            name=name.strip(),
            phone=phone.strip(),
            relation=relation.strip(),
        )
        await ops_service.check_in_visitor(payload, current_user=staff)

        if request.headers.get("HX-Request") == "true":
            response = Response(status_code=status.HTTP_200_OK)
            response.headers["HX-Redirect"] = "/admin/visitors"
            return response

        return RedirectResponse(
            url="/admin/visitors",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except AppException as e:
        logger.warning("Visitor registration error: %s", e.message)
        stmt = (
            select(StudentProfile)
            .options(selectinload(StudentProfile.user))
            .join(StudentProfile.user)
            .where(StudentProfile.is_deleted.is_(False))
            .limit(100)
        )
        res = await db.execute(stmt)
        students = list(res.scalars().all())
        return render_template(
            request,
            "admin/visitors/register_modal.html",
            {
                "students": students,
                "selected_student_id": student_id,
                "error": e.message,
                "name": name,
                "phone": phone,
                "relation": relation,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


@router.post("/{id}/checkout")
async def checkout_visitor_submit(
    request: Request,
    id: UUID,
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Record visitor departure/checkout."""
    staff, _ = current_staff
    verify_csrf(request, form_csrf=csrf_token)
    ops_service = OperationsService(db)
    await ops_service.check_out_visitor(id, current_user=staff)

    if request.headers.get("HX-Request") == "true":
        response = Response(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = "/admin/visitors"
        return response

    return RedirectResponse(
        url="/admin/visitors",
        status_code=status.HTTP_303_SEE_OTHER,
    )
