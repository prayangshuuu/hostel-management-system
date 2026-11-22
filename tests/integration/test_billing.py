"""Integration tests for fee structures, invoice generation, payments, and balances."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.allocation import Allocation, AllocationStatus
from app.models.billing import (
    FeePeriod,
    FeeStructure,
    Invoice,
    InvoiceStatus,
)
from app.models.hostel import Block, GenderType, Hostel, WardenAssignment
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole


async def setup_hostel_hierarchy(
    session: AsyncSession,
) -> tuple[Hostel, Block, Room, Bed]:
    """Helper to create a full hostel hierarchy."""
    hostel = Hostel(
        name=f"Hostel {uuid4().hex[:6]}",
        code=f"H-{uuid4().hex[:4]}",
        gender_type=GenderType.MIXED,
    )
    session.add(hostel)
    await session.flush()

    block = Block(hostel_id=hostel.id, name="Block A", floor_count=3)
    session.add(block)
    await session.flush()

    room = Room(
        block_id=block.id,
        number="201",
        floor=2,
        room_type=RoomType.DOUBLE,
        capacity=2,
        monthly_rent=Decimal("4000.00"),
        status=RoomStatus.AVAILABLE,
    )
    session.add(room)
    await session.flush()

    bed = Bed(room_id=room.id, label="201-A")
    session.add(bed)
    await session.flush()

    return hostel, block, room, bed


async def create_student_with_allocation(
    session: AsyncSession,
    user: User,
    bed: Bed,
    start_date: date = date(2026, 11, 1),
) -> tuple[StudentProfile, Allocation]:
    """Helper to create a student profile and allocate them to a bed."""
    student = StudentProfile(
        user_id=user.id,
        student_no=f"STU-{uuid4().hex[:6]}",
        gender=GenderType.MALE,
        department="Engineering",
        year=1,
        guardian_name="Parent",
        guardian_phone="+1234567890",
        emergency_contact="+1098765432",
    )
    session.add(student)
    await session.flush()

    allocation = Allocation(
        student_id=student.id,
        bed_id=bed.id,
        start_date=start_date,
        status=AllocationStatus.ACTIVE,
    )
    session.add(allocation)
    await session.flush()

    return student, allocation


@pytest.mark.asyncio
async def test_fee_structure_endpoints(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_headers: dict[str, str],
    student_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Test full CRUD on fee structures endpoint with role checks and validation."""
    hostel, _, _, _ = await setup_hostel_hierarchy(db_session)
    await db_session.commit()

    # 1. Non-admin forbidden from creating fee structures
    resp_forbidden = await client.post(
        "/api/v1/fee-structures",
        json={
            "hostel_id": str(hostel.id),
            "room_type": "double",
            "amount": "3500.00",
            "period": "monthly",
        },
        headers=student_headers,
    )
    assert resp_forbidden.status_code == 403

    # 2. Admin creates fee structure
    resp_create = await client.post(
        "/api/v1/fee-structures",
        json={
            "hostel_id": str(hostel.id),
            "room_type": "double",
            "amount": "3500.00",
            "period": "monthly",
        },
        headers=admin_headers,
    )
    assert resp_create.status_code == 201
    fs_data = resp_create.json()
    fs_id = fs_data["id"]
    assert fs_data["amount"] == "3500.00"
    assert fs_data["period"] == "monthly"
    assert fs_data["is_active"] is True

    # 3. Duplicate fee structure returns 409 Conflict
    resp_dup = await client.post(
        "/api/v1/fee-structures",
        json={
            "hostel_id": str(hostel.id),
            "room_type": "double",
            "amount": "4000.00",
            "period": "monthly",
        },
        headers=admin_headers,
    )
    assert resp_dup.status_code == 409
    assert resp_dup.json()["error"]["code"] == "FEE_STRUCTURE_ALREADY_EXISTS"

    # 4. List fee structures (authenticated)
    resp_list = await client.get(
        f"/api/v1/fee-structures?hostel_id={hostel.id}",
        headers=warden_headers,
    )
    assert resp_list.status_code == 200
    items = resp_list.json()
    assert len(items) >= 1
    assert items[0]["id"] == fs_id

    # 5. Get fee structure by ID
    resp_get = await client.get(
        f"/api/v1/fee-structures/{fs_id}",
        headers=student_headers,
    )
    assert resp_get.status_code == 200
    assert resp_get.json()["id"] == fs_id

    # 6. Patch fee structure (Admin only)
    resp_patch = await client.patch(
        f"/api/v1/fee-structures/{fs_id}",
        json={"amount": "3800.00", "is_active": False},
        headers=admin_headers,
    )
    assert resp_patch.status_code == 200
    assert resp_patch.json()["amount"] == "3800.00"
    assert resp_patch.json()["is_active"] is False

    # 7. Delete fee structure (Admin only)
    resp_del = await client.delete(
        f"/api/v1/fee-structures/{fs_id}",
        headers=admin_headers,
    )
    assert resp_del.status_code == 204

    # 8. Verify deleted
    resp_after = await client.get(
        f"/api/v1/fee-structures/{fs_id}",
        headers=admin_headers,
    )
    assert resp_after.status_code == 404


