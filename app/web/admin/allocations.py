"""Web routes for Staff Allocation management, bed picker modal, and actions."""

import logging
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.csrf import verify_csrf
from app.core.exceptions import AppException
from app.models.allocation import AllocationStatus
from app.models.hostel import GenderType
from app.models.room import Bed
from app.models.user import User
from app.repositories.allocation_repository import AllocationRepository
from app.repositories.hostel_repository import HostelRepository
from app.repositories.room_repository import RoomRepository
from app.repositories.student_repository import StudentRepository
from app.schemas.allocation import (
    AllocationCreate,
    AllocationTransferRequest,
    AllocationVacateRequest,
)
from app.schemas.common import PaginationParams
from app.services.allocation_service import AllocationService
from app.services.student_service import StudentService
from app.web.deps import render_template, require_staff_web

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/allocations", tags=["web-admin-allocations"])


@router.get("", response_class=HTMLResponse)
async def list_allocations(
    request: Request,
    page: int = 1,
    size: int = 15,
    hostel_id: UUID | None = None,
    room_id: UUID | None = None,
    status_filter: str | None = None,
    start_date: date | None = None,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render allocations list with filters."""
    user, warden_hostels = current_staff
    alloc_service = AllocationService(db)

    # Scoping for warden
    if user.role.value == "warden":
        if hostel_id and hostel_id not in warden_hostels:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Hostel not assigned to warden",
            )
        if not hostel_id and warden_hostels:
            hostel_id = warden_hostels[0]

    status_enum: AllocationStatus | None = None
    if status_filter and status_filter.lower() in AllocationStatus.__members__:
        status_enum = AllocationStatus[status_filter.lower()]

    params = PaginationParams(page=page, size=size)
    paged = await alloc_service.list_allocations(
        params=params,
        current_user=user,
        hostel_id=hostel_id,
        room_id=room_id,
        status=status_enum,
        start_date=start_date,
    )

    hostel_repo = HostelRepository(db)
    hostels, _ = await hostel_repo.list(PaginationParams(page=1, size=100))
    if user.role.value == "warden":
        hostels = [h for h in hostels if h.id in warden_hostels]

    query_parts = []
    if hostel_id:
        query_parts.append(f"hostel_id={hostel_id}")
    if room_id:
        query_parts.append(f"room_id={room_id}")
    if status_filter:
        query_parts.append(f"status_filter={status_filter}")
    query_string_suffix = ("&" + "&".join(query_parts)) if query_parts else ""

    return render_template(
        request,
        "admin/allocations/index.html",
        {
            "current_user": user,
            "active_nav": "allocations",
            "allocations": paged.items,
            "total_items": paged.total,
            "current_page": paged.page,
            "total_pages": paged.pages,
            "query_string_suffix": query_string_suffix,
            "hostels": hostels,
            "filters": {
                "hostel_id": str(hostel_id) if hostel_id else "",
                "room_id": str(room_id) if room_id else "",
                "status_filter": status_filter or "",
            },
        },
    )


@router.get("/modal/allocate", response_class=HTMLResponse)
async def allocate_modal(
    request: Request,
    student_id: UUID,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render bed picker allocation modal for a specific student."""
    user, warden_hostels = current_staff
    student_repo = StudentRepository(db)
    student = await student_repo.get_by_id(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    hostel_repo = HostelRepository(db)
    hostels, _ = await hostel_repo.list(PaginationParams(page=1, size=100))
    if user.role.value == "warden":
        hostels = [h for h in hostels if h.id in warden_hostels]

    # Filter hostels matching student gender or mixed
    matching_hostels = [
        h for h in hostels if h.gender_type == student.gender or h.gender_type == GenderType.MIXED
    ]

    return render_template(
        request,
        "admin/allocations/allocate_modal.html",
        {
            "current_user": user,
            "student": student,
            "hostels": matching_hostels,
            "today": date.today(),
            "error": None,
        },
    )


@router.get("/rooms-for-hostel", response_class=HTMLResponse)
async def rooms_for_hostel(
    request: Request,
    hostel_id: UUID,
    student_id: UUID,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """HTMX endpoint returning available rooms and bed tiles for chosen hostel."""
    _user, _ = current_staff
    student_repo = StudentRepository(db)
    student = await student_repo.get_by_id(student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    # Fetch rooms with available beds in this hostel
    room_repo = RoomRepository(db)
    alloc_repo = AllocationRepository(db)
    rooms_page, _ = await room_repo.search_available(
        hostel_id=hostel_id,
        params=PaginationParams(page=1, size=50),
    )

    # For each room, load its beds and active allocation status
    room_beds_data = []
    for r in rooms_page:
        room_beds = await db.execute(select(Bed).where(Bed.room_id == r.id).order_by(Bed.label))
        beds = room_beds.scalars().all()
        occupants = await alloc_repo.get_room_occupants(r.id)
        occupied_bed_ids = {o.bed_id for o in occupants}

        beds_status = [
            {"id": str(b.id), "label": b.label, "is_occupied": b.id in occupied_bed_ids}
            for b in beds
        ]
        room_beds_data.append({"room": r, "beds": beds_status})

    return render_template(
        request,
        "admin/allocations/bed_picker_partial.html",
        {
            "room_beds_data": room_beds_data,
            "student": student,
        },
    )


@router.post("/allocate", response_class=HTMLResponse)
async def allocate_submit(
    request: Request,
    student_id: UUID = Form(...),
    bed_id: UUID = Form(...),
    start_date: date = Form(...),
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Submit allocation from bed picker modal with inline error handling."""
    verify_csrf(request, form_csrf=csrf_token)
    user, _ = current_staff
    alloc_service = AllocationService(db)

    try:
        payload = AllocationCreate(
            student_id=student_id,
            bed_id=bed_id,
            start_date=start_date,
        )
        await alloc_service.allocate(payload, current_user=user)
        if request.headers.get("HX-Request") == "true":
            response = Response(status_code=status.HTTP_200_OK)
            response.headers["HX-Redirect"] = f"/admin/students/{student_id}?tab=allocation"
            return response
        return RedirectResponse(
            url=f"/admin/students/{student_id}?tab=allocation",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except AppException as e:
        logger.warning("Allocation error: %s", e.message)
        student_repo = StudentRepository(db)
        student = await student_repo.get_by_id(student_id)
        hostel_repo = HostelRepository(db)
        hostels, _ = await hostel_repo.list(PaginationParams(page=1, size=100))
        return render_template(
            request,
            "admin/allocations/allocate_modal.html",
            {
                "current_user": user,
                "student": student,
                "hostels": hostels,
                "today": start_date,
                "error": e.message,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


@router.get("/{id}/modal/transfer", response_class=HTMLResponse)
async def transfer_modal(
    request: Request,
    id: UUID,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render transfer modal for active allocation."""
    user, _ = current_staff
    alloc_service = AllocationService(db)
    alloc = await alloc_service.get_allocation(id, current_user=user)
    student_repo = StudentRepository(db)
    student = await student_repo.get_by_id(alloc.student_id)
    hostel_repo = HostelRepository(db)
    hostels, _ = await hostel_repo.list(PaginationParams(page=1, size=100))

    return render_template(
        request,
        "admin/allocations/transfer_modal.html",
        {
            "allocation": alloc,
            "student": student,
            "hostels": hostels,
            "today": date.today(),
            "error": None,
        },
    )


@router.post("/{id}/transfer", response_class=HTMLResponse)
async def transfer_submit(
    request: Request,
    id: UUID,
    target_bed_id: UUID = Form(...),
    transfer_date: date = Form(...),
    reason: str | None = Form(None),
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Submit room/bed transfer."""
    verify_csrf(request, form_csrf=csrf_token)
    user, _ = current_staff
    alloc_service = AllocationService(db)

    try:
        payload = AllocationTransferRequest(
            new_bed_id=target_bed_id,
            reason=reason,
        )
        await alloc_service.transfer(id, payload, current_user=user)
        alloc = await alloc_service.get_allocation(id, current_user=user)
        if request.headers.get("HX-Request") == "true":
            response = Response(status_code=status.HTTP_200_OK)
            response.headers["HX-Redirect"] = f"/admin/students/{alloc.student_id}?tab=allocation"
            return response
        return RedirectResponse(
            url=f"/admin/students/{alloc.student_id}?tab=allocation",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except AppException as e:
        logger.warning("Transfer error: %s", e.message)
        alloc = await alloc_service.get_allocation(id, current_user=user)
        student_repo = StudentRepository(db)
        student = await student_repo.get_by_id(alloc.student_id)
        hostel_repo = HostelRepository(db)
        hostels, _ = await hostel_repo.list(PaginationParams(page=1, size=100))
        return render_template(
            request,
            "admin/allocations/transfer_modal.html",
            {
                "allocation": alloc,
                "student": student,
                "hostels": hostels,
                "today": transfer_date,
                "error": e.message,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


@router.get("/{id}/modal/vacate", response_class=HTMLResponse)
async def vacate_modal(
    request: Request,
    id: UUID,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render vacate confirm modal."""
    user, _ = current_staff
    alloc_service = AllocationService(db)
    alloc = await alloc_service.get_allocation(id, current_user=user)
    return render_template(
        request,
        "admin/allocations/vacate_modal.html",
        {"allocation": alloc, "today": date.today(), "error": None},
    )


@router.post("/{id}/vacate")
async def vacate_submit(
    request: Request,
    id: UUID,
    vacate_date: date = Form(...),
    reason: str | None = Form(None),
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Vacate an active allocation."""
    verify_csrf(request, form_csrf=csrf_token)
    user, _ = current_staff
    alloc_service = AllocationService(db)
    payload = AllocationVacateRequest(end_date=vacate_date, reason=reason)
    await alloc_service.vacate(id, payload, current_user=user)
    alloc = await alloc_service.get_allocation(id, current_user=user)

    if request.headers.get("HX-Request") == "true":
        response = Response(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = f"/admin/students/{alloc.student_id}?tab=allocation"
        return response
    return RedirectResponse(
        url=f"/admin/students/{alloc.student_id}?tab=allocation",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/{id}/modal/cancel", response_class=HTMLResponse)
async def cancel_modal(
    request: Request,
    id: UUID,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render cancel confirm modal."""
    user, _ = current_staff
    alloc_service = AllocationService(db)
    alloc = await alloc_service.get_allocation(id, current_user=user)
    return render_template(
        request,
        "admin/allocations/cancel_modal.html",
        {"allocation": alloc},
    )


@router.post("/{id}/cancel")
async def cancel_submit(
    request: Request,
    id: UUID,
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Cancel allocation record."""
    verify_csrf(request, form_csrf=csrf_token)
    user, _ = current_staff
    alloc_service = AllocationService(db)
    alloc = await alloc_service.get_allocation(id, current_user=user)
    await alloc_service.cancel(id, current_user=user)

    if request.headers.get("HX-Request") == "true":
        response = Response(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = f"/admin/students/{alloc.student_id}?tab=allocation"
        return response
    return RedirectResponse(
        url=f"/admin/students/{alloc.student_id}?tab=allocation",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/assign-student-search", response_class=HTMLResponse)
async def assign_student_search(
    request: Request,
    q: str | None = None,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Live search HTMX endpoint returning unallocated students."""
    user, _ = current_staff
    if not q or len(q.strip()) < 1:
        msg = "<div class='p-3 text-xs text-zinc-400'>Type a student name or number...</div>"
        return HTMLResponse(msg)

    student_service = StudentService(db)
    paged = await student_service.list_students(
        params=PaginationParams(page=1, size=10),
        current_user=user,
        has_allocation=False,
        search=q.strip(),
    )

    return render_template(
        request,
        "admin/allocations/assign_student_results.html",
        {"students": paged.items},
    )
