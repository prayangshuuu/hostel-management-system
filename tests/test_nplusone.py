"""N+1 query audit, soft-delete leak verification, and database error translation tests."""

from datetime import date
from decimal import Decimal
from types import TracebackType
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models.allocation import Allocation, AllocationStatus
from app.models.billing import Invoice, InvoiceStatus
from app.models.complaint import (
    Complaint,
    ComplaintCategory,
    ComplaintPriority,
    ComplaintStatus,
)
from app.models.hostel import Block, GenderType, Hostel
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.repositories.allocation_repository import AllocationRepository
from app.repositories.student_repository import StudentRepository
from app.schemas.common import PaginationParams


class QueryCounter:
    """Context manager to intercept and count SQL queries executed via SQLAlchemy engine."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.queries: list[str] = []

    def _callback(
        self,
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        stmt = statement.strip()
        self.queries.append(stmt)

    def __enter__(self) -> "QueryCounter":
        self.queries.clear()
        event.listen(self.engine.sync_engine, "before_cursor_execute", self._callback)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        event.remove(self.engine.sync_engine, "before_cursor_execute", self._callback)

    @property
    def count(self) -> int:
        return len(self.queries)

    @property
    def select_queries(self) -> list[str]:
        return [q for q in self.queries if q.upper().startswith("SELECT")]

    @property
    def select_count(self) -> int:
        return len(self.select_queries)


def create_auth_headers(user: User) -> dict[str, str]:
    """Helper to generate bearer token header for a user."""
    token = create_access_token(user_id=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_nplusone_room_list_with_beds(
    client: AsyncClient,
    test_engine: AsyncEngine,
    admin_user: User,
    db_session: AsyncSession,
) -> None:
    """Verify listing rooms with beds executes an upper bound of queries."""
    hostel = Hostel(
        id=uuid4(),
        name="N1 Hostel",
        code="N1-H",
        gender_type=GenderType.MIXED,
    )
    block = Block(id=uuid4(), hostel_id=hostel.id, name="Block A", floor_count=3)
    db_session.add_all([hostel, block])
    await db_session.flush()

    for i in range(10):
        room = Room(
            id=uuid4(),
            block_id=block.id,
            number=f"Room-{100 + i}",
            floor=1,
            room_type=RoomType.DOUBLE,
            capacity=2,
            monthly_rent=Decimal("500.00"),
            status=RoomStatus.AVAILABLE,
        )
        db_session.add(room)
        await db_session.flush()
        bed_a = Bed(id=uuid4(), room_id=room.id, label="A", is_occupied=False)
        bed_b = Bed(id=uuid4(), room_id=room.id, label="B", is_occupied=False)
        db_session.add_all([bed_a, bed_b])
    await db_session.commit()

    headers = create_auth_headers(admin_user)

    with QueryCounter(test_engine) as counter:
        path = f"/api/v1/blocks/{block.id}/rooms?page=1&size=20"
        response = await client.get(path, headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 10
        for item in data["items"]:
            assert "beds_count" in str(item) or "capacity" in item

    # Query count bounded: auth + block check + count + select rooms + selectinload beds <= 5
    msg = f"Expected <= 5 select queries, got {counter.select_count}: {counter.select_queries}"
    assert counter.select_count <= 5, msg


@pytest.mark.asyncio
async def test_nplusone_student_list_with_profile_and_allocation(
    client: AsyncClient,
    test_engine: AsyncEngine,
    admin_user: User,
    db_session: AsyncSession,
) -> None:
    """Verify student list with profiles and allocations executes a constant number of queries."""
    hostel = Hostel(id=uuid4(), name="Student Hostel", code="SH-01", gender_type=GenderType.MIXED)
    block = Block(id=uuid4(), hostel_id=hostel.id, name="Block S", floor_count=2)
    room = Room(
        id=uuid4(),
        block_id=block.id,
        number="S-101",
        floor=1,
        room_type=RoomType.DORM,
        capacity=10,
        monthly_rent=Decimal("300.00"),
        status=RoomStatus.AVAILABLE,
    )
    db_session.add_all([hostel, block, room])
    await db_session.flush()

    beds = [Bed(id=uuid4(), room_id=room.id, label=f"B{i}", is_occupied=True) for i in range(10)]
    db_session.add_all(beds)
    await db_session.flush()

    for i in range(10):
        student_user = User(
            id=uuid4(),
            email=f"n1_student_{i}@example.com",
            full_name=f"Student {i}",
            hashed_password=hash_password("Pass123"),
            role=UserRole.STUDENT,
            is_active=True,
        )
        db_session.add(student_user)
        await db_session.flush()

        profile = StudentProfile(
            id=uuid4(),
            user_id=student_user.id,
            student_no=f"STU-N1-{i:03d}",
            gender=GenderType.MALE if i % 2 == 0 else GenderType.FEMALE,
            department="CS",
            year=2,
            guardian_name="Guardian",
            guardian_phone="+1234567890",
            emergency_contact="+1987654321",
        )
        db_session.add(profile)
        await db_session.flush()

        alloc = Allocation(
            id=uuid4(),
            student_id=profile.id,
            bed_id=beds[i].id,
            start_date=date.today(),
            status=AllocationStatus.ACTIVE,
        )
        db_session.add(alloc)

    await db_session.commit()

    headers = create_auth_headers(admin_user)

    with QueryCounter(test_engine) as counter:
        response = await client.get("/api/v1/students?page=1&size=20", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) >= 10
        for item in data["items"]:
            assert item["full_name"] is not None
            if item["student_no"].startswith("STU-N1-"):
                assert item["current_allocation"] is not None

    msg = f"Expected <= 6 select queries, got {counter.select_count}: {counter.select_queries}"
    assert counter.select_count <= 6, msg


@pytest.mark.asyncio
async def test_nplusone_hostel_list_capacity_aggregation(
    client: AsyncClient,
    test_engine: AsyncEngine,
    admin_user: User,
    db_session: AsyncSession,
) -> None:
    """Verify hostel list with capacity executes a batch query rather than N+1 queries."""
    for i in range(8):
        hostel = Hostel(
            id=uuid4(),
            name=f"Cap Hostel {i}",
            code=f"CAP-{i}",
            gender_type=GenderType.MIXED,
        )
        db_session.add(hostel)
        await db_session.flush()

        block = Block(id=uuid4(), hostel_id=hostel.id, name="Block Main", floor_count=2)
        db_session.add(block)
        await db_session.flush()

        room = Room(
            id=uuid4(),
            block_id=block.id,
            number="101",
            floor=1,
            room_type=RoomType.DOUBLE,
            capacity=2,
            monthly_rent=Decimal("400.00"),
            status=RoomStatus.AVAILABLE,
        )
        db_session.add(room)

    await db_session.commit()

    headers = create_auth_headers(admin_user)

    with QueryCounter(test_engine) as counter:
        response = await client.get("/api/v1/hostels?page=1&size=20", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) >= 8
        for item in data["items"]:
            if item["code"].startswith("CAP-"):
                assert item["total_capacity"] == 2

    msg = f"Expected <= 4 select queries, got {counter.select_count}: {counter.select_queries}"
    assert counter.select_count <= 4, msg


@pytest.mark.asyncio
async def test_nplusone_allocations_list(
    client: AsyncClient,
    test_engine: AsyncEngine,
    admin_user: User,
    db_session: AsyncSession,
) -> None:
    """Verify listing allocations with nested details executes bounded queries."""
    hostel = Hostel(id=uuid4(), name="Alloc Hostel", code="AL-01", gender_type=GenderType.MIXED)
    block = Block(id=uuid4(), hostel_id=hostel.id, name="Block A", floor_count=1)
    db_session.add_all([hostel, block])
    await db_session.flush()

    for i in range(8):
        room = Room(
            id=uuid4(),
            block_id=block.id,
            number=f"Room-{i}",
            floor=1,
            room_type=RoomType.SINGLE,
            capacity=1,
            monthly_rent=Decimal("600.00"),
            status=RoomStatus.FULL,
        )
        db_session.add(room)
        await db_session.flush()

        bed = Bed(id=uuid4(), room_id=room.id, label="A", is_occupied=True)
        db_session.add(bed)
        await db_session.flush()

        stu_user = User(
            id=uuid4(),
            email=f"alloc_user_{i}@example.com",
            full_name=f"Alloc User {i}",
            hashed_password=hash_password("Pass123"),
            role=UserRole.STUDENT,
            is_active=True,
        )
        db_session.add(stu_user)
        await db_session.flush()

        profile = StudentProfile(
            id=uuid4(),
            user_id=stu_user.id,
            student_no=f"STU-AL-{i}",
            gender=GenderType.MIXED,
            department="EEE",
            year=1,
            guardian_name="Guardian",
            guardian_phone="+1234567890",
            emergency_contact="+1987654321",
        )
        db_session.add(profile)
        await db_session.flush()

        alloc = Allocation(
            id=uuid4(),
            student_id=profile.id,
            bed_id=bed.id,
            start_date=date.today(),
            status=AllocationStatus.ACTIVE,
        )
        db_session.add(alloc)

    await db_session.commit()

    headers = create_auth_headers(admin_user)

    with QueryCounter(test_engine) as counter:
        response = await client.get("/api/v1/allocations?page=1&size=20", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) >= 8
        for item in data["items"]:
            assert item["student_name"] is not None
            assert item["room_number"] is not None
            assert item["bed_label"] is not None
            assert item["hostel_name"] is not None

    msg = f"Expected <= 5 select queries, got {counter.select_count}: {counter.select_queries}"
    assert counter.select_count <= 5, msg


@pytest.mark.asyncio
async def test_soft_delete_leak_student_and_allocations(
    db_session: AsyncSession,
) -> None:
    """Verify soft-deleted students and inactive allocations do not leak into active checks."""
    user = User(
        id=uuid4(),
        email="soft_leak_stu@example.com",
        full_name="Soft Leak Student",
        hashed_password=hash_password("Pass123"),
        role=UserRole.STUDENT,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    hostel = Hostel(id=uuid4(), name="Soft Hostel", code="SF-H", gender_type=GenderType.MIXED)
    block = Block(id=uuid4(), hostel_id=hostel.id, name="Block SF", floor_count=1)
    room = Room(
        id=uuid4(),
        block_id=block.id,
        number="SF-101",
        floor=1,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("500.00"),
        status=RoomStatus.AVAILABLE,
    )
    bed = Bed(id=uuid4(), room_id=room.id, label="A", is_occupied=False)
    db_session.add_all([hostel, block, room, bed])
    await db_session.flush()

    profile = StudentProfile(
        id=uuid4(),
        user_id=user.id,
        student_no="STU-LEAK-01",
        gender=GenderType.MALE,
        department="Math",
        year=3,
        guardian_name="Guardian",
        guardian_phone="+1234567890",
        emergency_contact="+1987654321",
        is_deleted=True,
    )
    db_session.add(profile)
    await db_session.flush()

    alloc = Allocation(
        id=uuid4(),
        student_id=profile.id,
        bed_id=bed.id,
        start_date=date.today(),
        status=AllocationStatus.ACTIVE,
    )
    db_session.add(alloc)
    await db_session.commit()

    alloc_repo = AllocationRepository(db_session)
    student_repo = StudentRepository(db_session)

    # 1. Soft-deleted student must not appear in active allocation checks
    active_alloc = await alloc_repo.get_active_by_student_id(profile.id)
    assert active_alloc is None

    # 2. Batch query must not return active allocation for soft-deleted student
    alloc_map = await alloc_repo.get_active_by_student_ids([profile.id])
    assert profile.id not in alloc_map

    # 3. Room occupants must not include soft-deleted student
    occupants = await alloc_repo.get_room_occupants(room.id)
    assert not any(o.student_id == profile.id for o in occupants)

    # 4. Student repository list must exclude soft-deleted student
    students, total = await student_repo.list(
        PaginationParams(page=1, size=20), search="STU-LEAK-01"
    )
    assert total == 0
    assert len(students) == 0


@pytest.mark.asyncio
async def test_inactive_vacated_allocation_leak(
    db_session: AsyncSession,
) -> None:
    """Verify that vacated/ended and cancelled allocations do not leak into active checks."""
    user = User(
        id=uuid4(),
        email="vacated_stu@example.com",
        full_name="Vacated Student",
        hashed_password=hash_password("Pass123"),
        role=UserRole.STUDENT,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    hostel = Hostel(id=uuid4(), name="Vac Hostel", code="VAC-H", gender_type=GenderType.MIXED)
    block = Block(id=uuid4(), hostel_id=hostel.id, name="Block V", floor_count=1)
    room = Room(
        id=uuid4(),
        block_id=block.id,
        number="V-101",
        floor=1,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("500.00"),
        status=RoomStatus.AVAILABLE,
    )
    bed = Bed(id=uuid4(), room_id=room.id, label="A", is_occupied=False)
    db_session.add_all([hostel, block, room, bed])
    await db_session.flush()

    profile = StudentProfile(
        id=uuid4(),
        user_id=user.id,
        student_no="STU-VAC-01",
        gender=GenderType.MALE,
        department="Physics",
        year=1,
        guardian_name="Guardian",
        guardian_phone="+1234567890",
        emergency_contact="+1987654321",
        is_deleted=False,
    )
    db_session.add(profile)
    await db_session.flush()

    ended_alloc = Allocation(
        id=uuid4(),
        student_id=profile.id,
        bed_id=bed.id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 6, 30),
        status=AllocationStatus.ENDED,
    )
    db_session.add(ended_alloc)
    await db_session.commit()

    alloc_repo = AllocationRepository(db_session)

    # 1. get_active_by_student_id must return None for ended allocation
    assert await alloc_repo.get_active_by_student_id(profile.id) is None

    # 2. get_active_by_bed_id must return None
    assert await alloc_repo.get_active_by_bed_id(bed.id) is None

    # 3. get_room_occupants must be empty
    occupants = await alloc_repo.get_room_occupants(room.id)
    assert len(occupants) == 0

    # 4. has_active_allocations_for_room must be False
    assert await alloc_repo.has_active_allocations_for_room(room.id) is False

    # 5. has_active_allocations_for_hostel must be False
    assert await alloc_repo.has_active_allocations_for_hostel(hostel.id) is False


@pytest.mark.asyncio
async def test_soft_deleted_hostel_rooms_do_not_leak_into_search_available(
    client: AsyncClient,
    admin_user: User,
    db_session: AsyncSession,
) -> None:
    """Verify rooms belonging to soft-deleted hostels do not appear in search."""
    deleted_hostel = Hostel(
        id=uuid4(),
        name="Deleted Hostel",
        code="DEL-HST",
        gender_type=GenderType.MIXED,
        is_deleted=True,
    )
    db_session.add(deleted_hostel)
    await db_session.flush()

    block = Block(id=uuid4(), hostel_id=deleted_hostel.id, name="Block Del", floor_count=1)
    db_session.add(block)
    await db_session.flush()

    room = Room(
        id=uuid4(),
        block_id=block.id,
        number="DEL-ROOM-999",
        floor=1,
        room_type=RoomType.SINGLE,
        capacity=1,
        monthly_rent=Decimal("500.00"),
        status=RoomStatus.AVAILABLE,
        is_deleted=False,
    )
    db_session.add(room)
    await db_session.flush()

    bed = Bed(id=uuid4(), room_id=room.id, label="A", is_occupied=False)
    db_session.add(bed)
    await db_session.commit()

    headers = create_auth_headers(admin_user)

    response = await client.get("/api/v1/rooms/available", headers=headers)
    assert response.status_code == 200
    data = response.json()
    numbers = [r["number"] for r in data["items"]]
    assert "DEL-ROOM-999" not in numbers


@pytest.mark.asyncio
async def test_database_integrity_error_translated_to_409_conflict(
    client: AsyncClient,
    admin_user: User,
) -> None:
    """Verify database IntegrityError is intercepted and returned as clean 409 Conflict."""
    headers = create_auth_headers(admin_user)

    payload = {
        "name": "Alpha Hostel",
        "code": "ALPHA-UQ-01",
        "gender_type": "mixed",
    }
    res1 = await client.post("/api/v1/hostels", json=payload, headers=headers)
    assert res1.status_code in (201, 200)

    res2 = await client.post("/api/v1/hostels", json=payload, headers=headers)
    assert res2.status_code == 409
    body = res2.json()
    assert "error" in body
    assert body["error"]["code"] in ("HOSTEL_CODE_EXISTS", "DATABASE_CONFLICT")
    raw_text = str(body)
    assert "SELECT" not in raw_text
    assert "INSERT" not in raw_text
    assert "Traceback" not in raw_text


@pytest.mark.asyncio
async def test_raw_integrity_error_global_handler(
    test_engine: AsyncEngine,
) -> None:
    """Verify FastAPI exception handler converts raw IntegrityError to clean 409 response."""
    app = create_app()

    @app.get("/test-trigger-integrity-error")
    async def trigger_integrity_error() -> None:
        raise IntegrityError(
            "INSERT INTO fake_table ...",
            {},
            Exception("duplicate key value violates unique constraint"),
        )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/test-trigger-integrity-error")
        assert response.status_code == 409
        data = response.json()
        assert data == {
            "error": {
                "code": "DATABASE_CONFLICT",
                "message": "Database integrity constraint violation",
                "details": {},
            }
        }
        assert "fake_table" not in response.text


@pytest.mark.asyncio
async def test_nplusone_invoices_list(
    client: AsyncClient,
    test_engine: AsyncEngine,
    admin_user: User,
    db_session: AsyncSession,
) -> None:
    """Verify listing invoices with nested details executes bounded queries."""
    hostel = Hostel(id=uuid4(), name="Inv Hostel", code="INV-01", gender_type=GenderType.MIXED)
    block = Block(id=uuid4(), hostel_id=hostel.id, name="Block I", floor_count=1)
    db_session.add_all([hostel, block])
    await db_session.flush()

    for i in range(8):
        room = Room(
            id=uuid4(),
            block_id=block.id,
            number=f"Room-I-{i}",
            floor=1,
            room_type=RoomType.SINGLE,
            capacity=1,
            monthly_rent=Decimal("500.00"),
            status=RoomStatus.FULL,
        )
        db_session.add(room)
        await db_session.flush()

        bed = Bed(id=uuid4(), room_id=room.id, label="A", is_occupied=True)
        db_session.add(bed)
        await db_session.flush()

        user = User(
            id=uuid4(),
            email=f"invoice_user_{i}@example.com",
            full_name=f"Invoice User {i}",
            hashed_password=hash_password("Pass123"),
            role=UserRole.STUDENT,
            is_active=True,
        )
        db_session.add(user)
        await db_session.flush()

        profile = StudentProfile(
            id=uuid4(),
            user_id=user.id,
            student_no=f"STU-INV-{i}",
            gender=GenderType.MALE,
            department="CSE",
            year=1,
            guardian_name="Guardian",
            guardian_phone="+1234567890",
            emergency_contact="+1987654321",
        )
        db_session.add(profile)
        await db_session.flush()

        alloc = Allocation(
            id=uuid4(),
            student_id=profile.id,
            bed_id=bed.id,
            start_date=date.today(),
            status=AllocationStatus.ACTIVE,
        )
        db_session.add(alloc)
        await db_session.flush()

        invoice = Invoice(
            id=uuid4(),
            student_id=profile.id,
            allocation_id=alloc.id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            amount=Decimal("500.00"),
            paid_amount=Decimal("0.00"),
            due_date=date(2026, 1, 15),
            status=InvoiceStatus.UNPAID,
        )
        db_session.add(invoice)

    await db_session.commit()

    headers = create_auth_headers(admin_user)

    with QueryCounter(test_engine) as counter:
        response = await client.get("/api/v1/invoices?page=1&size=20", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) >= 8
        for item in data["items"]:
            assert item["student_name"] is not None
            assert item["hostel_name"] is not None

    msg = f"Expected <= 4 select queries, got {counter.select_count}: {counter.select_queries}"
    assert counter.select_count <= 4, msg


@pytest.mark.asyncio
async def test_nplusone_complaints_list(
    client: AsyncClient,
    test_engine: AsyncEngine,
    admin_user: User,
    db_session: AsyncSession,
) -> None:
    """Verify listing complaints with nested relations executes bounded queries."""
    hostel = Hostel(id=uuid4(), name="Cmp Hostel", code="CMP-01", gender_type=GenderType.MIXED)
    block = Block(id=uuid4(), hostel_id=hostel.id, name="Block C", floor_count=1)
    db_session.add_all([hostel, block])
    await db_session.flush()

    for i in range(8):
        room = Room(
            id=uuid4(),
            block_id=block.id,
            number=f"Room-C-{i}",
            floor=1,
            room_type=RoomType.SINGLE,
            capacity=1,
            monthly_rent=Decimal("500.00"),
            status=RoomStatus.AVAILABLE,
        )
        db_session.add(room)
        await db_session.flush()

        user = User(
            id=uuid4(),
            email=f"cmp_user_{i}@example.com",
            full_name=f"Complaint User {i}",
            hashed_password=hash_password("Pass123"),
            role=UserRole.STUDENT,
            is_active=True,
        )
        db_session.add(user)
        await db_session.flush()

        profile = StudentProfile(
            id=uuid4(),
            user_id=user.id,
            student_no=f"STU-CMP-{i}",
            gender=GenderType.MALE,
            department="CSE",
            year=1,
            guardian_name="Guardian",
            guardian_phone="+1234567890",
            emergency_contact="+1987654321",
        )
        db_session.add(profile)
        await db_session.flush()

        complaint = Complaint(
            id=uuid4(),
            student_id=profile.id,
            room_id=room.id,
            title=f"Issue {i}",
            description="Leaky faucet",
            category=ComplaintCategory.PLUMBING,
            priority=ComplaintPriority.MEDIUM,
            status=ComplaintStatus.OPEN,
        )
        db_session.add(complaint)

    await db_session.commit()

    headers = create_auth_headers(admin_user)

    with QueryCounter(test_engine) as counter:
        response = await client.get("/api/v1/complaints?page=1&size=20", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) >= 8
        for item in data["items"]:
            assert item["student_name"] is not None
            assert item["room_number"] is not None
            assert item["hostel_name"] is not None

    msg = f"Expected <= 4 select queries, got {counter.select_count}: {counter.select_queries}"
    assert counter.select_count <= 4, msg


@pytest.mark.asyncio
async def test_foreign_key_integrity_error_translated_to_409(
    test_engine: AsyncEngine,
) -> None:
    """Verify database foreign key violation IntegrityError translates to clean HTTP 409."""
    app = create_app()

    @app.post("/test-trigger-fk-violation")
    async def trigger_fk_violation() -> None:
        raise IntegrityError(
            "INSERT INTO student_profiles (user_id) VALUES ('non-existent-uuid')",
            {},
            Exception("FOREIGN KEY constraint failed"),
        )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/test-trigger-fk-violation")
        assert response.status_code == 409
        data = response.json()
        assert data["error"]["code"] == "DATABASE_CONFLICT"
        assert data["error"]["message"] == "Database integrity constraint violation"
        assert "INSERT" not in response.text
        assert "student_profiles" not in response.text
