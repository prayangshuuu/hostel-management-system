"""Admin portal analytical reports with CSS bar charts and CSV export endpoints."""

from __future__ import annotations

import csv
import io
import logging
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User, UserRole
from app.repositories.hostel_repository import HostelRepository
from app.schemas.common import PaginationParams
from app.services.report_service import ReportService
from app.web.deps import render_template, require_staff_web

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/reports", tags=["admin-reports"])


@router.get("", response_class=HTMLResponse)
async def reports_hub_screen(
    request: Request,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
) -> Response:
    """Analytical reports directory hub."""
    return render_template(
        request,
        "admin/reports/index.html",
        {"active_nav": "reports"},
    )


# =============================================================================
# 1. Occupancy Report
# =============================================================================


@router.get("/occupancy", response_class=HTMLResponse)
async def occupancy_report_screen(
    request: Request,
    hostel_id: UUID | None = Query(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Hostel and block occupancy rate analytics with CSS fill bars."""
    staff, assigned_hostels = current_staff
    report_service = ReportService(db)
    hostel_repo = HostelRepository(db)

    all_hostels, _ = await hostel_repo.list(params=PaginationParams(page=1, size=100))
    if staff.role == UserRole.WARDEN:
        hostels = [h for h in all_hostels if h.id in assigned_hostels]
    else:
        hostels = all_hostels

    rows = await report_service.get_occupancy_report(staff, hostel_id=hostel_id)
    total_beds = sum(r.total_beds for r in rows)
    occupied_beds = sum(r.occupied_beds for r in rows)
    overall_rate = (occupied_beds / total_beds * 100) if total_beds > 0 else 0.0

    return render_template(
        request,
        "admin/reports/occupancy.html",
        {
            "active_nav": "reports",
            "hostels": hostels,
            "selected_hostel_id": hostel_id,
            "rows": rows,
            "total_beds": total_beds,
            "occupied_beds": occupied_beds,
            "overall_rate": round(overall_rate, 1),
        },
    )


@router.get("/occupancy/csv")
async def occupancy_report_csv(
    hostel_id: UUID | None = Query(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export occupancy report to CSV."""
    staff, _ = current_staff
    report_service = ReportService(db)
    rows = await report_service.get_occupancy_report(staff, hostel_id=hostel_id)
    csv_content = ReportService.generate_occupancy_csv(rows)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="occupancy_report.csv"'},
    )


# =============================================================================
# 2. Revenue Report
# =============================================================================


@router.get("/revenue", response_class=HTMLResponse)
async def revenue_report_screen(
    request: Request,
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    group_by: str = Query("month"),
    hostel_id: UUID | None = Query(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Revenue aggregation report with CSS collection bars."""
    staff, assigned_hostels = current_staff
    report_service = ReportService(db)
    hostel_repo = HostelRepository(db)

    all_hostels, _ = await hostel_repo.list(params=PaginationParams(page=1, size=100))
    if staff.role == UserRole.WARDEN:
        hostels = [h for h in all_hostels if h.id in assigned_hostels]
    else:
        hostels = all_hostels

    rows = await report_service.get_revenue_report(
        staff,
        from_date=from_date,
        to_date=to_date,
        group_by=group_by,
        hostel_id=hostel_id,
    )
    total_revenue = sum(r.total_revenue for r in rows)
    total_txns = sum(r.transaction_count for r in rows)

    return render_template(
        request,
        "admin/reports/revenue.html",
        {
            "active_nav": "reports",
            "hostels": hostels,
            "selected_hostel_id": hostel_id,
            "from_date": from_date.isoformat() if from_date else "",
            "to_date": to_date.isoformat() if to_date else "",
            "group_by": group_by,
            "rows": rows,
            "total_revenue": total_revenue,
            "total_txns": total_txns,
        },
    )


@router.get("/revenue/csv")
async def revenue_report_csv(
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    group_by: str = Query("month"),
    hostel_id: UUID | None = Query(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export revenue report to CSV."""
    staff, _ = current_staff
    report_service = ReportService(db)
    rows = await report_service.get_revenue_report(
        staff,
        from_date=from_date,
        to_date=to_date,
        group_by=group_by,
        hostel_id=hostel_id,
    )
    csv_content = ReportService.generate_revenue_csv(rows)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="revenue_report.csv"'},
    )


# =============================================================================
# 3. Defaulters Report
# =============================================================================


@router.get("/defaulters", response_class=HTMLResponse)
async def defaulters_report_screen(
    request: Request,
    hostel_id: UUID | None = Query(None),
    current_date: date | None = Query(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Overdue invoice defaulters list and recovery tracker."""
    staff, assigned_hostels = current_staff
    report_service = ReportService(db)
    hostel_repo = HostelRepository(db)

    all_hostels, _ = await hostel_repo.list(params=PaginationParams(page=1, size=100))
    if staff.role == UserRole.WARDEN:
        hostels = [h for h in all_hostels if h.id in assigned_hostels]
    else:
        hostels = all_hostels

    rows = await report_service.get_defaulters_report(
        staff,
        hostel_id=hostel_id,
        current_date=current_date or date.today(),
    )
    total_outstanding = sum(r.balance for r in rows)

    return render_template(
        request,
        "admin/reports/defaulters.html",
        {
            "active_nav": "reports",
            "hostels": hostels,
            "selected_hostel_id": hostel_id,
            "rows": rows,
            "total_defaulters": len(rows),
            "total_outstanding": total_outstanding,
        },
    )


@router.get("/defaulters/csv")
async def defaulters_report_csv(
    hostel_id: UUID | None = Query(None),
    current_date: date | None = Query(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export defaulters report to CSV."""
    staff, _ = current_staff
    report_service = ReportService(db)
    rows = await report_service.get_defaulters_report(
        staff,
        hostel_id=hostel_id,
        current_date=current_date or date.today(),
    )
    csv_content = ReportService.generate_defaulters_csv(rows)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="defaulters_report.csv"'},
    )


# =============================================================================
# 4. Complaints Report
# =============================================================================


@router.get("/complaints", response_class=HTMLResponse)
async def complaints_report_screen(
    request: Request,
    hostel_id: UUID | None = Query(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Complaints analytics, category breakdown, and resolution metrics."""
    staff, assigned_hostels = current_staff
    report_service = ReportService(db)
    hostel_repo = HostelRepository(db)

    all_hostels, _ = await hostel_repo.list(params=PaginationParams(page=1, size=100))
    if staff.role == UserRole.WARDEN:
        hostels = [h for h in all_hostels if h.id in assigned_hostels]
    else:
        hostels = all_hostels

    data = await report_service.get_complaints_report(staff, hostel_id=hostel_id)

    return render_template(
        request,
        "admin/reports/complaints.html",
        {
            "active_nav": "reports",
            "hostels": hostels,
            "selected_hostel_id": hostel_id,
            "data": data,
        },
    )


@router.get("/complaints/csv")
async def complaints_report_csv(
    hostel_id: UUID | None = Query(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export complaints metrics breakdown to CSV."""
    staff, _ = current_staff
    report_service = ReportService(db)
    data = await report_service.get_complaints_report(staff, hostel_id=hostel_id)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Category", "Ticket Count", "Total Complaints", "Avg Resolution Hours"])
    for cat, count in data.by_category.items():
        writer.writerow(
            [
                cat.capitalize(),
                count,
                data.total_complaints,
                f"{data.avg_resolution_hours:.1f}",
            ]
        )

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="complaints_report.csv"'},
    )


# =============================================================================
# 5. Attendance Report
# =============================================================================


@router.get("/attendance", response_class=HTMLResponse)
async def attendance_report_screen(
    request: Request,
    target_date: date | None = Query(None),
    hostel_id: UUID | None = Query(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Daily attendance summary (present, outside, on leave) with CSS visual graphs."""
    staff, assigned_hostels = current_staff
    report_service = ReportService(db)
    hostel_repo = HostelRepository(db)

    all_hostels, _ = await hostel_repo.list(params=PaginationParams(page=1, size=100))
    if staff.role == UserRole.WARDEN:
        hostels = [h for h in all_hostels if h.id in assigned_hostels]
    else:
        hostels = all_hostels

    sel_date = target_date or date.today()
    data = await report_service.get_attendance_report(
        staff, target_date=sel_date, hostel_id=hostel_id
    )
    present_pct = (
        (data.present_count / data.total_active_students * 100)
        if data.total_active_students > 0
        else 0.0
    )

    return render_template(
        request,
        "admin/reports/attendance.html",
        {
            "active_nav": "reports",
            "hostels": hostels,
            "selected_hostel_id": hostel_id,
            "target_date": sel_date.isoformat(),
            "data": data,
            "present_pct": round(present_pct, 1),
        },
    )


@router.get("/attendance/csv")
async def attendance_report_csv(
    target_date: date | None = Query(None),
    hostel_id: UUID | None = Query(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export attendance daily report to CSV."""
    staff, _ = current_staff
    report_service = ReportService(db)
    sel_date = target_date or date.today()
    data = await report_service.get_attendance_report(
        staff, target_date=sel_date, hostel_id=hostel_id
    )
    present_pct = (
        (data.present_count / data.total_active_students * 100)
        if data.total_active_students > 0
        else 0.0
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Target Date",
            "Total Active Students",
            "Present Count",
            "Absent / Outside Count",
            "On Leave Count",
            "Present Percentage",
        ]
    )
    writer.writerow(
        [
            sel_date.isoformat(),
            data.total_active_students,
            data.present_count,
            data.absent_count,
            data.on_leave_count,
            f"{present_pct:.2f}%",
        ]
    )

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="attendance_report.csv"'},
    )
