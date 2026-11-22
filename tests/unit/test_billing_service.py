"""Unit tests for BillingService business rules, exact decimal math, and scoping."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.models.allocation import Allocation, AllocationStatus
from app.models.billing import (
    FeePeriod,
    Invoice,
    InvoiceStatus,
    PaymentMethod,
)
from app.models.hostel import Block, GenderType, Hostel, WardenAssignment
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.schemas.billing import (
    FeeStructureCreate,
    FeeStructureUpdate,
    PaymentCreate,
)
from app.services.billing_service import BillingService


async def create_test_setup(
    session: AsyncSession,
) -> tuple[Hostel, Block, Room, Bed, StudentProfile, User, Allocation]:
    """Helper to set up core entities for billing unit tests."""
    hostel = Hostel(
        name=f"Billing Hostel {uuid.uuid4().hex[:6]}",
        code=f"BH-{uuid.uuid4().hex[:4]}",
        gender_type=GenderType.MIXED,
    )
    session.add(hostel)
    await session.flush()

    block = Block(hostel_id=hostel.id, name="Block A", floor_count=2)
    session.add(block)
    await session.flush()

    room = Room(
        block_id=block.id,
        number="101",
        floor=1,
        room_type=RoomType.DOUBLE,
        capacity=2,
        monthly_rent=Decimal("3000.00"),
        status=RoomStatus.AVAILABLE,
    )
    session.add(room)
    await session.flush()

    bed = Bed(room_id=room.id, label="101-A")
    session.add(bed)
    await session.flush()

    user = User(
        email=f"student_{uuid.uuid4().hex[:6]}@example.com",
        full_name="Billing Student",
        phone="+1999999999",
        hashed_password="hashed_pwd",
        role=UserRole.STUDENT,
        is_active=True,
    )
    session.add(user)
    await session.flush()

    student = StudentProfile(
        user_id=user.id,
        student_no=f"STU-{uuid.uuid4().hex[:6]}",
        gender=GenderType.MALE,
        department="Computer Science",
        year=2,
        guardian_name="Guardian",
        guardian_phone="+1888888888",
        emergency_contact="+1777777777",
    )
    session.add(student)
    await session.flush()

    allocation = Allocation(
        student_id=student.id,
        bed_id=bed.id,
        start_date=date(2026, 11, 1),
        status=AllocationStatus.ACTIVE,
    )
    session.add(allocation)
    await session.flush()

    return hostel, block, room, bed, student, user, allocation


@pytest.mark.asyncio
async def test_fee_structure_crud_and_uniqueness(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Test FeeStructure creation, duplicate conflict, update, and deletion."""
    hostel, _, _, _, _, _, _ = await create_test_setup(db_session)
    service = BillingService(db_session)

    # 1. Create fee structure
    create_dto = FeeStructureCreate(
        hostel_id=hostel.id,
        room_type=RoomType.DOUBLE,
        amount=Decimal("4500.00"),
        period=FeePeriod.MONTHLY,
    )
    fs = await service.create_fee_structure(create_dto)
    assert fs.id is not None
    assert fs.amount == Decimal("4500.00")
    assert fs.is_active is True

    # 2. Duplicate creation raises ConflictError
    with pytest.raises(ConflictError) as exc_info:
        await service.create_fee_structure(create_dto)
    assert exc_info.value.code == "FEE_STRUCTURE_ALREADY_EXISTS"

    # 3. Update fee structure
    updated = await service.update_fee_structure(
        fs.id, FeeStructureUpdate(amount=Decimal("5000.00"), is_active=False)
    )
    assert updated.amount == Decimal("5000.00")
    assert updated.is_active is False

    # 4. List fee structures
    items = await service.list_fee_structures(hostel_id=hostel.id)
    assert len(items) == 1
    assert items[0].id == fs.id

    # 5. Delete fee structure
    await service.delete_fee_structure(fs.id)
    with pytest.raises(NotFoundError):
        await service.get_fee_structure(fs.id)


