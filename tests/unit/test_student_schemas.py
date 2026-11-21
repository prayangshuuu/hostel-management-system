"""Unit tests for student request and response schemas."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.hostel import GenderType
from app.schemas.student import (
    StudentCreate,
    StudentCreatedResponse,
    StudentProfileRead,
    StudentSelfUpdate,
    StudentUpdate,
    validate_phone_number,
    validate_required_phone_number,
)


def test_phone_validation_valid() -> None:
    """Test valid phone number formats matching PHONE_REGEX."""
    valid_numbers = [
        "+1234567890",
        "+919876543210",
        "9876543210",
        "+447911123456",
        "+14155552671",
        "12345",
    ]
    for num in valid_numbers:
        assert validate_phone_number(num) == num
        assert validate_required_phone_number(num) == num


def test_phone_validation_none_allowed() -> None:
    """Test None is allowed for optional phone validator."""
    assert validate_phone_number(None) is None


def test_phone_validation_invalid() -> None:
    """Test invalid phone numbers raise ValueError."""
    invalid_numbers = [
        "",
        "   ",
        "0123456789",  # Starts with 0
        "+0123456",  # + followed by 0
        "abc",
        "+",
        "123-456-7890",  # hyphens not allowed by ^\+?[1-9]\d{1,14}$
        "+1 234 567",  # spaces not allowed
    ]
    for num in invalid_numbers:
        with pytest.raises(ValueError, match="Invalid phone number format"):
            validate_phone_number(num)
        with pytest.raises(ValueError, match="Invalid phone number format"):
            validate_required_phone_number(num)


def test_student_create_schema_valid() -> None:
    """Test valid StudentCreate payload."""
    payload = {
        "email": "Student@Example.com",
        "full_name": "Jane Doe",
        "phone": "+1234567890",
        "student_no": "  STU-2026-001  ",
        "gender": GenderType.FEMALE,
        "department": "Computer Science",
        "year": 3,
        "guardian_name": "John Doe",
        "guardian_phone": "+1987654321",
        "emergency_contact": "+1122334455",
    }
    schema = StudentCreate(**payload)
    assert schema.email == "student@example.com"
    assert schema.student_no == "STU-2026-001"
    assert schema.year == 3
    assert schema.password is None


def test_student_create_year_boundaries() -> None:
    """Test year validation (ge=1, le=6)."""
    base_data = {
        "email": "student@example.com",
        "full_name": "Jane Doe",
        "student_no": "STU-001",
        "gender": GenderType.FEMALE,
        "department": "CS",
        "guardian_name": "John",
        "guardian_phone": "+1234567890",
        "emergency_contact": "+1987654321",
    }
    # Year 0 invalid
    with pytest.raises(ValidationError):
        StudentCreate(**base_data, year=0)

    # Year 7 invalid
    with pytest.raises(ValidationError):
        StudentCreate(**base_data, year=7)

    # Years 1 and 6 valid
    s1 = StudentCreate(**base_data, year=1)
    assert s1.year == 1
    s6 = StudentCreate(**base_data, year=6)
    assert s6.year == 6


def test_student_create_weak_password_rejected() -> None:
    """Test that weak password in StudentCreate is rejected."""
    base_data = {
        "email": "student@example.com",
        "full_name": "Jane Doe",
        "student_no": "STU-001",
        "gender": GenderType.FEMALE,
        "department": "CS",
        "year": 2,
        "guardian_name": "John",
        "guardian_phone": "+1234567890",
        "emergency_contact": "+1987654321",
    }
    with pytest.raises(ValidationError):
        StudentCreate(**base_data, password="weak")


def test_student_update_schema() -> None:
    """Test StudentUpdate with partial fields and phone validation."""
    update = StudentUpdate(
        department="Mechanical",
        year=4,
        phone="+1234567890",
    )
    assert update.department == "Mechanical"
    assert update.year == 4
    assert update.phone == "+1234567890"
    assert update.guardian_name is None


def test_student_self_update_forbids_extra_fields() -> None:
    """Test StudentSelfUpdate rejects forbidden fields like department with ValidationError."""
    # Valid self-update
    valid = StudentSelfUpdate(
        phone="+1234567890",
        emergency_contact="+1987654321",
        guardian_phone="+1122334455",
    )
    assert valid.phone == "+1234567890"

    # Extra forbidden field
    with pytest.raises(ValidationError) as exc_info:
        StudentSelfUpdate(phone="+1234567890", department="Physics")  # type: ignore[call-arg]
    assert "Extra inputs are not permitted" in str(exc_info.value)

    with pytest.raises(ValidationError):
        StudentSelfUpdate(year=2)  # type: ignore[call-arg]


def test_student_profile_read_serialization() -> None:
    """Test StudentProfileRead serialization with flattened user fields."""
    pid = uuid.uuid4()
    uid = uuid.uuid4()
    now = datetime.now(UTC)

    data = {
        "id": pid,
        "user_id": uid,
        "student_no": "STU-001",
        "gender": GenderType.MALE,
        "department": "Civil",
        "year": 1,
        "guardian_name": "Guardian",
        "guardian_phone": "+1234567890",
        "emergency_contact": "+1987654321",
        "is_deleted": False,
        "created_at": now,
        "updated_at": now,
        "full_name": "Student A",
        "email": "studenta@example.com",
        "phone": "+1234567890",
        "is_active": True,
        "current_allocation": None,
    }
    read = StudentProfileRead.model_validate(data)
    assert read.id == pid
    assert read.email == "studenta@example.com"
    assert read.full_name == "Student A"
    assert read.current_allocation is None


def test_student_created_response() -> None:
    """Test StudentCreatedResponse includes temporary_password."""
    pid = uuid.uuid4()
    uid = uuid.uuid4()
    now = datetime.now(UTC)

    data = {
        "id": pid,
        "user_id": uid,
        "student_no": "STU-001",
        "gender": GenderType.MALE,
        "department": "Civil",
        "year": 1,
        "guardian_name": "Guardian",
        "guardian_phone": "+1234567890",
        "emergency_contact": "+1987654321",
        "is_deleted": False,
        "created_at": now,
        "updated_at": now,
        "full_name": "Student A",
        "email": "studenta@example.com",
        "phone": "+1234567890",
        "is_active": True,
        "current_allocation": None,
        "temporary_password": "TempPassword123",
    }
    created = StudentCreatedResponse.model_validate(data)
    assert created.temporary_password == "TempPassword123"