@pytest.mark.asyncio
async def test_invoice_generation_and_idempotency_api(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_headers: dict[str, str],
    warden_user: User,
    student_user: User,
    db_session: AsyncSession,
) -> None:
    """Test batch invoice generation via API, proration, idempotency, and warden scoping."""
    hostel, _, room, bed = await setup_hostel_hierarchy(db_session)
    _student, _allocation = await create_student_with_allocation(
        db_session, student_user, bed, start_date=date(2026, 11, 1)
    )

    # Assign warden to hostel
    assignment = WardenAssignment(user_id=warden_user.id, hostel_id=hostel.id)
    db_session.add(assignment)

    # Fee structure
    fs = FeeStructure(
        hostel_id=hostel.id,
        room_type=room.room_type,
        amount=Decimal("3000.00"),
        period=FeePeriod.MONTHLY,
    )
    db_session.add(fs)
    await db_session.commit()

    # 1. Assigned Warden generates invoices
    gen_payload = {
        "hostel_id": str(hostel.id),
        "period_start": "2026-11-01",
        "period_end": "2026-11-30",
        "due_date": "2026-11-15",
    }
    resp_gen = await client.post(
        "/api/v1/invoices/generate",
        json=gen_payload,
        headers=warden_headers,
    )
    assert resp_gen.status_code == 200, resp_gen.text
    gen_data = resp_gen.json()
    assert gen_data["generated_count"] == 1
    assert gen_data["skipped_count"] == 0
    invoices = gen_data["invoices"]
    assert len(invoices) == 1
    assert invoices[0]["amount"] == "3000.00"
    assert invoices[0]["balance"] == "3000.00"
    assert invoices[0]["status"] == "unpaid"
    invoice_id = invoices[0]["id"]

    # 2. Re-running generation is IDEMPOTENT (skipped_count=1, generated_count=0)
    resp_gen2 = await client.post(
        "/api/v1/invoices/generate",
        json=gen_payload,
        headers=admin_headers,
    )
    assert resp_gen2.status_code == 200
    gen_data2 = resp_gen2.json()
    assert gen_data2["generated_count"] == 0
    assert gen_data2["skipped_count"] == 1
    assert len(gen_data2["invoices"]) == 0

    # 3. List invoices endpoint
    resp_list = await client.get(
        f"/api/v1/invoices?hostel_id={hostel.id}&status=unpaid",
        headers=admin_headers,
    )
    assert resp_list.status_code == 200
    items = resp_list.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == invoice_id


