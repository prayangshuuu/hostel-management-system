"""Database seed script for local development, demo environments, and automated testing."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

# Ensure project root is in sys.path when executed directly
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import async_session_maker
from app.models.allocation import Allocation, AllocationStatus
from app.models.audit import AuditLog
from app.models.billing import (
    FeePeriod,
    FeeStructure,
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentMethod,
)
from app.models.complaint import (
    Complaint,
    ComplaintCategory,
    ComplaintComment,
    ComplaintPriority,
    ComplaintStatus,
)
from app.models.hostel import Block, GenderType, Hostel, WardenAssignment
from app.models.mess import MealOptOut, MealType, MessMenu
from app.models.notice import Notice, NoticeAudience, NoticeRead
from app.models.operations import (
    AttendanceLog,
    AttendanceType,
    LeaveRequest,
    LeaveStatus,
    Visitor,
)
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole

DEFAULT_ADMIN_EMAIL = "admin@hostel.example.com"
DEFAULT_ADMIN_PASS = "AdminPass123"  # noqa: S105
DEFAULT_WARDEN_BOYS_EMAIL = "warden.boys@hostel.example.com"
DEFAULT_WARDEN_GIRLS_EMAIL = "warden.girls@hostel.example.com"
DEFAULT_WARDEN_PASS = "WardenPass123"  # noqa: S105
DEFAULT_STUDENT_PASS = "StudentPass123"  # noqa: S105


async def reset_database(session: AsyncSession) -> None:
    """Clear all application table records in reverse dependency order."""
    print("🧹 Resetting database tables...")
    await session.execute(delete(AuditLog))
    await session.execute(delete(NoticeRead))
    await session.execute(delete(Notice))
    await session.execute(delete(MealOptOut))
    await session.execute(delete(MessMenu))
    await session.execute(delete(ComplaintComment))
    await session.execute(delete(Complaint))
    await session.execute(delete(Visitor))
    await session.execute(delete(LeaveRequest))
    await session.execute(delete(AttendanceLog))
    await session.execute(delete(Payment))
    await session.execute(delete(Invoice))
    await session.execute(delete(FeeStructure))
    await session.execute(delete(Allocation))
    await session.execute(delete(StudentProfile))
    await session.execute(delete(Bed))
    await session.execute(delete(Room))
    await session.execute(delete(WardenAssignment))
    await session.execute(delete(Block))
    await session.execute(delete(Hostel))
    await session.execute(delete(User))
    await session.commit()
    print("✅ All existing records purged.")


async def seed_data(reset: bool = False) -> None:
    """Populate database with comprehensive demo dataset."""
    settings = get_settings()

    # Safety guard: refuse to seed production environments
    env_str = str(os.getenv("APP_ENV", settings.APP_ENV)).strip().lower()
    if env_str == "production":
        print("❌ ERROR: Cannot run seed script in 'production' environment!", file=sys.stderr)
        sys.exit(1)

    async with async_session_maker() as session:
        # Check idempotency if not resetting
        if not reset:
            existing_admin = await session.execute(
                select(User).where(User.email == DEFAULT_ADMIN_EMAIL)
            )
            if existing_admin.scalar_one_or_none() is not None:
                print("[INFO] Database already seeded. Use --reset to re-seed from scratch.")
                return
        else:
            await reset_database(session)

        print("🌱 Seeding realistic hostel management dataset...")
        now = datetime.now(UTC)
        today = date.today()

        # 1. Administrative and Warden Users
        admin_user = User(
            id=uuid4(),
            email=DEFAULT_ADMIN_EMAIL,
            full_name="System Administrator",
            hashed_password=hash_password(DEFAULT_ADMIN_PASS),
            role=UserRole.ADMIN,
            phone="+919876543200",
            is_active=True,
        )

        warden_boys = User(
            id=uuid4(),
            email=DEFAULT_WARDEN_BOYS_EMAIL,
            full_name="Prof. Rajesh Sharma (Boys Warden)",
            hashed_password=hash_password(DEFAULT_WARDEN_PASS),
            role=UserRole.WARDEN,
            phone="+919876543201",
            is_active=True,
        )

        warden_girls = User(
            id=uuid4(),
            email=DEFAULT_WARDEN_GIRLS_EMAIL,
            full_name="Dr. Sunita Verma (Girls Warden)",
            hashed_password=hash_password(DEFAULT_WARDEN_PASS),
            role=UserRole.WARDEN,
            phone="+919876543202",
            is_active=True,
        )

        session.add_all([admin_user, warden_boys, warden_girls])
        await session.flush()

        # 2. Hostels
        hostel_boys = Hostel(
            id=uuid4(),
            name="Aryabhatta Hall of Residence",
            code="ABH",
            gender_type=GenderType.MALE,
            address="North Campus, Academic Road",
            total_capacity=50,
        )

        hostel_girls = Hostel(
            id=uuid4(),
            name="Gargi Hall of Residence",
            code="GGH",
            gender_type=GenderType.FEMALE,
            address="South Campus, Lake View Road",
            total_capacity=50,
        )

        session.add_all([hostel_boys, hostel_girls])
        await session.flush()

        # 3. Warden Assignments
        assign_boys = WardenAssignment(
            id=uuid4(),
            user_id=warden_boys.id,
            hostel_id=hostel_boys.id,
        )
        assign_girls = WardenAssignment(
            id=uuid4(),
            user_id=warden_girls.id,
            hostel_id=hostel_girls.id,
        )
        session.add_all([assign_boys, assign_girls])
        await session.flush()

        # 4. Blocks (2 per hostel)
        block_ab_a = Block(id=uuid4(), hostel_id=hostel_boys.id, name="Block A", floor_count=3)
        block_ab_b = Block(id=uuid4(), hostel_id=hostel_boys.id, name="Block B", floor_count=3)
        block_gg_a = Block(id=uuid4(), hostel_id=hostel_girls.id, name="Block A", floor_count=3)
        block_gg_b = Block(id=uuid4(), hostel_id=hostel_girls.id, name="Block B", floor_count=3)

        blocks = [block_ab_a, block_ab_b, block_gg_a, block_gg_b]
        session.add_all(blocks)
        await session.flush()

        # 5. Rooms and Beds (10 rooms per block -> 40 rooms total, 100 beds)
        rooms: list[Room] = []
        beds: list[Bed] = []

        room_specs = [
            ("101", RoomType.SINGLE, 1, Decimal("15000.00"), 1),
            ("102", RoomType.SINGLE, 1, Decimal("15000.00"), 1),
            ("103", RoomType.DOUBLE, 2, Decimal("10000.00"), 1),
            ("104", RoomType.DOUBLE, 2, Decimal("10000.00"), 1),
            ("105", RoomType.DOUBLE, 2, Decimal("10000.00"), 1),
            ("201", RoomType.TRIPLE, 3, Decimal("7500.00"), 2),
            ("202", RoomType.TRIPLE, 3, Decimal("7500.00"), 2),
            ("203", RoomType.TRIPLE, 3, Decimal("7500.00"), 2),
            ("204", RoomType.DORM, 4, Decimal("5000.00"), 2),
            ("205", RoomType.DORM, 4, Decimal("5000.00"), 2),
        ]

        for blk in blocks:
            for num, rtype, cap, rent, floor in room_specs:
                r = Room(
                    id=uuid4(),
                    block_id=blk.id,
                    number=f"{blk.name[-1]}-{num}",
                    floor=floor,
                    capacity=cap,
                    room_type=rtype,
                    monthly_rent=rent,
                    status=RoomStatus.AVAILABLE,
                )
                rooms.append(r)

        session.add_all(rooms)
        await session.flush()

        # Generate beds for all rooms
        for r in rooms:
            for i in range(r.capacity):
                label = chr(ord("A") + i)
                b = Bed(
                    id=uuid4(),
                    room_id=r.id,
                    label=label,
                    is_occupied=False,
                )
                beds.append(b)

        session.add_all(beds)
        await session.flush()

        # 6. Fee Structures (Monthly per hostel & room type)
        fee_structures: list[FeeStructure] = []
        for h in [hostel_boys, hostel_girls]:
            fee_structures.extend(
                [
                    FeeStructure(
                        id=uuid4(),
                        hostel_id=h.id,
                        room_type=RoomType.SINGLE,
                        period=FeePeriod.MONTHLY,
                        amount=Decimal("15000.00"),
                        is_active=True,
                    ),
                    FeeStructure(
                        id=uuid4(),
                        hostel_id=h.id,
                        room_type=RoomType.DOUBLE,
                        period=FeePeriod.MONTHLY,
                        amount=Decimal("10000.00"),
                        is_active=True,
                    ),
                    FeeStructure(
                        id=uuid4(),
                        hostel_id=h.id,
                        room_type=RoomType.TRIPLE,
                        period=FeePeriod.MONTHLY,
                        amount=Decimal("7500.00"),
                        is_active=True,
                    ),
                    FeeStructure(
                        id=uuid4(),
                        hostel_id=h.id,
                        room_type=RoomType.DORM,
                        period=FeePeriod.MONTHLY,
                        amount=Decimal("5000.00"),
                        is_active=True,
                    ),
                ]
            )
        session.add_all(fee_structures)
        await session.flush()

        # 7. Students (80 students: 40 male for Aryabhatta, 40 female for Gargi)
        first_names_male = [
            "Aarav",
            "Aditya",
            "Amit",
            "Anand",
            "Aryan",
            "Ayush",
            "Bhuvan",
            "Chetan",
            "Dev",
            "Dhruv",
            "Gaurav",
            "Harsh",
            "Ishan",
            "Jay",
            "Kabir",
            "Karan",
            "Manish",
            "Mayank",
            "Mohit",
            "Naveen",
            "Nikhil",
            "Omkar",
            "Pankaj",
            "Pranav",
            "Rahul",
            "Rajat",
            "Rishi",
            "Rohan",
            "Rohit",
            "Sahil",
            "Sameer",
            "Sanjay",
            "Shivam",
            "Siddharth",
            "Sumit",
            "Tanmay",
            "Utkarsh",
            "Varun",
            "Vikas",
            "Yash",
        ]
        first_names_female = [
            "Aadya",
            "Ananya",
            "Ankita",
            "Avani",
            "Bhavna",
            "Deepika",
            "Divya",
            "Gauri",
            "Ishita",
            "Jyoti",
            "Kavya",
            "Khushi",
            "Kriti",
            "Meera",
            "Neha",
            "Nikita",
            "Palak",
            "Pooja",
            "Prerna",
            "Priya",
            "Radhika",
            "Rhea",
            "Riddhi",
            "Riya",
            "Sakshi",
            "Samiksha",
            "Sanya",
            "Shreya",
            "Simran",
            "Sneha",
            "Sonam",
            "Srishti",
            "Swati",
            "Tanvi",
            "Tara",
            "Trisha",
            "Vaidehi",
            "Vandana",
            "Vidhi",
            "Zoya",
        ]
        last_names = [
            "Sharma",
            "Verma",
            "Patel",
            "Gupta",
            "Singh",
            "Kumar",
            "Mishra",
            "Joshi",
            "Reddy",
            "Nair",
            "Iyer",
            "Choudhury",
            "Bose",
            "Ghosh",
            "Das",
            "Mukherjee",
            "Yadav",
            "Pandey",
            "Tiwari",
            "Bhatnagar",
        ]

        male_students: list[tuple[User, StudentProfile]] = []
        female_students: list[tuple[User, StudentProfile]] = []

        hashed_student_pw = hash_password(DEFAULT_STUDENT_PASS)

        for i, fn in enumerate(first_names_male, start=1):
            ln = last_names[i % len(last_names)]
            student_no = f"STU-B{i:03d}"
            email = f"student.b{i:03d}@hostel.example.com"
            u = User(
                id=uuid4(),
                email=email,
                full_name=f"{fn} {ln}",
                hashed_password=hashed_student_pw,
                role=UserRole.STUDENT,
                phone=f"+9198110{i:05d}",
                is_active=True,
            )
            prof = StudentProfile(
                id=uuid4(),
                user_id=u.id,
                student_no=student_no,
                gender=GenderType.MALE,
                department="Computer Science" if i % 2 == 0 else "Electrical Engineering",
                year=((i % 4) + 1),
                guardian_name=f"Mr. {ln}",
                guardian_phone=f"+9198220{i:05d}",
                emergency_contact=f"+9198330{i:05d}",
            )
            male_students.append((u, prof))

        for i, fn in enumerate(first_names_female, start=1):
            ln = last_names[i % len(last_names)]
            student_no = f"STU-G{i:03d}"
            email = f"student.g{i:03d}@hostel.example.com"
            u = User(
                id=uuid4(),
                email=email,
                full_name=f"{fn} {ln}",
                hashed_password=hashed_student_pw,
                role=UserRole.STUDENT,
                phone=f"+9198440{i:05d}",
                is_active=True,
            )
            prof = StudentProfile(
                id=uuid4(),
                user_id=u.id,
                student_no=student_no,
                gender=GenderType.FEMALE,
                department="Information Technology" if i % 2 == 0 else "Mechanical Engineering",
                year=((i % 4) + 1),
                guardian_name=f"Mr. {ln}",
                guardian_phone=f"+9198550{i:05d}",
                emergency_contact=f"+9198660{i:05d}",
            )
            female_students.append((u, prof))

        all_students = male_students + female_students
        for u, prof in all_students:
            session.add(u)
            session.add(prof)
        await session.flush()

        # 8. Allocations:
        boy_room_ids = {r.id for r in rooms if r.block_id in (block_ab_a.id, block_ab_b.id)}
        girl_room_ids = {r.id for r in rooms if r.block_id in (block_gg_a.id, block_gg_b.id)}

        boy_beds = [b for b in beds if b.room_id in boy_room_ids]
        girl_beds = [b for b in beds if b.room_id in girl_room_ids]

        allocations: list[Allocation] = []
        active_allocations: list[Allocation] = []

        # Allocate 35 active boys
        for idx in range(35):
            u, prof = male_students[idx]
            bed = boy_beds[idx]
            bed.is_occupied = True
            alloc = Allocation(
                id=uuid4(),
                student_id=prof.id,
                bed_id=bed.id,
                start_date=today - timedelta(days=60),
                status=AllocationStatus.ACTIVE,
            )
            allocations.append(alloc)
            active_allocations.append(alloc)

        # 5 vacated boys (past allocation)
        for idx in range(35, 40):
            u, prof = male_students[idx]
            bed = boy_beds[idx]
            alloc = Allocation(
                id=uuid4(),
                student_id=prof.id,
                bed_id=bed.id,
                start_date=today - timedelta(days=180),
                end_date=today - timedelta(days=90),
                status=AllocationStatus.ENDED,
            )
            allocations.append(alloc)

        # Allocate 35 active girls
        for idx in range(35):
            u, prof = female_students[idx]
            bed = girl_beds[idx]
            bed.is_occupied = True
            alloc = Allocation(
                id=uuid4(),
                student_id=prof.id,
                bed_id=bed.id,
                start_date=today - timedelta(days=60),
                status=AllocationStatus.ACTIVE,
            )
            allocations.append(alloc)
            active_allocations.append(alloc)

        # 5 vacated girls (past allocation)
        for idx in range(35, 40):
            u, prof = female_students[idx]
            bed = girl_beds[idx]
            alloc = Allocation(
                id=uuid4(),
                student_id=prof.id,
                bed_id=bed.id,
                start_date=today - timedelta(days=180),
                end_date=today - timedelta(days=90),
                status=AllocationStatus.ENDED,
            )
            allocations.append(alloc)

        session.add_all(allocations)
        await session.flush()

        # 9. Invoices and Payments for Active Allocations
        invoices: list[Invoice] = []
        payments: list[Payment] = []

        bed_map = {b.id: b for b in beds}
        room_map = {r.id: r for r in rooms}
        month_start = today.replace(day=1)
        month_end = today.replace(day=28)

        for idx, alloc in enumerate(active_allocations):
            bed = bed_map[alloc.bed_id]
            room = room_map[bed.room_id]
            rent = room.monthly_rent

            # 0-30: PAID
            # 31-50: PARTIAL
            # 51-60: UNPAID (due soon)
            # 61-69: OVERDUE (past due date)
            if idx < 30:
                inv = Invoice(
                    id=uuid4(),
                    student_id=alloc.student_id,
                    allocation_id=alloc.id,
                    period_start=month_start,
                    period_end=month_end,
                    amount=rent,
                    paid_amount=rent,
                    due_date=today.replace(day=15),
                    status=InvoiceStatus.PAID,
                )
                invoices.append(inv)
                pay = Payment(
                    id=uuid4(),
                    invoice_id=inv.id,
                    amount=rent,
                    method=PaymentMethod.CARD if idx % 2 == 0 else PaymentMethod.ONLINE,
                    reference=f"PAY-{inv.id.hex[:8].upper()}",
                    paid_at=now - timedelta(days=idx % 10 + 1),
                )
                payments.append(pay)
            elif idx < 50:
                partial_amt = (rent / Decimal("2")).quantize(Decimal("0.01"))
                inv = Invoice(
                    id=uuid4(),
                    student_id=alloc.student_id,
                    allocation_id=alloc.id,
                    period_start=month_start,
                    period_end=month_end,
                    amount=rent,
                    paid_amount=partial_amt,
                    due_date=today.replace(day=15),
                    status=InvoiceStatus.PARTIAL,
                )
                invoices.append(inv)
                pay = Payment(
                    id=uuid4(),
                    invoice_id=inv.id,
                    amount=partial_amt,
                    method=PaymentMethod.BANK,
                    reference=f"PAY-{inv.id.hex[:8].upper()}",
                    paid_at=now - timedelta(days=2),
                )
                payments.append(pay)
            elif idx < 60:
                inv = Invoice(
                    id=uuid4(),
                    student_id=alloc.student_id,
                    allocation_id=alloc.id,
                    period_start=month_start,
                    period_end=month_end,
                    amount=rent,
                    paid_amount=Decimal("0.00"),
                    due_date=today + timedelta(days=10),
                    status=InvoiceStatus.UNPAID,
                )
                invoices.append(inv)
            else:
                inv = Invoice(
                    id=uuid4(),
                    student_id=alloc.student_id,
                    allocation_id=alloc.id,
                    period_start=month_start - timedelta(days=30),
                    period_end=month_end - timedelta(days=30),
                    amount=rent,
                    paid_amount=Decimal("0.00"),
                    due_date=today - timedelta(days=14),
                    status=InvoiceStatus.OVERDUE,
                )
                invoices.append(inv)

        session.add_all(invoices)
        await session.flush()
        session.add_all(payments)
        await session.flush()

        # 10. Operations: Attendance
        att_logs: list[AttendanceLog] = []
        for idx, alloc in enumerate(active_allocations[:45]):
            log = AttendanceLog(
                id=uuid4(),
                student_id=alloc.student_id,
                type=AttendanceType.CHECK_IN,
                timestamp=now - timedelta(hours=3),
                recorded_by=warden_boys.id if idx % 2 == 0 else warden_girls.id,
                remarks="Routine campus entry",
            )
            att_logs.append(log)

        for idx, alloc in enumerate(active_allocations[45:55]):
            rec_id = warden_boys.id if idx % 2 == 0 else warden_girls.id
            log1 = AttendanceLog(
                id=uuid4(),
                student_id=alloc.student_id,
                type=AttendanceType.CHECK_IN,
                timestamp=now - timedelta(hours=8),
                recorded_by=rec_id,
                remarks="Morning entry",
            )
            log2 = AttendanceLog(
                id=uuid4(),
                student_id=alloc.student_id,
                type=AttendanceType.CHECK_OUT,
                timestamp=now - timedelta(hours=1),
                recorded_by=rec_id,
                remarks="Outing permitted",
            )
            att_logs.extend([log1, log2])

        session.add_all(att_logs)
        await session.flush()

        # 11. Leave Requests
        leaves: list[LeaveRequest] = []
        for idx in range(5):
            alloc = active_allocations[idx]
            leaves.append(
                LeaveRequest(
                    id=uuid4(),
                    student_id=alloc.student_id,
                    from_date=today,
                    to_date=today + timedelta(days=3),
                    reason="Family function at hometown",
                    status=LeaveStatus.APPROVED,
                    reviewed_by=warden_boys.id,
                    reviewed_at=now - timedelta(days=1),
                    review_notes="Approved with guardian verification.",
                )
            )
        for idx in range(5, 10):
            alloc = active_allocations[idx]
            leaves.append(
                LeaveRequest(
                    id=uuid4(),
                    student_id=alloc.student_id,
                    from_date=today + timedelta(days=1),
                    to_date=today + timedelta(days=4),
                    reason="Attending technical conference",
                    status=LeaveStatus.PENDING,
                )
            )
        session.add_all(leaves)
        await session.flush()

        # 12. Visitors
        visitors: list[Visitor] = []
        for idx in range(6):
            alloc = active_allocations[idx]
            visitors.append(
                Visitor(
                    id=uuid4(),
                    student_id=alloc.student_id,
                    name=f"Visitor {idx + 1}",
                    relation="Parent" if idx % 2 == 0 else "Sibling",
                    phone=f"+9199000{idx:05d}",
                    check_in_at=now - timedelta(hours=2),
                    check_out_at=now - timedelta(minutes=30) if idx % 2 == 0 else None,
                    remarks="Official visiting hours visit",
                )
            )
        session.add_all(visitors)
        await session.flush()

        # 13. Complaints
        complaints: list[Complaint] = []
        categories = list(ComplaintCategory)
        for idx in range(12):
            alloc = active_allocations[idx]
            bed = bed_map[alloc.bed_id]
            st = (
                ComplaintStatus.OPEN
                if idx < 4
                else (ComplaintStatus.IN_PROGRESS if idx < 7 else ComplaintStatus.RESOLVED)
            )
            cat = categories[idx % len(categories)]
            comp = Complaint(
                id=uuid4(),
                student_id=alloc.student_id,
                room_id=bed.room_id,
                title=f"{cat.value.capitalize()} issue in room",
                description="Requires inspection and repair as soon as possible.",
                category=cat,
                priority=ComplaintPriority.MEDIUM if idx % 2 == 0 else ComplaintPriority.HIGH,
                status=st,
                resolved_at=now - timedelta(hours=2) if st == ComplaintStatus.RESOLVED else None,
            )
            complaints.append(comp)

        session.add_all(complaints)
        await session.flush()

        # 14. Mess Menus (Weekly for both hostels)
        menus: list[MessMenu] = []
        meal_dishes = {
            MealType.BREAKFAST: ["Idli", "Sambar", "Coconut Chutney", "Tea", "Coffee"],
            MealType.LUNCH: ["Rice", "Dal Makhani", "Paneer Butter Masala", "Cucumber Salad"],
            MealType.SNACKS: ["Samosa", "Mint Chutney", "Masala Chai"],
            MealType.DINNER: ["Roti", "Dal Tadka", "Mixed Vegetable Curry", "Kheer"],
        }
        for h in [hostel_boys, hostel_girls]:
            for dow in range(7):  # 0=Monday to 6=Sunday
                for mt, dishes in meal_dishes.items():
                    menus.append(
                        MessMenu(
                            id=uuid4(),
                            hostel_id=h.id,
                            day_of_week=dow,
                            meal_type=mt,
                            items=dishes,
                        )
                    )
        session.add_all(menus)
        await session.flush()

        # 15. Notices
        notices = [
            Notice(
                id=uuid4(),
                title="Welcome to the New Academic Session 2026-27",
                body="Hostel gates close strictly at 22:00 IST. Please ensure adherence to rules.",
                audience=NoticeAudience.ALL,
                is_pinned=True,
                published_at=now - timedelta(days=5),
            ),
            Notice(
                id=uuid4(),
                hostel_id=hostel_boys.id,
                title="Aryabhatta Hall: Scheduled Electrical Maintenance",
                body="Power backup generator testing will be conducted on Saturday 10:00 - 12:00.",
                audience=NoticeAudience.STUDENTS,
                is_pinned=False,
                published_at=now - timedelta(days=1),
            ),
            Notice(
                id=uuid4(),
                hostel_id=hostel_girls.id,
                title="Gargi Hall: Annual Cultural Fest Committee Meeting",
                body="All floor representatives to meet at the common hall on Friday 18:00.",
                audience=NoticeAudience.STUDENTS,
                is_pinned=False,
                published_at=now - timedelta(days=2),
            ),
        ]
        session.add_all(notices)
        await session.flush()

        # Mark some notices read
        notice_reads = [
            NoticeRead(
                id=uuid4(),
                notice_id=notices[0].id,
                user_id=male_students[0][0].id,
                read_at=now - timedelta(days=3),
            )
        ]
        session.add_all(notice_reads)
        await session.commit()

        print("\n✨ Database seeding completed successfully!")
        print("=" * 65)
        print(f"Hostels:        2 ({hostel_boys.name}, {hostel_girls.name})")
        print(f"Blocks:         {len(blocks)}")
        print(f"Rooms:          {len(rooms)}")
        print(f"Beds:           {len(beds)}")
        print(f"Students:       {len(all_students)} (40 Male, 40 Female)")
        print(f"Allocations:    {len(allocations)} (70 Active, 10 Vacated)")
        print(f"Invoices:       {len(invoices)} (Paid, Partial, Unpaid, Overdue)")
        print(f"Attendance:     {len(att_logs)} logs recorded")
        print(f"Complaints:     {len(complaints)} open / in-progress / resolved")
        print(f"Weekly Menus:   {len(menus)} meal slots configured")
        print(f"Notices:        {len(notices)} system notices published")
        print("=" * 65)
        print("\n🔑 DEMO LOGIN CREDENTIALS:")
        print("-" * 65)
        print(f"Admin:        {DEFAULT_ADMIN_EMAIL:<35} Password: {DEFAULT_ADMIN_PASS}")
        print(f"Warden (Boys):{DEFAULT_WARDEN_BOYS_EMAIL:<35} Password: {DEFAULT_WARDEN_PASS}")
        print(f"Warden (Girls):{DEFAULT_WARDEN_GIRLS_EMAIL:<35} Password: {DEFAULT_WARDEN_PASS}")
        print(f"Student (Male): student.b001@hostel.example.com Password: {DEFAULT_STUDENT_PASS}")
        print(f"Student (Fem):  student.g001@hostel.example.com Password: {DEFAULT_STUDENT_PASS}")
        print("-" * 65)


def main() -> None:
    """CLI entrypoint parsing arguments."""
    parser = argparse.ArgumentParser(description="Seed hostel database with realistic sample data")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Purge existing records before seeding",
    )
    args = parser.parse_args()
    asyncio.run(seed_data(reset=args.reset))


if __name__ == "__main__":
    main()
