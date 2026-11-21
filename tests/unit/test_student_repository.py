"""Unit tests for StudentRepository database operations."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hostel import GenderType
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.repositories.student_repository import StudentRepository
from app.schemas.common import PaginationParams


@pytest.mark.asyncio
async def test_student_repo_create_and_get(db_session: AsyncSession) -> None:
    """Test creating and retrieving student profile by ID, user_id, and student_no."""
    user = User(
        id=uuid4(),
        email="repo_stu@example.com",
        full_name="Repo Student",
        hashed_password="pw",
        role=UserRole.STUDENT,
    )
    db_session.add(user)
    await db_session.flush()

    repo = StudentRepository(db_session)
    profile = StudentProfile(
        id=uuid4(),
        user_id=user.id,
        student_no="REPO-STU-001",
        gender=GenderType.FEMALE,
        department="Computer Science",
        year=2,
        guardian_name="Guardian Rep",
        guardian_phone="+1234567890",
        emergency_contact="+1987654321",
    )
    created = await repo.create(profile)
    assert created.id == profile.id

    # Retrieve by ID
    fetched_by_id = await repo.get_by_id(profile.id)
    assert fetched_by_id is not None
    assert fetched_by_id.student_no == "REPO-STU-001"
    assert fetched_by_id.user.email == "repo_stu@example.com"

    # Retrieve by user_id
    fetched_by_user = await repo.get_by_user_id(user.id)
    assert fetched_by_user is not None
    assert fetched_by_user.id == profile.id

    # Retrieve by student_no (case-insensitive)
    fetched_by_no = await repo.get_by_student_no("repo-stu-001")
    assert fetched_by_no is not None
    assert fetched_by_no.id == profile.id


@pytest.mark.asyncio
async def test_student_repo_update_and_soft_delete(db_session: AsyncSession) -> None:
    """Test updating and soft deleting a student profile."""
    user = User(
        id=uuid4(),
        email="update_stu@example.com",
        full_name="Update Student",
        hashed_password="pw",
        role=UserRole.STUDENT,
    )
    db_session.add(user)
    await db_session.flush()

    repo = StudentRepository(db_session)
    profile = StudentProfile(
        id=uuid4(),
        user_id=user.id,
        student_no="REPO-STU-UPDATE",
        gender=GenderType.MALE,
        department="Mechanical",
        year=1,
        guardian_name="Guardian Orig",
        guardian_phone="+1111111111",
        emergency_contact="+1222222222",
    )
    await repo.create(profile)

    # Update
    profile.department = "Mechatronics"
    profile.year = 2
    updated = await repo.update(profile)
    assert updated.department == "Mechatronics"
    assert updated.year == 2

    # Soft delete
    await repo.soft_delete(profile)
    assert profile.is_deleted is True

    # Excluded when include_deleted=False
    assert await repo.get_by_id(profile.id, include_deleted=False) is None
    assert await repo.get_by_user_id(user.id, include_deleted=False) is None
    assert await repo.get_by_student_no("REPO-STU-UPDATE", include_deleted=False) is None

    # Included when include_deleted=True
    assert await repo.get_by_id(profile.id, include_deleted=True) is not None


@pytest.mark.asyncio
async def test_student_repo_list_filters_and_search(db_session: AsyncSession) -> None:
    """Test listing student profiles with department, year, gender, search, and allocation."""
    repo = StudentRepository(db_session)

    u1 = User(
        id=uuid4(),
        email="alice@example.com",
        full_name="Alice Wonder",
        hashed_password="pw",
        role=UserRole.STUDENT,
    )
    u2 = User(
        id=uuid4(),
        email="bob@example.com",
        full_name="Bob Builder",
        hashed_password="pw",
        role=UserRole.STUDENT,
    )
    db_session.add_all([u1, u2])
    await db_session.flush()

    p1 = StudentProfile(
        id=uuid4(),
        user_id=u1.id,
        student_no="ALICE-01",
        gender=GenderType.FEMALE,
        department="Computer Science",
        year=3,
        guardian_name="Alice Guardian",
        guardian_phone="+1000000001",
        emergency_contact="+1000000002",
    )
    p2 = StudentProfile(
        id=uuid4(),
        user_id=u2.id,
        student_no="BOB-02",
        gender=GenderType.MALE,
        department="Civil Engineering",
        year=1,
        guardian_name="Bob Guardian",
        guardian_phone="+2000000001",
        emergency_contact="+2000000002",
    )
    await repo.create(p1)
    await repo.create(p2)

    params = PaginationParams(page=1, size=10)

    # Filter by department
    cs_students, cs_count = await repo.list(params, department="Computer Science")
    assert cs_count == 1
    assert cs_students[0].student_no == "ALICE-01"

    # Filter by year
    y1_students, y1_count = await repo.list(params, year=1)
    assert y1_count == 1
    assert y1_students[0].student_no == "BOB-02"

    # Filter by gender
    f_students, f_count = await repo.list(params, gender=GenderType.FEMALE)
    assert f_count == 1
    assert f_students[0].student_no == "ALICE-01"

    # Search by student_no
    search_no, count_no = await repo.list(params, search="bob-02")
    assert count_no == 1
    assert search_no[0].student_no == "BOB-02"

    # Search by full_name
    search_name, count_name = await repo.list(params, search="alice")
    assert count_name == 1
    assert search_name[0].student_no == "ALICE-01"

    # Search by email
    search_email, count_email = await repo.list(params, search="bob@example.com")
    assert count_email == 1
    assert search_email[0].student_no == "BOB-02"

    # Filter has_allocation=True (no allocations table -> 0 results)
    alloc_true, alloc_true_count = await repo.list(params, has_allocation=True)
    assert alloc_true_count == 0
    assert len(alloc_true) == 0

    # Filter has_allocation=False (all are unallocated -> 2 results)
    alloc_false, alloc_false_count = await repo.list(params, has_allocation=False)
    assert alloc_false_count == 2
    assert len(alloc_false) == 2