@pytest.mark.asyncio
async def test_payment_recording_lifecycle_api(
    client: AsyncClient,
    admin_headers: dict[str, str],
    student_headers: dict[str, str],
    student_user: User,
    db_session: AsyncSession,
) -> None:
    """Test payment recording, status updates, overpayment rejection, and ledger retrieval."""
    _hostel, _, _room, bed = await setup_hostel_hierarchy(db_session)
    student, allocation = await create_student_with_allocation(db_session, student_user, bed)

    invoice = Invoice(
        student_id=student.id,
        allocation_id=allocation.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        amount=Decimal("2000.00"),
        paid_amount=Decimal("0.00"),
        due_date=date(2026, 11, 15),
        status=InvoiceStatus.UNPAID,
    )
    db_session.add(invoice)
    await db_session.commit()

    # 1. Overpayment rejected (status 400)
    resp_overpay = await client.post(
        f"/api/v1/invoices/{invoice.id}/payments",
        json={"amount": "2000.01", "method": "online"},
        headers=student_headers,
    )
    assert resp_overpay.status_code == 400
    assert resp_overpay.json()["error"]["code"] == "OVERPAYMENT_NOT_ALLOWED"

    # Zero and negative amounts rejected by schema validation (status 422)
    resp_zero = await client.post(
        f"/api/v1/invoices/{invoice.id}/payments",
        json={"amount": "0.00", "method": "online"},
        headers=student_headers,
    )
    assert resp_zero.status_code == 422

    resp_neg = await client.post(
        f"/api/v1/invoices/{invoice.id}/payments",
        json={"amount": "-50.00", "method": "online"},
        headers=student_headers,
    )
    assert resp_neg.status_code == 422

    # 2. Student pays 800.00 -> partial status
    resp_pay1 = await client.post(
        f"/api/v1/invoices/{invoice.id}/payments",
        json={
            "amount": "800.00",
            "method": "online",
            "reference": "TXN-STUDENT-001",
        },
        headers=student_headers,
    )
    assert resp_pay1.status_code == 201
    pay1_data = resp_pay1.json()
    assert pay1_data["amount"] == "800.00"
    assert pay1_data["reference"] == "TXN-STUDENT-001"

    # Verify invoice detail shows partial status and payment in ledger
    resp_detail = await client.get(
        f"/api/v1/invoices/{invoice.id}",
        headers=student_headers,
    )
    assert resp_detail.status_code == 200
    inv_data = resp_detail.json()
    assert inv_data["status"] == "partial"
    assert inv_data["paid_amount"] == "800.00"
    assert inv_data["balance"] == "1200.00"
    assert len(inv_data["payments"]) == 1

    # 3. Duplicate payment reference returns 409 Conflict
    resp_dup_ref = await client.post(
        f"/api/v1/invoices/{invoice.id}/payments",
        json={
            "amount": "100.00",
            "method": "online",
            "reference": "TXN-STUDENT-001",
        },
        headers=student_headers,
    )
    assert resp_dup_ref.status_code == 409
    assert resp_dup_ref.json()["error"]["code"] == "DUPLICATE_PAYMENT_REFERENCE"

    # 4. Final payment of remaining 1200.00 -> status paid
    resp_pay2 = await client.post(
        f"/api/v1/invoices/{invoice.id}/payments",
        json={
            "amount": "1200.00",
            "method": "card",
            "reference": "TXN-STUDENT-002",
        },
        headers=student_headers,
    )
    assert resp_pay2.status_code == 201

    # Verify invoice is fully paid
    resp_detail2 = await client.get(
        f"/api/v1/invoices/{invoice.id}",
        headers=student_headers,
    )
    assert resp_detail2.status_code == 200
    assert resp_detail2.json()["status"] == "paid"
    assert resp_detail2.json()["balance"] == "0.00"
    assert len(resp_detail2.json()["payments"]) == 2

    # 5. Cannot pay an already fully paid invoice
    resp_pay_after = await client.post(
        f"/api/v1/invoices/{invoice.id}/payments",
        json={"amount": "10.00", "method": "cash"},
        headers=admin_headers,
    )
    assert resp_pay_after.status_code == 400
    assert resp_pay_after.json()["error"]["code"] == "INVOICE_ALREADY_PAID"

    # 6. Cannot delete invoice with recorded payments (409 Conflict)
    resp_del_inv = await client.delete(
        f"/api/v1/invoices/{invoice.id}",
        headers=admin_headers,
    )
    assert resp_del_inv.status_code == 409
    assert resp_del_inv.json()["error"]["code"] == "INVOICE_HAS_PAYMENTS"


