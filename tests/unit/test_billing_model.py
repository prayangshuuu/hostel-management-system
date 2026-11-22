"""Unit tests for billing, fee structure, invoice, and payment models."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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


@pytest.mark.asyncio
async def test_billing_models_creation_and_relationships(
    db_session: AsyncSession,
) -> None:
    """Test creating FeeStructure, Invoice, and Payment and verifying relationships."""
    # 1. Create Hostel
    hostel = Hostel(
        name="Finance Test Hostel",
        code=f"FTH-{uuid.uuid4().hex[:6]}",
        gender_type=GenderType.MIXED,
    )
    db_session.add(hostel)
    await db_session.flush()

    # 2. Create Block, Room, Bed
    block = Block(hostel_id=hostel.id, name="Block A", floor_count=2)
    db_session.add(block)
    await db_session.flush()

    room = Room(
        block_id=block.id,
        number="101",
        floor=1,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("500.00"),
        status=RoomStatus.AVAILABLE,
    )
    db_session.add(room)
    await db_session.flush()

    bed = Bed(room_id=room.id, label="A", is_occupied=True)
    db_session.add(bed)
    await db_session.flush()

    # 3. Create Student
    user = User(
        email=f"finance_student_{uuid.uuid4().hex[:6]}@example.com",
        full_name="Finance Student",
        hashed_password="hash",
        role=UserRole.STUDENT,
    )
    db_session.add(user)
    await db_session.flush()

    student = StudentProfile(
        user_id=user.id,
        student_no=f"STU-{uuid.uuid4().hex[:6]}",
        gender=GenderType.MALE,
        department="Finance",
        year=2,
        guardian_name="Guardian",
        guardian_phone="+1234567890",
        emergency_contact="+1234567890",
    )
    db_session.add(student)
    await db_session.flush()

    # 4. Create Allocation
    allocation = Allocation(
        student_id=student.id,
        bed_id=bed.id,
        start_date=date(2026, 1, 1),
        status=AllocationStatus.ACTIVE,
    )
    db_session.add(allocation)
    await db_session.flush()

    # 5. Create FeeStructure
    fee_struct = FeeStructure(
        hostel_id=hostel.id,
        room_type=RoomType.SINGLE,
        amount=Decimal("500.00"),
        period=FeePeriod.MONTHLY,
    )
    db_session.add(fee_struct)
    await db_session.flush()

    # 6. Create Invoice
    invoice = Invoice(
        student_id=student.id,
        allocation_id=allocation.id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        amount=Decimal("500.00"),
        paid_amount=Decimal("0.00"),
        due_date=date(2026, 1, 15),
        status=InvoiceStatus.UNPAID,
    )
    db_session.add(invoice)
    await db_session.flush()

    # 7. Create Payment
    payment = Payment(
        invoice_id=invoice.id,
        amount=Decimal("250.00"),
        method=PaymentMethod.ONLINE,
        reference=f"PAY-{uuid.uuid4().hex[:8]}",
        paid_at=datetime.now(UTC),
    )
    db_session.add(payment)
    await db_session.flush()

    # Verify relationships & queries
    res = await db_session.execute(
        select(Invoice)
        .options(
            selectinload(Invoice.student),
            selectinload(Invoice.allocation),
            selectinload(Invoice.payments),
        )
        .where(Invoice.id == invoice.id)
    )
    loaded_invoice = res.scalar_one()
    assert loaded_invoice.amount == Decimal("500.00")
    assert loaded_invoice.status == InvoiceStatus.UNPAID
    assert loaded_invoice.student.id == student.id
    assert loaded_invoice.allocation.id == allocation.id
    assert len(loaded_invoice.payments) == 1
    assert loaded_invoice.payments[0].amount == Decimal("250.00")


@pytest.mark.asyncio
async def test_duplicate_payment_reference_fails(
    db_session: AsyncSession,
) -> None:
    """Test unique constraint on payment reference when non-null."""
    hostel = Hostel(
        name="Payment Ref Hostel",
        code=f"PRH-{uuid.uuid4().hex[:6]}",
        gender_type=GenderType.MIXED,
    )
    db_session.add(hostel)
    await db_session.flush()

    block = Block(hostel_id=hostel.id, name="Block A", floor_count=1)
    db_session.add(block)
    await db_session.flush()

    room = Room(
        block_id=block.id,
        number="102",
        floor=1,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("400.00"),
        status=RoomStatus.AVAILABLE,
    )
    db_session.add(room)
    await db_session.flush()

    bed = Bed(room_id=room.id, label="A", is_occupied=True)
    db_session.add(bed)
    await db_session.flush()

    user = User(
        email=f"payment_user_{uuid.uuid4().hex[:6]}@example.com",
        full_name="Payment User",
        hashed_password="hash",
        role=UserRole.STUDENT,
    )
    db_session.add(user)
    await db_session.flush()

    student = StudentProfile(
        user_id=user.id,
        student_no=f"STU-{uuid.uuid4().hex[:6]}",
        gender=GenderType.FEMALE,
        department="Computer Science",
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
        start_date=date(2026, 2, 1),
        status=AllocationStatus.ACTIVE,
    )
    db_session.add(allocation)
    await db_session.flush()

    invoice = Invoice(
        student_id=student.id,
        allocation_id=allocation.id,
        period_start=date(2026, 2, 1),
        period_end=date(2026, 2, 28),
        amount=Decimal("400.00"),
        paid_amount=Decimal("0.00"),
        due_date=date(2026, 2, 15),
        status=InvoiceStatus.UNPAID,
    )
    db_session.add(invoice)
    await db_session.flush()

    ref = f"REF-DUP-{uuid.uuid4().hex[:8]}"
    pay1 = Payment(
        invoice_id=invoice.id,
        amount=Decimal("100.00"),
        method=PaymentMethod.CASH,
        reference=ref,
    )
    db_session.add(pay1)
    await db_session.flush()

    pay2 = Payment(
        invoice_id=invoice.id,
        amount=Decimal("100.00"),
        method=PaymentMethod.CASH,
        reference=ref,
    )
    db_session.add(pay2)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
