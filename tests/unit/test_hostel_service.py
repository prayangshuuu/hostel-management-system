"""Unit tests for HostelService business logic and warden access rules."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.models.hostel import GenderType
from app.models.user import User, UserRole
from app.schemas.common import PaginationParams
from app.schemas.hostel import (
    BlockCreate,
    BlockUpdate,
    HostelCreate,
    HostelUpdate,
)
from app.services.hostel_service import HostelService, ensure_hostel_access


@pytest.mark.asyncio
async def test_ensure_hostel_access_rules(db_session: AsyncSession) -> None:
    """Verify access rules: admin passes, assigned warden passes, others raise ForbiddenError."""
    service = HostelService(db_session)
    hostel = await service.create_hostel(
        HostelCreate(name="Access Hostel", code="ACC-01", gender_type=GenderType.MIXED)
    )

    admin_user = User(
        id=uuid4(),
        email="access_admin@example.com",
        full_name="Admin",
        hashed_password="pw",
        role=UserRole.ADMIN,
    )
    assigned_warden = User(
        id=uuid4(),
        email="assigned_w@example.com",
        full_name="Assigned Warden",
        hashed_password="pw",
        role=UserRole.WARDEN,
    )
    unassigned_warden = User(
        id=uuid4(),
        email="unassigned_w@example.com",
        full_name="Unassigned Warden",
        hashed_password="pw",
        role=UserRole.WARDEN,
    )
    student = User(
        id=uuid4(),
        email="student_w@example.com",
        full_name="Student",
        hashed_password="pw",
        role=UserRole.STUDENT,
    )
    db_session.add_all([admin_user, assigned_warden, unassigned_warden, student])
    await db_session.flush()

    await service.assign_warden(hostel.id, assigned_warden.id)

    # Admin passes
    assert await service.ensure_hostel_access(admin_user, hostel.id) is True
    assert await ensure_hostel_access(db_session, admin_user, hostel.id) is True

    # Assigned warden passes
    assert await service.ensure_hostel_access(assigned_warden, hostel.id) is True

    # Unassigned warden raises ForbiddenError
    with pytest.raises(ForbiddenError) as exc_unassigned:
        await service.ensure_hostel_access(unassigned_warden, hostel.id)
    assert exc_unassigned.value.code == "FORBIDDEN"

    # Student raises ForbiddenError
    with pytest.raises(ForbiddenError) as exc_student:
        await service.ensure_hostel_access(student, hostel.id)
    assert exc_student.value.code == "FORBIDDEN"


@pytest.mark.asyncio
async def test_hostel_service_crud_and_conflicts(db_session: AsyncSession) -> None:
    """Verify hostel CRUD operations and conflict handling."""
    service = HostelService(db_session)

    # Create
    hostel = await service.create_hostel(
        HostelCreate(name="Service Hostel", code="SRV-01", gender_type=GenderType.FEMALE)
    )
    assert hostel.code == "SRV-01"

    # Duplicate code on create raises ConflictError
    with pytest.raises(ConflictError) as exc_dup:
        await service.create_hostel(
            HostelCreate(name="Another Hostel", code="srv-01", gender_type=GenderType.MALE)
        )
    assert exc_dup.value.code == "HOSTEL_CODE_EXISTS"

    # Get
    fetched = await service.get_hostel(hostel.id)
    assert fetched.id == hostel.id

    # Not found
    with pytest.raises(NotFoundError):
        await service.get_hostel(uuid4())

    # List
    page = await service.list_hostels(PaginationParams(page=1, size=10))
    assert page.total == 1
    assert page.items[0].id == hostel.id

    # Create second hostel
    hostel2 = await service.create_hostel(
        HostelCreate(name="Service Hostel 2", code="SRV-02", gender_type=GenderType.MALE)
    )

    # Update with duplicate code
    with pytest.raises(ConflictError):
        await service.update_hostel(hostel2.id, HostelUpdate(code="SRV-01"))

    # Update success
    updated = await service.update_hostel(
        hostel.id, HostelUpdate(name="Updated Service Hostel", address="New Addr")
    )
    assert updated.name == "Updated Service Hostel"
    assert updated.address == "New Addr"

    # Delete (soft delete)
    deleted = await service.delete_hostel(hostel.id)
    assert deleted.is_deleted is True

    # Get now raises NotFoundError
    with pytest.raises(NotFoundError):
        await service.get_hostel(hostel.id)


@pytest.mark.asyncio
async def test_block_service_crud_and_conflicts(db_session: AsyncSession) -> None:
    """Verify block CRUD operations and duplicate name validation."""
    service = HostelService(db_session)
    hostel = await service.create_hostel(
        HostelCreate(name="Block Service Hostel", code="BSH-01", gender_type=GenderType.MIXED)
    )

    # Create block
    block1 = await service.create_block(hostel.id, BlockCreate(name="Block 1", floor_count=4))
    assert block1.name == "Block 1"

    # Duplicate block name in same hostel
    with pytest.raises(ConflictError) as exc_dup:
        await service.create_block(hostel.id, BlockCreate(name="block 1", floor_count=2))
    assert exc_dup.value.code == "BLOCK_NAME_EXISTS"

    # Block on non-existent hostel
    with pytest.raises(NotFoundError):
        await service.create_block(uuid4(), BlockCreate(name="Ghost Block"))

    # List blocks
    blocks = await service.list_blocks(hostel.id)
    assert len(blocks) == 1
    assert blocks[0].id == block1.id

    # Get block
    fetched = await service.get_block(block1.id)
    assert fetched.id == block1.id

    with pytest.raises(NotFoundError):
        await service.get_block(uuid4())

    # Create second block
    block2 = await service.create_block(hostel.id, BlockCreate(name="Block 2", floor_count=2))

    # Update with conflict
    with pytest.raises(ConflictError):
        await service.update_block(block2.id, BlockUpdate(name="Block 1"))

    # Update success
    updated = await service.update_block(block1.id, BlockUpdate(floor_count=6))
    assert updated.floor_count == 6

    # Delete block
    await service.delete_block(block2.id)
    with pytest.raises(NotFoundError):
        await service.get_block(block2.id)


@pytest.mark.asyncio
async def test_warden_assignment_service_rules(db_session: AsyncSession) -> None:
    """Verify warden assignment logic: non-warden user, duplicate assignment, list, remove."""
    service = HostelService(db_session)
    hostel = await service.create_hostel(
        HostelCreate(name="Warden Hall", code="WH-01", gender_type=GenderType.MIXED)
    )

    warden = User(
        id=uuid4(),
        email="wh_warden@example.com",
        full_name="WH Warden",
        hashed_password="pw",
        role=UserRole.WARDEN,
    )
    student = User(
        id=uuid4(),
        email="wh_student@example.com",
        full_name="WH Student",
        hashed_password="pw",
        role=UserRole.STUDENT,
    )
    db_session.add_all([warden, student])
    await db_session.flush()

    # Assign non-existent user
    with pytest.raises(NotFoundError) as exc_not_found:
        await service.assign_warden(hostel.id, uuid4())
    assert exc_not_found.value.code == "USER_NOT_FOUND"

    # Assign non-warden user (student)
    with pytest.raises(ValidationAppError) as exc_role:
        await service.assign_warden(hostel.id, student.id)
    assert exc_role.value.code == "INVALID_WARDEN_ROLE"
    assert exc_role.value.status_code == 422

    # Assign valid warden
    assignment = await service.assign_warden(hostel.id, warden.id)
    assert assignment.hostel_id == hostel.id
    assert assignment.user_id == warden.id
    assert assignment.user.email == "wh_warden@example.com"

    # Duplicate assignment
    with pytest.raises(ConflictError) as exc_dup:
        await service.assign_warden(hostel.id, warden.id)
    assert exc_dup.value.code == "WARDEN_ALREADY_ASSIGNED"

    # List wardens
    wardens = await service.list_wardens(hostel.id)
    assert len(wardens) == 1
    assert wardens[0].user_id == warden.id

    # Remove non-existent assignment
    with pytest.raises(NotFoundError) as exc_rem_nf:
        await service.remove_warden(hostel.id, student.id)
    assert exc_rem_nf.value.code == "WARDEN_ASSIGNMENT_NOT_FOUND"

    # Remove valid assignment
    await service.remove_warden(hostel.id, warden.id)
    wardens_after = await service.list_wardens(hostel.id)
    assert len(wardens_after) == 0