@pytest.mark.asyncio
async def test_student_self_service_and_balance_endpoints(
    client: AsyncClient,
    admin_headers: dict[str, str],
    student_headers: dict[str, str],
    student_user: User,
    db_session: AsyncSession,
) -> None:
    """Test student self-service and balance endpoints."""
    _hostel, _, _, bed = await setup_hostel_hierarchy(db_session)
    student, allocation = await create_student_with_allocation(db_session, student_user, bed)

    # Add unpaid invoice
    invoice = Invoice(
        student_id=student.id,
        allocation_id=allocation.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        amount=Decimal("1500.00"),
        paid_amount=Decimal("0.00"),
        due_date=date.today() + timedelta(days=7),
        status=InvoiceStatus.UNPAID,
    )
    db_session.add(invoice)
    await db_session.commit()

    # 1. Student views own invoices
    resp_my_invoices = await client.get(
        "/api/v1/students/me/invoices",
        headers=student_headers,
    )
    assert resp_my_invoices.status_code == 200
    invoices = resp_my_invoices.json()
    assert len(invoices) == 1
    assert invoices[0]["id"] == str(invoice.id)
    assert invoices[0]["amount"] == "1500.00"

    # 2. Student views own balance
    resp_my_balance = await client.get(
        "/api/v1/students/me/balance",
        headers=student_headers,
    )
    assert resp_my_balance.status_code == 200
    bal = resp_my_balance.json()
    assert bal["student_id"] == str(student.id)
    assert bal["total_billed"] == "1500.00"
    assert bal["total_paid"] == "0.00"
    assert bal["current_balance"] == "1500.00"
    assert bal["unpaid_invoices_count"] == 1

    # 3. Admin views student balance via /students/{id}/balance
    resp_admin_bal = await client.get(
        f"/api/v1/students/{student.id}/balance",
        headers=admin_headers,
    )
    assert resp_admin_bal.status_code == 200
    assert resp_admin_bal.json()["current_balance"] == "1500.00"


@pytest.mark.asyncio
async def test_overdue_marking_and_void_endpoints(
    client: AsyncClient,
    admin_headers: dict[str, str],
    student_headers: dict[str, str],
    student_user: User,
    db_session: AsyncSession,
) -> None:
    """Test mark-overdue endpoint and invoice void endpoint."""
    _hostel, _, _, bed = await setup_hostel_hierarchy(db_session)
    student, allocation = await create_student_with_allocation(db_session, student_user, bed)

    # Invoices: 1 past due unpaid, 1 past due partial, 1 past due paid,
    # 1 past due void, 1 future unpaid
    past_due_inv = Invoice(
        student_id=student.id,
        allocation_id=allocation.id,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        amount=Decimal("1000.00"),
        paid_amount=Decimal("0.00"),
        due_date=date.today() - timedelta(days=2),
        status=InvoiceStatus.UNPAID,
    )
    past_due_partial = Invoice(
        student_id=student.id,
        allocation_id=allocation.id,
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
        amount=Decimal("1000.00"),
        paid_amount=Decimal("300.00"),
        due_date=date.today() - timedelta(days=5),
        status=InvoiceStatus.PARTIAL,
    )
    past_due_paid = Invoice(
        student_id=student.id,
        allocation_id=allocation.id,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        amount=Decimal("1000.00"),
        paid_amount=Decimal("1000.00"),
        due_date=date.today() - timedelta(days=10),
        status=InvoiceStatus.PAID,
    )
    past_due_void = Invoice(
        student_id=student.id,
        allocation_id=allocation.id,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        amount=Decimal("1000.00"),
        paid_amount=Decimal("0.00"),
        due_date=date.today() - timedelta(days=20),
        status=InvoiceStatus.VOID,
    )
    future_inv = Invoice(
        student_id=student.id,
        allocation_id=allocation.id,
        period_start=date(2026, 12, 1),
        period_end=date(2026, 12, 31),
        amount=Decimal("1000.00"),
        paid_amount=Decimal("0.00"),
        due_date=date.today() + timedelta(days=15),
        status=InvoiceStatus.UNPAID,
    )
    db_session.add_all([past_due_inv, past_due_partial, past_due_paid, past_due_void, future_inv])
    await db_session.commit()

    # 1. Non-admin cannot trigger mark-overdue
    resp_forbid = await client.post(
        "/api/v1/invoices/mark-overdue",
        headers=student_headers,
    )
    assert resp_forbid.status_code == 403

    # 2. Admin triggers mark-overdue
    resp_mark = await client.post(
        "/api/v1/invoices/mark-overdue",
        headers=admin_headers,
    )
    assert resp_mark.status_code == 200
    assert resp_mark.json()["updated_count"] >= 2

    # Verify past_due_inv became overdue, past_due_partial became overdue
    resp_check1 = await client.get(
        f"/api/v1/invoices/{past_due_inv.id}",
        headers=admin_headers,
    )
    assert resp_check1.json()["status"] == "overdue"

    resp_check2 = await client.get(
        f"/api/v1/invoices/{past_due_partial.id}",
        headers=admin_headers,
    )
    assert resp_check2.json()["status"] == "overdue"

    # Verify paid remains paid, void remains void, future remains unpaid
    resp_check3 = await client.get(
        f"/api/v1/invoices/{past_due_paid.id}",
        headers=admin_headers,
    )
    assert resp_check3.json()["status"] == "paid"

    resp_check4 = await client.get(
        f"/api/v1/invoices/{past_due_void.id}",
        headers=admin_headers,
    )
    assert resp_check4.json()["status"] == "void"

    resp_future_check = await client.get(
        f"/api/v1/invoices/{future_inv.id}",
        headers=admin_headers,
    )
    assert resp_future_check.json()["status"] == "unpaid"

    # 3. Admin voids future invoice
    resp_void = await client.post(
        f"/api/v1/invoices/{future_inv.id}/void",
        headers=admin_headers,
    )
    assert resp_void.status_code == 200
    assert resp_void.json()["status"] == "void"


