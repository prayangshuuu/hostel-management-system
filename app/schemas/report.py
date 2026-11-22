"""Schemas for dashboard summaries, operational reports, and student dashboard."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DashboardSummaryRead(BaseModel):
    """Consolidated summary metrics for admins and wardens."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    total_hostels: int
    total_rooms: int
    total_beds: int
    occupied_beds: int
    occupancy_rate: float
    active_students: int
    open_complaints: int = Field(validation_alias="open_complaints")
    pending_leaves: int
    present_now: int
    invoices_due_this_month: Decimal
    collected_this_month: Decimal
    outstanding_total: Decimal

    @property
    def open_complaints_count(self) -> int:
        """Alias for open complaints count."""
        return self.open_complaints


class OccupancyReportRowRead(BaseModel):
    """Bed capacity and occupancy breakdown for a hostel/block/room type."""

    model_config = ConfigDict(from_attributes=True)

    hostel_id: UUID
    hostel_name: str
    block_id: UUID
    block_name: str
    room_type: str
    total_beds: int
    occupied_beds: int
    available_beds: int
    occupancy_rate: float


class RevenueReportRowRead(BaseModel):
    """Revenue aggregation record grouped by month, hostel, or payment method."""

    model_config = ConfigDict(from_attributes=True)

    group_key: str
    total_revenue: Decimal
    transaction_count: int
    hostel_id: UUID | None = None
    hostel_name: str | None = None
    payment_method: str | None = None


class DefaulterReportRowRead(BaseModel):
    """Student with overdue invoice details."""

    model_config = ConfigDict(from_attributes=True)

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


class ComplaintsReportRead(BaseModel):
    """Aggregated complaint metrics by status and category with resolution time."""

    model_config = ConfigDict(from_attributes=True)

    total_complaints: int
    by_status: dict[str, int]
    by_category: dict[str, int]
    avg_resolution_hours: float


class AttendanceReportRead(BaseModel):
    """Attendance metrics for a target date."""

    model_config = ConfigDict(from_attributes=True)

    target_date: date
    total_active_students: int
    present_count: int
    absent_count: int
    on_leave_count: int


class StudentRoomInfoRead(BaseModel):
    """Room details for student dashboard."""

    model_config = ConfigDict(from_attributes=True)

    room_id: UUID
    room_number: str
    block_name: str
    hostel_name: str
    bed_label: str


class StudentDashboardRead(BaseModel):
    """Personalized operational and billing dashboard for a student."""

    model_config = ConfigDict(from_attributes=True)

    room: StudentRoomInfoRead | None = None
    room_number: str | None = None
    block_name: str | None = None
    hostel_name: str | None = None
    roommates: list[str] = Field(default_factory=list)
    balance: Decimal = Decimal("0.00")
    unread_notices_count: int = 0
    open_complaints_count: int = 0
