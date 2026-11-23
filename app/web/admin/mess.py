"""Admin portal mess menu weekly editor and kitchen headcount routes."""

from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csrf import verify_csrf
from app.db.session import get_db
from app.models.mess import MealType
from app.models.user import User, UserRole
from app.repositories.hostel_repository import HostelRepository
from app.schemas.common import PaginationParams
from app.schemas.mess import MessMenuBulkUpdateRequest, MessMenuItemCreate
from app.services.mess_service import MessService
from app.web.deps import render_template, require_staff_web

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/mess", tags=["admin-mess"])

DAYS_OF_WEEK = [
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
    (6, "Sunday"),
]
MEAL_TYPES = [MealType.BREAKFAST, MealType.LUNCH, MealType.DINNER]


@router.get("", response_class=HTMLResponse)
async def mess_menu_screen(
    request: Request,
    hostel_id: UUID | None = Query(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Weekly mess menu editor (7x3 grid on desktop, accordion on mobile)."""
    staff, assigned_hostels = current_staff
    mess_service = MessService(db)
    hostel_repo = HostelRepository(db)

    all_hostels, _ = await hostel_repo.list(params=PaginationParams(page=1, size=100))
    if staff.role == UserRole.WARDEN:
        hostels = [h for h in all_hostels if h.id in assigned_hostels]
    else:
        hostels = all_hostels

    selected_hostel_id = hostel_id or (hostels[0].id if hostels else None)
    menu_matrix: dict[int, dict[str, str]] = {
        d: {m.value: "" for m in MEAL_TYPES} for d, _ in DAYS_OF_WEEK
    }

    if selected_hostel_id:
        weekly_menu = await mess_service.get_hostel_menu(selected_hostel_id, current_user=staff)
        for item in weekly_menu.items:
            day = item.day_of_week
            m_type = (
                item.meal_type.value if hasattr(item.meal_type, "value") else str(item.meal_type)
            )
            if day in menu_matrix and m_type in menu_matrix[day]:
                menu_matrix[day][m_type] = ", ".join(item.items)

    return render_template(
        request,
        "admin/mess/index.html",
        {
            "active_nav": "mess",
            "hostels": hostels,
            "selected_hostel_id": selected_hostel_id,
            "days": DAYS_OF_WEEK,
            "meal_types": MEAL_TYPES,
            "menu_matrix": menu_matrix,
        },
    )


@router.post("/update")
async def update_mess_menu_submit(
    request: Request,
    hostel_id: UUID = Form(...),
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Save full weekly menu in one single batch request."""
    staff, _ = current_staff
    verify_csrf(request, form_csrf=csrf_token)
    form_data = await request.form()
    mess_service = MessService(db)

    entries: list[MessMenuItemCreate] = []
    for day, _ in DAYS_OF_WEEK:
        for meal in MEAL_TYPES:
            field_name = f"items_{day}_{meal.value}"
            raw_val = form_data.get(field_name, "")
            if isinstance(raw_val, str) and raw_val.strip():
                raw_items = [
                    item.strip()
                    for line in raw_val.splitlines()
                    for item in line.split(",")
                    if item.strip()
                ]
                if raw_items:
                    entries.append(
                        MessMenuItemCreate(
                            day_of_week=day,
                            meal_type=meal,
                            items=raw_items,
                        )
                    )

    payload = MessMenuBulkUpdateRequest(entries=entries)
    await mess_service.update_hostel_menu(hostel_id, payload, current_user=staff)

    if request.headers.get("HX-Request") == "true":
        response = Response(status_code=status.HTTP_200_OK)
        response.headers["HX-Redirect"] = f"/admin/mess?hostel_id={hostel_id}"
        return response

    return RedirectResponse(
        url=f"/admin/mess?hostel_id={hostel_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/headcount", response_class=HTMLResponse)
async def mess_headcount_screen(
    request: Request,
    hostel_id: UUID | None = Query(None),
    target_date: date | None = Query(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Projected meal headcount cards (allocated, opted out, on leave, expected)."""
    staff, assigned_hostels = current_staff
    mess_service = MessService(db)
    hostel_repo = HostelRepository(db)

    all_hostels, _ = await hostel_repo.list(params=PaginationParams(page=1, size=100))
    if staff.role == UserRole.WARDEN:
        hostels = [h for h in all_hostels if h.id in assigned_hostels]
    else:
        hostels = all_hostels

    selected_hostel_id = hostel_id or (hostels[0].id if hostels else None)
    selected_date = target_date or date.today()

    headcount_data = None
    if selected_hostel_id:
        headcount_data = await mess_service.get_headcount(
            hostel_id=selected_hostel_id,
            target_date=selected_date,
            current_user=staff,
        )

    return render_template(
        request,
        "admin/mess/headcount.html",
        {
            "active_nav": "headcount",
            "hostels": hostels,
            "selected_hostel_id": selected_hostel_id,
            "target_date": selected_date.isoformat(),
            "headcount_data": headcount_data,
        },
    )
