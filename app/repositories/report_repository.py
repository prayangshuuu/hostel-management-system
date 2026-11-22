"""Database repository for dashboard summaries, operational reports, and student dashboard."""

from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    and_,
    case,
    distinct,
    func,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.allocation import Allocation, AllocationStatus
from app.models.billing import (
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentMethod,
)
from app.models.complaint import (
    Complaint,
    ComplaintCategory,
    ComplaintStatus,
)
from app.models.hostel import Block, Hostel
from app.models.notice import Notice, NoticeAudience, NoticeRead
from app.models.operations import (
    AttendanceLog,
    AttendanceType,
    LeaveRequest,
    LeaveStatus,
)
from app.models.room import Bed, Room
from app.models.student import StudentProfile
from app.models.user import User


@dataclass(frozen=True, slots=True)
class DashboardSummaryData:
    """Summary metrics for the administrative and warden dashboard."""

    total_hostels: int
    total_rooms: int
    total_beds: int
    occupied_beds: int
    occupancy_rate: float
    active_students: int
    open_complaints: int
    pending_leaves: int
    present_now: int
    invoices_due_this_month: Decimal
    collected_this_month: Decimal
    outstanding_total: Decimal

    def to_dict(self) -> dict[str, Any]:
        """Convert dataclass to dictionary."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OccupancyReportRow:
    """Breakdown of bed capacity and occupancy per hostel, block, and room type."""

    hostel_id: UUID
    hostel_name: str
    block_id: UUID
    block_name: str
    room_type: str
    total_beds: int
    occupied_beds: int
    available_beds: int
    occupancy_rate: float

    def to_dict(self) -> dict[str, Any]:
        """Convert dataclass to dictionary."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RevenueReportRow:
    """Revenue aggregation record grouped by month, hostel, or payment method."""

    group_key: str
    total_revenue: Decimal
    transaction_count: int
    hostel_id: UUID | None = None
    hostel_name: str | None = None
    payment_method: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert dataclass to dictionary."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DefaulterReportRow:
    """Student with outstanding overdue invoices."""

    student_id: UUID
    student_no: str
    student_name: str
    hostel_name: str
    room_number: str
    invoice_id: UUID
    amount: Decimal
    paid_amount: Decimal
    balance: Decimal
    due_date: date
    days_overdue: int

    def to_dict(self) -> dict[str, Any]:
        """Convert dataclass to dictionary."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ComplaintsReportData:
    """Aggregated complaints metrics."""

    total_complaints: int
    by_status: dict[str, int]
    by_category: dict[str, int]
    avg_resolution_hours: float

    def to_dict(self) -> dict[str, Any]:
        """Convert dataclass to dictionary."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AttendanceReportData:
    """Aggregated attendance metrics for a specific date."""

    target_date: date
    total_active_students: int
    present_count: int
    absent_count: int
    on_leave_count: int

    def to_dict(self) -> dict[str, Any]:
        """Convert dataclass to dictionary."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StudentRoomInfo:
    """Room allocation summary for a student."""

    room_id: UUID
    room_number: str
    block_name: str
    hostel_name: str
    bed_label: str

    def to_dict(self) -> dict[str, Any]:
        """Convert dataclass to dictionary."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StudentDashboardData:
    """Personalized dashboard metrics for an authenticated student."""

    room: StudentRoomInfo | None
    roommates: list[str]
    balance: Decimal
    unread_notices_count: int
    open_complaints_count: int

    def to_dict(self) -> dict[str, Any]:
        """Convert dataclass to dictionary."""
        return asdict(self)


