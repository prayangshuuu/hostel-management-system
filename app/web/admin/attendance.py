"""Admin portal attendance routes: mobile-first gate screen, present now, and attendance logs."""

from __future__ import annotations

import logging
from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.csrf import verify_csrf
from app.core.exceptions import AppException
from app.db.session import get_db
from app.models.operations import AttendanceType
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.repositories.allocation_repository import AllocationRepository
from app.repositories.hostel_repository import HostelRepository
from app.schemas.common import PaginationParams
from app.schemas.operations import AttendanceActionRequest
from app.services.operations_service import OperationsService
from app.web.deps import render_template, require_staff_web

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/attendance", tags=["admin-attendance"])


@router.get("/gate", response_class=HTMLResponse)
async def gate_screen(
    request: Request,
    q: str | None = Query(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Mobile-first gate screen for rapid student check-in/out."""
    staff, _ = current_staff
    ops_service = OperationsService(db)
    student = None
    latest_log = None
    allocation = None

    if q and q.strip():
        search_term = q.strip().lower()
        stmt = (
            select(StudentProfile)
            .options(selectinload(StudentProfile.user))
            .join(StudentProfile.user)
            .where(
                (StudentProfile.student_no.ilike(f"%{search_term}%"))
                | (User.full_name.ilike(f"%{search_term}%"))
            )
            .where(StudentProfile.is_deleted.is_(False))
            .limit(1)
        )
        res = await db.execute(stmt)
        student = res.scalar_one_or_none()
        if student:
            latest_log = await ops_service.attendance_repo.get_latest_for_student(student.id)
            alloc_repo = AllocationRepository(db)
            allocation = await alloc_repo.get_active_by_student_id(student.id)

    # Last 10 actions
    recent_logs, _ = await ops_service.list_attendance(
        params=PaginationParams(page=1, size=10),
        current_user=staff,
    )

    return render_template(
        request,
        "admin/attendance/gate.html",
        {
            "active_nav": "gate",
            "q": q or "",
            "student": student,
            "latest_log": latest_log,
            "allocation": allocation,
            "recent_logs": recent_logs,
        },
    )


@router.get("/gate/search", response_class=HTMLResponse)
async def gate_search_partial(
    request: Request,
    q: str | None = Query(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """HTMX partial returning searched student card with check-in/out button."""
    ops_service = OperationsService(db)
    student = None
    latest_log = None
    allocation = None

    if q and q.strip():
        search_term = q.strip().lower()
        stmt = (
            select(StudentProfile)
            .options(selectinload(StudentProfile.user))
            .join(StudentProfile.user)
            .where(
                (StudentProfile.student_no.ilike(f"%{search_term}%"))
                | (User.full_name.ilike(f"%{search_term}%"))
            )
            .where(StudentProfile.is_deleted.is_(False))
            .limit(1)
        )
        res = await db.execute(stmt)
        student = res.scalar_one_or_none()
        if student:
            latest_log = await ops_service.attendance_repo.get_latest_for_student(student.id)
            alloc_repo = AllocationRepository(db)
            allocation = await alloc_repo.get_active_by_student_id(student.id)

    return render_template(
        request,
        "admin/attendance/gate_search_result.html",
        {
            "q": q or "",
            "student": student,
            "latest_log": latest_log,
            "allocation": allocation,
            "error": None,
        },
    )


@router.post("/gate/action")
async def gate_action_submit(
    request: Request,
    student_id: UUID = Form(...),
    action: str = Form(...),
    remarks: str | None = Form(None),
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Process gate check-in or check-out with inline error trapping."""
    staff, _ = current_staff
    verify_csrf(request, form_csrf=csrf_token)
    ops_service = OperationsService(db)
    payload = AttendanceActionRequest(student_id=student_id, remarks=remarks)

    try:
        if action == "check_in":
            await ops_service.check_in(payload, current_user=staff)
        elif action == "check_out":
            await ops_service.check_out(payload, current_user=staff)
        else:
            raise AppException("Invalid attendance action", code="INVALID_ACTION", status_code=400)

        if request.headers.get("HX-Request") == "true":
            student = await ops_service.student_repo.get_by_id(student_id)
            latest_log = await ops_service.attendance_repo.get_latest_for_student(student_id)
            alloc_repo = AllocationRepository(db)
            allocation = await alloc_repo.get_active_by_student_id(student_id)
            response = render_template(
                request,
                "admin/attendance/gate_search_result.html",
                {
                    "student": student,
                    "latest_log": latest_log,
                    "allocation": allocation,
                    "success": f"Successfully recorded {action.replace('_', ' ').title()}",
                },
            )
            response.headers["HX-Trigger"] = "gateActionSuccess"
            return response

        return RedirectResponse(
            url="/admin/attendance/gate",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except AppException as e:
        logger.warning("Gate attendance error: %s", e.message)
        student = await ops_service.student_repo.get_by_id(student_id)
        latest_log = await ops_service.attendance_repo.get_latest_for_student(student_id)
        alloc_repo = AllocationRepository(db)
        allocation = await alloc_repo.get_active_by_student_id(student_id)
        return render_template(
            request,
            "admin/attendance/gate_search_result.html",
            {
                "student": student,
                "latest_log": latest_log,
                "allocation": allocation,
                "error": e.message,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


@router.get("/present", response_class=HTMLResponse)
async def present_now_screen(
    request: Request,
    hostel_id: UUID | None = Query(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """View students currently present in hostel based on latest attendance log."""
    staff, assigned_hostels = current_staff
    ops_service = OperationsService(db)
    hostel_repo = HostelRepository(db)

    all_hostels, _ = await hostel_repo.list(params=PaginationParams(page=1, size=100))
    if staff.role == UserRole.WARDEN:
        hostels = [h for h in all_hostels if h.id in assigned_hostels]
    else:
        hostels = all_hostels

    selected_hostel_id = hostel_id or (hostels[0].id if hostels else None)
    present_students = await ops_service.get_present_students(
        current_user=staff,
        hostel_id=selected_hostel_id,
    )

    return render_template(
        request,
        "admin/attendance/present.html",
        {
            "active_nav": "present",
            "hostels": hostels,
            "selected_hostel_id": selected_hostel_id,
            "present_students": present_students,
            "total_present": len(present_students),
        },
    )


@router.get("", response_class=HTMLResponse)
async def attendance_logs_screen(
    request: Request,
    hostel_id: UUID | None = Query(None),
    type: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=100),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Historical attendance logs with filters and pagination."""
    staff, assigned_hostels = current_staff
    ops_service = OperationsService(db)
    hostel_repo = HostelRepository(db)

    all_hostels, _ = await hostel_repo.list(params=PaginationParams(page=1, size=100))
    if staff.role == UserRole.WARDEN:
        hostels = [h for h in all_hostels if h.id in assigned_hostels]
    else:
        hostels = all_hostels

    att_type = None
    if type:
        try:
            att_type = AttendanceType(type.lower())
        except ValueError:
            att_type = None

    dt_from = datetime.combine(date_from, datetime.min.time()) if date_from else None
    dt_to = datetime.combine(date_to, datetime.max.time()) if date_to else None

    params = PaginationParams(page=page, size=size)
    logs, total = await ops_service.list_attendance(
        params=params,
        current_user=staff,
        hostel_id=hostel_id,
        date_from=dt_from,
        date_to=dt_to,
        type=att_type,
    )
    pages = (total + size - 1) // size if total > 0 else 1

    return render_template(
        request,
        "admin/attendance/index.html",
        {
            "active_nav": "attendance",
            "hostels": hostels,
            "selected_hostel_id": hostel_id,
            "selected_type": type,
            "date_from": date_from.isoformat() if date_from else "",
            "date_to": date_to.isoformat() if date_to else "",
            "logs": logs,
            "total": total,
            "page": page,
            "pages": pages,
            "size": size,
        },
    )
