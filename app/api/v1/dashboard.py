"""API endpoints for executive and student dashboards."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.user import User, UserRole
from app.schemas.report import DashboardSummaryRead
from app.services.report_service import ReportService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get(
    "/summary",
    response_model=DashboardSummaryRead,
    summary="Get executive dashboard summary (Admin or Warden)",
)
async def get_dashboard_summary(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
    hostel_id: UUID | None = None,
) -> DashboardSummaryRead:
    """Consolidated metrics across occupancy, revenue, complaints, and attendance."""
    service = ReportService(session)
    summary_data = await service.get_dashboard_summary(
        current_user=current_user,
        hostel_id=hostel_id,
    )
    return DashboardSummaryRead(
        total_hostels=summary_data.total_hostels,
        total_rooms=summary_data.total_rooms,
        total_beds=summary_data.total_beds,
        occupied_beds=summary_data.occupied_beds,
        occupancy_rate=summary_data.occupancy_rate,
        active_students=summary_data.active_students,
        open_complaints=summary_data.open_complaints,
        pending_leaves=summary_data.pending_leaves,
        present_now=summary_data.present_now,
        invoices_due_this_month=summary_data.invoices_due_this_month,
        collected_this_month=summary_data.collected_this_month,
        outstanding_total=summary_data.outstanding_total,
    )