class ReportRepository:
    """Repository handling high-performance aggregate SQL queries for reports and dashboards."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _is_sqlite(self) -> bool:
        """Check if current database session is running on SQLite."""
        bind: Any = getattr(self.session, "bind", None)
        if bind is None:
            try:
                bind = self.session.get_bind()
            except Exception:
                return False
        dialect = getattr(bind, "dialect", None)
        dialect_name = getattr(dialect, "name", "")
        return bool(dialect_name == "sqlite")

    async def get_dashboard_summary(
        self,
        hostel_ids: list[UUID] | None = None,
        target_date: date | None = None,
    ) -> DashboardSummaryData:
        """Fetch consolidated dashboard summary metrics across operations and billing."""
        if hostel_ids is not None and len(hostel_ids) == 0:
            return DashboardSummaryData(
                total_hostels=0,
                total_rooms=0,
                total_beds=0,
                occupied_beds=0,
                occupancy_rate=0.0,
                active_students=0,
                open_complaints=0,
                pending_leaves=0,
                present_now=0,
                invoices_due_this_month=Decimal("0.00"),
                collected_this_month=Decimal("0.00"),
                outstanding_total=Decimal("0.00"),
            )

        ref_date = target_date or date.today()
        month_start = ref_date.replace(day=1)
        _, last_day = calendar.monthrange(ref_date.year, ref_date.month)
        month_end = date(ref_date.year, ref_date.month, last_day)

        start_dt = datetime(ref_date.year, ref_date.month, 1, 0, 0, 0, tzinfo=UTC)
        if ref_date.month == 12:
            next_month_start_dt = datetime(ref_date.year + 1, 1, 1, 0, 0, 0, tzinfo=UTC)
        else:
            next_month_start_dt = datetime(
                ref_date.year, ref_date.month + 1, 1, 0, 0, 0, tzinfo=UTC
            )

        # 1. Total Hostels (non-deleted)
        hostels_stmt = select(func.count(Hostel.id)).where(Hostel.is_deleted.is_(False))
        if hostel_ids is not None:
            hostels_stmt = hostels_stmt.where(Hostel.id.in_(hostel_ids))
        total_hostels = int((await self.session.execute(hostels_stmt)).scalar() or 0)

        # 2. Total Rooms (non-deleted, filtered by hostel_ids)
        rooms_stmt = (
            select(func.count(Room.id))
            .select_from(Room)
            .join(Block, Block.id == Room.block_id)
            .join(Hostel, Hostel.id == Block.hostel_id)
            .where(
                Room.is_deleted.is_(False),
                Hostel.is_deleted.is_(False),
            )
        )
        if hostel_ids is not None:
            rooms_stmt = rooms_stmt.where(Hostel.id.in_(hostel_ids))
        total_rooms = int((await self.session.execute(rooms_stmt)).scalar() or 0)

        # 3. Total Beds & Occupied Beds
        beds_stmt = (
            select(
                func.count(Bed.id).label("total_beds"),
                func.coalesce(
                    func.sum(case((Bed.is_occupied.is_(True), 1), else_=0)),
                    0,
                ).label("occupied_beds"),
            )
            .select_from(Bed)
            .join(Room, Room.id == Bed.room_id)
            .join(Block, Block.id == Room.block_id)
            .join(Hostel, Hostel.id == Block.hostel_id)
            .where(
                Room.is_deleted.is_(False),
                Hostel.is_deleted.is_(False),
            )
        )
        if hostel_ids is not None:
            beds_stmt = beds_stmt.where(Hostel.id.in_(hostel_ids))
        bed_row = (await self.session.execute(beds_stmt)).one()
        total_beds = int(bed_row.total_beds or 0)
        occupied_beds = int(bed_row.occupied_beds or 0)
        occupancy_rate = round((occupied_beds / total_beds) * 100.0, 2) if total_beds > 0 else 0.0

        # 4. Active Students
        active_stmt = (
            select(func.count(distinct(Allocation.student_id)))
            .select_from(Allocation)
            .join(Bed, Bed.id == Allocation.bed_id)
            .join(Room, Room.id == Bed.room_id)
            .join(Block, Block.id == Room.block_id)
            .join(Hostel, Hostel.id == Block.hostel_id)
            .join(StudentProfile, StudentProfile.id == Allocation.student_id)
            .where(
                Allocation.status == AllocationStatus.ACTIVE,
                Room.is_deleted.is_(False),
                Hostel.is_deleted.is_(False),
                StudentProfile.is_deleted.is_(False),
            )
        )
        if hostel_ids is not None:
            active_stmt = active_stmt.where(Hostel.id.in_(hostel_ids))
        active_students = int((await self.session.execute(active_stmt)).scalar() or 0)

        # 5. Open Complaints
        complaints_stmt = (
            select(func.count(Complaint.id))
            .select_from(Complaint)
            .join(Room, Room.id == Complaint.room_id)
            .join(Block, Block.id == Room.block_id)
            .join(Hostel, Hostel.id == Block.hostel_id)
            .where(
                Complaint.status.in_([ComplaintStatus.OPEN, ComplaintStatus.IN_PROGRESS]),
                Room.is_deleted.is_(False),
                Hostel.is_deleted.is_(False),
            )
        )
        if hostel_ids is not None:
            complaints_stmt = complaints_stmt.where(Hostel.id.in_(hostel_ids))
        open_complaints = int((await self.session.execute(complaints_stmt)).scalar() or 0)

        # 6. Pending Leaves
        leaves_stmt = (
            select(func.count(distinct(LeaveRequest.id)))
            .select_from(LeaveRequest)
            .join(StudentProfile, StudentProfile.id == LeaveRequest.student_id)
            .join(
                Allocation,
                (Allocation.student_id == StudentProfile.id)
                & (Allocation.status == AllocationStatus.ACTIVE),
            )
            .join(Bed, Bed.id == Allocation.bed_id)
            .join(Room, Room.id == Bed.room_id)
            .join(Block, Block.id == Room.block_id)
            .join(Hostel, Hostel.id == Block.hostel_id)
            .where(
                LeaveRequest.status == LeaveStatus.PENDING,
                StudentProfile.is_deleted.is_(False),
                Room.is_deleted.is_(False),
                Hostel.is_deleted.is_(False),
            )
        )
        if hostel_ids is not None:
            leaves_stmt = leaves_stmt.where(Hostel.id.in_(hostel_ids))
        pending_leaves = int((await self.session.execute(leaves_stmt)).scalar() or 0)

        # 7. Present Now (active students whose latest attendance log is check_in)
        att_subq = (
            select(
                AttendanceLog.student_id,
                AttendanceLog.type,
                func.row_number()
                .over(
                    partition_by=AttendanceLog.student_id,
                    order_by=(AttendanceLog.timestamp.desc(), AttendanceLog.created_at.desc()),
                )
                .label("rn"),
            )
        ).subquery()

        present_stmt = (
            select(func.count(distinct(StudentProfile.id)))
            .select_from(StudentProfile)
            .join(att_subq, (att_subq.c.student_id == StudentProfile.id) & (att_subq.c.rn == 1))
            .join(
                Allocation,
                (Allocation.student_id == StudentProfile.id)
                & (Allocation.status == AllocationStatus.ACTIVE),
            )
            .join(Bed, Bed.id == Allocation.bed_id)
            .join(Room, Room.id == Bed.room_id)
            .join(Block, Block.id == Room.block_id)
            .join(Hostel, Hostel.id == Block.hostel_id)
            .where(
                att_subq.c.type == AttendanceType.CHECK_IN,
                StudentProfile.is_deleted.is_(False),
                Room.is_deleted.is_(False),
                Hostel.is_deleted.is_(False),
            )
        )
        if hostel_ids is not None:
            present_stmt = present_stmt.where(Hostel.id.in_(hostel_ids))
        present_now = int((await self.session.execute(present_stmt)).scalar() or 0)

        # 8. Invoices Due This Month
        due_stmt = (
            select(func.coalesce(func.sum(Invoice.amount), Decimal("0.00")))
            .select_from(Invoice)
            .join(Allocation, Allocation.id == Invoice.allocation_id)
            .join(Bed, Bed.id == Allocation.bed_id)
            .join(Room, Room.id == Bed.room_id)
            .join(Block, Block.id == Room.block_id)
            .join(Hostel, Hostel.id == Block.hostel_id)
            .where(
                Invoice.status != InvoiceStatus.VOID,
                or_(
                    and_(Invoice.due_date >= month_start, Invoice.due_date <= month_end),
                    and_(Invoice.period_start >= month_start, Invoice.period_start <= month_end),
                ),
                Hostel.is_deleted.is_(False),
            )
        )
        if hostel_ids is not None:
            due_stmt = due_stmt.where(Hostel.id.in_(hostel_ids))
        invoices_due_this_month = Decimal(str((await self.session.execute(due_stmt)).scalar() or 0))

        # 9. Collected This Month
        collected_stmt = (
            select(func.coalesce(func.sum(Payment.amount), Decimal("0.00")))
            .select_from(Payment)
            .join(Invoice, Invoice.id == Payment.invoice_id)
            .join(Allocation, Allocation.id == Invoice.allocation_id)
            .join(Bed, Bed.id == Allocation.bed_id)
            .join(Room, Room.id == Bed.room_id)
            .join(Block, Block.id == Room.block_id)
            .join(Hostel, Hostel.id == Block.hostel_id)
            .where(
                Payment.paid_at >= start_dt,
                Payment.paid_at < next_month_start_dt,
                Invoice.status != InvoiceStatus.VOID,
                Hostel.is_deleted.is_(False),
            )
        )
        if hostel_ids is not None:
            collected_stmt = collected_stmt.where(Hostel.id.in_(hostel_ids))
        collected_this_month = Decimal(
            str((await self.session.execute(collected_stmt)).scalar() or 0)
        )

        # 10. Outstanding Total
        outstanding_stmt = (
            select(func.coalesce(func.sum(Invoice.amount - Invoice.paid_amount), Decimal("0.00")))
            .select_from(Invoice)
            .join(Allocation, Allocation.id == Invoice.allocation_id)
            .join(Bed, Bed.id == Allocation.bed_id)
            .join(Room, Room.id == Bed.room_id)
            .join(Block, Block.id == Room.block_id)
            .join(Hostel, Hostel.id == Block.hostel_id)
            .where(
                Invoice.status.in_(
                    [InvoiceStatus.UNPAID, InvoiceStatus.PARTIAL, InvoiceStatus.OVERDUE]
                ),
                Hostel.is_deleted.is_(False),
            )
        )
        if hostel_ids is not None:
            outstanding_stmt = outstanding_stmt.where(Hostel.id.in_(hostel_ids))
        outstanding_total = Decimal(
            str((await self.session.execute(outstanding_stmt)).scalar() or 0)
        )

        return DashboardSummaryData(
            total_hostels=total_hostels,
            total_rooms=total_rooms,
            total_beds=total_beds,
            occupied_beds=occupied_beds,
            occupancy_rate=occupancy_rate,
            active_students=active_students,
            open_complaints=open_complaints,
            pending_leaves=pending_leaves,
            present_now=present_now,
            invoices_due_this_month=invoices_due_this_month,
            collected_this_month=collected_this_month,
            outstanding_total=outstanding_total,
        )

    async def get_occupancy_report(
        self,
        hostel_ids: list[UUID] | None = None,
    ) -> list[OccupancyReportRow]:
        """Fetch occupancy breakdown grouped by hostel, block, and room type."""
        if hostel_ids is not None and len(hostel_ids) == 0:
            return []

        stmt = (
            select(
                Hostel.id.label("hostel_id"),
                Hostel.name.label("hostel_name"),
                Block.id.label("block_id"),
                Block.name.label("block_name"),
                Room.room_type.label("room_type"),
                func.count(Bed.id).label("total_beds"),
                func.coalesce(
                    func.sum(case((Bed.is_occupied.is_(True), 1), else_=0)),
                    0,
                ).label("occupied_beds"),
            )
            .select_from(Hostel)
            .join(Block, Block.hostel_id == Hostel.id)
            .join(Room, Room.block_id == Block.id)
            .outerjoin(Bed, Bed.room_id == Room.id)
            .where(
                Hostel.is_deleted.is_(False),
                Room.is_deleted.is_(False),
            )
            .group_by(
                Hostel.id,
                Hostel.name,
                Block.id,
                Block.name,
                Room.room_type,
            )
            .order_by(
                Hostel.name.asc(),
                Block.name.asc(),
                Room.room_type.asc(),
            )
        )
        if hostel_ids is not None:
            stmt = stmt.where(Hostel.id.in_(hostel_ids))

        result = await self.session.execute(stmt)
        rows = result.all()

        report_rows: list[OccupancyReportRow] = []
        for row in rows:
            total_beds = int(row.total_beds or 0)
            occupied_beds = int(row.occupied_beds or 0)
            available_beds = max(0, total_beds - occupied_beds)
            occupancy_rate = (
                round((occupied_beds / total_beds) * 100.0, 2) if total_beds > 0 else 0.0
            )
            room_type_str = (
                row.room_type.value if hasattr(row.room_type, "value") else str(row.room_type)
            )
            report_rows.append(
                OccupancyReportRow(
                    hostel_id=row.hostel_id,
                    hostel_name=row.hostel_name,
                    block_id=row.block_id,
                    block_name=row.block_name,
                    room_type=room_type_str,
                    total_beds=total_beds,
                    occupied_beds=occupied_beds,
                    available_beds=available_beds,
                    occupancy_rate=occupancy_rate,
                )
            )
        return report_rows

    async def get_revenue_report(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
        group_by: str = "month",
        hostel_ids: list[UUID] | None = None,
    ) -> list[RevenueReportRow]:
        """Fetch revenue aggregations grouped by 'month', 'hostel', or 'method'."""
        if hostel_ids is not None and len(hostel_ids) == 0:
            return []

        if group_by not in ("month", "hostel", "method"):
            raise ValueError(
                f"Invalid group_by parameter '{group_by}'. Expected 'month', 'hostel', or 'method'."
            )

        if group_by == "month":
            if self._is_sqlite():
                group_expr = func.strftime("%Y-%m", Payment.paid_at).label("month_label")
            else:
                group_expr = func.to_char(Payment.paid_at, "YYYY-MM").label("month_label")

            stmt = (
                select(
                    group_expr,
                    func.coalesce(func.sum(Payment.amount), Decimal("0.00")).label("total_revenue"),
                    func.count(Payment.id).label("transaction_count"),
                )
                .select_from(Payment)
                .join(Invoice, Invoice.id == Payment.invoice_id)
                .join(Allocation, Allocation.id == Invoice.allocation_id)
                .join(Bed, Bed.id == Allocation.bed_id)
                .join(Room, Room.id == Bed.room_id)
                .join(Block, Block.id == Room.block_id)
                .join(Hostel, Hostel.id == Block.hostel_id)
                .where(
                    Invoice.status != InvoiceStatus.VOID,
                    Hostel.is_deleted.is_(False),
                )
                .group_by(group_expr)
                .order_by(group_expr.asc())
            )
        elif group_by == "hostel":
            stmt = (
                select(
                    Hostel.id.label("hostel_id"),
                    Hostel.name.label("hostel_name"),
                    func.coalesce(func.sum(Payment.amount), Decimal("0.00")).label("total_revenue"),
                    func.count(Payment.id).label("transaction_count"),
                )
                .select_from(Payment)
                .join(Invoice, Invoice.id == Payment.invoice_id)
                .join(Allocation, Allocation.id == Invoice.allocation_id)
                .join(Bed, Bed.id == Allocation.bed_id)
                .join(Room, Room.id == Bed.room_id)
                .join(Block, Block.id == Room.block_id)
                .join(Hostel, Hostel.id == Block.hostel_id)
                .where(
                    Invoice.status != InvoiceStatus.VOID,
                    Hostel.is_deleted.is_(False),
                )
                .group_by(Hostel.id, Hostel.name)
                .order_by(Hostel.name.asc())
            )
        else:  # method
            stmt = (
                select(
                    Payment.method.label("payment_method"),
                    func.coalesce(func.sum(Payment.amount), Decimal("0.00")).label("total_revenue"),
                    func.count(Payment.id).label("transaction_count"),
                )
                .select_from(Payment)
                .join(Invoice, Invoice.id == Payment.invoice_id)
                .join(Allocation, Allocation.id == Invoice.allocation_id)
                .join(Bed, Bed.id == Allocation.bed_id)
                .join(Room, Room.id == Bed.room_id)
                .join(Block, Block.id == Room.block_id)
                .join(Hostel, Hostel.id == Block.hostel_id)
                .where(
                    Invoice.status != InvoiceStatus.VOID,
                    Hostel.is_deleted.is_(False),
                )
                .group_by(Payment.method)
                .order_by(Payment.method.asc())
            )

        if from_date is not None:
            dt_from = datetime.combine(from_date, time.min).replace(tzinfo=UTC)
            stmt = stmt.where(Payment.paid_at >= dt_from)
        if to_date is not None:
            dt_to = datetime.combine(to_date, time.max).replace(tzinfo=UTC)
            stmt = stmt.where(Payment.paid_at <= dt_to)
        if hostel_ids is not None:
            stmt = stmt.where(Hostel.id.in_(hostel_ids))

        result = await self.session.execute(stmt)
        rows = result.all()

        revenue_rows: list[RevenueReportRow] = []
        for row in rows:
            rev = Decimal(str(row.total_revenue))
            cnt = int(row.transaction_count)
            if group_by == "month":
                revenue_rows.append(
                    RevenueReportRow(
                        group_key=str(row.month_label),
                        total_revenue=rev,
                        transaction_count=cnt,
                    )
                )
            elif group_by == "hostel":
                revenue_rows.append(
                    RevenueReportRow(
                        group_key=str(row.hostel_name),
                        total_revenue=rev,
                        transaction_count=cnt,
                        hostel_id=row.hostel_id,
                        hostel_name=str(row.hostel_name),
                    )
                )
            else:  # method
                method_val = (
                    row.payment_method.value
                    if isinstance(row.payment_method, PaymentMethod)
                    else str(row.payment_method)
                )
                revenue_rows.append(
                    RevenueReportRow(
                        group_key=method_val,
                        total_revenue=rev,
                        transaction_count=cnt,
                        payment_method=method_val,
                    )
                )

        return revenue_rows

    async def get_defaulters_report(
        self,
        hostel_ids: list[UUID] | None = None,
        current_date: date | None = None,
    ) -> list[DefaulterReportRow]:
        """Fetch overdue invoice defaulters with overdue amount and days elapsed."""
        if hostel_ids is not None and len(hostel_ids) == 0:
            return []

        today = current_date or date.today()

        overdue_cond = or_(
            Invoice.status == InvoiceStatus.OVERDUE,
            and_(
                Invoice.status.in_([InvoiceStatus.UNPAID, InvoiceStatus.PARTIAL]),
                Invoice.due_date < today,
            ),
        )

        stmt = (
            select(
                StudentProfile.id.label("student_id"),
                StudentProfile.student_no.label("student_no"),
                User.full_name.label("student_name"),
                Hostel.name.label("hostel_name"),
                Room.number.label("room_number"),
                Invoice.id.label("invoice_id"),
                Invoice.amount.label("amount"),
                Invoice.paid_amount.label("paid_amount"),
                (Invoice.amount - Invoice.paid_amount).label("balance"),
                Invoice.due_date.label("due_date"),
            )
            .select_from(Invoice)
            .join(StudentProfile, StudentProfile.id == Invoice.student_id)
            .join(User, User.id == StudentProfile.user_id)
            .join(Allocation, Allocation.id == Invoice.allocation_id)
            .join(Bed, Bed.id == Allocation.bed_id)
            .join(Room, Room.id == Bed.room_id)
            .join(Block, Block.id == Room.block_id)
            .join(Hostel, Hostel.id == Block.hostel_id)
            .where(
                Invoice.status != InvoiceStatus.VOID,
                overdue_cond,
                (Invoice.amount - Invoice.paid_amount) > Decimal("0.00"),
                Hostel.is_deleted.is_(False),
                StudentProfile.is_deleted.is_(False),
            )
            .order_by(
                Invoice.due_date.asc(),
                User.full_name.asc(),
            )
        )
        if hostel_ids is not None:
            stmt = stmt.where(Hostel.id.in_(hostel_ids))

        result = await self.session.execute(stmt)
        rows = result.all()

        defaulters: list[DefaulterReportRow] = []
        for row in rows:
            days_overdue = max(0, (today - row.due_date).days)
            defaulters.append(
                DefaulterReportRow(
                    student_id=row.student_id,
                    student_no=row.student_no,
                    student_name=row.student_name,
                    hostel_name=row.hostel_name,
                    room_number=row.room_number,
                    invoice_id=row.invoice_id,
                    amount=Decimal(str(row.amount)),
                    paid_amount=Decimal(str(row.paid_amount)),
                    balance=Decimal(str(row.balance)),
                    due_date=row.due_date,
                    days_overdue=days_overdue,
                )
            )
        return defaulters

    async def get_complaints_report(
        self,
        hostel_ids: list[UUID] | None = None,
    ) -> ComplaintsReportData:
        """Fetch complaint metrics by status, category, and average resolution time in hours."""
        if hostel_ids is not None and len(hostel_ids) == 0:
            return ComplaintsReportData(
                total_complaints=0,
                by_status={},
                by_category={},
                avg_resolution_hours=0.0,
            )

        # 1. Counts by status
        status_stmt = (
            select(
                Complaint.status,
                func.count(Complaint.id).label("status_count"),
            )
            .select_from(Complaint)
            .join(Room, Room.id == Complaint.room_id)
            .join(Block, Block.id == Room.block_id)
            .join(Hostel, Hostel.id == Block.hostel_id)
            .where(
                Hostel.is_deleted.is_(False),
                Room.is_deleted.is_(False),
            )
            .group_by(Complaint.status)
        )
        if hostel_ids is not None:
            status_stmt = status_stmt.where(Hostel.id.in_(hostel_ids))
        status_res = await self.session.execute(status_stmt)
        by_status: dict[str, int] = {}
        for status_row in status_res.all():
            k = (
                status_row.status.value
                if hasattr(status_row.status, "value")
                else str(status_row.status)
            )
            by_status[k] = int(status_row.status_count)

        # 2. Counts by category
        cat_stmt = (
            select(
                Complaint.category,
                func.count(Complaint.id).label("cat_count"),
            )
            .select_from(Complaint)
            .join(Room, Room.id == Complaint.room_id)
            .join(Block, Block.id == Room.block_id)
            .join(Hostel, Hostel.id == Block.hostel_id)
            .where(
                Hostel.is_deleted.is_(False),
                Room.is_deleted.is_(False),
            )
            .group_by(Complaint.category)
        )
        if hostel_ids is not None:
            cat_stmt = cat_stmt.where(Hostel.id.in_(hostel_ids))
        cat_res = await self.session.execute(cat_stmt)
        by_category: dict[str, int] = {}
        for cat_row in cat_res.all():
            k = (
                cat_row.category.value
                if isinstance(cat_row.category, ComplaintCategory)
                else str(cat_row.category)
            )
            by_category[k] = int(cat_row.cat_count)

        # 3. Average resolution hours using CASE WHEN resolved_at IS NOT NULL
        if self._is_sqlite():
            diff_expr = (
                func.julianday(Complaint.resolved_at) - func.julianday(Complaint.created_at)
            ) * 24.0
        else:
            diff_expr = func.extract("epoch", Complaint.resolved_at - Complaint.created_at) / 3600.0

        avg_stmt = (
            select(
                func.coalesce(
                    func.avg(
                        case(
                            (Complaint.resolved_at.is_not(None), diff_expr),
                            else_=None,
                        )
                    ),
                    0.0,
                ).label("avg_hours")
            )
            .select_from(Complaint)
            .join(Room, Room.id == Complaint.room_id)
            .join(Block, Block.id == Room.block_id)
            .join(Hostel, Hostel.id == Block.hostel_id)
            .where(
                Hostel.is_deleted.is_(False),
                Room.is_deleted.is_(False),
            )
        )
        if hostel_ids is not None:
            avg_stmt = avg_stmt.where(Hostel.id.in_(hostel_ids))

        avg_res = await self.session.execute(avg_stmt)
        avg_resolution_hours = round(float(avg_res.scalar() or 0.0), 2)
        total_complaints = sum(by_status.values())

        return ComplaintsReportData(
            total_complaints=total_complaints,
            by_status=by_status,
            by_category=by_category,
            avg_resolution_hours=avg_resolution_hours,
        )

    async def get_attendance_report(
        self,
        target_date: date,
        hostel_ids: list[UUID] | None = None,
    ) -> AttendanceReportData:
        """Fetch consolidated student attendance status breakdown for a specific target date."""
        if hostel_ids is not None and len(hostel_ids) == 0:
            return AttendanceReportData(
                target_date=target_date,
                total_active_students=0,
                present_count=0,
                absent_count=0,
                on_leave_count=0,
            )

        # 1. Active allocated students in scope on target_date
        active_stmt = (
            select(Allocation.student_id)
            .distinct()
            .select_from(Allocation)
            .join(Bed, Bed.id == Allocation.bed_id)
            .join(Room, Room.id == Bed.room_id)
            .join(Block, Block.id == Room.block_id)
            .join(Hostel, Hostel.id == Block.hostel_id)
            .join(StudentProfile, StudentProfile.id == Allocation.student_id)
            .where(
                Allocation.status == AllocationStatus.ACTIVE,
                Allocation.start_date <= target_date,
                or_(Allocation.end_date.is_(None), Allocation.end_date >= target_date),
                Room.is_deleted.is_(False),
                Hostel.is_deleted.is_(False),
                StudentProfile.is_deleted.is_(False),
            )
        )
        if hostel_ids is not None:
            active_stmt = active_stmt.where(Hostel.id.in_(hostel_ids))

        active_res = await self.session.execute(active_stmt)
        active_student_ids = list(active_res.scalars().all())

        if not active_student_ids:
            return AttendanceReportData(
                target_date=target_date,
                total_active_students=0,
                present_count=0,
                absent_count=0,
                on_leave_count=0,
            )

        # 2. Approved leaves active on target_date
        leave_stmt = (
            select(LeaveRequest.student_id)
            .distinct()
            .select_from(LeaveRequest)
            .where(
                LeaveRequest.student_id.in_(active_student_ids),
                LeaveRequest.status == LeaveStatus.APPROVED,
                LeaveRequest.from_date <= target_date,
                LeaveRequest.to_date >= target_date,
            )
        )
        leave_res = await self.session.execute(leave_stmt)
        on_leave_student_ids = set(leave_res.scalars().all())

        # 3. Present students: latest attendance log on or before target_date is CHECK_IN
        end_of_day = datetime.combine(target_date, time.max).replace(tzinfo=UTC)
        att_subq = (
            select(
                AttendanceLog.student_id,
                AttendanceLog.type,
                func.row_number()
                .over(
                    partition_by=AttendanceLog.student_id,
                    order_by=(AttendanceLog.timestamp.desc(), AttendanceLog.created_at.desc()),
                )
                .label("rn"),
            ).where(
                AttendanceLog.student_id.in_(active_student_ids),
                AttendanceLog.timestamp <= end_of_day,
            )
        ).subquery()

        present_stmt = (
            select(att_subq.c.student_id)
            .distinct()
            .where(
                att_subq.c.rn == 1,
                att_subq.c.type == AttendanceType.CHECK_IN,
            )
        )
        present_res = await self.session.execute(present_stmt)
        present_student_ids = set(present_res.scalars().all())

        # 4. Partition disjoint sets
        effective_present = present_student_ids - on_leave_student_ids
        all_active_set = set(active_student_ids)
        effective_absent = all_active_set - on_leave_student_ids - effective_present

        return AttendanceReportData(
            target_date=target_date,
            total_active_students=len(all_active_set),
            present_count=len(effective_present),
            absent_count=len(effective_absent),
            on_leave_count=len(on_leave_student_ids),
        )

    async def get_student_dashboard_data(self, student_id: UUID) -> StudentDashboardData:
        """Fetch personalized dashboard data for an authenticated student."""
        # 1. Allocation details
        alloc_stmt = (
            select(
                Room.id.label("room_id"),
                Room.number.label("room_number"),
                Block.name.label("block_name"),
                Hostel.name.label("hostel_name"),
                Hostel.id.label("hostel_id"),
                Bed.label.label("bed_label"),
                StudentProfile.user_id.label("user_id"),
            )
            .select_from(Allocation)
            .join(Bed, Bed.id == Allocation.bed_id)
            .join(Room, Room.id == Bed.room_id)
            .join(Block, Block.id == Room.block_id)
            .join(Hostel, Hostel.id == Block.hostel_id)
            .join(StudentProfile, StudentProfile.id == Allocation.student_id)
            .where(
                Allocation.student_id == student_id,
                Allocation.status == AllocationStatus.ACTIVE,
                Room.is_deleted.is_(False),
                Hostel.is_deleted.is_(False),
            )
        )
        alloc_res = await self.session.execute(alloc_stmt)
        alloc_row = alloc_res.first()

        room_info: StudentRoomInfo | None = None
        roommates: list[str] = []
        hostel_id: UUID | None = None
        user_id: UUID | None = None

        if alloc_row:
            room_info = StudentRoomInfo(
                room_id=alloc_row.room_id,
                room_number=alloc_row.room_number,
                block_name=alloc_row.block_name,
                hostel_name=alloc_row.hostel_name,
                bed_label=alloc_row.bed_label,
            )
            hostel_id = alloc_row.hostel_id
            user_id = alloc_row.user_id

            mate_stmt = (
                select(User.full_name)
                .select_from(Allocation)
                .join(Bed, Bed.id == Allocation.bed_id)
                .join(StudentProfile, StudentProfile.id == Allocation.student_id)
                .join(User, User.id == StudentProfile.user_id)
                .where(
                    Bed.room_id == alloc_row.room_id,
                    Allocation.status == AllocationStatus.ACTIVE,
                    Allocation.student_id != student_id,
                    StudentProfile.is_deleted.is_(False),
                )
                .order_by(User.full_name.asc())
            )
            mate_res = await self.session.execute(mate_stmt)
            roommates = list(mate_res.scalars().all())

        if user_id is None:
            user_stmt = select(StudentProfile.user_id).where(StudentProfile.id == student_id)
            user_res = await self.session.execute(user_stmt)
            user_id = user_res.scalar_one_or_none()

        # 2. Outstanding Balance
        bal_stmt = (
            select(func.coalesce(func.sum(Invoice.amount - Invoice.paid_amount), Decimal("0.00")))
            .select_from(Invoice)
            .where(
                Invoice.student_id == student_id,
                Invoice.status.in_(
                    [InvoiceStatus.UNPAID, InvoiceStatus.PARTIAL, InvoiceStatus.OVERDUE]
                ),
            )
        )
        balance = Decimal(str((await self.session.execute(bal_stmt)).scalar() or 0))

        # 3. Open Complaints Count
        comp_stmt = (
            select(func.count(Complaint.id))
            .select_from(Complaint)
            .where(
                Complaint.student_id == student_id,
                Complaint.status.in_([ComplaintStatus.OPEN, ComplaintStatus.IN_PROGRESS]),
            )
        )
        open_complaints_count = int((await self.session.execute(comp_stmt)).scalar() or 0)

        # 4. Unread Notices Count
        unread_notices_count = 0
        if user_id is not None:
            now = datetime.now(UTC)
            read_subq = select(NoticeRead.notice_id).where(NoticeRead.user_id == user_id)
            notices_stmt = (
                select(func.count(Notice.id))
                .select_from(Notice)
                .where(
                    Notice.audience.in_([NoticeAudience.ALL, NoticeAudience.STUDENTS]),
                    or_(
                        Notice.hostel_id.is_(None),
                        Notice.hostel_id == hostel_id,
                    )
                    if hostel_id
                    else Notice.hostel_id.is_(None),
                    Notice.published_at <= now,
                    or_(Notice.expires_at.is_(None), Notice.expires_at >= now),
                    Notice.id.not_in(read_subq),
                )
            )
            unread_notices_count = int((await self.session.execute(notices_stmt)).scalar() or 0)

        return StudentDashboardData(
            room=room_info,
            roommates=roommates,
            balance=balance,
            unread_notices_count=unread_notices_count,
            open_complaints_count=open_complaints_count,
        )
