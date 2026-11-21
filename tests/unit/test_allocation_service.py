"""Unit tests for AllocationService business logic, lifecycle, and access control."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.core.security import hash_password
from app.models.allocation import AllocationStatus
from app.models.hostel import Block, GenderType, Hostel, WardenAssignment
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.repositories.allocation_repository import AllocationRepository
from app.repositories.hostel_repository import BlockRepository, HostelRepository
from app.repositories.room_repository import BedRepository, RoomRepository
from app.repositories.student_repository import StudentRepository
from app.schemas.allocation import (
    AllocationCreate,
    AllocationTransferRequest,
    AllocationVacateRequest,
)
from app.schemas.common import PaginationParams
from app.services.allocation_service import AllocationService
from app.services.hostel_service import HostelService
from app.services.room_service import RoomService


async def create_hostel(
    session: AsyncSession,
    code: str = "H-01",
    gender_type: GenderType = GenderType.MIXED,
    name: str = "Test Hostel",
) -> Hostel:
    """Helper to persist a test hostel."""
    repo = HostelRepository(session)
    hostel = Hostel(name=name, code=code, gender_type=gender_type, address="123 Test St")
    return await repo.create(hostel)


async def create_block(session: AsyncSession, hostel_id: UUID, name: str = "Block A") -> Block:
    """Helper to persist a test block."""
    repo = BlockRepository(session)
    block = Block(hostel_id=hostel_id, name=name, floor_count=3)
    return await repo.create(block)


async def create_room_with_beds(
    session: AsyncSession,
    block_id: UUID,
    number: str = "101",
    capacity: int = 2,
    status: RoomStatus = RoomStatus.AVAILABLE,
) -> tuple[Room, list[Bed]]:
    """Helper to persist a test room with beds."""
    room_repo = RoomRepository(session)
    bed_repo = BedRepository(session)

    room = Room(
        block_id=block_id,
        number=number,
        floor=1,
        room_type=RoomType.DOUBLE if capacity == 2 else RoomType.SINGLE,
        capacity=capacity,
        monthly_rent=Decimal("5000.00"),
        status=status,
    )
    saved_room = await room_repo.create(room)

    beds: list[Bed] = []
    labels = ["A", "B", "C", "D"][:capacity]
    for lbl in labels:
        bed = Bed(room_id=saved_room.id, label=lbl, is_occupied=False)
        saved_bed = await bed_repo.create(bed)
        beds.append(saved_bed)

    reloaded_room = await room_repo.get_by_id(saved_room.id, load_beds=True)
    return reloaded_room or saved_room, beds


async def create_student(
    session: AsyncSession,
    email: str = "student@test.com",
    student_no: str = "STU-001",
    gender: GenderType = GenderType.MALE,
    is_active: bool = True,
) -> StudentProfile:
    """Helper to persist a test student and linked user."""
    student_repo = StudentRepository(session)
    user = User(
        id=uuid4(),
        email=email,
        full_name=f"Student {student_no}",
        phone="+1234567890",
        hashed_password=hash_password("Pass1234"),
        role=UserRole.STUDENT,
        is_active=is_active,
    )
    session.add(user)
    await session.flush()

    profile = StudentProfile(
        id=uuid4(),
        user_id=user.id,
        student_no=student_no,
        gender=gender,
        department="Computer Science",
        year=2,
        guardian_name="Guardian",
        guardian_phone="+1111111111",
        emergency_contact="+1222222222",
    )
    created = await student_repo.create(profile)
    created.user = user
    return created


async def create_warden(
    session: AsyncSession,
    email: str = "warden@test.com",
    assigned_hostel_id: UUID | None = None,
) -> User:
    """Helper to persist a test warden and optional hostel assignment."""
    user = User(
        id=uuid4(),
        email=email,
        full_name="Test Warden",
        phone="+1999999999",
        hashed_password=hash_password("WardenPass123"),
        role=UserRole.WARDEN,
        is_active=True,
    )
    session.add(user)
    await session.flush()

    if assigned_hostel_id is not None:
        assignment = WardenAssignment(hostel_id=assigned_hostel_id, user_id=user.id)
        session.add(assignment)
        await session.flush()

    return user


@pytest.mark.asyncio
async def test_allocate_by_bed_id_success(db_session: AsyncSession, admin_user: User) -> None:
    """Verify allocating an active student to an available bed by bed_id."""
    hostel = await create_hostel(db_session, code="H-ALLOC-1")
    block = await create_block(db_session, hostel.id)
    room, beds = await create_room_with_beds(db_session, block.id, capacity=2)
    student = await create_student(db_session, email="stu_b1@test.com", student_no="S-B1")

    service = AllocationService(db_session)
    data = AllocationCreate(
        student_id=student.id,
        bed_id=beds[0].id,
        start_date=date.today(),
    )
    allocation = await service.allocate(data, admin_user)

    assert allocation.id is not None
    assert allocation.student_id == student.id
    assert allocation.bed_id == beds[0].id
    assert allocation.status == AllocationStatus.ACTIVE
    assert allocation.start_date == date.today()
    assert allocation.end_date is None

    # Bed must be marked occupied
    bed_check = await BedRepository(db_session).get_by_id(beds[0].id)
    assert bed_check is not None
    assert bed_check.is_occupied is True

    # Room has capacity 2 with 1 occupied -> still AVAILABLE
    room_check = await RoomRepository(db_session).get_by_id(room.id)
    assert room_check is not None
    assert room_check.status == RoomStatus.AVAILABLE


@pytest.mark.asyncio
async def test_allocate_by_room_id_success_picks_free_bed(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Verify allocate by room_id automatically picks the first available bed."""
    hostel = await create_hostel(db_session, code="H-ALLOC-2")
    block = await create_block(db_session, hostel.id)
    room, beds = await create_room_with_beds(db_session, block.id, capacity=2)
    student = await create_student(db_session, email="stu_r1@test.com", student_no="S-R1")

    service = AllocationService(db_session)
    data = AllocationCreate(
        student_id=student.id,
        room_id=room.id,
        start_date=date.today(),
    )
    allocation = await service.allocate(data, admin_user)

    assert allocation.student_id == student.id
    assert allocation.bed_id == beds[0].id
    assert allocation.status == AllocationStatus.ACTIVE