@pytest.mark.asyncio
async def test_payment_three_partial_payments_decimal_precision_api(
    client: AsyncClient,
    admin_headers: dict[str, str],
    student_headers: dict[str, str],
    student_user: User,
    db_session: AsyncSession,
) -> None:
    """Test 3 partial payments summing exactly to total via REST API."""
    _hostel, _, _room, bed = await setup_hostel_hierarchy(db_session)
    student, allocation = await create_student_with_allocation(db_session, student_user, bed)

    invoice = Invoice(
        student_id=student.id,
        allocation_id=allocation.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        amount=Decimal("1000.00"),
        paid_amount=Decimal("0.00"),
        due_date=date(2026, 11, 15),
        status=InvoiceStatus.UNPAID,
    )
    db_session.add(invoice)
    await db_session.commit()

    # Payment 1: 333.33 -> status partial, balance 666.67
    r1 = await client.post(
        f"/api/v1/invoices/{invoice.id}/payments",
        json={"amount": "333.33", "method": "online", "reference": "PART-001"},
        headers=student_headers,
    )
    assert r1.status_code == 201

    inv1 = (await client.get(f"/api/v1/invoices/{invoice.id}", headers=student_headers)).json()
    assert inv1["paid_amount"] == "333.33"
    assert inv1["balance"] == "666.67"
    assert inv1["status"] == "partial"

    # Payment 2: 333.33 -> status partial, balance 333.34
    r2 = await client.post(
        f"/api/v1/invoices/{invoice.id}/payments",
        json={"amount": "333.33", "method": "bank", "reference": "PART-002"},
        headers=student_headers,
    )
    assert r2.status_code == 201

    inv2 = (await client.get(f"/api/v1/invoices/{invoice.id}", headers=student_headers)).json()
    assert inv2["paid_amount"] == "666.66"
    assert inv2["balance"] == "333.34"
    assert inv2["status"] == "partial"

    # Payment 3: 333.34 -> exactly equals 1000.00 -> status paid, balance 0.00
    r3 = await client.post(
        f"/api/v1/invoices/{invoice.id}/payments",
        json={"amount": "333.34", "method": "card", "reference": "PART-003"},
        headers=student_headers,
    )
    assert r3.status_code == 201

    inv3 = (await client.get(f"/api/v1/invoices/{invoice.id}", headers=student_headers)).json()
    assert inv3["paid_amount"] == "1000.00"
    assert inv3["balance"] == "0.00"
    assert inv3["status"] == "paid"
    assert len(inv3["payments"]) == 3


