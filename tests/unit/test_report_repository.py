"""Unit tests for ReportRepository aggregate queries and reports."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
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
    ComplaintPriority,
    ComplaintStatus,
)
from app.models.hostel import Block, GenderType, Hostel
from app.models.notice import Notice, NoticeAudience, NoticeRead
from app.models.operations import (
    AttendanceLog,
    AttendanceType,
    LeaveRequest,
    LeaveStatus,
)
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.repositories.report_repository import ReportRepository


async def _create_user(
    db: AsyncSession,
    role: UserRole = UserRole.STUDENT,
    full_name: str | None = None,
) -> User:
    """Helper to create and persist a test user."""
    uid = uuid4().hex[:8]
    user = User(
        email=f"user_{uid}@example.com",
        full_name=full_name or f"User {uid}",
        hashed_password="dummy_hashed_password",
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _create_student_profile(db: AsyncSession, user: User) -> StudentProfile:
    """Helper to create and persist a student profile."""
    uid = uuid4().hex[:6]
    profile = StudentProfile(
        user_id=user.id,
        student_no=f"STU-{uid}",
        gender=GenderType.MALE,
        department="Computer Science",
        year=2,
        guardian_name="Guardian Name",
        guardian_phone="1234567890",
        emergency_contact="0987654321",
    )
    db.add(profile)
    await db.flush()
    return profile


@pytest.mark.asyncio
async def test_empty_database_summary_and_reports(db_session: AsyncSession) -> None:
    """Test that all reports return zeros/empty lists gracefully when DB is empty."""
    repo = ReportRepository(db_session)

    # 1. Summary on empty database
    summary = await repo.get_dashboard_summary()
    assert summary.total_hostels == 0
    assert summary.total_rooms == 0
    assert summary.total_beds == 0
    assert summary.occupied_beds == 0
    assert summary.occupancy_rate == 0.0
    assert summary.active_students == 0
    assert summary.open_complaints == 0
    assert summary.pending_leaves == 0
    assert summary.present_now == 0
    assert summary.invoices_due_this_month == Decimal("0.00")
    assert summary.collected_this_month == Decimal("0.00")
    assert summary.outstanding_total == Decimal("0.00")
    assert summary.to_dict()["total_hostels"] == 0

    # 2. Summary with empty list of hostel_ids
    empty_scope_summary = await repo.get_dashboard_summary(hostel_ids=[])
    assert empty_scope_summary.total_hostels == 0
    assert empty_scope_summary.total_beds == 0

    # 3. Occupancy report on empty database
    occupancy = await repo.get_occupancy_report()
    assert occupancy == []
    assert await repo.get_occupancy_report(hostel_ids=[]) == []

    # 4. Revenue report on empty database
    rev_month = await repo.get_revenue_report(group_by="month")
    assert rev_month == []
    rev_hostel = await repo.get_revenue_report(group_by="hostel")
    assert rev_hostel == []
    rev_method = await repo.get_revenue_report(group_by="method")
    assert rev_method == []
    assert await repo.get_revenue_report(hostel_ids=[]) == []

    # 5. Defaulters report on empty database
    defaulters = await repo.get_defaulters_report()
    assert defaulters == []
    assert await repo.get_defaulters_report(hostel_ids=[]) == []

    # 6. Complaints report on empty database
    complaints = await repo.get_complaints_report()
    assert complaints.total_complaints == 0
    assert complaints.by_status == {}
    assert complaints.by_category == {}
    assert complaints.avg_resolution_hours == 0.0
    assert (await repo.get_complaints_report(hostel_ids=[])).total_complaints == 0

    # 7. Attendance report on empty database
    att = await repo.get_attendance_report(target_date=date.today())
    assert att.total_active_students == 0
    assert att.present_count == 0
    assert att.absent_count == 0
    assert att.on_leave_count == 0
    assert (
        await repo.get_attendance_report(target_date=date.today(), hostel_ids=[])
    ).total_active_students == 0

    # 8. Student dashboard for non-existent student
    non_existent_id = uuid4()
    dash = await repo.get_student_dashboard_data(non_existent_id)
    assert dash.room is None
    assert dash.roommates == []
    assert dash.balance == Decimal("0.00")
    assert dash.open_complaints_count == 0
    assert dash.unread_notices_count == 0


@pytest.mark.asyncio
async def test_dashboard_summary_populated_and_scoped(db_session: AsyncSession) -> None:
    """Test dashboard summary with populated data and hostel scoping."""
    repo = ReportRepository(db_session)
    today = date.today()

    # Hostels
    h1 = Hostel(name="Alpha Hostel", code=f"AH-{uuid4().hex[:4]}", gender_type=GenderType.MALE)
    h2 = Hostel(name="Beta Hostel", code=f"BH-{uuid4().hex[:4]}", gender_type=GenderType.FEMALE)
    db_session.add_all([h1, h2])
    await db_session.flush()

    # Blocks
    b1 = Block(hostel_id=h1.id, name="Block A", floor_count=2)
    b2 = Block(hostel_id=h2.id, name="Block B", floor_count=1)
    db_session.add_all([b1, b2])
    await db_session.flush()

    # Rooms: Room 1 in Block A (double, 2 beds), Room 2 in Block B (single, 1 bed)
    r1 = Room(
        block_id=b1.id,
        number="101",
        floor=1,
        room_type=RoomType.DOUBLE,
        capacity=2,
        monthly_rent=Decimal("3000.00"),
        status=RoomStatus.AVAILABLE,
    )
    r2 = Room(
        block_id=b2.id,
        number="201",
        floor=1,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("4000.00"),
        status=RoomStatus.AVAILABLE,
    )
    db_session.add_all([r1, r2])
    await db_session.flush()

    # Beds: 2 in Room 1, 1 in Room 2
    bed1 = Bed(room_id=r1.id, label="A", is_occupied=True)
    bed2 = Bed(room_id=r1.id, label="B", is_occupied=False)
    bed3 = Bed(room_id=r2.id, label="A", is_occupied=True)
    db_session.add_all([bed1, bed2, bed3])
    await db_session.flush()

    # Students & Allocations
    u1 = await _create_user(db_session, full_name="Student One")
    s1 = await _create_student_profile(db_session, u1)
    alloc1 = Allocation(
        student_id=s1.id,
        bed_id=bed1.id,
        start_date=today - timedelta(days=10),
        status=AllocationStatus.ACTIVE,
    )

    u2 = await _create_user(db_session, full_name="Student Two")
    s2 = await _create_student_profile(db_session, u2)
    alloc2 = Allocation(
        student_id=s2.id,
        bed_id=bed3.id,
        start_date=today - timedelta(days=5),
        status=AllocationStatus.ACTIVE,
    )
    db_session.add_all([alloc1, alloc2])
    await db_session.flush()

    # Complaints: 1 OPEN in Room 1 (Hostel 1), 1 RESOLVED in Room 2 (Hostel 2)
    c1 = Complaint(
        student_id=s1.id,
        room_id=r1.id,
        title="Leaky tap",
        description="Bathroom tap leaks",
        category=ComplaintCategory.PLUMBING,
        priority=ComplaintPriority.MEDIUM,
        status=ComplaintStatus.OPEN,
    )
    c2 = Complaint(
        student_id=s2.id,
        room_id=r2.id,
        title="Light bulb",
        description="Bulb broken",
        category=ComplaintCategory.ELECTRICAL,
        priority=ComplaintPriority.LOW,
        status=ComplaintStatus.RESOLVED,
        resolved_at=datetime.now(UTC),
    )
    db_session.add_all([c1, c2])
    await db_session.flush()

    # Leaves: s1 has PENDING leave, s2 has APPROVED leave
    l1 = LeaveRequest(
        student_id=s1.id,
        from_date=today + timedelta(days=2),
        to_date=today + timedelta(days=5),
        reason="Family event",
        status=LeaveStatus.PENDING,
    )
    l2 = LeaveRequest(
        student_id=s2.id,
        from_date=today,
        to_date=today + timedelta(days=1),
        reason="Medical checkup",
        status=LeaveStatus.APPROVED,
    )
    db_session.add_all([l1, l2])
    await db_session.flush()

    # Attendance: s1 latest is CHECK_IN (present), s2 latest is CHECK_OUT
    att1 = AttendanceLog(
        student_id=s1.id,
        type=AttendanceType.CHECK_IN,
        timestamp=datetime.now(UTC) - timedelta(hours=2),
        recorded_by=u1.id,
    )
    att2 = AttendanceLog(
        student_id=s2.id,
        type=AttendanceType.CHECK_OUT,
        timestamp=datetime.now(UTC) - timedelta(hours=1),
        recorded_by=u2.id,
    )
    db_session.add_all([att1, att2])
    await db_session.flush()

    # Invoices & Payments:
    # Inv 1 (Hostel 1): amount 3000, paid 1000, balance 2000, due today (in current month)
    inv1 = Invoice(
        student_id=s1.id,
        allocation_id=alloc1.id,
        period_start=today.replace(day=1),
        period_end=today,
        amount=Decimal("3000.00"),
        paid_amount=Decimal("1000.00"),
        due_date=today,
        status=InvoiceStatus.PARTIAL,
    )
    # Inv 2 (Hostel 2): amount 4000, paid 4000, balance 0, due today
    inv2 = Invoice(
        student_id=s2.id,
        allocation_id=alloc2.id,
        period_start=today.replace(day=1),
        period_end=today,
        amount=Decimal("4000.00"),
        paid_amount=Decimal("4000.00"),
        due_date=today,
        status=InvoiceStatus.PAID,
    )
    db_session.add_all([inv1, inv2])
    await db_session.flush()

    # Payments: 1000 on Inv 1, 4000 on Inv 2
    pay1 = Payment(
        invoice_id=inv1.id,
        amount=Decimal("1000.00"),
        method=PaymentMethod.CASH,
        paid_at=datetime.now(UTC),
    )
    pay2 = Payment(
        invoice_id=inv2.id,
        amount=Decimal("4000.00"),
        method=PaymentMethod.ONLINE,
        paid_at=datetime.now(UTC),
    )
    db_session.add_all([pay1, pay2])
    await db_session.flush()

    # 1. Global summary (Admin view)
    summary_all = await repo.get_dashboard_summary()
    assert summary_all.total_hostels == 2
    assert summary_all.total_rooms == 2
    assert summary_all.total_beds == 3
    assert summary_all.occupied_beds == 2
    assert summary_all.occupancy_rate == round((2 / 3) * 100.0, 2)
    assert summary_all.active_students == 2
    assert summary_all.open_complaints == 1  # Only c1 is OPEN
    assert summary_all.pending_leaves == 1  # Only l1 is PENDING
    assert summary_all.present_now == 1  # Only s1 has latest CHECK_IN
    assert summary_all.invoices_due_this_month == Decimal("7000.00")  # 3000 + 4000
    assert summary_all.collected_this_month == Decimal("5000.00")  # 1000 + 4000
    assert summary_all.outstanding_total == Decimal("2000.00")  # Inv 1 partial balance

    # 2. Scoped summary (Warden for Hostel 1 only)
    summary_h1 = await repo.get_dashboard_summary(hostel_ids=[h1.id])
    assert summary_h1.total_hostels == 1
    assert summary_h1.total_rooms == 1
    assert summary_h1.total_beds == 2
    assert summary_h1.occupied_beds == 1
    assert summary_h1.occupancy_rate == 50.0
    assert summary_h1.active_students == 1
    assert summary_h1.open_complaints == 1
    assert summary_h1.pending_leaves == 1
    assert summary_h1.present_now == 1
    assert summary_h1.invoices_due_this_month == Decimal("3000.00")
    assert summary_h1.collected_this_month == Decimal("1000.00")
    assert summary_h1.outstanding_total == Decimal("2000.00")


@pytest.mark.asyncio
async def test_occupancy_report_details(db_session: AsyncSession) -> None:
    """Test occupancy report grouped by hostel, block, and room type."""
    repo = ReportRepository(db_session)

    hostel = Hostel(name="Zeta Hostel", code=f"ZH-{uuid4().hex[:4]}", gender_type=GenderType.MIXED)
    db_session.add(hostel)
    await db_session.flush()

    block = Block(hostel_id=hostel.id, name="Block Z", floor_count=1)
    db_session.add(block)
    await db_session.flush()

    # Room of type DOUBLE with 2 beds (1 occupied, 1 available)
    room = Room(
        block_id=block.id,
        number="Z-101",
        floor=1,
        room_type=RoomType.DOUBLE,
        capacity=2,
        monthly_rent=Decimal("2500.00"),
        status=RoomStatus.AVAILABLE,
    )
    db_session.add(room)
    await db_session.flush()

    b1 = Bed(room_id=room.id, label="1", is_occupied=True)
    b2 = Bed(room_id=room.id, label="2", is_occupied=False)
    db_session.add_all([b1, b2])
    await db_session.flush()

    rows = await repo.get_occupancy_report(hostel_ids=[hostel.id])
    assert len(rows) == 1
    r = rows[0]
    assert r.hostel_name == "Zeta Hostel"
    assert r.block_name == "Block Z"
    assert r.room_type == RoomType.DOUBLE.value
    assert r.total_beds == 2
    assert r.occupied_beds == 1
    assert r.available_beds == 1
    assert r.occupancy_rate == 50.0
    assert r.to_dict()["occupied_beds"] == 1


@pytest.mark.asyncio
async def test_revenue_report_groupings_and_date_filtering(db_session: AsyncSession) -> None:
    """Test revenue report with month, hostel, and method groupings and date filters."""
    repo = ReportRepository(db_session)
    now = datetime.now(UTC)

    hostel = Hostel(name="Gamma Hostel", code=f"GH-{uuid4().hex[:4]}", gender_type=GenderType.MIXED)
    db_session.add(hostel)
    await db_session.flush()

    block = Block(hostel_id=hostel.id, name="Block G", floor_count=1)
    db_session.add(block)
    await db_session.flush()

    room = Room(
        block_id=block.id,
        number="G-101",
        floor=1,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("5000.00"),
        status=RoomStatus.AVAILABLE,
    )
    db_session.add(room)
    await db_session.flush()

    bed = Bed(room_id=room.id, label="G1", is_occupied=True)
    db_session.add(bed)
    await db_session.flush()

    user = await _create_user(db_session)
    student = await _create_student_profile(db_session, user)
    alloc = Allocation(
        student_id=student.id,
        bed_id=bed.id,
        start_date=date.today(),
        status=AllocationStatus.ACTIVE,
    )
    db_session.add(alloc)
    await db_session.flush()

    inv = Invoice(
        student_id=student.id,
        allocation_id=alloc.id,
        period_start=date.today(),
        period_end=date.today(),
        amount=Decimal("5000.00"),
        paid_amount=Decimal("5000.00"),
        due_date=date.today(),
        status=InvoiceStatus.PAID,
    )
    db_session.add(inv)
    await db_session.flush()

    # Two payments: one cash (2000), one online (3000)
    p1 = Payment(
        invoice_id=inv.id,
        amount=Decimal("2000.00"),
        method=PaymentMethod.CASH,
        paid_at=now - timedelta(days=2),
    )
    p2 = Payment(
        invoice_id=inv.id,
        amount=Decimal("3000.00"),
        method=PaymentMethod.ONLINE,
        paid_at=now,
    )
    db_session.add_all([p1, p2])
    await db_session.flush()

    # 1. Group by month
    by_month = await repo.get_revenue_report(group_by="month", hostel_ids=[hostel.id])
    assert len(by_month) == 1
    assert by_month[0].total_revenue == Decimal("5000.00")
    assert by_month[0].transaction_count == 2
    assert by_month[0].group_key == now.strftime("%Y-%m")

    # 2. Group by hostel
    by_hostel = await repo.get_revenue_report(group_by="hostel", hostel_ids=[hostel.id])
    assert len(by_hostel) == 1
    assert by_hostel[0].group_key == "Gamma Hostel"
    assert by_hostel[0].total_revenue == Decimal("5000.00")
    assert by_hostel[0].transaction_count == 2
    assert by_hostel[0].hostel_id == hostel.id

    # 3. Group by method
    by_method = await repo.get_revenue_report(group_by="method", hostel_ids=[hostel.id])
    assert len(by_method) == 2
    methods = {row.group_key: row.total_revenue for row in by_method}
    assert methods[PaymentMethod.CASH.value] == Decimal("2000.00")
    assert methods[PaymentMethod.ONLINE.value] == Decimal("3000.00")

    # 4. Date filtering: only today
    today_only = await repo.get_revenue_report(
        from_date=now.date(),
        to_date=now.date(),
        group_by="method",
        hostel_ids=[hostel.id],
    )
    assert len(today_only) == 1
    assert today_only[0].group_key == PaymentMethod.ONLINE.value
    assert today_only[0].total_revenue == Decimal("3000.00")

    # 5. Invalid group_by raises ValueError
    with pytest.raises(ValueError, match="Invalid group_by"):
        await repo.get_revenue_report(group_by="invalid_group")


@pytest.mark.asyncio
async def test_defaulters_report(db_session: AsyncSession) -> None:
    """Test overdue invoice defaulters report with calculation of days overdue."""
    repo = ReportRepository(db_session)
    today = date.today()

    hostel = Hostel(name="Delta Hostel", code=f"DH-{uuid4().hex[:4]}", gender_type=GenderType.MALE)
    db_session.add(hostel)
    await db_session.flush()

    block = Block(hostel_id=hostel.id, name="Block D", floor_count=1)
    db_session.add(block)
    await db_session.flush()

    room = Room(
        block_id=block.id,
        number="D-101",
        floor=1,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("2000.00"),
        status=RoomStatus.AVAILABLE,
    )
    db_session.add(room)
    await db_session.flush()

    bed = Bed(room_id=room.id, label="D1", is_occupied=True)
    db_session.add(bed)
    await db_session.flush()

    user = await _create_user(db_session, full_name="Defaulter Student")
    student = await _create_student_profile(db_session, user)
    alloc = Allocation(
        student_id=student.id,
        bed_id=bed.id,
        start_date=today - timedelta(days=60),
        status=AllocationStatus.ACTIVE,
    )
    db_session.add(alloc)
    await db_session.flush()

    # Overdue invoice: due 15 days ago, amount 2000, paid 500, balance 1500
    inv = Invoice(
        student_id=student.id,
        allocation_id=alloc.id,
        period_start=today - timedelta(days=45),
        period_end=today - timedelta(days=15),
        amount=Decimal("2000.00"),
        paid_amount=Decimal("500.00"),
        due_date=today - timedelta(days=15),
        status=InvoiceStatus.OVERDUE,
    )
    db_session.add(inv)
    await db_session.flush()

    defaulters = await repo.get_defaulters_report(hostel_ids=[hostel.id])
    assert len(defaulters) == 1
    d = defaulters[0]
    assert d.student_id == student.id
    assert d.student_name == "Defaulter Student"
    assert d.hostel_name == "Delta Hostel"
    assert d.room_number == "D-101"
    assert d.amount == Decimal("2000.00")
    assert d.paid_amount == Decimal("500.00")
    assert d.balance == Decimal("1500.00")
    assert d.due_date == today - timedelta(days=15)
    assert d.days_overdue == 15


@pytest.mark.asyncio
async def test_complaints_report_metrics_and_avg_resolution(db_session: AsyncSession) -> None:
    """Test complaints report breakdown by status, category, and average resolution time."""
    repo = ReportRepository(db_session)
    now = datetime.now(UTC)

    hostel = Hostel(name="Theta Hostel", code=f"TH-{uuid4().hex[:4]}", gender_type=GenderType.MIXED)
    db_session.add(hostel)
    await db_session.flush()

    block = Block(hostel_id=hostel.id, name="Block T", floor_count=1)
    db_session.add(block)
    await db_session.flush()

    room = Room(
        block_id=block.id,
        number="T-101",
        floor=1,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("2000.00"),
        status=RoomStatus.AVAILABLE,
    )
    db_session.add(room)
    await db_session.flush()

    user = await _create_user(db_session)
    student = await _create_student_profile(db_session, user)

    # 1. Open complaint (Electrical)
    c1 = Complaint(
        student_id=student.id,
        room_id=room.id,
        title="Fan not working",
        description="Ceiling fan won't turn on",
        category=ComplaintCategory.ELECTRICAL,
        priority=ComplaintPriority.HIGH,
        status=ComplaintStatus.OPEN,
    )
    # 2. Resolved complaint (Plumbing), resolved 4 hours after creation
    c2 = Complaint(
        student_id=student.id,
        room_id=room.id,
        title="Pipe leak",
        description="Wash basin pipe leaks",
        category=ComplaintCategory.PLUMBING,
        priority=ComplaintPriority.MEDIUM,
        status=ComplaintStatus.RESOLVED,
        created_at=now - timedelta(hours=6),
        resolved_at=now - timedelta(hours=2),
    )
    db_session.add_all([c1, c2])
    await db_session.flush()

    report = await repo.get_complaints_report(hostel_ids=[hostel.id])
    assert report.total_complaints == 2
    assert report.by_status[ComplaintStatus.OPEN.value] == 1
    assert report.by_status[ComplaintStatus.RESOLVED.value] == 1
    assert report.by_category[ComplaintCategory.ELECTRICAL.value] == 1
    assert report.by_category[ComplaintCategory.PLUMBING.value] == 1
    assert 3.9 <= report.avg_resolution_hours <= 4.1  # Approx 4 hours


@pytest.mark.asyncio
async def test_attendance_report_disjoint_categories(db_session: AsyncSession) -> None:
    """Test attendance report partitions students into present, on-leave, and absent."""
    repo = ReportRepository(db_session)
    today = date.today()

    hostel = Hostel(
        name="Epsilon Hostel", code=f"EH-{uuid4().hex[:4]}", gender_type=GenderType.MIXED
    )
    db_session.add(hostel)
    await db_session.flush()

    block = Block(hostel_id=hostel.id, name="Block E", floor_count=1)
    db_session.add(block)
    await db_session.flush()

    room = Room(
        block_id=block.id,
        number="E-101",
        floor=1,
        room_type=RoomType.TRIPLE,
        capacity=3,
        monthly_rent=Decimal("2000.00"),
        status=RoomStatus.AVAILABLE,
    )
    db_session.add(room)
    await db_session.flush()

    bed1 = Bed(room_id=room.id, label="1", is_occupied=True)
    bed2 = Bed(room_id=room.id, label="2", is_occupied=True)
    bed3 = Bed(room_id=room.id, label="3", is_occupied=True)
    db_session.add_all([bed1, bed2, bed3])
    await db_session.flush()

    # Student 1: Present (checked in)
    u1 = await _create_user(db_session, full_name="Student One")
    s1 = await _create_student_profile(db_session, u1)
    a1 = Allocation(
        student_id=s1.id,
        bed_id=bed1.id,
        start_date=today - timedelta(days=5),
        status=AllocationStatus.ACTIVE,
    )

    # Student 2: On leave (approved leave on target_date)
    u2 = await _create_user(db_session, full_name="Student Two")
    s2 = await _create_student_profile(db_session, u2)
    a2 = Allocation(
        student_id=s2.id,
        bed_id=bed2.id,
        start_date=today - timedelta(days=5),
        status=AllocationStatus.ACTIVE,
    )
    leave = LeaveRequest(
        student_id=s2.id,
        from_date=today - timedelta(days=1),
        to_date=today + timedelta(days=2),
        reason="Home trip",
        status=LeaveStatus.APPROVED,
    )

    # Student 3: Absent (no attendance log, or checked out)
    u3 = await _create_user(db_session, full_name="Student Three")
    s3 = await _create_student_profile(db_session, u3)
    a3 = Allocation(
        student_id=s3.id,
        bed_id=bed3.id,
        start_date=today - timedelta(days=5),
        status=AllocationStatus.ACTIVE,
    )

    db_session.add_all([a1, a2, a3, leave])
    await db_session.flush()

    # Log check_in for s1
    att1 = AttendanceLog(
        student_id=s1.id,
        type=AttendanceType.CHECK_IN,
        timestamp=datetime.now(UTC),
        recorded_by=u1.id,
    )
    db_session.add(att1)
    await db_session.flush()

    att_report = await repo.get_attendance_report(target_date=today, hostel_ids=[hostel.id])
    assert att_report.total_active_students == 3
    assert att_report.present_count == 1
    assert att_report.on_leave_count == 1
    assert att_report.absent_count == 1
    # Check identity
    assert (
        att_report.present_count + att_report.on_leave_count + att_report.absent_count
        == att_report.total_active_students
    )


@pytest.mark.asyncio
async def test_student_dashboard_personal_data(db_session: AsyncSession) -> None:
    """Test personalized student dashboard query."""
    repo = ReportRepository(db_session)
    today = date.today()

    hostel = Hostel(name="Omega Hostel", code=f"OH-{uuid4().hex[:4]}", gender_type=GenderType.MIXED)
    db_session.add(hostel)
    await db_session.flush()

    block = Block(hostel_id=hostel.id, name="Block O", floor_count=1)
    db_session.add(block)
    await db_session.flush()

    room = Room(
        block_id=block.id,
        number="O-101",
        floor=1,
        room_type=RoomType.DOUBLE,
        capacity=2,
        monthly_rent=Decimal("2500.00"),
        status=RoomStatus.AVAILABLE,
    )
    db_session.add(room)
    await db_session.flush()

    bed1 = Bed(room_id=room.id, label="A", is_occupied=True)
    bed2 = Bed(room_id=room.id, label="B", is_occupied=True)
    db_session.add_all([bed1, bed2])
    await db_session.flush()

    # Student 1
    u1 = await _create_user(db_session, full_name="Alice Smith")
    s1 = await _create_student_profile(db_session, u1)
    a1 = Allocation(
        student_id=s1.id, bed_id=bed1.id, start_date=today, status=AllocationStatus.ACTIVE
    )

    # Roommate: Student 2
    u2 = await _create_user(db_session, full_name="Bob Jones")
    s2 = await _create_student_profile(db_session, u2)
    a2 = Allocation(
        student_id=s2.id, bed_id=bed2.id, start_date=today, status=AllocationStatus.ACTIVE
    )

    db_session.add_all([a1, a2])
    await db_session.flush()

    # Invoice for Student 1 with outstanding balance of 1500
    inv = Invoice(
        student_id=s1.id,
        allocation_id=a1.id,
        period_start=today,
        period_end=today,
        amount=Decimal("2500.00"),
        paid_amount=Decimal("1000.00"),
        due_date=today + timedelta(days=7),
        status=InvoiceStatus.PARTIAL,
    )
    # Complaint for Student 1
    comp = Complaint(
        student_id=s1.id,
        room_id=room.id,
        title="Desk chair broken",
        description="Wheel came off",
        category=ComplaintCategory.FURNITURE,
        status=ComplaintStatus.OPEN,
    )
    # Notice for students
    notice = Notice(
        hostel_id=hostel.id,
        title="Hostel Meeting",
        body="Meeting at 7pm in common hall",
        audience=NoticeAudience.STUDENTS,
        published_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.add_all([inv, comp, notice])
    await db_session.flush()

    dash = await repo.get_student_dashboard_data(s1.id)
    assert dash.room is not None
    assert dash.room.room_number == "O-101"
    assert dash.room.block_name == "Block O"
    assert dash.room.hostel_name == "Omega Hostel"
    assert dash.room.bed_label == "A"
    assert dash.roommates == ["Bob Jones"]
    assert dash.balance == Decimal("1500.00")
    assert dash.open_complaints_count == 1
    assert dash.unread_notices_count == 1

    # Mark notice as read
    read = NoticeRead(notice_id=notice.id, user_id=u1.id)
    db_session.add(read)
    await db_session.flush()

    dash_after_read = await repo.get_student_dashboard_data(s1.id)
    assert dash_after_read.unread_notices_count == 0
