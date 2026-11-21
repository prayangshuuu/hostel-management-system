"""Unit tests for hostel, block, and warden assignment Pydantic schemas."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.hostel import GenderType, WardenAssignment
from app.models.user import User, UserRole
from app.schemas.hostel import (
    BlockCreate,
    BlockRead,
    BlockUpdate,
    HostelCreate,
    HostelRead,
    HostelUpdate,
    WardenAssignmentRead,
    WardenAssignRequest,
)


def test_hostel_create_schema_valid() -> None:
    """Verify valid HostelCreate payload passes validation and strips whitespace."""
    payload = HostelCreate(
        name="  Alpha Hostel  ",
        code="  AH-01  ",
        gender_type=GenderType.MALE,
        address="123 Main Road",
    )
    assert payload.name == "Alpha Hostel"
    assert payload.code == "AH-01"
    assert payload.gender_type == GenderType.MALE
    assert payload.address == "123 Main Road"


def test_hostel_create_schema_invalid() -> None:
    """Verify invalid HostelCreate payload raises ValidationError."""
    with pytest.raises(ValidationError):
        HostelCreate(name="", code="VALID-01")

    with pytest.raises(ValidationError):
        HostelCreate(name="Valid Name", code="")


def test_hostel_update_schema() -> None:
    """Verify HostelUpdate allows partial updates and validates bounds."""
    update = HostelUpdate(name="Updated Name")
    assert update.name == "Updated Name"
    assert update.code is None
    assert update.gender_type is None
    assert update.address is None

    with pytest.raises(ValidationError):
        HostelUpdate(name="")


def test_hostel_read_schema() -> None:
    """Verify HostelRead exposes computed total_capacity with default 0."""
    now = datetime.now(UTC)
    hostel_id = uuid4()
    read = HostelRead(
        id=hostel_id,
        name="Beta Hostel",
        code="BH-02",
        gender_type=GenderType.MIXED,
        address=None,
        is_deleted=False,
        created_at=now,
        updated_at=now,
    )
    assert read.id == hostel_id
    assert read.total_capacity == 0
    assert read.is_deleted is False


def test_block_schemas() -> None:
    """Verify BlockCreate, BlockUpdate, and BlockRead validation."""
    create = BlockCreate(name="  Block A  ", floor_count=3)
    assert create.name == "Block A"
    assert create.floor_count == 3

    with pytest.raises(ValidationError):
        BlockCreate(name="Block B", floor_count=0)

    with pytest.raises(ValidationError):
        BlockCreate(name="", floor_count=1)

    update = BlockUpdate(floor_count=5)
    assert update.floor_count == 5
    assert update.name is None

    now = datetime.now(UTC)
    block_id = uuid4()
    hostel_id = uuid4()
    read = BlockRead(
        id=block_id,
        hostel_id=hostel_id,
        name="Block A",
        floor_count=3,
        created_at=now,
        updated_at=now,
    )
    assert read.id == block_id
    assert read.hostel_id == hostel_id
    assert read.floor_count == 3


def test_warden_assignment_schemas() -> None:
    """Verify WardenAssignRequest and WardenAssignmentRead deserialization."""
    user_id = uuid4()
    req = WardenAssignRequest(user_id=user_id)
    assert req.user_id == user_id

    now = datetime.now(UTC)
    assignment_id = uuid4()
    hostel_id = uuid4()

    # From dict
    read = WardenAssignmentRead.model_validate(
        {
            "id": assignment_id,
            "user_id": user_id,
            "hostel_id": hostel_id,
            "user_email": "warden@example.com",
            "user_full_name": "Test Warden",
            "created_at": now,
        }
    )
    assert read.user_email == "warden@example.com"
    assert read.user_full_name == "Test Warden"

    # From ORM object with user
    user = User(
        id=user_id,
        email="warden_orm@example.com",
        full_name="ORM Warden",
        hashed_password="pw",
        role=UserRole.WARDEN,
    )
    assignment = WardenAssignment(
        id=assignment_id,
        user_id=user_id,
        hostel_id=hostel_id,
        created_at=now,
    )
    assignment.user = user

    read_orm = WardenAssignmentRead.model_validate(assignment)
    assert read_orm.id == assignment_id
    assert read_orm.user_id == user_id
    assert read_orm.hostel_id == hostel_id
    assert read_orm.user_email == "warden_orm@example.com"
    assert read_orm.user_full_name == "ORM Warden"
