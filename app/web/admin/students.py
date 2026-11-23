"""Web routes for Staff/Admin Student Management."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.csrf import verify_csrf
from app.core.exceptions import AppException
from app.models.hostel import GenderType
from app.models.user import User
from app.repositories.allocation_repository import AllocationRepository
from app.repositories.billing_repository import InvoiceRepository
from app.repositories.complaint_repository import ComplaintRepository
from app.repositories.operations_repository import AttendanceRepository, LeaveRepository
from app.schemas.common import PaginationParams
from app.schemas.student import StudentCreate, StudentUpdate
from app.services.student_service import StudentService
from app.web.deps import render_template, require_staff_web

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/students", tags=["web-admin-students"])


@router.get("", response_class=HTMLResponse)
async def list_students(
    request: Request,
    page: int = 1,
    size: int = 15,
    department: str | None = None,
    year: int | None = None,
    gender: str | None = None,
    allocated: str | None = None,
    search: str | None = None,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render students list with filters and search."""
    user, _ = current_staff
    student_service = StudentService(db)

    has_alloc: bool | None = None
    if allocated == "yes":
        has_alloc = True
    elif allocated == "no":
        has_alloc = False

    gender_enum: GenderType | None = None
    if gender and gender.upper() in GenderType.__members__:
        gender_enum = GenderType[gender.upper()]

    params = PaginationParams(page=page, size=size)
    paged = await student_service.list_students(
        params=params,
        current_user=user,
        department=department,
        year=year,
        gender=gender_enum,
        has_allocation=has_alloc,
        search=search,
    )

    query_parts = []
    if department:
        query_parts.append(f"department={department}")
    if year:
        query_parts.append(f"year={year}")
    if gender:
        query_parts.append(f"gender={gender}")
    if allocated:
        query_parts.append(f"allocated={allocated}")
    if search:
        query_parts.append(f"search={search}")
    query_string_suffix = ("&" + "&".join(query_parts)) if query_parts else ""

    return render_template(
        request,
        "admin/students/index.html",
        {
            "current_user": user,
            "active_nav": "students",
            "students": paged.items,
            "total_items": paged.total,
            "current_page": paged.page,
            "total_pages": paged.pages,
            "query_string_suffix": query_string_suffix,
            "filters": {
                "department": department or "",
                "year": year or "",
                "gender": gender or "",
                "allocated": allocated or "",
                "search": search or "",
            },
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_student_modal(
    request: Request,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
) -> Response:
    """Render create student modal fragment."""
    user, _ = current_staff
    return render_template(
        request,
        "admin/students/create_modal.html",
        {"current_user": user, "error": None},
    )


@router.post("", response_class=HTMLResponse)
async def create_student(
    request: Request,
    email: str = Form(...),
    full_name: str = Form(...),
    student_no: str = Form(...),
    gender: str = Form(...),
    department: str = Form(...),
    year: int = Form(...),
    guardian_name: str = Form(...),
    guardian_phone: str = Form(...),
    emergency_contact: str = Form(...),
    phone: str | None = Form(None),
    password: str | None = Form(None),
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Create student account + profile."""
    verify_csrf(request, form_csrf=csrf_token)
    user, _ = current_staff
    student_service = StudentService(db)

    try:
        gender_enum = GenderType[gender.upper()]
        payload = StudentCreate(
            email=email.strip(),
            full_name=full_name.strip(),
            student_no=student_no.strip(),
            gender=gender_enum,
            department=department.strip(),
            year=year,
            guardian_name=guardian_name.strip(),
            guardian_phone=guardian_phone.strip(),
            emergency_contact=emergency_contact.strip(),
            phone=phone.strip() if phone else None,
            password=password.strip() if password else None,
        )
        created = await student_service.create_student(payload, current_user=user)
        if request.headers.get("HX-Request") == "true":
            response = Response(status_code=status.HTTP_200_OK)
            response.headers["HX-Redirect"] = f"/admin/students/{created.id}"
            return response
        return RedirectResponse(
            url=f"/admin/students/{created.id}", status_code=status.HTTP_303_SEE_OTHER
        )
    except AppException as e:
        logger.warning("Error creating student: %s", e.message)
        return render_template(
            request,
            "admin/students/create_modal.html",
            {
                "current_user": user,
                "error": e.message,
                "form_data": {
                    "email": email,
                    "full_name": full_name,
                    "student_no": student_no,
                    "gender": gender,
                    "department": department,
                    "year": year,
                    "guardian_name": guardian_name,
                    "guardian_phone": guardian_phone,
                    "emergency_contact": emergency_contact,
                    "phone": phone or "",
                },
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    except Exception as e:
        logger.exception("Validation exception creating student: %s", e)
        return render_template(
            request,
            "admin/students/create_modal.html",
            {"current_user": user, "error": str(e)},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


@router.get("/{id}", response_class=HTMLResponse)
async def student_detail(
    request: Request,
    id: UUID,
    tab: str = "profile",
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render student detail page with tabs."""
    user, _ = current_staff
    student_service = StudentService(db)
    student = await student_service.get_student(id, current_user=user)

    # Load associated entities for tabs
    tab_params = PaginationParams(page=1, size=20)
    alloc_repo = AllocationRepository(db)
    active_allocation = await alloc_repo.get_active_by_student_id(student.id)
    allocations, _ = await alloc_repo.list(tab_params, student_id=student.id)

    invoice_repo = InvoiceRepository(db)
    invoices, _ = await invoice_repo.list(tab_params, student_id=student.id)

    att_repo = AttendanceRepository(db)
    attendance_logs, _ = await att_repo.list(tab_params, student_id=student.id)

    leave_repo = LeaveRepository(db)
    leaves, _ = await leave_repo.list(tab_params, student_id=student.id)

    comp_repo = ComplaintRepository(db)
    complaints, _ = await comp_repo.list(tab_params, student_id=student.id)

    return render_template(
        request,
        "admin/students/detail.html",
        {
            "current_user": user,
            "active_nav": "students",
            "active_tab": tab,
            "student": student,
            "active_allocation": active_allocation,
            "allocations": allocations,
            "invoices": invoices,
            "attendance_logs": attendance_logs,
            "leaves": leaves,
            "complaints": complaints,
        },
    )


@router.get("/{id}/edit", response_class=HTMLResponse)
async def edit_student_modal(
    request: Request,
    id: UUID,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render edit student modal."""
    user, _ = current_staff
    student_service = StudentService(db)
    student = await student_service.get_student(id, current_user=user)
    return render_template(
        request,
        "admin/students/edit_modal.html",
        {"current_user": user, "student": student, "error": None},
    )


@router.post("/{id}/edit", response_class=HTMLResponse)
async def edit_student_submit(
    request: Request,
    id: UUID,
    full_name: str | None = Form(None),
    department: str | None = Form(None),
    year: int | None = Form(None),
    guardian_name: str | None = Form(None),
    guardian_phone: str | None = Form(None),
    emergency_contact: str | None = Form(None),
    phone: str | None = Form(None),
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Submit updated student profile fields."""
    verify_csrf(request, form_csrf=csrf_token)
    user, _ = current_staff
    student_service = StudentService(db)

    try:
        update_data = StudentUpdate(
            full_name=full_name.strip() if full_name else None,
            department=department.strip() if department else None,
            year=year,
            guardian_name=guardian_name.strip() if guardian_name else None,
            guardian_phone=guardian_phone.strip() if guardian_phone else None,
            emergency_contact=emergency_contact.strip() if emergency_contact else None,
            phone=phone.strip() if phone else None,
        )
        await student_service.update_student(id, update_data, current_user=user)
        if request.headers.get("HX-Request") == "true":
            response = Response(status_code=status.HTTP_200_OK)
            response.headers["HX-Redirect"] = f"/admin/students/{id}"
            return response
        return RedirectResponse(
            url=f"/admin/students/{id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as e:
        logger.warning("Error updating student: %s", e)
        student = await student_service.get_student(id, current_user=user)
        return render_template(
            request,
            "admin/students/edit_modal.html",
            {"current_user": user, "student": student, "error": str(e)},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


@router.post("/{id}/deactivate")
async def deactivate_student(
    request: Request,
    id: UUID,
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Soft delete student profile and deactivate account."""
    verify_csrf(request, form_csrf=csrf_token)
    user, _ = current_staff
    student_service = StudentService(db)
    await student_service.delete_student(id, current_user=user)

    if request.headers.get("HX-Request") == "true":
        response = Response(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = "/admin/students"
        return response
    return RedirectResponse(url="/admin/students", status_code=status.HTTP_303_SEE_OTHER)