@pytest.mark.asyncio
async def test_billing_scoping_and_authorization_api(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_headers: dict[str, str],
    warden_user: User,
    student_headers: dict[str, str],
    student_user: User,
    db_session: AsyncSession,
) -> None:
    """Test scoping & authorization rules across students and wardens."""
    # 1. Setup Hostel 1 and assign warden to Hostel 1
    h1, _, _room1, bed1 = await setup_hostel_hierarchy(db_session)
    assignment = WardenAssignment(user_id=warden_user.id, hostel_id=h1.id)
    db_session.add(assignment)

    student1, alloc1 = await create_student_with_allocation(db_session, student_user, bed1)

    # 2. Setup Hostel 2 (NOT assigned to warden)
    h2, _, _room2, bed2 = await setup_hostel_hierarchy(db_session)

    # Create Student 2
    user2 = User(
        id=uuid4(),
        email=f"stu2_{uuid4().hex[:6]}@example.com",
        full_name="Second Student",
        phone="+1333333333",
        hashed_password=hash_password("Pass123!"),
        role=UserRole.STUDENT,
        is_active=True,
    )
    db_session.add(user2)
    await db_session.flush()

    student2, alloc2 = await create_student_with_allocation(db_session, user2, bed2)

    # Create invoices for Student 1 (Hostel 1) and Student 2 (Hostel 2)
    inv1 = Invoice(
        student_id=student1.id,
        allocation_id=alloc1.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        amount=Decimal("1500.00"),
        paid_amount=Decimal("0.00"),
        due_date=date(2026, 11, 15),
        status=InvoiceStatus.UNPAID,
    )
    inv2 = Invoice(
        student_id=student2.id,
        allocation_id=alloc2.id,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        amount=Decimal("2000.00"),
        paid_amount=Decimal("0.00"),
        due_date=date(2026, 11, 15),
        status=InvoiceStatus.UNPAID,
    )
    db_session.add_all([inv1, inv2])
    await db_session.commit()

    # Rule A: Student 1 viewing Student 2's invoice -> 403 Forbidden
    resp_s1_view_s2 = await client.get(
        f"/api/v1/invoices/{inv2.id}",
        headers=student_headers,
    )
    assert resp_s1_view_s2.status_code == 403

    # Rule B: Student 1 paying Student 2's invoice -> 403 Forbidden
    resp_s1_pay_s2 = await client.post(
        f"/api/v1/invoices/{inv2.id}/payments",
        json={"amount": "100.00", "method": "online"},
        headers=student_headers,
    )
    assert resp_s1_pay_s2.status_code == 403

    # Rule C: Student cannot list all invoices -> 403 Forbidden
    resp_s1_list_all = await client.get(
        "/api/v1/invoices",
        headers=student_headers,
    )
    assert resp_s1_list_all.status_code == 403

    # Rule D: Student cannot list payments ledger -> 403 Forbidden
    resp_s1_list_payments = await client.get(
        "/api/v1/payments",
        headers=student_headers,
    )
    assert resp_s1_list_payments.status_code == 403

    # Rule E: Warden cannot generate invoices for unassigned Hostel 2 -> 403 Forbidden
    resp_w_gen = await client.post(
        "/api/v1/invoices/generate",
        json={
            "hostel_id": str(h2.id),
            "period_start": "2026-11-01",
            "period_end": "2026-11-30",
            "due_date": "2026-11-15",
        },
        headers=warden_headers,
    )
    assert resp_w_gen.status_code == 403

    # Rule F: Warden cannot list invoices for unassigned Hostel 2 -> 403 Forbidden
    resp_w_list_unassigned = await client.get(
        f"/api/v1/invoices?hostel_id={h2.id}",
        headers=warden_headers,
    )
    assert resp_w_list_unassigned.status_code == 403

    # Rule G: Warden cannot view invoice in unassigned Hostel 2 -> 403 Forbidden
    resp_w_view_inv2 = await client.get(
        f"/api/v1/invoices/{inv2.id}",
        headers=warden_headers,
    )
    assert resp_w_view_inv2.status_code == 403

    # Rule H: Warden cannot access student balance for student in unassigned Hostel 2 -> 403
    resp_w_bal_s2 = await client.get(
        f"/api/v1/students/{student2.id}/balance",
        headers=warden_headers,
    )
    assert resp_w_bal_s2.status_code == 403

    # Rule I: Warden CAN view invoice in assigned Hostel 1 -> 200 OK
    resp_w_view_inv1 = await client.get(
        f"/api/v1/invoices/{inv1.id}",
        headers=warden_headers,
    )
    assert resp_w_view_inv1.status_code == 200

    # Rule J: Warden CAN list payments scoped to assigned hostels -> 200 OK
    resp_w_payments = await client.get(
        "/api/v1/payments",
        headers=warden_headers,
    )
    assert resp_w_payments.status_code == 200


