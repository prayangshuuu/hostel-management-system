"""API endpoints for operational and financial reports with CSV export support."""

from __future__ import annotations

import io
from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.core.exceptions import ValidationAppError
from app.models.user import User, UserRole
from app.schemas.report import (
    AttendanceReportRead,
    ComplaintsReportRead,
    DefaulterReportRowRead,
    OccupancyReportRowRead,
    RevenueReportRowRead,
)
from app.services.report_service import ReportService

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get(
    "/occupancy",
    summary="Get occupancy report per hostel/block/room-type (Admin or Warden)",
    response_model=list[OccupancyReportRowRead] | None,
)
async def get_occupancy_report(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
    hostel_id: UUID | None = None,
    format: Annotated[Literal["json", "csv"], Query(description="Output format")] = "json",
) -> Any:
    """Retrieve occupancy breakdown grouped by hostel, block, and room type with CSV support."""
    service = ReportService(session)
    rows = await service.get_occupancy_report(current_user=current_user, hostel_id=hostel_id)

    if format == "csv":
        csv_content = service.generate_occupancy_csv(rows)
        return StreamingResponse(
            io.StringIO(csv_content),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="occupancy_report.csv"'},
        )

    return [OccupancyReportRowRead.model_validate(r) for r in rows]


@router.get(
    "/revenue",
    summary="Get revenue report grouped by month, hostel, or payment method (Admin or Warden)",
    response_model=list[RevenueReportRowRead] | None,
)
async def get_revenue_report(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
    from_date: Annotated[date | None, Query(alias="from", description="Start date filter")] = None,
    to_date: Annotated[date | None, Query(alias="to", description="End date filter")] = None,
    group_by: Annotated[
        Literal["month", "hostel", "method"],
        Query(description="Grouping dimension: month, hostel, or method"),
    ] = "month",
    hostel_id: UUID | None = None,
    format: Annotated[Literal["json", "csv"], Query(description="Output format")] = "json",
) -> Any:
    """Retrieve revenue aggregations with CSV export support."""
    if from_date and to_date and from_date > to_date:
        raise ValidationAppError(
            "Start date ('from') must not be after end date ('to')",
            code="INVALID_DATE_RANGE",
        )

    service = ReportService(session)
    rows = await service.get_revenue_report(
        current_user=current_user,
        from_date=from_date,
        to_date=to_date,
        group_by=group_by,
        hostel_id=hostel_id,
    )

    if format == "csv":
        csv_content = service.generate_revenue_csv(rows)
        filename = f"revenue_report_{group_by}.csv"
        return StreamingResponse(
            io.StringIO(csv_content),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return [RevenueReportRowRead.model_validate(r) for r in rows]


@router.get(
    "/defaulters",
    summary="Get defaulters report with overdue invoices (Admin or Warden)",
    response_model=list[DefaulterReportRowRead] | None,
)
async def get_defaulters_report(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
    hostel_id: UUID | None = None,
    format: Annotated[Literal["json", "csv"], Query(description="Output format")] = "json",
) -> Any:
    """Retrieve students with overdue invoices and outstanding balances with CSV export."""
    service = ReportService(session)
    rows = await service.get_defaulters_report(current_user=current_user, hostel_id=hostel_id)

    if format == "csv":
        csv_content = service.generate_defaulters_csv(rows)
        return StreamingResponse(
            io.StringIO(csv_content),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="defaulters_report.csv"'},
        )

    return [DefaulterReportRowRead.model_validate(r) for r in rows]


@router.get(
    "/complaints",
    response_model=ComplaintsReportRead,
    summary="Get complaints report by status, category, and avg resolution time (Admin or Warden)",
)
async def get_complaints_report(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
    hostel_id: UUID | None = None,
) -> ComplaintsReportRead:
    """Retrieve breakdown of complaints and average resolution hours."""
    service = ReportService(session)
    data = await service.get_complaints_report(current_user=current_user, hostel_id=hostel_id)
    return ComplaintsReportRead(
        total_complaints=data.total_complaints,
        by_status=data.by_status,
        by_category=data.by_category,
        avg_resolution_hours=data.avg_resolution_hours,
    )


@router.get(
    "/attendance",
    response_model=AttendanceReportRead,
    summary="Get attendance report for a specific date (Admin or Warden)",
)
async def get_attendance_report(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
    target_date: Annotated[
        date | None, Query(alias="date", description="Target date (defaults to today)")
    ] = None,
    hostel_id: UUID | None = None,
) -> AttendanceReportRead:
    """Retrieve attendance presence, leaves, and absences for target date."""
    resolved_date = target_date or date.today()
    service = ReportService(session)
    data = await service.get_attendance_report(
        current_user=current_user,
        target_date=resolved_date,
        hostel_id=hostel_id,
    )
    return AttendanceReportRead(
        target_date=data.target_date,
        total_active_students=data.total_active_students,
        present_count=data.present_count,
        absent_count=data.absent_count,
        on_leave_count=data.on_leave_count,
    )
