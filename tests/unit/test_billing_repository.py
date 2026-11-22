"""Unit tests for FeeStructureRepository, InvoiceRepository, and PaymentRepository."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.allocation import Allocation, AllocationStatus
from app.models.billing import (
    FeePeriod,
    FeeStructure,
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentMethod,
)
from app.models.hostel import Block, GenderType, Hostel
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.repositories.billing_repository import (
    FeeStructureRepository,
    InvoiceRepository,
    PaymentRepository,
)
from app.schemas.common import PaginationParams


@pytest.mark.asyncio
async def test_billing_repositories_queries_and_filters(
    db_session: AsyncSession,
) -> None:
    """Test repository methods for fee structures, invoices, and payments."""
    fee_repo = FeeStructureRepository(db_session)
    inv_repo = InvoiceRepository(db_session)
    pay_repo = PaymentRepository(db_session)

    # 1. Hostel hierarchy setup
    hostel = Hostel(
        name=f"Repo Hostel {uuid4().hex[:6]}",
        code=f"RH-{uuid4().hex[:4]}",
        gender_type=GenderType.MIXED,
    )
    db_session.add(hostel)
    await db_session.flush()

    block = Block(hostel_id=hostel.id, name="Block A", floor_count=1)
    db_session.add(block)
    await db_session.flush()

    room = Room(
        block_id=block.id,
        number="101",
        floor=1,
        room_type=RoomType.DOUBLE,
        capacity=2,
        monthly_rent=Decimal("2000.00"),
        status=RoomStatus.AVAILABLE,
    )
    db_session.add(room)
    await db_session.flush()

    bed = Bed(room_id=room.id, label="101-A")
    db_session.add(bed)
    await db_session.flush()

    user = User(
        email=f"repo_{uuid4().hex[:6]}@example.com",
        full_name="Repo Student",
        phone="+1234567890",
        hashed_password="pwd",
        role=UserRole.STUDENT,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    student = StudentProfile(
        user_id=user.id,
        student_no=f"STU-{uuid4().hex[:6]}",
        gender=GenderType.MALE,
        department="Science",
        year=1,
        guardian_name="Guardian",
        guardian_phone="+1234567890",
        emergency_contact="+1234567890",
    )
    db_session.add(student)
    await db_session.flush()

    allocation = Allocation(
        student_id=student.id,
        bed_id=bed.id,
        start_date=date(2026, 11, 1),
        status=AllocationStatus.ACTIVE,
    )
    db_session.add(allocation)
    await db_session.flush()

    # 2. Fee structure repo tests
    fs = FeeStructure(
        hostel_id=hostel.id,
        room_type=RoomType.DOUBLE,
        amount=Decimal("2500.00"),
        period=FeePeriod.MONTHLY,
    )
    created_fs = await fee_repo.create(fs)
    assert created_fs.id is not None

    found_fs = await fee_repo.get_by_hostel_room_period(
        hostel.id, RoomType.DOUBLE, FeePeriod.MONTHLY
    )
    assert found_fs is not None
    assert found_fs.id == created_fs.id

    by_id_fs = await fee_repo.get_by_id(created_fs.id)
    assert by_id_fs is not None
    assert by_id_fs.amount == Decimal("2500.00")

    list_fs = await fee_repo.list_by_hostel(hostel_id=hostel.id, is_active=True)
    assert len(list_fs) == 1

    # 3. Invoice repo tests
    inv = Invoice(
        student_id=student.id,
        allocation_id=allocation.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        amount=Decimal("2500.00"),
        paid_amount=Decimal("0.00"),
        due_date=date(2026, 11, 15),
        status=InvoiceStatus.UNPAID,
    )
    created_inv = await inv_repo.create(inv)
    assert created_inv.id is not None

    found_existing = await inv_repo.get_existing_for_allocation_period(
        allocation_id=allocation.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
    )
    assert found_existing is not None
    assert found_existing.id == created_inv.id

    inv_list, total = await inv_repo.list(
        params=PaginationParams(page=1, size=10),
        student_id=student.id,
        hostel_id=hostel.id,
        status=InvoiceStatus.UNPAID,
    )
    assert total == 1
    assert len(inv_list) == 1

    # 4. Payment repo tests
    payment = Payment(
        invoice_id=created_inv.id,
        amount=Decimal("1000.00"),
        method=PaymentMethod.ONLINE,
        reference="REF-REPO-001",
    )
    created_pay = await pay_repo.create(payment)
    assert created_pay.id is not None

    by_ref = await pay_repo.get_by_reference("REF-REPO-001")
    assert by_ref is not None
    assert by_ref.id == created_pay.id

    by_inv = await pay_repo.list_by_invoice(created_inv.id)
    assert len(by_inv) == 1

    pay_list, pay_total = await pay_repo.list(
        params=PaginationParams(page=1, size=10),
        warden_hostel_ids=[hostel.id],
    )
    assert pay_total == 1
    assert len(pay_list) == 1
