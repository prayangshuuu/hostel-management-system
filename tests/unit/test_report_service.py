"""Unit tests for ReportService scoping, aggregation orchestration, and CSV generation."""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.hostel import GenderType, Hostel, WardenAssignment
from app.models.user import User, UserRole
from app.repositories.report_repository import (
    DefaulterReportRow,
    OccupancyReportRow,
    RevenueReportRow,
)
from app.services.report_service import ReportService


@pytest.mark.asyncio
async def test_report_service_scoping_rules(db_session: AsyncSession) -> None:
    """Verify role-based scoping resolution for admins, wardens, and students."""
    service = ReportService(db_session)

    # Setup Hostels
    h1 = Hostel(name="Hostel 1", code="H1", gender_type=GenderType.MALE)
    h2 = Hostel(name="Hostel 2", code="H2", gender_type=GenderType.FEMALE)
    db_session.add_all([h1, h2])
    await db_session.flush()

    # Users
    admin = User(
        id=uuid4(),
        email="admin_scoping@test.com",
        full_name="Admin",
        hashed_password="pw",
        role=UserRole.ADMIN,
    )
    warden = User(
        id=uuid4(),
        email="warden_scoping@test.com",
        full_name="Warden",
        hashed_password="pw",
        role=UserRole.WARDEN,
    )
    unassigned_warden = User(
        id=uuid4(),
        email="unassigned_scoping@test.com",
        full_name="Unassigned Warden",
        hashed_password="pw",
        role=UserRole.WARDEN,
    )
    student = User(
        id=uuid4(),
        email="student_scoping@test.com",
        full_name="Student",
        hashed_password="pw",
        role=UserRole.STUDENT,
    )
    db_session.add_all([admin, warden, unassigned_warden, student])
    await db_session.flush()

    # Assign warden to h1
    assign = WardenAssignment(user_id=warden.id, hostel_id=h1.id)
    db_session.add(assign)
    await db_session.flush()

    # 1. Admin without hostel filter -> None (all)
    admin_scope_all = await service._resolve_hostel_scope(admin, None)
    assert admin_scope_all is None

    # 2. Admin with valid hostel -> [h1.id]
    admin_scope_h1 = await service._resolve_hostel_scope(admin, h1.id)
    assert admin_scope_h1 == [h1.id]

    # 3. Admin with non-existent hostel -> NotFoundError
    with pytest.raises(NotFoundError):
        await service._resolve_hostel_scope(admin, uuid4())

    # 4. Warden without hostel filter -> [h1.id]
    warden_scope_all = await service._resolve_hostel_scope(warden, None)
    assert warden_scope_all == [h1.id]

    # 5. Warden with assigned hostel -> [h1.id]
    warden_scope_h1 = await service._resolve_hostel_scope(warden, h1.id)
    assert warden_scope_h1 == [h1.id]

    # 6. Warden with unassigned hostel -> ForbiddenError
    with pytest.raises(ForbiddenError):
        await service._resolve_hostel_scope(warden, h2.id)

    # 7. Unassigned warden -> []
    unassigned_scope = await service._resolve_hostel_scope(unassigned_warden, None)
    assert unassigned_scope == []

    # 8. Student -> ForbiddenError
    with pytest.raises(ForbiddenError):
        await service._resolve_hostel_scope(student, None)


def test_generate_occupancy_csv() -> None:
    """Verify CSV formatting for occupancy report."""
    h_id = uuid4()
    b_id = uuid4()
    rows = [
        OccupancyReportRow(
            hostel_id=h_id,
            hostel_name="Alpha Hall",
            block_id=b_id,
            block_name="Block A",
            room_type="double",
            total_beds=20,
            occupied_beds=15,
            available_beds=5,
            occupancy_rate=75.0,
        )
    ]
    csv_str = ReportService.generate_occupancy_csv(rows)
    reader = list(csv.reader(io.StringIO(csv_str)))
    assert len(reader) == 2  # header + 1 row
    assert reader[0] == [
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
    assert reader[1][1] == "Alpha Hall"
    assert reader[1][4] == "double"
    assert reader[1][5] == "20"
    assert reader[1][6] == "15"
    assert reader[1][8] == "75.00"


def test_generate_revenue_csv() -> None:
    """Verify CSV formatting for revenue report."""
    rows = [
        RevenueReportRow(
            group_key="2026-11",
            total_revenue=Decimal("150000.00"),
            transaction_count=25,
            hostel_id=None,
            hostel_name=None,
            payment_method=None,
        )
    ]
    csv_str = ReportService.generate_revenue_csv(rows)
    reader = list(csv.reader(io.StringIO(csv_str)))
    assert len(reader) == 2
    assert reader[0] == [
        "Group Key",
        "Total Revenue",
        "Transaction Count",
        "Hostel ID",
        "Hostel Name",
        "Payment Method",
    ]
    assert reader[1][0] == "2026-11"
    assert reader[1][1] == "150000.00"
    assert reader[1][2] == "25"


def test_generate_defaulters_csv() -> None:
    """Verify CSV formatting for defaulters report."""
    s_id = uuid4()
    inv_id = uuid4()
    rows = [
        DefaulterReportRow(
            student_id=s_id,
            student_no="STU-001",
            student_name="John Doe",
            hostel_name="Alpha Hall",
            room_number="101",
            invoice_id=inv_id,
            amount=Decimal("10000.00"),
            paid_amount=Decimal("2000.00"),
            balance=Decimal("8000.00"),
            due_date=date(2026, 11, 1),
            days_overdue=21,
        )
    ]
    csv_str = ReportService.generate_defaulters_csv(rows)
    reader = list(csv.reader(io.StringIO(csv_str)))
    assert len(reader) == 2
    assert reader[0] == [
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
    assert reader[1][1] == "STU-001"
    assert reader[1][2] == "John Doe"
    assert reader[1][8] == "8000.00"
    assert reader[1][10] == "21"
