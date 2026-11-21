"""Unit tests for UserRepository operations."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.common import PaginationParams


@pytest.mark.asyncio
async def test_user_repo_create_and_get(db_session: AsyncSession) -> None:
    """Verify UserRepository can create and get user by ID."""
    repo = UserRepository(db_session)
    user = User(
        id=uuid4(),
        email="repo_test@example.com",
        full_name="Repo Test",
        hashed_password="hashed_pw_test",
        role=UserRole.STUDENT,
        is_active=True,
    )
    created = await repo.create(user)
    assert created.id == user.id

    fetched = await repo.get_by_id(user.id)
    assert fetched is not None
    assert fetched.email == "repo_test@example.com"
    assert fetched.role == UserRole.STUDENT


@pytest.mark.asyncio
async def test_user_repo_get_by_email_case_insensitive(db_session: AsyncSession) -> None:
    """Verify UserRepository case-insensitive email lookup."""
    repo = UserRepository(db_session)
    user = User(
        id=uuid4(),
        email="mixedcase@example.com",
        full_name="Mixed Case",
        hashed_password="hashed_pw_test",
        role=UserRole.WARDEN,
        is_active=True,
    )
    await repo.create(user)

    # Search with uppercase
    found_upper = await repo.get_by_email("MIXEDCASE@EXAMPLE.COM")
    assert found_upper is not None
    assert found_upper.id == user.id

    # Search with whitespace
    found_spaced = await repo.get_by_email("  MixedCase@example.com  ")
    assert found_spaced is not None
    assert found_spaced.id == user.id

    # Non-existent
    assert await repo.get_by_email("unknown@example.com") is None


@pytest.mark.asyncio
async def test_user_repo_update(db_session: AsyncSession) -> None:
    """Verify UserRepository update method flushes changes."""
    repo = UserRepository(db_session)
    user = User(
        id=uuid4(),
        email="update_target@example.com",
        full_name="Initial Name",
        hashed_password="hashed_pw_test",
        role=UserRole.STUDENT,
        is_active=True,
    )
    await repo.create(user)

    user.full_name = "Updated Name"
    user.phone = "+999999"
    updated = await repo.update(user)
    assert updated.full_name == "Updated Name"
    assert updated.phone == "+999999"


@pytest.mark.asyncio
async def test_user_repo_list_filters_and_search(db_session: AsyncSession) -> None:
    """Verify UserRepository list with role, active status, and search filters."""
    repo = UserRepository(db_session)
    u1 = User(
        id=uuid4(),
        email="alice@hostel.example",
        full_name="Alice Smith",
        hashed_password="hashed_pw_test",
        role=UserRole.STUDENT,
        is_active=True,
    )
    u2 = User(
        id=uuid4(),
        email="bob@hostel.example",
        full_name="Bob Jones",
        hashed_password="hashed_pw_test",
        role=UserRole.WARDEN,
        is_active=True,
    )
    u3 = User(
        id=uuid4(),
        email="charlie@hostel.example",
        full_name="Charlie Brown",
        hashed_password="hashed_pw_test",
        role=UserRole.STUDENT,
        is_active=False,
    )
    await repo.create(u1)
    await repo.create(u2)
    await repo.create(u3)

    params = PaginationParams(page=1, size=10)

    # Filter by role
    students, count = await repo.list(params, role=UserRole.STUDENT)
    assert count == 2
    assert len(students) == 2

    # Filter by is_active
    active_users, count = await repo.list(params, is_active=True)
    assert count == 2
    assert len(active_users) == 2

    # Search by full_name
    found_bob, count = await repo.list(params, search="jones")
    assert count == 1
    assert found_bob[0].id == u2.id

    # Search by email
    found_charlie, count = await repo.list(params, search="charlie@")
    assert count == 1
    assert found_charlie[0].id == u3.id