@pytest.mark.asyncio
async def test_invoice_proration_scenarios_api(
    client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Test full period, mid-month start, and mid-month end proration via API."""
    hostel, _block, room, bed1 = await setup_hostel_hierarchy(db_session)

    # Bed 2 and Bed 3 in the same room
    bed2 = Bed(room_id=room.id, label="201-B")
    bed3 = Bed(room_id=room.id, label="201-C")
    db_session.add_all([bed2, bed3])
    await db_session.flush()

    # Fee structure: 3000.00 monthly
    fs = FeeStructure(
        hostel_id=hostel.id,
        room_type=room.room_type,
        amount=Decimal("3000.00"),
        period=FeePeriod.MONTHLY,
    )
    db_session.add(fs)

    # Student 1: Full period Nov 1 to Nov 30 (30 days)
    u1 = User(
        id=uuid4(),
        email=f"u1_{uuid4().hex[:6]}@example.com",
        full_name="Student Full",
        phone="+1444444441",
        hashed_password="pwd",
        role=UserRole.STUDENT,
        is_active=True,
    )
    db_session.add(u1)
    await db_session.flush()
    s1, _alloc1 = await create_student_with_allocation(
        db_session, u1, bed1, start_date=date(2026, 11, 1)
    )

    # Student 2: Mid-month start Nov 16 to Nov 30 (15 days out of 30)
    u2 = User(
        id=uuid4(),
        email=f"u2_{uuid4().hex[:6]}@example.com",
        full_name="Student MidStart",
        phone="+1444444442",
        hashed_password="pwd",
        role=UserRole.STUDENT,
        is_active=True,
    )
    db_session.add(u2)
    await db_session.flush()
    s2, _alloc2 = await create_student_with_allocation(
        db_session, u2, bed2, start_date=date(2026, 11, 16)
    )

    # Student 3: Mid-month end Nov 1 to Nov 10 (10 days out of 30)
    u3 = User(
        id=uuid4(),
        email=f"u3_{uuid4().hex[:6]}@example.com",
        full_name="Student MidEnd",
        phone="+1444444443",
        hashed_password="pwd",
        role=UserRole.STUDENT,
        is_active=True,
    )
    db_session.add(u3)
    await db_session.flush()
    s3, alloc3 = await create_student_with_allocation(
        db_session, u3, bed3, start_date=date(2026, 11, 1)
    )
    alloc3.end_date = date(2026, 11, 10)
    alloc3.status = AllocationStatus.ENDED

    await db_session.commit()

    # Generate invoices for Nov 1 to Nov 30
    resp_gen = await client.post(
        "/api/v1/invoices/generate",
        json={
            "hostel_id": str(hostel.id),
            "period_start": "2026-11-01",
            "period_end": "2026-11-30",
            "due_date": "2026-11-15",
        },
        headers=admin_headers,
    )
    assert resp_gen.status_code == 200
    gen_data = resp_gen.json()
    assert gen_data["generated_count"] == 3

    invoices_by_student = {inv["student_id"]: inv["amount"] for inv in gen_data["invoices"]}
    # Full period: 30/30 * 3000.00 = 3000.00
    assert invoices_by_student[str(s1.id)] == "3000.00"
    # Mid-month start: 15/30 * 3000.00 = 1500.00
    assert invoices_by_student[str(s2.id)] == "1500.00"
    # Mid-month end: 10/30 * 3000.00 = 1000.00
    assert invoices_by_student[str(s3.id)] == "1000.00"
