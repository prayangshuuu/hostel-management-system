"""Unit tests for Room and Bed schemas and validation."""

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.exceptions import ValidationAppError
from app.models.room import RoomStatus, RoomType
from app.schemas.room import (
    BedRead,
    RoomBase,
    RoomCreate,
    RoomRead,
    RoomUpdate,
    RoomWithBedsRead,
    validate_capacity_for_room_type,
)


def test_validate_capacity_for_room_type() -> None:
    """Verify validation function succeeds for valid type and capacity combinations."""
    validate_capacity_for_room_type(RoomType.SINGLE, 1)
    validate_capacity_for_room_type(RoomType.DOUBLE, 2)
    validate_capacity_for_room_type(RoomType.TRIPLE, 3)
    validate_capacity_for_room_type(RoomType.DORM, 4)
    validate_capacity_for_room_type(RoomType.DORM, 8)


def test_validate_capacity_mismatch_raises() -> None:
    """Verify ValidationAppError is raised when capacity does not match room type."""
    with pytest.raises(ValidationAppError) as exc_single:
        validate_capacity_for_room_type(RoomType.SINGLE, 2)
    assert exc_single.value.code == "INVALID_CAPACITY_FOR_ROOM_TYPE"
    assert exc_single.value.status_code == 422

    with pytest.raises(ValidationAppError) as exc_double:
        validate_capacity_for_room_type(RoomType.DOUBLE, 1)
    assert exc_double.value.code == "INVALID_CAPACITY_FOR_ROOM_TYPE"

    with pytest.raises(ValidationAppError) as exc_triple:
        validate_capacity_for_room_type(RoomType.TRIPLE, 4)
    assert exc_triple.value.code == "INVALID_CAPACITY_FOR_ROOM_TYPE"

    with pytest.raises(ValidationAppError) as exc_dorm:
        validate_capacity_for_room_type(RoomType.DORM, 3)
    assert exc_dorm.value.code == "INVALID_CAPACITY_FOR_ROOM_TYPE"


def test_room_base_valid() -> None:
    """Verify RoomBase model creation and whitespace stripping."""
    schema = RoomBase(
        number="  101A  ",
        floor=2,
        room_type=RoomType.DOUBLE,
        capacity=2,
        monthly_rent=Decimal("5000.00"),
    )
    assert schema.number == "101A"
    assert schema.floor == 2
    assert schema.room_type == RoomType.DOUBLE
    assert schema.capacity == 2
    assert schema.monthly_rent == Decimal("5000.00")


def test_room_base_mismatch_raises_validation_error() -> None:
    """Verify RoomBase validation rejects invalid capacity for room type."""
    with pytest.raises(ValidationAppError) as exc:
        RoomBase(
            number="101",
            floor=1,
            room_type=RoomType.SINGLE,
            capacity=2,
            monthly_rent=Decimal("3000.00"),
        )
    assert exc.value.code == "INVALID_CAPACITY_FOR_ROOM_TYPE"
    assert exc.value.status_code == 422


def test_room_create_inheritance() -> None:
    """Verify RoomCreate inherits correctly from RoomBase."""
    schema = RoomCreate(
        number="202",
        floor=1,
        room_type=RoomType.TRIPLE,
        capacity=3,
        monthly_rent=Decimal("4000.00"),
    )
    assert schema.number == "202"
    assert schema.capacity == 3


def test_room_update_partial_and_validation() -> None:
    """Verify RoomUpdate handles partial fields and enforces capacity consistency."""
    # Updating only rent is valid
    update_rent = RoomUpdate(monthly_rent=Decimal("6000.00"))
    assert update_rent.monthly_rent == Decimal("6000.00")

    # Updating matching room_type and capacity is valid
    update_both = RoomUpdate(room_type=RoomType.DORM, capacity=6)
    assert update_both.room_type == RoomType.DORM
    assert update_both.capacity == 6

    # Updating with mismatch raises ValidationAppError
    with pytest.raises(ValidationAppError) as exc:
        RoomUpdate(room_type=RoomType.SINGLE, capacity=3)
    assert exc.value.code == "INVALID_CAPACITY_FOR_ROOM_TYPE"
    assert exc.value.status_code == 422


def test_bed_read_schema() -> None:
    """Verify BedRead schema attributes and validation."""
    bed_id = uuid4()
    room_id = uuid4()
    now = datetime.now()
    bed = BedRead(
        id=bed_id,
        room_id=room_id,
        label="A",
        is_occupied=False,
        created_at=now,
        updated_at=now,
    )
    assert bed.id == bed_id
    assert bed.room_id == room_id
    assert bed.label == "A"
    assert bed.is_occupied is False


def test_room_read_and_with_beds_schema() -> None:
    """Verify RoomRead and RoomWithBedsRead schema attributes."""
    room_id = uuid4()
    block_id = uuid4()
    now = datetime.now()

    room = RoomRead(
        id=room_id,
        block_id=block_id,
        number="301",
        floor=3,
        room_type=RoomType.DOUBLE,
        capacity=2,
        monthly_rent=Decimal("4500.00"),
        status=RoomStatus.AVAILABLE,
        is_deleted=False,
        occupied_beds_count=1,
        available_beds_count=1,
        created_at=now,
        updated_at=now,
    )
    assert room.id == room_id
    assert room.occupied_beds_count == 1
    assert room.available_beds_count == 1

    bed = BedRead(
        id=uuid4(),
        room_id=room_id,
        label="A",
        is_occupied=True,
        created_at=now,
        updated_at=now,
    )
    room_with_beds = RoomWithBedsRead(
        id=room_id,
        block_id=block_id,
        number="301",
        floor=3,
        room_type=RoomType.DOUBLE,
        capacity=2,
        monthly_rent=Decimal("4500.00"),
        status=RoomStatus.AVAILABLE,
        is_deleted=False,
        occupied_beds_count=1,
        available_beds_count=1,
        created_at=now,
        updated_at=now,
        beds=[bed],
    )
    assert len(room_with_beds.beds) == 1
    assert room_with_beds.beds[0].label == "A"


def test_room_schemas_dict_and_non_str_validator() -> None:
    """Verify validator handles non-string inputs and dict payloads."""
    # Field validator when input is None or non-string
    assert RoomBase.strip_whitespace(None) is None
    assert RoomUpdate.strip_whitespace(None) is None

    # RoomRead with dict input
    data = {
        "id": uuid4(),
        "block_id": uuid4(),
        "number": "101",
        "floor": 1,
        "room_type": RoomType.SINGLE,
        "capacity": 1,
        "monthly_rent": Decimal("3000.00"),
        "status": RoomStatus.AVAILABLE,
        "is_deleted": False,
        "occupied_beds_count": 0,
        "available_beds_count": 1,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    read = RoomRead.model_validate(data)
    assert read.number == "101"