@pytest.mark.asyncio
async def test_invoice_generation_full_month_and_idempotency(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Test invoice generation for a full month and verifying idempotency."""
    hostel, _, room, _, _, _, _ = await create_test_setup(db_session)
    service = BillingService(db_session)

    # Configure fee structure
    await service.create_fee_structure(
        FeeStructureCreate(
            hostel_id=hostel.id,
            room_type=room.room_type,
            amount=Decimal("3000.00"),
            period=FeePeriod.MONTHLY,
        )
    )

    period_start = date(2026, 11, 1)
    period_end = date(2026, 11, 30)
    due_date = date(2026, 11, 15)

    # First generation run
    res1 = await service.generate_invoices(
        hostel_id=hostel.id,
        period_start=period_start,
        period_end=period_end,
        due_date=due_date,
        current_user=admin_user,
    )
    assert res1.generated_count == 1
    assert res1.skipped_count == 0
    assert len(res1.invoices) == 1
    invoice = res1.invoices[0]
    assert invoice.amount == Decimal("3000.00")
    assert invoice.paid_amount == Decimal("0.00")
    assert invoice.balance == Decimal("3000.00")
    assert invoice.status == InvoiceStatus.UNPAID

    # Second generation run (Idempotent: skips existing invoice)
    res2 = await service.generate_invoices(
        hostel_id=hostel.id,
        period_start=period_start,
        period_end=period_end,
        due_date=due_date,
        current_user=admin_user,
    )
    assert res2.generated_count == 0
    assert res2.skipped_count == 1
    assert len(res2.invoices) == 0


@pytest.mark.asyncio
async def test_invoice_generation_proration_mid_month_start(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Test prorated invoice calculation for mid-month allocation start."""
    hostel, _, room, _bed, _student, _, alloc = await create_test_setup(db_session)
    # Start allocation on Nov 16 of a 30-day month (Nov 1 to Nov 30 -> 15 days out of 30)
    alloc.start_date = date(2026, 11, 16)
    await db_session.flush()

    service = BillingService(db_session)
    await service.create_fee_structure(
        FeeStructureCreate(
            hostel_id=hostel.id,
            room_type=room.room_type,
            amount=Decimal("3000.00"),
            period=FeePeriod.MONTHLY,
        )
    )

    res = await service.generate_invoices(
        hostel_id=hostel.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        due_date=date(2026, 11, 25),
        current_user=admin_user,
    )
    assert res.generated_count == 1
    # 15 days / 30 days * 3000.00 = 1500.00
    assert res.invoices[0].amount == Decimal("1500.00")


@pytest.mark.asyncio
async def test_invoice_generation_proration_mid_month_end(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Test prorated invoice calculation for mid-month allocation vacate/end."""
    hostel, _, room, _, _, _, alloc = await create_test_setup(db_session)
    # Allocation started Nov 1, ended Nov 10 (10 days out of 30)
    alloc.start_date = date(2026, 11, 1)
    alloc.end_date = date(2026, 11, 10)
    alloc.status = AllocationStatus.ENDED
    await db_session.flush()

    service = BillingService(db_session)
    await service.create_fee_structure(
        FeeStructureCreate(
            hostel_id=hostel.id,
            room_type=room.room_type,
            amount=Decimal("3000.00"),
            period=FeePeriod.MONTHLY,
        )
    )

    res = await service.generate_invoices(
        hostel_id=hostel.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        due_date=date(2026, 11, 20),
        current_user=admin_user,
    )
    assert res.generated_count == 1
    # 10 days / 30 days * 3000.00 = 1000.00
    assert res.invoices[0].amount == Decimal("1000.00")


@pytest.mark.asyncio
async def test_payment_recording_decimal_precision_three_partial_payments(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Test exact Decimal math with 3 partial payments summing exactly to total."""
    _hostel, _, _room, _, _, _student_user, alloc = await create_test_setup(db_session)
    service = BillingService(db_session)

    invoice = Invoice(
        student_id=alloc.student_id,
        allocation_id=alloc.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        amount=Decimal("1000.00"),
        paid_amount=Decimal("0.00"),
        due_date=date(2026, 11, 15),
        status=InvoiceStatus.UNPAID,
    )
    db_session.add(invoice)
    await db_session.flush()

    # Payment 1: 333.33 -> status PARTIAL
    p1 = await service.record_payment(
        invoice_id=invoice.id,
        data=PaymentCreate(
            amount=Decimal("333.33"),
            method=PaymentMethod.ONLINE,
            reference="TXN-001",
        ),
        current_user=admin_user,
    )
    assert p1.amount == Decimal("333.33")
    inv = await service.get_invoice(invoice.id, admin_user)
    assert inv.paid_amount == Decimal("333.33")
    assert inv.balance == Decimal("666.67")
    assert inv.status == InvoiceStatus.PARTIAL

    # Payment 2: 333.33 -> status PARTIAL
    p2 = await service.record_payment(
        invoice_id=invoice.id,
        data=PaymentCreate(
            amount=Decimal("333.33"),
            method=PaymentMethod.BANK,
            reference="TXN-002",
        ),
        current_user=admin_user,
    )
    assert p2.amount == Decimal("333.33")
    inv = await service.get_invoice(invoice.id, admin_user)
    assert inv.paid_amount == Decimal("666.66")
    assert inv.balance == Decimal("333.34")
    assert inv.status == InvoiceStatus.PARTIAL

    # Payment 3: 333.34 -> exactly equals 1000.00 -> status PAID
    p3 = await service.record_payment(
        invoice_id=invoice.id,
        data=PaymentCreate(
            amount=Decimal("333.34"),
            method=PaymentMethod.CARD,
            reference="TXN-003",
        ),
        current_user=admin_user,
    )
    assert p3.amount == Decimal("333.34")
    inv = await service.get_invoice(invoice.id, admin_user)
    assert inv.paid_amount == Decimal("1000.00")
    assert inv.balance == Decimal("0.00")
    assert inv.status == InvoiceStatus.PAID


@pytest.mark.asyncio
async def test_payment_overpayment_and_invalid_amounts_rejected(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Test overpayment, zero, and negative amounts are rejected with proper errors."""
    _hostel, _, _, _, _, _, alloc = await create_test_setup(db_session)
    service = BillingService(db_session)

    invoice = Invoice(
        student_id=alloc.student_id,
        allocation_id=alloc.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        amount=Decimal("500.00"),
        paid_amount=Decimal("0.00"),
        due_date=date(2026, 11, 15),
        status=InvoiceStatus.UNPAID,
    )
    db_session.add(invoice)
    await db_session.flush()

    # Overpayment rejected
    with pytest.raises(BusinessRuleError) as exc_overpay:
        await service.record_payment(
            invoice_id=invoice.id,
            data=PaymentCreate(
                amount=Decimal("500.01"),
                method=PaymentMethod.ONLINE,
            ),
            current_user=admin_user,
        )
    assert exc_overpay.value.code == "OVERPAYMENT_NOT_ALLOWED"
    assert exc_overpay.value.status_code == 400

    # Negative / zero rejected by schema validation
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PaymentCreate(
            amount=Decimal("0.00"),
            method=PaymentMethod.CASH,
        )

    # Also verify service layer guard via model_construct
    with pytest.raises(BusinessRuleError) as exc_zero:
        await service.record_payment(
            invoice_id=invoice.id,
            data=PaymentCreate.model_construct(
                amount=Decimal("0.00"),
                method=PaymentMethod.CASH,
            ),
            current_user=admin_user,
        )
    assert exc_zero.value.code == "INVALID_PAYMENT_AMOUNT"


@pytest.mark.asyncio
async def test_payment_reference_uniqueness(db_session: AsyncSession, admin_user: User) -> None:
    """Test duplicate payment reference raises ConflictError."""
    _hostel, _, _, _, _, _, alloc = await create_test_setup(db_session)
    service = BillingService(db_session)

    inv = Invoice(
        student_id=alloc.student_id,
        allocation_id=alloc.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        amount=Decimal("1000.00"),
        paid_amount=Decimal("0.00"),
        due_date=date(2026, 11, 15),
        status=InvoiceStatus.UNPAID,
    )
    db_session.add(inv)
    await db_session.flush()

    await service.record_payment(
        invoice_id=inv.id,
        data=PaymentCreate(
            amount=Decimal("100.00"),
            method=PaymentMethod.ONLINE,
            reference="REF-UNIQUE-001",
        ),
        current_user=admin_user,
    )

    # Same reference on second payment must fail
    with pytest.raises(ConflictError) as exc_ref:
        await service.record_payment(
            invoice_id=inv.id,
            data=PaymentCreate(
                amount=Decimal("100.00"),
                method=PaymentMethod.ONLINE,
                reference="REF-UNIQUE-001",
            ),
            current_user=admin_user,
        )
    assert exc_ref.value.code == "DUPLICATE_PAYMENT_REFERENCE"


@pytest.mark.asyncio
async def test_cannot_pay_void_or_fully_paid_invoice(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Test paying void or already paid invoice is blocked."""
    _hostel, _, _, _, _, _, alloc = await create_test_setup(db_session)
    service = BillingService(db_session)

    # 1. Void invoice
    inv_void = Invoice(
        student_id=alloc.student_id,
        allocation_id=alloc.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        amount=Decimal("500.00"),
        paid_amount=Decimal("0.00"),
        due_date=date(2026, 11, 15),
        status=InvoiceStatus.VOID,
    )
    db_session.add(inv_void)
    await db_session.flush()

    with pytest.raises(BusinessRuleError) as exc_void:
        await service.record_payment(
            invoice_id=inv_void.id,
            data=PaymentCreate(amount=Decimal("100.00"), method=PaymentMethod.CASH),
            current_user=admin_user,
        )
    assert exc_void.value.code == "INVOICE_VOID"

    # 2. Already fully paid invoice
    inv_paid = Invoice(
        student_id=alloc.student_id,
        allocation_id=alloc.id,
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
        amount=Decimal("500.00"),
        paid_amount=Decimal("500.00"),
        due_date=date(2026, 10, 15),
        status=InvoiceStatus.PAID,
    )
    db_session.add(inv_paid)
    await db_session.flush()

    with pytest.raises(BusinessRuleError) as exc_paid:
        await service.record_payment(
            invoice_id=inv_paid.id,
            data=PaymentCreate(amount=Decimal("50.00"), method=PaymentMethod.CASH),
            current_user=admin_user,
        )
    assert exc_paid.value.code == "INVOICE_ALREADY_PAID"


@pytest.mark.asyncio
async def test_overdue_invoice_marking(db_session: AsyncSession, admin_user: User) -> None:
    """Test mark_overdue transitions past-due invoices while keeping paid/void untouched."""
    _hostel, _, _, _, _, _, alloc = await create_test_setup(db_session)
    service = BillingService(db_session)

    today = date(2026, 11, 20)

    # 1. Unpaid past due -> should become OVERDUE
    inv_unpaid_overdue = Invoice(
        student_id=alloc.student_id,
        allocation_id=alloc.id,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        amount=Decimal("1000.00"),
        paid_amount=Decimal("0.00"),
        due_date=date(2026, 7, 10),
        status=InvoiceStatus.UNPAID,
    )
    # 2. Partial past due -> should become OVERDUE
    inv_partial_overdue = Invoice(
        student_id=alloc.student_id,
        allocation_id=alloc.id,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        amount=Decimal("1000.00"),
        paid_amount=Decimal("400.00"),
        due_date=date(2026, 8, 10),
        status=InvoiceStatus.PARTIAL,
    )
    # 3. Paid past due -> should REMAIN PAID
    inv_paid_past_due = Invoice(
        student_id=alloc.student_id,
        allocation_id=alloc.id,
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        amount=Decimal("1000.00"),
        paid_amount=Decimal("1000.00"),
        due_date=date(2026, 9, 10),
        status=InvoiceStatus.PAID,
    )
    # 4. Unpaid not yet due -> should REMAIN UNPAID
    inv_unpaid_future = Invoice(
        student_id=alloc.student_id,
        allocation_id=alloc.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        amount=Decimal("1000.00"),
        paid_amount=Decimal("0.00"),
        due_date=date(2026, 11, 25),
        status=InvoiceStatus.UNPAID,
    )
    # 5. Void past due -> should REMAIN VOID
    inv_void_past_due = Invoice(
        student_id=alloc.student_id,
        allocation_id=alloc.id,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        amount=Decimal("1000.00"),
        paid_amount=Decimal("0.00"),
        due_date=date(2026, 10, 10),
        status=InvoiceStatus.VOID,
    )

    db_session.add_all(
        [
            inv_unpaid_overdue,
            inv_partial_overdue,
            inv_paid_past_due,
            inv_unpaid_future,
            inv_void_past_due,
        ]
    )
    await db_session.flush()

    count = await service.mark_overdue(today=today)
    assert count == 2

    # Verify statuses
    i1 = await service.get_invoice(inv_unpaid_overdue.id, admin_user)
    assert i1.status == InvoiceStatus.OVERDUE

    i2 = await service.get_invoice(inv_partial_overdue.id, admin_user)
    assert i2.status == InvoiceStatus.OVERDUE

    i3 = await service.get_invoice(inv_paid_past_due.id, admin_user)
    assert i3.status == InvoiceStatus.PAID

    i4 = await service.get_invoice(inv_unpaid_future.id, admin_user)
    assert i4.status == InvoiceStatus.UNPAID

    i5 = await service.get_invoice(inv_void_past_due.id, admin_user)
    assert i5.status == InvoiceStatus.VOID


@pytest.mark.asyncio
async def test_student_balance_aggregation(db_session: AsyncSession, admin_user: User) -> None:
    """Test student balance computation correctly calculates billed, paid, and overdue."""
    _hostel, _, _, _, student, _, alloc = await create_test_setup(db_session)
    service = BillingService(db_session)

    # Invoice 1: Paid 1000.00
    inv1 = Invoice(
        student_id=student.id,
        allocation_id=alloc.id,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        amount=Decimal("1000.00"),
        paid_amount=Decimal("1000.00"),
        due_date=date(2026, 9, 15),
        status=InvoiceStatus.PAID,
    )
    # Invoice 2: Overdue 1000.00, paid 300.00 -> remaining overdue 700.00
    inv2 = Invoice(
        student_id=student.id,
        allocation_id=alloc.id,
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
        amount=Decimal("1000.00"),
        paid_amount=Decimal("300.00"),
        due_date=date.today() - timedelta(days=5),
        status=InvoiceStatus.OVERDUE,
    )
    # Invoice 3: Current unpaid 1000.00, due in 10 days
    inv3 = Invoice(
        student_id=student.id,
        allocation_id=alloc.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        amount=Decimal("1000.00"),
        paid_amount=Decimal("0.00"),
        due_date=date.today() + timedelta(days=10),
        status=InvoiceStatus.UNPAID,
    )
    # Invoice 4: Void invoice (must be ignored)
    inv4 = Invoice(
        student_id=student.id,
        allocation_id=alloc.id,
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        amount=Decimal("500.00"),
        paid_amount=Decimal("0.00"),
        due_date=date(2026, 8, 15),
        status=InvoiceStatus.VOID,
    )
    db_session.add_all([inv1, inv2, inv3, inv4])
    await db_session.flush()

    balance = await service.get_student_balance(student.id)
    assert balance.total_billed == Decimal("3000.00")
    assert balance.total_paid == Decimal("1300.00")
    assert balance.current_balance == Decimal("1700.00")
    assert balance.overdue_amount == Decimal("700.00")
    assert balance.unpaid_invoices_count == 2


@pytest.mark.asyncio
async def test_delete_invoice_guarded_against_recorded_payments(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Test invoice delete is blocked if payments exist, but allowed before payments."""
    _hostel, _, _, _, _, _, alloc = await create_test_setup(db_session)
    service = BillingService(db_session)

    inv = Invoice(
        student_id=alloc.student_id,
        allocation_id=alloc.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        amount=Decimal("1000.00"),
        paid_amount=Decimal("0.00"),
        due_date=date(2026, 11, 15),
        status=InvoiceStatus.UNPAID,
    )
    db_session.add(inv)
    await db_session.flush()

    # Record partial payment
    await service.record_payment(
        invoice_id=inv.id,
        data=PaymentCreate(amount=Decimal("200.00"), method=PaymentMethod.CASH),
        current_user=admin_user,
    )

    # Delete must fail
    with pytest.raises(ConflictError) as exc_del:
        await service.delete_invoice(inv.id)
    assert exc_del.value.code == "INVOICE_HAS_PAYMENTS"

    # Voiding invoice works
    voided = await service.void_invoice(inv.id)
    assert voided.status == InvoiceStatus.VOID


@pytest.mark.asyncio
async def test_invoice_generation_proration_mid_month_start_and_end(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Test proration when allocation starts and ends mid-month in the same billing cycle."""
    hostel, _, room, _, _, _, alloc = await create_test_setup(db_session)
    # Start Nov 5, End Nov 14 -> 10 days out of 30 days
    alloc.start_date = date(2026, 11, 5)
    alloc.end_date = date(2026, 11, 14)
    alloc.status = AllocationStatus.ENDED
    await db_session.flush()

    service = BillingService(db_session)
    await service.create_fee_structure(
        FeeStructureCreate(
            hostel_id=hostel.id,
            room_type=room.room_type,
            amount=Decimal("3000.00"),
            period=FeePeriod.MONTHLY,
        )
    )

    res = await service.generate_invoices(
        hostel_id=hostel.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        due_date=date(2026, 11, 20),
        current_user=admin_user,
    )
    assert res.generated_count == 1
    # 10 days / 30 days * 3000.00 = 1000.00
    assert res.invoices[0].amount == Decimal("1000.00")


@pytest.mark.asyncio
async def test_billing_scoping_student_authorization(
    db_session: AsyncSession,
) -> None:
    """Test student can only view and pay own invoice, rejecting another student's invoice."""
    # Setup student 1
    _h1, _, _, _, _s1, user1, alloc1 = await create_test_setup(db_session)
    # Setup student 2
    _h2, _, _, _, _s2, _user2, alloc2 = await create_test_setup(db_session)

    service = BillingService(db_session)

    inv1 = Invoice(
        student_id=alloc1.student_id,
        allocation_id=alloc1.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        amount=Decimal("1500.00"),
        paid_amount=Decimal("0.00"),
        due_date=date(2026, 11, 15),
        status=InvoiceStatus.UNPAID,
    )
    inv2 = Invoice(
        student_id=alloc2.student_id,
        allocation_id=alloc2.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        amount=Decimal("2000.00"),
        paid_amount=Decimal("0.00"),
        due_date=date(2026, 11, 15),
        status=InvoiceStatus.UNPAID,
    )
    db_session.add_all([inv1, inv2])
    await db_session.flush()

    # Student 1 viewing own invoice succeeds
    fetched = await service.get_invoice(inv1.id, user1)
    assert fetched.id == inv1.id

    # Student 1 viewing Student 2's invoice raises ForbiddenError
    with pytest.raises(ForbiddenError):
        await service.get_invoice(inv2.id, user1)

    # Student 1 paying own invoice succeeds
    p1 = await service.record_payment(
        invoice_id=inv1.id,
        data=PaymentCreate(amount=Decimal("500.00"), method=PaymentMethod.ONLINE),
        current_user=user1,
    )
    assert p1.amount == Decimal("500.00")

    # Student 1 paying Student 2's invoice raises ForbiddenError
    with pytest.raises(ForbiddenError):
        await service.record_payment(
            invoice_id=inv2.id,
            data=PaymentCreate(amount=Decimal("500.00"), method=PaymentMethod.ONLINE),
            current_user=user1,
        )


@pytest.mark.asyncio
async def test_billing_scoping_warden_authorization(
    db_session: AsyncSession,
) -> None:
    """Test warden can only view/pay invoices and balances for assigned hostels."""
    from app.schemas.common import PaginationParams

    # Hostel 1 & Warden assigned to Hostel 1
    h1, _, _, _, _, _, alloc1 = await create_test_setup(db_session)
    # Hostel 2 & unassigned to warden
    h2, _, _, _, student2, _, alloc2 = await create_test_setup(db_session)

    warden = User(
        email=f"warden_{uuid.uuid4().hex[:6]}@example.com",
        full_name="Assigned Warden",
        phone="+1555555555",
        hashed_password="hash",
        role=UserRole.WARDEN,
        is_active=True,
    )
    db_session.add(warden)
    await db_session.flush()

    # Assign warden to Hostel 1 only
    assignment = WardenAssignment(user_id=warden.id, hostel_id=h1.id)
    db_session.add(assignment)
    await db_session.flush()

    service = BillingService(db_session)

    inv1 = Invoice(
        student_id=alloc1.student_id,
        allocation_id=alloc1.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        amount=Decimal("1500.00"),
        paid_amount=Decimal("0.00"),
        due_date=date(2026, 11, 15),
        status=InvoiceStatus.UNPAID,
    )
    inv2 = Invoice(
        student_id=alloc2.student_id,
        allocation_id=alloc2.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        amount=Decimal("2000.00"),
        paid_amount=Decimal("0.00"),
        due_date=date(2026, 11, 15),
        status=InvoiceStatus.UNPAID,
    )
    db_session.add_all([inv1, inv2])
    await db_session.flush()

    # 1. Warden viewing assigned hostel invoice -> OK
    fetched = await service.get_invoice(inv1.id, warden)
    assert fetched.id == inv1.id

    # 2. Warden viewing unassigned hostel invoice -> ForbiddenError
    with pytest.raises(ForbiddenError):
        await service.get_invoice(inv2.id, warden)

    # 3. Warden paying unassigned hostel invoice -> ForbiddenError
    with pytest.raises(ForbiddenError):
        await service.record_payment(
            invoice_id=inv2.id,
            data=PaymentCreate(amount=Decimal("100.00"), method=PaymentMethod.CASH),
            current_user=warden,
        )

    # 4. Warden listing invoices for unassigned hostel -> ForbiddenError
    with pytest.raises(ForbiddenError):
        await service.list_invoices(
            params=PaginationParams(page=1, size=10),
            current_user=warden,
            hostel_id=h2.id,
        )

    # 5. Warden accessing student balance for student in unassigned hostel -> ForbiddenError
    with pytest.raises(ForbiddenError):
        await service.get_student_balance_scoped(student2.id, warden)


@pytest.mark.asyncio
async def test_student_self_service_service_layer(
    db_session: AsyncSession,
) -> None:
    """Test get_my_invoices and get_my_balance on BillingService."""
    _h, _, _, _, student, student_user, alloc = await create_test_setup(db_session)
    service = BillingService(db_session)

    inv = Invoice(
        student_id=student.id,
        allocation_id=alloc.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        amount=Decimal("1200.00"),
        paid_amount=Decimal("200.00"),
        due_date=date(2026, 11, 15),
        status=InvoiceStatus.PARTIAL,
    )
    db_session.add(inv)
    await db_session.flush()

    my_invoices = await service.get_my_invoices(student_user)
    assert len(my_invoices) == 1
    assert my_invoices[0].id == inv.id

    my_balance = await service.get_my_balance(student_user)
    assert my_balance.total_billed == Decimal("1200.00")
    assert my_balance.total_paid == Decimal("200.00")
    assert my_balance.current_balance == Decimal("1000.00")