@pytest.mark.asyncio
async def test_allocate_rule1_single_active_allocation_per_student(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Core rule 1: A student can have only one active allocation."""
    hostel = await create_hostel(db_session, code="H-R1")
    block = await create_block(db_session, hostel.id)
    _, beds = await create_room_with_beds(db_session, block.id, capacity=2)
    student = await create_student(db_session, email="stu_r1_dup@test.com", student_no="S-R1-DUP")

    service = AllocationService(db_session)
    # 1st allocation succeeds
    await service.allocate(
        AllocationCreate(student_id=student.id, bed_id=beds[0].id),
        admin_user,
    )

    # 2nd allocation for same student must fail with STUDENT_ALREADY_ALLOCATED (400)
    with pytest.raises(BusinessRuleError) as exc_info:
        await service.allocate(
            AllocationCreate(student_id=student.id, bed_id=beds[1].id),
            admin_user,
        )
    assert exc_info.value.code == "STUDENT_ALREADY_ALLOCATED"
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_allocate_rule2_single_active_allocation_per_bed(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Core rule 2: A bed can hold only one active allocation."""
    hostel = await create_hostel(db_session, code="H-R2")
    block = await create_block(db_session, hostel.id)
    _, beds = await create_room_with_beds(db_session, block.id, capacity=2)
    student1 = await create_student(db_session, email="stu_b2_1@test.com", student_no="S-B2-1")
    student2 = await create_student(db_session, email="stu_b2_2@test.com", student_no="S-B2-2")

    service = AllocationService(db_session)
    # Student 1 gets bed 0
    await service.allocate(
        AllocationCreate(student_id=student1.id, bed_id=beds[0].id),
        admin_user,
    )

    # Student 2 attempts to get bed 0 -> fails with BED_ALREADY_OCCUPIED (400)
    with pytest.raises(BusinessRuleError) as exc_info:
        await service.allocate(
            AllocationCreate(student_id=student2.id, bed_id=beds[0].id),
            admin_user,
        )
    assert exc_info.value.code == "BED_ALREADY_OCCUPIED"
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_allocate_rule3_room_status_auto_updates(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Core rule 3: Room auto-updates: 'full' on all occupied, 'available' when vacated."""
    hostel = await create_hostel(db_session, code="H-R3")
    block = await create_block(db_session, hostel.id)
    room, beds = await create_room_with_beds(db_session, block.id, capacity=2)
    student1 = await create_student(db_session, email="stu_s1@test.com", student_no="S-S1")
    student2 = await create_student(db_session, email="stu_s2@test.com", student_no="S-S2")

    service = AllocationService(db_session)
    room_repo = RoomRepository(db_session)

    # 1. First allocation: 1/2 occupied -> AVAILABLE
    alloc1 = await service.allocate(
        AllocationCreate(student_id=student1.id, bed_id=beds[0].id),
        admin_user,
    )
    r1 = await room_repo.get_by_id(room.id)
    assert r1 is not None and r1.status == RoomStatus.AVAILABLE

    # 2. Second allocation: 2/2 occupied -> FULL
    await service.allocate(
        AllocationCreate(student_id=student2.id, bed_id=beds[1].id),
        admin_user,
    )
    r2 = await room_repo.get_by_id(room.id)
    assert r2 is not None and r2.status == RoomStatus.FULL

    # 3. Vacate first allocation: 1/2 occupied -> transitions back to AVAILABLE
    await service.vacate(
        alloc1.id,
        AllocationVacateRequest(reason="Moving out"),
        admin_user,
    )
    r3 = await room_repo.get_by_id(room.id)
    assert r3 is not None and r3.status == RoomStatus.AVAILABLE


@pytest.mark.asyncio
async def test_allocate_rule4_gender_match(db_session: AsyncSession, admin_user: User) -> None:
    """Core rule 4: Room gender must match hostel gender_type (mixed allows both)."""
    # 1. Male hostel with female student -> GENDER_MISMATCH (400)
    male_hostel = await create_hostel(db_session, code="H-MALE", gender_type=GenderType.MALE)
    male_block = await create_block(db_session, male_hostel.id)
    _, male_beds = await create_room_with_beds(db_session, male_block.id, capacity=1)
    female_student = await create_student(
        db_session,
        email="female_s@test.com",
        student_no="S-FEMALE",
        gender=GenderType.FEMALE,
    )

    service = AllocationService(db_session)
    with pytest.raises(BusinessRuleError) as exc_info:
        await service.allocate(
            AllocationCreate(student_id=female_student.id, bed_id=male_beds[0].id),
            admin_user,
        )
    assert exc_info.value.code == "GENDER_MISMATCH"
    assert exc_info.value.status_code == 400

    # 2. Female hostel with male student -> GENDER_MISMATCH (400)
    female_hostel = await create_hostel(db_session, code="H-FEMALE", gender_type=GenderType.FEMALE)
    female_block = await create_block(db_session, female_hostel.id)
    _, female_beds = await create_room_with_beds(db_session, female_block.id, capacity=1)
    male_student = await create_student(
        db_session,
        email="male_s@test.com",
        student_no="S-MALE",
        gender=GenderType.MALE,
    )

    with pytest.raises(BusinessRuleError) as exc_info2:
        await service.allocate(
            AllocationCreate(student_id=male_student.id, bed_id=female_beds[0].id),
            admin_user,
        )
    assert exc_info2.value.code == "GENDER_MISMATCH"
    assert exc_info2.value.status_code == 400

    # 3. Mixed hostel allows both male and female students
    mixed_hostel = await create_hostel(db_session, code="H-MIXED", gender_type=GenderType.MIXED)
    mixed_block = await create_block(db_session, mixed_hostel.id)
    _, mixed_beds = await create_room_with_beds(db_session, mixed_block.id, capacity=2)

    alloc_m = await service.allocate(
        AllocationCreate(student_id=male_student.id, bed_id=mixed_beds[0].id),
        admin_user,
    )
    alloc_f = await service.allocate(
        AllocationCreate(student_id=female_student.id, bed_id=mixed_beds[1].id),
        admin_user,
    )
    assert alloc_m.status == AllocationStatus.ACTIVE
    assert alloc_f.status == AllocationStatus.ACTIVE


@pytest.mark.asyncio
async def test_allocate_rule5_room_under_maintenance(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Core rule 5: Rooms in maintenance cannot receive allocations."""
    hostel = await create_hostel(db_session, code="H-MAINT")
    block = await create_block(db_session, hostel.id)
    _, beds = await create_room_with_beds(
        db_session, block.id, capacity=1, status=RoomStatus.MAINTENANCE
    )
    student = await create_student(db_session, email="stu_maint@test.com", student_no="S-MAINT")

    service = AllocationService(db_session)
    with pytest.raises(BusinessRuleError) as exc_info:
        await service.allocate(
            AllocationCreate(student_id=student.id, bed_id=beds[0].id),
            admin_user,
        )
    assert exc_info.value.code == "ROOM_UNDER_MAINTENANCE"
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_allocate_rule6_ending_frees_bed_and_sets_end_date(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Core rule 6: Ending an allocation frees the bed and sets end_date."""
    hostel = await create_hostel(db_session, code="H-END")
    block = await create_block(db_session, hostel.id)
    _, beds = await create_room_with_beds(db_session, block.id, capacity=1)
    student = await create_student(db_session, email="stu_end@test.com", student_no="S-END")

    service = AllocationService(db_session)
    allocation = await service.allocate(
        AllocationCreate(student_id=student.id, bed_id=beds[0].id),
        admin_user,
    )

    vacate_date = date.today()
    vacated = await service.vacate(
        allocation.id,
        AllocationVacateRequest(end_date=vacate_date, reason="Graduated"),
        admin_user,
    )

    assert vacated.status == AllocationStatus.ENDED
    assert vacated.end_date == vacate_date
    assert vacated.reason == "Graduated"

    bed_check = await BedRepository(db_session).get_by_id(beds[0].id)
    assert bed_check is not None
    assert bed_check.is_occupied is False


@pytest.mark.asyncio
async def test_allocate_rule7_wardens_scoped_to_assigned_hostels(
    db_session: AsyncSession,
) -> None:
    """Core rule 7: Wardens only act on hostels they are assigned to."""
    h1 = await create_hostel(db_session, code="H-ASSIGNED-1")
    b1 = await create_block(db_session, h1.id)
    _, beds1 = await create_room_with_beds(db_session, b1.id, capacity=1)

    h2 = await create_hostel(db_session, code="H-UNASSIGNED-2")
    b2 = await create_block(db_session, h2.id)
    _, beds2 = await create_room_with_beds(db_session, b2.id, capacity=1)

    warden = await create_warden(
        db_session, email="warden_scoped@test.com", assigned_hostel_id=h1.id
    )
    student1 = await create_student(db_session, email="s_w1@test.com", student_no="S-W1")
    student2 = await create_student(db_session, email="s_w2@test.com", student_no="S-W2")

    service = AllocationService(db_session)

    # 1. Warden succeeds in assigned hostel H1
    alloc1 = await service.allocate(
        AllocationCreate(student_id=student1.id, bed_id=beds1[0].id),
        warden,
    )
    assert alloc1.status == AllocationStatus.ACTIVE

    # 2. Warden fails in unassigned hostel H2 with ForbiddenError (403)
    with pytest.raises(ForbiddenError) as exc_info:
        await service.allocate(
            AllocationCreate(student_id=student2.id, bed_id=beds2[0].id),
            warden,
        )
    assert exc_info.value.code == "FORBIDDEN"
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_allocate_room_full(db_session: AsyncSession, admin_user: User) -> None:
    """Allocate by room picks free bed; full room raises ROOM_FULL (400)."""
    hostel = await create_hostel(db_session, code="H-FULL")
    block = await create_block(db_session, hostel.id)
    room, beds = await create_room_with_beds(db_session, block.id, capacity=1)
    student1 = await create_student(db_session, email="stu_f1@test.com", student_no="S-F1")
    student2 = await create_student(db_session, email="stu_f2@test.com", student_no="S-F2")

    service = AllocationService(db_session)
    # Fill the room
    await service.allocate(
        AllocationCreate(student_id=student1.id, bed_id=beds[0].id),
        admin_user,
    )

    # Allocate by room_id when full
    with pytest.raises(BusinessRuleError) as exc_info:
        await service.allocate(
            AllocationCreate(student_id=student2.id, room_id=room.id),
            admin_user,
        )
    assert exc_info.value.code == "ROOM_FULL"
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_allocate_inactive_student_user(db_session: AsyncSession, admin_user: User) -> None:
    """Inactive student user cannot be allocated -> USER_INACTIVE (400)."""
    hostel = await create_hostel(db_session, code="H-INACTIVE")
    block = await create_block(db_session, hostel.id)
    _, beds = await create_room_with_beds(db_session, block.id, capacity=1)
    student = await create_student(
        db_session, email="stu_inact@test.com", student_no="S-INACT", is_active=False
    )

    service = AllocationService(db_session)
    with pytest.raises(BusinessRuleError) as exc_info:
        await service.allocate(
            AllocationCreate(student_id=student.id, bed_id=beds[0].id),
            admin_user,
        )
    assert exc_info.value.code == "USER_INACTIVE"
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_allocate_student_not_found(db_session: AsyncSession, admin_user: User) -> None:
    """Non-existent student -> STUDENT_NOT_FOUND (404)."""
    service = AllocationService(db_session)
    with pytest.raises(NotFoundError) as exc_info:
        await service.allocate(
            AllocationCreate(student_id=uuid4(), bed_id=uuid4()),
            admin_user,
        )
    assert exc_info.value.code == "STUDENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_allocate_bed_not_found(db_session: AsyncSession, admin_user: User) -> None:
    """Non-existent bed -> BED_NOT_FOUND (404)."""
    student = await create_student(db_session, email="stu_bnf@test.com", student_no="S-BNF")
    service = AllocationService(db_session)
    with pytest.raises(NotFoundError) as exc_info:
        await service.allocate(
            AllocationCreate(student_id=student.id, bed_id=uuid4()),
            admin_user,
        )
    assert exc_info.value.code == "BED_NOT_FOUND"


@pytest.mark.asyncio
async def test_allocate_bed_not_in_room(db_session: AsyncSession, admin_user: User) -> None:
    """Mismatch between bed_id and room_id -> BED_NOT_IN_ROOM (400)."""
    hostel = await create_hostel(db_session, code="H-NOTINROOM")
    block = await create_block(db_session, hostel.id)
    _, beds1 = await create_room_with_beds(db_session, block.id, number="101", capacity=1)
    room2, _ = await create_room_with_beds(db_session, block.id, number="102", capacity=1)
    student = await create_student(db_session, email="stu_nir@test.com", student_no="S-NIR")

    service = AllocationService(db_session)
    with pytest.raises(BusinessRuleError) as exc_info:
        await service.allocate(
            AllocationCreate(student_id=student.id, bed_id=beds1[0].id, room_id=room2.id),
            admin_user,
        )
    assert exc_info.value.code == "BED_NOT_IN_ROOM"


@pytest.mark.asyncio
async def test_allocate_student_role_forbidden(
    db_session: AsyncSession, student_user: User
) -> None:
    """Student role cannot allocate beds -> FORBIDDEN (403)."""
    service = AllocationService(db_session)
    with pytest.raises(ForbiddenError):
        await service.allocate(
            AllocationCreate(student_id=uuid4(), bed_id=uuid4()),
            student_user,
        )


@pytest.mark.asyncio
async def test_allocate_db_integrity_error_maps_to_conflict(
    db_session: AsyncSession, admin_user: User
) -> None:
    """DB IntegrityError on allocation creation maps to ConflictError (ALLOCATION_CONFLICT, 409)."""
    hostel = await create_hostel(db_session, code="H-INTEG")
    block = await create_block(db_session, hostel.id)
    _, beds = await create_room_with_beds(db_session, block.id, capacity=1)
    student = await create_student(db_session, email="stu_integ@test.com", student_no="S-INTEG")

    service = AllocationService(db_session)
    with patch.object(
        service.allocation_repo,
        "create",
        AsyncMock(side_effect=IntegrityError("stmt", {}, Exception("uq_violation"))),
    ):
        with pytest.raises(ConflictError) as exc_info:
            await service.allocate(
                AllocationCreate(student_id=student.id, bed_id=beds[0].id),
                admin_user,
            )
        assert exc_info.value.code == "ALLOCATION_CONFLICT"
        assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_vacate_non_active_allocation_fails(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Vacating an already ended allocation raises ALLOCATION_NOT_ACTIVE (400)."""
    hostel = await create_hostel(db_session, code="H-VACNONACT")
    block = await create_block(db_session, hostel.id)
    _, beds = await create_room_with_beds(db_session, block.id, capacity=1)
    student = await create_student(db_session, email="stu_vna@test.com", student_no="S-VNA")

    service = AllocationService(db_session)
    alloc = await service.allocate(
        AllocationCreate(student_id=student.id, bed_id=beds[0].id),
        admin_user,
    )
    # Vacate once
    await service.vacate(alloc.id, AllocationVacateRequest(), admin_user)

    # Vacate again -> ALLOCATION_NOT_ACTIVE
    with pytest.raises(BusinessRuleError) as exc_info:
        await service.vacate(alloc.id, AllocationVacateRequest(), admin_user)
    assert exc_info.value.code == "ALLOCATION_NOT_ACTIVE"


@pytest.mark.asyncio
async def test_transfer_atomic_success(db_session: AsyncSession, admin_user: User) -> None:
    """Transfer is atomic: frees old bed, marks new bed occupied, creates new allocation."""
    hostel = await create_hostel(db_session, code="H-XFER-OK")
    block = await create_block(db_session, hostel.id)
    _, old_beds = await create_room_with_beds(db_session, block.id, number="101", capacity=1)
    _, new_beds = await create_room_with_beds(db_session, block.id, number="102", capacity=1)
    student = await create_student(db_session, email="stu_xfer@test.com", student_no="S-XFER")

    service = AllocationService(db_session)
    old_alloc = await service.allocate(
        AllocationCreate(student_id=student.id, bed_id=old_beds[0].id),
        admin_user,
    )

    new_alloc = await service.transfer(
        old_alloc.id,
        AllocationTransferRequest(new_bed_id=new_beds[0].id, reason="Requested room change"),
        admin_user,
    )

    assert new_alloc.id != old_alloc.id
    assert new_alloc.status == AllocationStatus.ACTIVE
    assert new_alloc.bed_id == new_beds[0].id

    # Check old allocation
    old_alloc_check = await AllocationRepository(db_session).get_by_id(old_alloc.id)
    assert old_alloc_check is not None
    assert old_alloc_check.status == AllocationStatus.ENDED
    assert old_alloc_check.end_date == date.today()

    # Check bed occupancies
    bed_repo = BedRepository(db_session)
    b_old = await bed_repo.get_by_id(old_beds[0].id)
    b_new = await bed_repo.get_by_id(new_beds[0].id)
    assert b_old is not None and b_old.is_occupied is False
    assert b_new is not None and b_new.is_occupied is True


@pytest.mark.asyncio
async def test_transfer_same_bed_fails(db_session: AsyncSession, admin_user: User) -> None:
    """Transfer to the currently occupied bed raises CANNOT_TRANSFER_TO_SAME_BED (400)."""
    hostel = await create_hostel(db_session, code="H-XFER-SAME")
    block = await create_block(db_session, hostel.id)
    _, beds = await create_room_with_beds(db_session, block.id, capacity=1)
    student = await create_student(db_session, email="stu_xfersame@test.com", student_no="S-XS")

    service = AllocationService(db_session)
    alloc = await service.allocate(
        AllocationCreate(student_id=student.id, bed_id=beds[0].id),
        admin_user,
    )

    with pytest.raises(BusinessRuleError) as exc_info:
        await service.transfer(
            alloc.id,
            AllocationTransferRequest(new_bed_id=beds[0].id),
            admin_user,
        )
    assert exc_info.value.code == "CANNOT_TRANSFER_TO_SAME_BED"


@pytest.mark.asyncio
async def test_transfer_is_atomic_forced_failure_preserves_original(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Transfer is atomic: forced failure on allocate step leaves original allocation intact."""
    hostel = await create_hostel(db_session, code="H-XFER-ATOMIC")
    block = await create_block(db_session, hostel.id)
    _room1, beds1 = await create_room_with_beds(db_session, block.id, number="201", capacity=1)
    # Destination room is under MAINTENANCE
    _maint_room, maint_beds = await create_room_with_beds(
        db_session, block.id, number="202", capacity=1, status=RoomStatus.MAINTENANCE
    )
    student = await create_student(db_session, email="stu_atomic@test.com", student_no="S-ATOMIC")

    service = AllocationService(db_session)
    alloc = await service.allocate(
        AllocationCreate(student_id=student.id, bed_id=beds1[0].id),
        admin_user,
    )

    # Attempt transfer to maintenance room bed
    with pytest.raises(BusinessRuleError) as exc_info:
        await service.transfer(
            alloc.id,
            AllocationTransferRequest(new_bed_id=maint_beds[0].id),
            admin_user,
        )
    assert exc_info.value.code == "ROOM_UNDER_MAINTENANCE"

    # Original allocation must still be ACTIVE
    await db_session.refresh(alloc)
    assert alloc.status == AllocationStatus.ACTIVE
    assert alloc.end_date is None

    # Original bed must still be occupied
    await db_session.refresh(beds1[0])
    assert beds1[0].is_occupied is True


@pytest.mark.asyncio
async def test_cancel_future_allocation_success(db_session: AsyncSession, admin_user: User) -> None:
    """Cancel: only allowed if start_date in future; succeeds and frees bed."""
    hostel = await create_hostel(db_session, code="H-CANCEL-FUT")
    block = await create_block(db_session, hostel.id)
    _, beds = await create_room_with_beds(db_session, block.id, capacity=1)
    student = await create_student(db_session, email="stu_fut@test.com", student_no="S-FUT")

    future_start = date.today() + timedelta(days=5)
    service = AllocationService(db_session)
    alloc = await service.allocate(
        AllocationCreate(student_id=student.id, bed_id=beds[0].id, start_date=future_start),
        admin_user,
    )

    cancelled = await service.cancel(alloc.id, admin_user)
    assert cancelled.status == AllocationStatus.CANCELLED

    # Bed is freed
    b_check = await BedRepository(db_session).get_by_id(beds[0].id)
    assert b_check is not None
    assert b_check.is_occupied is False


@pytest.mark.asyncio
async def test_cancel_today_or_past_start_date_fails(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Cancel: past or today start_date raises CANNOT_CANCEL_ACTIVE_ALLOCATION (400)."""
    hostel = await create_hostel(db_session, code="H-CANCEL-TODAY")
    block = await create_block(db_session, hostel.id)
    _, beds = await create_room_with_beds(db_session, block.id, capacity=1)
    student = await create_student(db_session, email="stu_today@test.com", student_no="S-TODAY")

    service = AllocationService(db_session)
    alloc = await service.allocate(
        AllocationCreate(student_id=student.id, bed_id=beds[0].id, start_date=date.today()),
        admin_user,
    )

    with pytest.raises(BusinessRuleError) as exc_info:
        await service.cancel(alloc.id, admin_user)
    assert exc_info.value.code == "CANNOT_CANCEL_ACTIVE_ALLOCATION"
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_hostel_and_room_delete_guards(db_session: AsyncSession, admin_user: User) -> None:
    """Hostel and room delete blocked with active allocations (409 ConflictError)."""
    hostel = await create_hostel(db_session, code="H-DEL-GUARD")
    block = await create_block(db_session, hostel.id)
    room, beds = await create_room_with_beds(db_session, block.id, capacity=1)
    student = await create_student(db_session, email="stu_delguard@test.com", student_no="S-DEL")

    alloc_service = AllocationService(db_session)
    hostel_service = HostelService(db_session)
    room_service = RoomService(db_session)

    alloc = await alloc_service.allocate(
        AllocationCreate(student_id=student.id, bed_id=beds[0].id),
        admin_user,
    )

    # 1. Delete room blocked
    with pytest.raises(ConflictError) as exc_room:
        await room_service.delete_room(room.id, admin_user)
    assert exc_room.value.code == "ROOM_HAS_ACTIVE_ALLOCATIONS"
    assert exc_room.value.status_code == 409

    # 2. Delete hostel blocked
    with pytest.raises(ConflictError) as exc_hostel:
        await hostel_service.delete_hostel(hostel.id)
    assert exc_hostel.value.code == "HOSTEL_HAS_ACTIVE_ALLOCATIONS"
    assert exc_hostel.value.status_code == 409

    # 3. Vacate allocation
    await alloc_service.vacate(alloc.id, AllocationVacateRequest(), admin_user)

    # 4. Now room and hostel can be soft-deleted without error
    deleted_room = await room_service.delete_room(room.id, admin_user)
    assert deleted_room.is_deleted is True

    deleted_hostel = await hostel_service.delete_hostel(hostel.id)
    assert deleted_hostel.is_deleted is True


@pytest.mark.asyncio
async def test_get_allocation_scoping_and_not_found(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Verify get_allocation scoping for admin, assigned/unassigned warden, and students."""
    h1 = await create_hostel(db_session, code="H-SCOPE-1")
    b1 = await create_block(db_session, h1.id)
    _, beds1 = await create_room_with_beds(db_session, b1.id, capacity=1)

    s1 = await create_student(db_session, email="s_sc1@test.com", student_no="S-SC1")
    s2 = await create_student(db_session, email="s_sc2@test.com", student_no="S-SC2")
    assigned_warden = await create_warden(
        db_session, email="w_asgn@test.com", assigned_hostel_id=h1.id
    )
    unassigned_warden = await create_warden(
        db_session, email="w_unasgn@test.com", assigned_hostel_id=None
    )

    service = AllocationService(db_session)
    alloc = await service.allocate(
        AllocationCreate(student_id=s1.id, bed_id=beds1[0].id),
        admin_user,
    )

    # Admin can view
    a_admin = await service.get_allocation(alloc.id, admin_user)
    assert a_admin.id == alloc.id

    # Assigned warden can view
    a_warden = await service.get_allocation(alloc.id, assigned_warden)
    assert a_warden.id == alloc.id

    # Unassigned warden cannot view -> 403
    with pytest.raises(ForbiddenError):
        await service.get_allocation(alloc.id, unassigned_warden)

    # Student owner can view
    a_student = await service.get_allocation(alloc.id, s1.user)
    assert a_student.id == alloc.id

    # Another student cannot view -> 403
    with pytest.raises(ForbiddenError):
        await service.get_allocation(alloc.id, s2.user)

    # Non-existent -> 404
    with pytest.raises(NotFoundError):
        await service.get_allocation(uuid4(), admin_user)


@pytest.mark.asyncio
async def test_get_room_occupants(db_session: AsyncSession, admin_user: User) -> None:
    """Verify get_room_occupants returns student details for occupied beds."""
    hostel = await create_hostel(db_session, code="H-OCC")
    block = await create_block(db_session, hostel.id)
    room, beds = await create_room_with_beds(db_session, block.id, capacity=2)
    s1 = await create_student(db_session, email="stu_occ1@test.com", student_no="S-OCC1")

    service = AllocationService(db_session)
    await service.allocate(
        AllocationCreate(student_id=s1.id, bed_id=beds[0].id),
        admin_user,
    )

    occupants = await service.get_room_occupants(room.id, admin_user)
    assert len(occupants) == 1
    assert occupants[0].bed_label == "A"
    assert occupants[0].student_no == "S-OCC1"
    assert occupants[0].student_id == s1.id


@pytest.mark.asyncio
async def test_list_allocations_filters(db_session: AsyncSession, admin_user: User) -> None:
    """Verify list_allocations pagination and filtering."""
    hostel = await create_hostel(db_session, code="H-LIST")
    block = await create_block(db_session, hostel.id)
    _room, beds = await create_room_with_beds(db_session, block.id, capacity=2)
    s1 = await create_student(db_session, email="stu_l1@test.com", student_no="S-L1")
    s2 = await create_student(db_session, email="stu_l2@test.com", student_no="S-L2")

    service = AllocationService(db_session)
    a1 = await service.allocate(
        AllocationCreate(student_id=s1.id, bed_id=beds[0].id),
        admin_user,
    )
    a2 = await service.allocate(
        AllocationCreate(student_id=s2.id, bed_id=beds[1].id),
        admin_user,
    )

    page = await service.list_allocations(
        params=PaginationParams(page=1, size=10),
        current_user=admin_user,
        hostel_id=hostel.id,
    )
    assert page.total >= 2
    assert any(item.id == a1.id for item in page.items)
    assert any(item.id == a2.id for item in page.items)


@pytest.mark.asyncio
async def test_get_student_active_allocation_and_my_active_allocation(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Verify get_student_active_allocation and get_my_active_allocation."""
    hostel = await create_hostel(db_session, code="H-MY-ALLOC")
    block = await create_block(db_session, hostel.id)
    _, beds = await create_room_with_beds(db_session, block.id, capacity=2)
    s1 = await create_student(db_session, email="stu_my1@test.com", student_no="S-MY1")
    s2 = await create_student(db_session, email="stu_my2@test.com", student_no="S-MY2")

    service = AllocationService(db_session)
    alloc = await service.allocate(
        AllocationCreate(student_id=s1.id, bed_id=beds[0].id),
        admin_user,
    )

    # Student retrieves own active allocation
    my_alloc = await service.get_my_active_allocation(s1.user)
    assert my_alloc.id == alloc.id

    # Admin retrieves student's active allocation
    admin_lookup = await service.get_student_active_allocation(s1.id, admin_user)
    assert admin_lookup.id == alloc.id

    # Student 2 has no active allocation -> 404
    with pytest.raises(NotFoundError):
        await service.get_my_active_allocation(s2.user)

    with pytest.raises(NotFoundError):
        await service.get_student_active_allocation(s2.id, admin_user)

    # Student 1 cannot view Student 2's active allocation -> 403
    with pytest.raises(ForbiddenError):
        await service.get_student_active_allocation(s2.id, s1.user)


@pytest.mark.asyncio
async def test_transfer_to_full_room_fails_atomically(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Transfer to full room raises ROOM_FULL (400) and preserves original allocation."""
    hostel = await create_hostel(db_session, code="H-XFER-FULL")
    block = await create_block(db_session, hostel.id)
    _, beds1 = await create_room_with_beds(db_session, block.id, number="301", capacity=1)
    full_room, full_beds = await create_room_with_beds(
        db_session, block.id, number="302", capacity=1
    )
    s1 = await create_student(db_session, email="stu_xf1@test.com", student_no="S-XF1")
    s2 = await create_student(db_session, email="stu_xf2@test.com", student_no="S-XF2")

    service = AllocationService(db_session)
    alloc1 = await service.allocate(
        AllocationCreate(student_id=s1.id, bed_id=beds1[0].id),
        admin_user,
    )
    # Fill the destination room
    await service.allocate(
        AllocationCreate(student_id=s2.id, bed_id=full_beds[0].id),
        admin_user,
    )

    # Transfer s1 into full room -> ROOM_FULL
    with pytest.raises(BusinessRuleError) as exc_info:
        await service.transfer(
            alloc1.id,
            AllocationTransferRequest(new_room_id=full_room.id),
            admin_user,
        )
    assert exc_info.value.code == "ROOM_FULL"

    # Original allocation remains active
    await db_session.refresh(alloc1)
    assert alloc1.status == AllocationStatus.ACTIVE


@pytest.mark.asyncio
async def test_transfer_gender_mismatch_fails_atomically(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Transfer to gender mismatched hostel raises GENDER_MISMATCH (400) and preserves original."""
    h_mixed = await create_hostel(db_session, code="H-XFER-G1", gender_type=GenderType.MIXED)
    b_mixed = await create_block(db_session, h_mixed.id)
    _, beds_mixed = await create_room_with_beds(db_session, b_mixed.id, capacity=1)

    h_female = await create_hostel(db_session, code="H-XFER-G2", gender_type=GenderType.FEMALE)
    b_female = await create_block(db_session, h_female.id)
    _, beds_female = await create_room_with_beds(db_session, b_female.id, capacity=1)

    male_student = await create_student(
        db_session, email="male_xfer@test.com", student_no="S-MXF", gender=GenderType.MALE
    )

    service = AllocationService(db_session)
    alloc = await service.allocate(
        AllocationCreate(student_id=male_student.id, bed_id=beds_mixed[0].id),
        admin_user,
    )

    # Transfer male student into female hostel -> GENDER_MISMATCH
    with pytest.raises(BusinessRuleError) as exc_info:
        await service.transfer(
            alloc.id,
            AllocationTransferRequest(new_bed_id=beds_female[0].id),
            admin_user,
        )
    assert exc_info.value.code == "GENDER_MISMATCH"

    # Original allocation remains active
    await db_session.refresh(alloc)
    assert alloc.status == AllocationStatus.ACTIVE


@pytest.mark.asyncio
async def test_cancel_non_active_allocation_fails(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Cancelling an already ended or cancelled allocation raises ALLOCATION_NOT_ACTIVE (400)."""
    hostel = await create_hostel(db_session, code="H-CANC-NONACT")
    block = await create_block(db_session, hostel.id)
    _, beds = await create_room_with_beds(db_session, block.id, capacity=1)
    student = await create_student(db_session, email="stu_cnact@test.com", student_no="S-CNACT")

    future_start = date.today() + timedelta(days=2)
    service = AllocationService(db_session)
    alloc = await service.allocate(
        AllocationCreate(student_id=student.id, bed_id=beds[0].id, start_date=future_start),
        admin_user,
    )

    # Cancel once -> succeeds
    await service.cancel(alloc.id, admin_user)

    # Cancel again -> ALLOCATION_NOT_ACTIVE
    with pytest.raises(BusinessRuleError) as exc_info:
        await service.cancel(alloc.id, admin_user)
    assert exc_info.value.code == "ALLOCATION_NOT_ACTIVE"
