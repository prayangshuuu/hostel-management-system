"""Service layer for executive dashboards, operational reports, and CSV exports."""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.user import User, UserRole
from app.repositories.hostel_repository import HostelRepository, WardenAssignmentRepository
from app.repositories.report_repository import (
    AttendanceReportData,
    ComplaintsReportData,
    DashboardSummaryData,
    DefaulterReportRow,
    OccupancyReportRow,
    ReportRepository,
    RevenueReportRow,
    StudentDashboardData,
)
from app.repositories.student_repository import StudentRepository


class ReportService:
    """Service handling executive reporting, warden-scoped analytics, and CSV exports."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.report_repo = ReportRepository(session)
        self.warden_repo = WardenAssignmentRepository(session)
        self.hostel_repo = HostelRepository(session)
        self.student_repo = StudentRepository(session)

    async def _resolve_hostel_scope(
        self,
        current_user: User,
        requested_hostel_id: UUID | None = None,
    ) -> list[UUID] | None:
        """Resolve permitted hostel IDs based on current user role and requested filter.

        - Admin: full access to all hostels (None) or specific requested hostel.
        - Warden: access only to assigned hostels. If requested hostel is not assigned, raises 403.
        - Returns list of permitted UUIDs or None (for all hostels).
        """
        if current_user.role == UserRole.ADMIN:
            if requested_hostel_id is not None:
                # Verify hostel exists
                hostel = await self.hostel_repo.get_by_id(requested_hostel_id)
                if hostel is None or hostel.is_deleted:
                    raise NotFoundError(
                        f"Hostel '{requested_hostel_id}' not found",
                        code="HOSTEL_NOT_FOUND",
                    )
                return [requested_hostel_id]
            return None

        if current_user.role == UserRole.WARDEN:
            assigned_ids = await self.warden_repo.list_hostel_ids_for_warden(current_user.id)
            if not assigned_ids:
                return []

            if requested_hostel_id is not None:
                if requested_hostel_id not in assigned_ids:
                    raise ForbiddenError(
                        "You are not assigned to this hostel",
                        code="FORBIDDEN",
                    )
                return [requested_hostel_id]
            return assigned_ids

        raise ForbiddenError(
            "Only administrators and wardens can access report analytics",
            code="FORBIDDEN",
        )

    async def get_dashboard_summary(
        self,
        current_user: User,
        hostel_id: UUID | None = None,
        target_date: date | None = None,
    ) -> DashboardSummaryData:
        """Fetch consolidated dashboard summary metrics scoped to current user."""
        hostel_ids = await self._resolve_hostel_scope(current_user, hostel_id)
        return await self.report_repo.get_dashboard_summary(
            hostel_ids=hostel_ids,
            target_date=target_date,
        )

    async def get_occupancy_report(
        self,
        current_user: User,
        hostel_id: UUID | None = None,
    ) -> list[OccupancyReportRow]:
        """Fetch occupancy breakdown grouped by hostel, block, and room type."""
        hostel_ids = await self._resolve_hostel_scope(current_user, hostel_id)
        return await self.report_repo.get_occupancy_report(hostel_ids=hostel_ids)

    async def get_revenue_report(
        self,
        current_user: User,
        from_date: date | None = None,
        to_date: date | None = None,
        group_by: str = "month",
        hostel_id: UUID | None = None,
    ) -> list[RevenueReportRow]:
        """Fetch revenue aggregations grouped by month, hostel, or payment method."""
        hostel_ids = await self._resolve_hostel_scope(current_user, hostel_id)
        return await self.report_repo.get_revenue_report(
            from_date=from_date,
            to_date=to_date,
            group_by=group_by,
            hostel_ids=hostel_ids,
        )

    async def get_defaulters_report(
        self,
        current_user: User,
        hostel_id: UUID | None = None,
        current_date: date | None = None,
    ) -> list[DefaulterReportRow]:
        """Fetch overdue invoice defaulters."""
        hostel_ids = await self._resolve_hostel_scope(current_user, hostel_id)
        return await self.report_repo.get_defaulters_report(
            hostel_ids=hostel_ids,
            current_date=current_date,
        )

    async def get_complaints_report(
        self,
        current_user: User,
        hostel_id: UUID | None = None,
    ) -> ComplaintsReportData:
        """Fetch complaint metrics by status, category, and average resolution time."""
        hostel_ids = await self._resolve_hostel_scope(current_user, hostel_id)
        return await self.report_repo.get_complaints_report(hostel_ids=hostel_ids)

    async def get_attendance_report(
        self,
        current_user: User,
        target_date: date,
        hostel_id: UUID | None = None,
    ) -> AttendanceReportData:
        """Fetch attendance metrics for a specific target date."""
        hostel_ids = await self._resolve_hostel_scope(current_user, hostel_id)
        return await self.report_repo.get_attendance_report(
            target_date=target_date,
            hostel_ids=hostel_ids,
        )

    async def get_student_dashboard(
        self,
        current_user: User,
    ) -> StudentDashboardData:
        """Fetch personalized operational and financial dashboard for student."""
        profile = await self.student_repo.get_by_user_id(current_user.id)
        if profile is None:
            return StudentDashboardData(
                room=None,
                roommates=[],
                balance=Decimal("0.00"),
                unread_notices_count=0,
                open_complaints_count=0,
            )
        return await self.report_repo.get_student_dashboard_data(student_id=profile.id)

    @staticmethod
    def generate_occupancy_csv(rows: list[OccupancyReportRow]) -> str:
        """Serialize occupancy report rows to CSV format."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Hostel ID",
                "Hostel Name",
                "Block ID",
                "Block Name",
                "Room Type",
                "Total Beds",
                "Occupied Beds",
                "Available Beds",
                "Occupancy Rate (%)",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    str(row.hostel_id),
                    row.hostel_name,
                    str(row.block_id),
                    row.block_name,
                    row.room_type,
                    row.total_beds,
                    row.occupied_beds,
                    row.available_beds,
                    f"{row.occupancy_rate:.2f}",
                ]
            )
        return output.getvalue()

    @staticmethod
    def generate_revenue_csv(rows: list[RevenueReportRow]) -> str:
        """Serialize revenue report rows to CSV format."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Group Key",
                "Total Revenue",
                "Transaction Count",
                "Hostel ID",
                "Hostel Name",
                "Payment Method",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.group_key,
                    str(row.total_revenue),
                    row.transaction_count,
                    str(row.hostel_id) if row.hostel_id else "",
                    row.hostel_name or "",
                    row.payment_method or "",
                ]
            )
        return output.getvalue()

    @staticmethod
    def generate_defaulters_csv(rows: list[DefaulterReportRow]) -> str:
        """Serialize defaulters report rows to CSV format."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Student ID",
                "Student No",
                "Student Name",
                "Hostel Name",
                "Room Number",
                "Invoice ID",
                "Amount",
                "Paid Amount",
                "Balance",
                "Due Date",
                "Days Overdue",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    str(row.student_id),
                    row.student_no,
                    row.student_name,
                    row.hostel_name,
                    row.room_number,
                    str(row.invoice_id),
                    str(row.amount),
                    str(row.paid_amount),
                    str(row.balance),
                    row.due_date.isoformat(),
                    row.days_overdue,
                ]
            )
        return output.getvalue()
