"""Unit tests for hostel, block, and warden assignment repositories."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hostel import Block, GenderType, Hostel, WardenAssignment
from app.models.user import User, UserRole
from app.repositories.hostel_repository import (
    BlockRepository,
    HostelRepository,
    WardenAssignmentRepository,
)
from app.schemas.common import PaginationParams


@pytest.mark.asyncio
async def test_hostel_repository_crud(db_session: AsyncSession) -> None:
    """Verify HostelRepository create, get_by_id, get_by_code, update, soft_delete, and list."""
    repo = HostelRepository(db_session)

    hostel = Hostel(
        name="Rep Hall",
        code="REP-01",
        gender_type=GenderType.MALE,
        address="10 University Way",
    )
    created = await repo.create(hostel)
    assert created.id is not None

    by_id = await repo.get_by_id(created.id)
    assert by_id is not None
    assert by_id.code == "REP-01"

    by_code = await repo.get_by_code("rep-01")
    assert by_code is not None
    assert by_code.id == created.id

    # Update
    created.name = "Rep Hall Updated"
    updated = await repo.update(created)
    assert updated.name == "Rep Hall Updated"

    # List with pagination and search
    params = PaginationParams(page=1, size=10)
    items, total = await repo.list(params, gender_type=GenderType.MALE, search="Updated")
    assert total == 1
    assert len(items) == 1
    assert items[0].id == created.id

    # Soft delete
    deleted = await repo.soft_delete(created)
    assert deleted.is_deleted is True

    # Excluded when include_deleted=False
    assert await repo.get_by_id(created.id, include_deleted=False) is None
    assert await repo.get_by_code("REP-01", include_deleted=False) is None

    # Included when include_deleted=True
    assert await repo.get_by_id(created.id, include_deleted=True) is not None
    assert await repo.get_by_code("REP-01", include_deleted=True) is not None

    # Excluded from list
    items_after, total_after = await repo.list(params)
    assert total_after == 0
    assert len(items_after) == 0


@pytest.mark.asyncio
async def test_block_repository_crud(db_session: AsyncSession) -> None:
    """Verify BlockRepository create, get_by_id, get_by_name, update, list_by_hostel, delete."""
    hostel_repo = HostelRepository(db_session)
    block_repo = BlockRepository(db_session)

    hostel = await hostel_repo.create(
        Hostel(name="Block Test Hostel", code="BTH-01", gender_type=GenderType.MIXED)
    )

    block1 = await block_repo.create(Block(hostel_id=hostel.id, name="Wing A", floor_count=2))
    block2 = await block_repo.create(Block(hostel_id=hostel.id, name="Wing B", floor_count=3))

    by_id = await block_repo.get_by_id(block1.id)
    assert by_id is not None
    assert by_id.name == "Wing A"

    by_name = await block_repo.get_by_name(hostel.id, "wing a")
    assert by_name is not None
    assert by_name.id == block1.id

    blocks = await block_repo.list_by_hostel(hostel.id)
    assert len(blocks) == 2
    assert blocks[0].name == "Wing A"
    assert blocks[1].name == "Wing B"

    # Update
    block1.floor_count = 5
    updated = await block_repo.update(block1)
    assert updated.floor_count == 5

    # Delete
    await block_repo.delete(block2)
    assert await block_repo.get_by_id(block2.id) is None


@pytest.mark.asyncio
async def test_warden_assignment_repository_crud(db_session: AsyncSession) -> None:
    """Verify WardenAssignmentRepository create, get, list_by_hostel, is_warden_assigned, delete."""
    hostel_repo = HostelRepository(db_session)
    warden_repo = WardenAssignmentRepository(db_session)

    user = User(
        id=uuid4(),
        email="repo_warden@example.com",
        full_name="Repo Warden",
        hashed_password="pw",
        role=UserRole.WARDEN,
    )
    db_session.add(user)
    await db_session.flush()

    hostel = await hostel_repo.create(
        Hostel(name="Warden Test Hostel", code="WTH-01", gender_type=GenderType.FEMALE)
    )

    # Initial check
    assert await warden_repo.is_warden_assigned(user.id, hostel.id) is False

    assignment = await warden_repo.create(WardenAssignment(hostel_id=hostel.id, user_id=user.id))
    assert assignment.id is not None

    # Check is_warden_assigned
    assert await warden_repo.is_warden_assigned(user.id, hostel.id) is True

    # Get
    fetched = await warden_repo.get(hostel.id, user.id)
    assert fetched is not None
    assert fetched.id == assignment.id
    assert fetched.user.email == "repo_warden@example.com"

    # Get by ID
    by_id = await warden_repo.get_by_id(assignment.id)
    assert by_id is not None
    assert by_id.user.full_name == "Repo Warden"

    # List
    assignments = await warden_repo.list_by_hostel(hostel.id)
    assert len(assignments) == 1
    assert assignments[0].user_id == user.id

    # Delete
    await warden_repo.delete(assignment)
    assert await warden_repo.is_warden_assigned(user.id, hostel.id) is False
    assert await warden_repo.get(hostel.id, user.id) is None
