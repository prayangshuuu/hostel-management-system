"""Unit tests for domain audit logging hooks in services."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.models.allocation import Allocation, AllocationStatus
from app.models.audit import AuditLog
from app.models.billing import FeePeriod, FeeStructure, Invoice, InvoiceStatus, PaymentMethod
from app.models.complaint import Complaint, ComplaintCategory, ComplaintPriority, ComplaintStatus
from app.models.hostel import Block, GenderType, Hostel
from app.models.operations import LeaveRequest, LeaveStatus
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.allocation import (
    AllocationCreate,
    AllocationTransferRequest,
    AllocationVacateRequest,
)
from app.schemas.billing import PaymentCreate
from app.schemas.complaint import ComplaintStatusUpdateRequest
from app.schemas.user import UserCreate
from app.services.allocation_service import AllocationService
from app.services.billing_service import BillingService
from app.services.complaint_service import ComplaintService
from app.services.operations_service import OperationsService
from app.services.room_service import RoomService
from app.services.user_service import UserService


async def test_user_service_audit_hooks(db_session: AsyncSession) -> None:
    """Verify UserService create and deactivate write audit logs, failed create writes none."""
    user_repo = UserRepository(db_session)
    user_service = UserService(user_repo)

    admin = User(
        id=uuid4(),
        email="admin_auditor@example.com",
        full_name="Admin Auditor",
        phone="1010",
        hashed_password="hash",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(admin)
    await db_session.flush()

    # 1. Create User
    new_user = await user_service.create_user(
        UserCreate(
            email="new_audited_user@example.com",
            full_name="Audited User",
            phone="2020",
            password="ValidPassword123!",
            role=UserRole.STUDENT,
        ),
        current_user=admin,
    )

    # Check exactly 1 audit log created
    stmt = select(AuditLog).where(
        AuditLog.action == "user.create",
        AuditLog.entity_id == new_user.id,
    )
    res = await db_session.execute(stmt)
    log = res.scalar_one()
    assert log.actor_id == admin.id
    assert log.entity == "User"
    assert log.payload["email"] == "new_audited_user@example.com"
    # Never log password
    assert "password" not in log.payload

    # 2. Failed Create (duplicate email) creates no new audit log
    with pytest.raises(ConflictError):
        await user_service.create_user(
            UserCreate(
                email="new_audited_user@example.com",
                full_name="Duplicate User",
                phone="2021",
                password="ValidPassword123!",
                role=UserRole.STUDENT,
            ),
            current_user=admin,
        )

    count_stmt = select(func.count(AuditLog.id)).where(AuditLog.action == "user.create")
    count_res = await db_session.execute(count_stmt)
    assert count_res.scalar() == 1

    # 3. Deactivate User
    await user_service.deactivate_user(new_user.id, current_user=admin)
    stmt_deact = select(AuditLog).where(
        AuditLog.action == "user.deactivate",
        AuditLog.entity_id == new_user.id,
    )
    res_deact = await db_session.execute(stmt_deact)
    log_deact = res_deact.scalar_one()
    assert log_deact.actor_id == admin.id
    assert log_deact.payload["is_active"] is False


async def test_room_service_maintenance_audit_hooks(db_session: AsyncSession) -> None:
    """Verify RoomService set_maintenance and set_available audit logs."""
    room_service = RoomService(db_session)

    admin = User(
        id=uuid4(),
        email="room_auditor@example.com",
        full_name="Room Auditor",
        phone="3030",
        hashed_password="hash",
        role=UserRole.ADMIN,
        is_active=True,
    )
    hostel = Hostel(
        id=uuid4(),
        name="Room Audit Hostel",
        code="RAH",
        gender_type=GenderType.MIXED,
        address="Campus",
        total_capacity=10,
    )
    block = Block(id=uuid4(), hostel_id=hostel.id, name="Block A", floor_count=2)
    room = Room(
        id=uuid4(),
        block_id=block.id,
        number="101",
        floor=1,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("500.00"),
        status=RoomStatus.AVAILABLE,
    )
    bed = Bed(id=uuid4(), room_id=room.id, label="A", is_occupied=False)
    db_session.add_all([admin, hostel, block, room, bed])
    await db_session.flush()

    # Set maintenance
    await room_service.set_maintenance(room.id, current_user=admin)
    stmt1 = select(AuditLog).where(
        AuditLog.action == "room.maintenance_toggle",
        AuditLog.entity_id == room.id,
    )
    res1 = await db_session.execute(stmt1)
    log1 = res1.scalars().first()
    assert log1 is not None
    assert log1.payload["status"] == RoomStatus.MAINTENANCE.value

    # Set available
    await room_service.set_available(room.id, current_user=admin)
    stmt2 = select(AuditLog).where(
        AuditLog.action == "room.maintenance_toggle",
        AuditLog.entity_id == room.id,
    )
    res2 = await db_session.execute(stmt2)
    logs = res2.scalars().all()
    assert len(logs) == 2
    assert logs[1].payload["status"] == RoomStatus.AVAILABLE.value


async def test_allocation_service_audit_hooks(db_session: AsyncSession) -> None:
    """Verify AllocationService allocate, vacate, and transfer audit logs."""
    allocation_service = AllocationService(db_session)

    admin = User(
        id=uuid4(),
        email="alloc_admin@example.com",
        full_name="Alloc Admin",
        phone="4040",
        hashed_password="hash",
        role=UserRole.ADMIN,
        is_active=True,
    )
    student_user = User(
        id=uuid4(),
        email="student_alloc@example.com",
        full_name="Student Alloc",
        phone="5050",
        hashed_password="hash",
        role=UserRole.STUDENT,
        is_active=True,
    )
    student_profile = StudentProfile(
        id=uuid4(),
        user_id=student_user.id,
        student_no="STU-ALLOC-001",
        gender=GenderType.MIXED,
        department="CS",
        year=1,
        guardian_name="Guardian",
        guardian_phone="999",
        emergency_contact="888",
    )
    hostel = Hostel(
        id=uuid4(),
        name="Alloc Hostel",
        code="AH",
        gender_type=GenderType.MIXED,
        address="Campus",
        total_capacity=10,
    )
    block = Block(id=uuid4(), hostel_id=hostel.id, name="Block A", floor_count=2)
    room1 = Room(
        id=uuid4(),
        block_id=block.id,
        number="201",
        floor=2,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("500.00"),
        status=RoomStatus.AVAILABLE,
    )
    bed1 = Bed(id=uuid4(), room_id=room1.id, label="A", is_occupied=False)
    room2 = Room(
        id=uuid4(),
        block_id=block.id,
        number="202",
        floor=2,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("500.00"),
        status=RoomStatus.AVAILABLE,
    )
    bed2 = Bed(id=uuid4(), room_id=room2.id, label="A", is_occupied=False)

    db_session.add_all(
        [
            admin,
            student_user,
            student_profile,
            hostel,
            block,
            room1,
            bed1,
            room2,
            bed2,
        ]
    )
    await db_session.flush()

    # 1. Allocate
    alloc = await allocation_service.allocate(
        AllocationCreate(
            student_id=student_profile.id,
            bed_id=bed1.id,
            start_date=date.today(),
        ),
        current_user=admin,
    )

    stmt_create = select(AuditLog).where(
        AuditLog.action == "allocation.create",
        AuditLog.entity_id == alloc.id,
    )
    res_create = await db_session.execute(stmt_create)
    log_create = res_create.scalar_one()
    assert log_create.actor_id == admin.id
    assert log_create.payload["student_id"] == str(student_profile.id)

    # 2. Transfer
    transferred = await allocation_service.transfer(
        alloc.id,
        AllocationTransferRequest(new_bed_id=bed2.id, reason="Room change"),
        current_user=admin,
    )
    stmt_trans = select(AuditLog).where(
        AuditLog.action == "allocation.transfer",
        AuditLog.entity_id == transferred.id,
    )
    res_trans = await db_session.execute(stmt_trans)
    log_trans = res_trans.scalar_one()
    assert log_trans.actor_id == admin.id
    assert log_trans.payload["new_bed_id"] == str(bed2.id)

    # 3. Vacate
    await allocation_service.vacate(
        transferred.id,
        AllocationVacateRequest(reason="Course completed"),
        current_user=admin,
    )
    stmt_vacate = select(AuditLog).where(
        AuditLog.action == "allocation.vacate",
        AuditLog.entity_id == transferred.id,
    )
    res_vacate = await db_session.execute(stmt_vacate)
    log_vacate = res_vacate.scalar_one()
    assert log_vacate.actor_id == admin.id
    assert log_vacate.payload["reason"] == "Course completed"


async def test_billing_complaint_operations_audit_hooks(db_session: AsyncSession) -> None:
    """Verify Payment, Void Invoice, Complaint Status Change, and Leave Review audit hooks."""
    admin = User(
        id=uuid4(),
        email="ops_admin@example.com",
        full_name="Ops Admin",
        phone="7070",
        hashed_password="hash",
        role=UserRole.ADMIN,
        is_active=True,
    )
    student_user = User(
        id=uuid4(),
        email="ops_student@example.com",
        full_name="Ops Student",
        phone="8080",
        hashed_password="hash",
        role=UserRole.STUDENT,
        is_active=True,
    )
    student_profile = StudentProfile(
        id=uuid4(),
        user_id=student_user.id,
        student_no="STU-OPS-001",
        gender=GenderType.MIXED,
        department="CS",
        year=1,
        guardian_name="Guardian",
        guardian_phone="999",
        emergency_contact="888",
    )
    hostel = Hostel(
        id=uuid4(),
        name="Ops Hostel",
        code="OH",
        gender_type=GenderType.MIXED,
        address="Campus",
        total_capacity=10,
    )
    block = Block(id=uuid4(), hostel_id=hostel.id, name="Block A", floor_count=2)
    room = Room(
        id=uuid4(),
        block_id=block.id,
        number="301",
        floor=3,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("500.00"),
        status=RoomStatus.AVAILABLE,
    )
    bed = Bed(id=uuid4(), room_id=room.id, label="A", is_occupied=True)
    alloc = Allocation(
        id=uuid4(),
        student_id=student_profile.id,
        bed_id=bed.id,
        start_date=date.today(),
        status=AllocationStatus.ACTIVE,
    )
    fee_struct = FeeStructure(
        id=uuid4(),
        hostel_id=hostel.id,
        room_type=RoomType.SINGLE,
        amount=Decimal("600.00"),
        period=FeePeriod.MONTHLY,
    )
    invoice = Invoice(
        id=uuid4(),
        student_id=student_profile.id,
        allocation_id=alloc.id,
        period_start=date.today(),
        period_end=date.today() + timedelta(days=30),
        amount=Decimal("600.00"),
        paid_amount=Decimal("0.00"),
        due_date=date.today() + timedelta(days=15),
        status=InvoiceStatus.UNPAID,
    )
    complaint = Complaint(
        id=uuid4(),
        student_id=student_profile.id,
        room_id=room.id,
        title="Leaky tap",
        description="Bathroom faucet is leaking.",
        category=ComplaintCategory.PLUMBING,
        priority=ComplaintPriority.MEDIUM,
        status=ComplaintStatus.OPEN,
    )
    leave = LeaveRequest(
        id=uuid4(),
        student_id=student_profile.id,
        from_date=date.today() + timedelta(days=5),
        to_date=date.today() + timedelta(days=8),
        reason="Family function",
        status=LeaveStatus.PENDING,
    )

    db_session.add_all(
        [
            admin,
            student_user,
            student_profile,
            hostel,
            block,
            room,
            bed,
            alloc,
            fee_struct,
            invoice,
            complaint,
            leave,
        ]
    )
    await db_session.flush()

    # 1. BillingService: record_payment
    billing_svc = BillingService(db_session)
    payment = await billing_svc.record_payment(
        invoice_id=invoice.id,
        data=PaymentCreate(amount=Decimal("200.00"), method=PaymentMethod.CASH),
        current_user=admin,
    )
    stmt_pay = select(AuditLog).where(
        AuditLog.action == "payment.create",
        AuditLog.entity_id == payment.id,
    )
    res_pay = await db_session.execute(stmt_pay)
    log_pay = res_pay.scalar_one()
    assert log_pay.actor_id == admin.id
    assert log_pay.payload["amount"] == "200.00"

    # 2. BillingService: void_invoice
    await billing_svc.void_invoice(invoice.id, current_user=admin)
    stmt_void = select(AuditLog).where(
        AuditLog.action == "invoice.void",
        AuditLog.entity_id == invoice.id,
    )
    res_void = await db_session.execute(stmt_void)
    log_void = res_void.scalar_one()
    assert log_void.actor_id == admin.id

    # 3. ComplaintService: update_status
    complaint_svc = ComplaintService(db_session)
    await complaint_svc.update_status(
        complaint.id,
        ComplaintStatusUpdateRequest(status=ComplaintStatus.IN_PROGRESS),
        current_user=admin,
    )
    stmt_comp = select(AuditLog).where(
        AuditLog.action == "complaint.status_change",
        AuditLog.entity_id == complaint.id,
    )
    res_comp = await db_session.execute(stmt_comp)
    log_comp = res_comp.scalar_one()
    assert log_comp.actor_id == admin.id
    assert log_comp.payload["old_status"] == ComplaintStatus.OPEN.value
    assert log_comp.payload["new_status"] == ComplaintStatus.IN_PROGRESS.value

    # 4. OperationsService: approve_leave_request
    ops_svc = OperationsService(db_session)
    await ops_svc.approve_leave_request(leave.id, current_user=admin)
    stmt_leave = select(AuditLog).where(
        AuditLog.action == "leave.approve",
        AuditLog.entity_id == leave.id,
    )
    res_leave = await db_session.execute(stmt_leave)
    log_leave = res_leave.scalar_one()
    assert log_leave.actor_id == admin.id
    assert log_leave.payload["status"] == LeaveStatus.APPROVED.value
