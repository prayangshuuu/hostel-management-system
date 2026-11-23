"""Web routes for Room Detail and bed assignment from room."""

import logging
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.csrf import verify_csrf
from app.core.exceptions import AppException
from app.models.user import User
from app.repositories.allocation_repository import AllocationRepository
from app.repositories.hostel_repository import BlockRepository, HostelRepository
from app.schemas.allocation import AllocationCreate
from app.services.allocation_service import AllocationService
from app.services.room_service import RoomService
from app.web.deps import render_template, require_staff_web

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/rooms", tags=["web-admin-rooms"])


@router.get("/{id}", response_class=HTMLResponse)
async def room_detail(
    request: Request,
    id: UUID,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render room detail page with beds and occupant details."""
    user, _warden_hostels = current_staff
    room_service = RoomService(db)
    room = await room_service.get_room(id, current_user=user)

    block_repo = BlockRepository(db)
    block = await block_repo.get_by_id(room.block_id)

    hostel_repo = HostelRepository(db)
    hostel = await hostel_repo.get_by_id(block.hostel_id) if block else None

    # Load beds with occupants
    alloc_repo = AllocationRepository(db)
    occupants = await alloc_repo.get_room_occupants(room.id)
    occupant_by_bed = {o.bed_id: o for o in occupants}

    beds_data = []
    has_free_beds = False
    for b in room.beds:
        occ = occupant_by_bed.get(b.id)
        if not occ:
            has_free_beds = True
        beds_data.append(
            {
                "bed": b,
                "allocation": occ,
            }
        )

    return render_template(
        request,
        "admin/rooms/detail.html",
        {
            "current_user": user,
            "active_nav": "allocations",
            "room": room,
            "block": block,
            "hostel": hostel,
            "beds_data": beds_data,
            "has_free_beds": has_free_beds,
        },
    )


@router.get("/{id}/modal/assign", response_class=HTMLResponse)
async def assign_student_modal(
    request: Request,
    id: UUID,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render assign student modal with live search autocomplete."""
    user, _ = current_staff
    room_service = RoomService(db)
    room = await room_service.get_room(id, current_user=user)

    # Free beds in this room
    alloc_repo = AllocationRepository(db)
    occupants = await alloc_repo.get_room_occupants(room.id)
    occupied_bed_ids = {o.bed_id for o in occupants}
    free_beds = [b for b in room.beds if b.id not in occupied_bed_ids]

    return render_template(
        request,
        "admin/rooms/assign_modal.html",
        {
            "room": room,
            "free_beds": free_beds,
            "today": date.today(),
            "error": None,
        },
    )


@router.post("/{id}/assign", response_class=HTMLResponse)
async def assign_student_submit(
    request: Request,
    id: UUID,
    student_id: UUID = Form(...),
    bed_id: UUID = Form(...),
    start_date: date = Form(...),
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Assign student to bed from room detail page."""
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
            response.headers["HX-Redirect"] = f"/admin/rooms/{id}"
            return response
        return RedirectResponse(url=f"/admin/rooms/{id}", status_code=status.HTTP_303_SEE_OTHER)
    except AppException as e:
        logger.warning("Error assigning student from room: %s", e.message)
        room_service = RoomService(db)
        room = await room_service.get_room(id, current_user=user)
        alloc_repo = AllocationRepository(db)
        occupants = await alloc_repo.get_room_occupants(room.id)
        occupied_bed_ids = {o.bed_id for o in occupants}
        free_beds = [b for b in room.beds if b.id not in occupied_bed_ids]
        return render_template(
            request,
            "admin/rooms/assign_modal.html",
            {
                "room": room,
                "free_beds": free_beds,
                "today": start_date,
                "error": e.message,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
