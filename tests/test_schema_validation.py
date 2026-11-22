"""Schema validation negative sweep tests.

Verifies strict negative validation across all Create/Update/Request schemas:
1. Forbidden extra fields (model_config extra='forbid')
2. String boundary lengths (empty strings, exceeding max_length)
3. Negative and zero money values
4. Bad email and phone formats
5. Invalid chronological dates (end < start, due < start, expires <= published)
6. Complex schema validators (room capacity vs room type, bed/room XOR rules)
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.exceptions import ValidationAppError
from app.models.billing import PaymentMethod
from app.models.complaint import ComplaintCategory
from app.models.hostel import GenderType
from app.models.mess import MealType
from app.models.room import RoomType
from app.schemas.allocation import (
    AllocationCreate,
    AllocationTransferRequest,
    AllocationVacateRequest,
)
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshTokenRequest,
)
from app.schemas.billing import (
    FeeStructureCreate,
    InvoiceGenerateRequest,
    PaymentCreate,
)
from app.schemas.complaint import (
    ComplaintCommentCreate,
    ComplaintCreate,
)
from app.schemas.hostel import (
    BlockCreate,
    BlockUpdate,
    HostelCreate,
    WardenAssignRequest,
)
from app.schemas.mess import (
    MealOptOutCreate,
    MessMenuItemCreate,
)
from app.schemas.notice import (
    NoticeCreate,
    NoticeUpdate,
)
from app.schemas.operations import (
    AttendanceActionRequest,
    LeaveRequestCreate,
    VisitorCreate,
)
from app.schemas.room import (
    RoomCreate,
    RoomUpdate,
)
from app.schemas.student import (
    StudentCreate,
    StudentSelfUpdate,
)
from app.schemas.user import (
    UserCreate,
    UserUpdate,
)

# =============================================================================
# 1. User & Auth Schemas Negative Validation
# =============================================================================


class TestUserAndAuthSchemasValidation:
    """Negative validation tests for User and Auth schemas."""

    def test_user_create_forbidden_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            UserCreate(
                email="valid@example.com",
                full_name="Valid Name",
                password="Password123",
                unknown_extra_field="not_allowed",  # type: ignore[call-arg]
            )

    def test_user_create_string_boundaries(self) -> None:
        # full_name empty
        with pytest.raises(ValidationError):
            UserCreate(email="valid@example.com", full_name="", password="Password123")
        # full_name too long (> 255)
        with pytest.raises(ValidationError):
            UserCreate(email="valid@example.com", full_name="A" * 256, password="Password123")

    def test_user_create_bad_email_formats(self) -> None:
        bad_emails = ["not-an-email", "missing@domain", "@nodomain.com", "plainaddress"]
        for bad in bad_emails:
            with pytest.raises(ValidationError):
                UserCreate(email=bad, full_name="Valid Name", password="Password123")

    def test_user_create_password_policy(self) -> None:
        # < 8 chars
        with pytest.raises(ValidationError, match="at least 8 characters"):
            UserCreate(email="v@e.com", full_name="Name", password="P1a")
        # No letters
        with pytest.raises(ValidationError, match="at least one letter"):
            UserCreate(email="v@e.com", full_name="Name", password="123456789")
        # No numbers
        with pytest.raises(ValidationError, match="at least one number"):
            UserCreate(email="v@e.com", full_name="Name", password="LettersOnlyHere")

    def test_user_update_negative_validation(self) -> None:
        # Extra field
        with pytest.raises(ValidationError, match="extra_forbidden"):
            UserUpdate(role=None, forbidden_key=123)  # type: ignore[call-arg]
        # Empty full_name
        with pytest.raises(ValidationError):
            UserUpdate(full_name="")
        # Too long full_name
        with pytest.raises(ValidationError):
            UserUpdate(full_name="B" * 256)

    def test_auth_schemas_validation(self) -> None:
        # LoginRequest extra fields
        with pytest.raises(ValidationError, match="extra_forbidden"):
            LoginRequest(email="v@e.com", password="pwd", extra="bad")  # type: ignore[call-arg]
        # LoginRequest bad email
        with pytest.raises(ValidationError):
            LoginRequest(email="bademail", password="pwd")
        # RefreshTokenRequest extra fields
        with pytest.raises(ValidationError, match="extra_forbidden"):
            RefreshTokenRequest(refresh_token="tok", evil_field=True)  # type: ignore[call-arg]
        # ChangePasswordRequest extra fields
        with pytest.raises(ValidationError, match="extra_forbidden"):
            ChangePasswordRequest(
                current_password="old",
                new_password="ValidNew123",
                extra=1,  # type: ignore[call-arg]
            )
        # ChangePasswordRequest weak new password
        with pytest.raises(ValidationError):
            ChangePasswordRequest(current_password="old", new_password="short")


# =============================================================================
# 2. Student Schemas Negative Validation
# =============================================================================


class TestStudentSchemasValidation:
    """Negative validation tests for StudentCreate and StudentUpdate schemas."""

    @pytest.fixture
    def valid_student_data(self) -> dict[str, object]:
        return {
            "email": "student@example.com",
            "full_name": "Alice Smith",
            "student_no": "STU-2026-001",
            "gender": GenderType.FEMALE,
            "department": "Computer Science",
            "year": 2,
            "guardian_name": "Bob Smith",
            "guardian_phone": "+1234567890",
            "emergency_contact": "+1987654321",
        }

    def test_student_create_forbidden_extra_fields(
        self, valid_student_data: dict[str, object]
    ) -> None:
        data = {**valid_student_data, "unauthorized_role": "admin"}
        with pytest.raises(ValidationError, match="extra_forbidden"):
            StudentCreate(**data)

    def test_student_create_string_boundaries(self, valid_student_data: dict[str, object]) -> None:
        # student_no empty
        with pytest.raises(ValidationError):
            StudentCreate(**{**valid_student_data, "student_no": ""})
        # student_no too long
        with pytest.raises(ValidationError):
            StudentCreate(**{**valid_student_data, "student_no": "S" * 51})
        # department empty
        with pytest.raises(ValidationError):
            StudentCreate(**{**valid_student_data, "department": ""})
        # department too long
        with pytest.raises(ValidationError):
            StudentCreate(**{**valid_student_data, "department": "D" * 101})
        # guardian_name empty
        with pytest.raises(ValidationError):
            StudentCreate(**{**valid_student_data, "guardian_name": ""})
        # guardian_name too long
        with pytest.raises(ValidationError):
            StudentCreate(**{**valid_student_data, "guardian_name": "G" * 256})

    def test_student_create_year_boundaries(self, valid_student_data: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            StudentCreate(**{**valid_student_data, "year": 0})
        with pytest.raises(ValidationError):
            StudentCreate(**{**valid_student_data, "year": 7})

    def test_student_create_bad_phone_formats(self, valid_student_data: dict[str, object]) -> None:
        bad_phones = ["abc", "123-456-7890", "+0123456", "  ", ""]
        for bad in bad_phones:
            with pytest.raises(ValueError):
                StudentCreate(**{**valid_student_data, "guardian_phone": bad})
            with pytest.raises(ValueError):
                StudentCreate(**{**valid_student_data, "emergency_contact": bad})

    def test_student_self_update_forbids_admin_fields(self) -> None:
        # Students cannot self-update department, year, full_name, or is_active
        with pytest.raises(ValidationError, match="extra_forbidden"):
            StudentSelfUpdate(department="New Department")  # type: ignore[call-arg]
        with pytest.raises(ValidationError, match="extra_forbidden"):
            StudentSelfUpdate(full_name="New Full Name")  # type: ignore[call-arg]
        with pytest.raises(ValidationError, match="extra_forbidden"):
            StudentSelfUpdate(year=4)  # type: ignore[call-arg]


# =============================================================================
# 3. Hostel and Block Schemas Negative Validation
# =============================================================================


class TestHostelSchemasValidation:
    """Negative validation tests for Hostel and Block schemas."""

    def test_hostel_create_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            HostelCreate(name="Hostel Alpha", code="HA", hacker_field=True)  # type: ignore[call-arg]

    def test_hostel_create_string_boundaries(self) -> None:
        # Empty name
        with pytest.raises(ValidationError):
            HostelCreate(name="", code="HA")
        # Too long name
        with pytest.raises(ValidationError):
            HostelCreate(name="N" * 256, code="HA")
        # Empty code
        with pytest.raises(ValidationError):
            HostelCreate(name="Hostel", code="")
        # Too long code
        with pytest.raises(ValidationError):
            HostelCreate(name="Hostel", code="C" * 51)

    def test_block_create_and_update_validation(self) -> None:
        # Extra fields
        with pytest.raises(ValidationError, match="extra_forbidden"):
            BlockCreate(name="Block A", extra_key="no")  # type: ignore[call-arg]
        with pytest.raises(ValidationError, match="extra_forbidden"):
            BlockUpdate(name="Block A", extra_key="no")  # type: ignore[call-arg]
        # Floor count < 1
        with pytest.raises(ValidationError):
            BlockCreate(name="Block A", floor_count=0)
        with pytest.raises(ValidationError):
            BlockUpdate(floor_count=0)
        # Empty name
        with pytest.raises(ValidationError):
            BlockCreate(name="")

    def test_warden_assign_request_validation(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            WardenAssignRequest(user_id=uuid4(), invalid_extra="fail")  # type: ignore[call-arg]


# =============================================================================
# 4. Room and Bed Schemas Negative Validation
# =============================================================================


class TestRoomSchemasValidation:
    """Negative validation tests for RoomCreate and RoomUpdate schemas."""

    def test_room_create_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            RoomCreate(
                number="101",
                room_type=RoomType.SINGLE,
                capacity=1,
                monthly_rent=Decimal("250.00"),
                unwanted_extra=1,  # type: ignore[call-arg]
            )

    def test_room_create_negative_money_values(self) -> None:
        # Negative monthly rent
        with pytest.raises(ValidationError):
            RoomCreate(
                number="101",
                room_type=RoomType.SINGLE,
                capacity=1,
                monthly_rent=Decimal("-100.00"),
            )
        # Zero monthly rent
        with pytest.raises(ValidationError):
            RoomCreate(
                number="101",
                room_type=RoomType.SINGLE,
                capacity=1,
                monthly_rent=Decimal("0.00"),
            )

    def test_room_create_string_boundaries(self) -> None:
        # Empty number
        with pytest.raises(ValidationError):
            RoomCreate(
                number="",
                room_type=RoomType.SINGLE,
                capacity=1,
                monthly_rent=Decimal("250.00"),
            )
        # Too long number (> 50)
        with pytest.raises(ValidationError):
            RoomCreate(
                number="R" * 51,
                room_type=RoomType.SINGLE,
                capacity=1,
                monthly_rent=Decimal("250.00"),
            )

    def test_room_create_capacity_mismatch(self) -> None:
        # SINGLE requires capacity=1
        with pytest.raises(ValidationAppError) as exc:
            RoomCreate(
                number="101",
                room_type=RoomType.SINGLE,
                capacity=2,
                monthly_rent=Decimal("200.00"),
            )
        assert exc.value.code == "INVALID_CAPACITY_FOR_ROOM_TYPE"

        # DOUBLE requires capacity=2
        with pytest.raises(ValidationAppError):
            RoomCreate(
                number="102",
                room_type=RoomType.DOUBLE,
                capacity=1,
                monthly_rent=Decimal("200.00"),
            )

        # TRIPLE requires capacity=3
        with pytest.raises(ValidationAppError):
            RoomCreate(
                number="103",
                room_type=RoomType.TRIPLE,
                capacity=4,
                monthly_rent=Decimal("200.00"),
            )

        # DORM requires capacity >= 4
        with pytest.raises(ValidationAppError):
            RoomCreate(
                number="104",
                room_type=RoomType.DORM,
                capacity=3,
                monthly_rent=Decimal("200.00"),
            )

    def test_room_update_negative_validation(self) -> None:
        # Extra fields
        with pytest.raises(ValidationError, match="extra_forbidden"):
            RoomUpdate(monthly_rent=Decimal("300.00"), extra_col="bad")  # type: ignore[call-arg]
        # Negative rent
        with pytest.raises(ValidationError):
            RoomUpdate(monthly_rent=Decimal("-50.00"))
        # Inconsistent capacity update
        with pytest.raises(ValidationAppError):
            RoomUpdate(room_type=RoomType.SINGLE, capacity=3)


# =============================================================================
# 5. Allocation Schemas Negative Validation
# =============================================================================


class TestAllocationSchemasValidation:
    """Negative validation tests for allocation request schemas."""

    def test_allocation_create_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            AllocationCreate(
                student_id=uuid4(),
                bed_id=uuid4(),
                extra_field="fail",  # type: ignore[call-arg]
            )

    def test_allocation_create_missing_bed_and_room(self) -> None:
        # Both bed_id and room_id None must raise ValidationError
        with pytest.raises(
            ValidationError, match="At least one of bed_id or room_id must be provided"
        ):
            AllocationCreate(student_id=uuid4(), bed_id=None, room_id=None)

    def test_allocation_transfer_missing_new_targets(self) -> None:
        with pytest.raises(
            ValidationError, match="At least one of new_bed_id or new_room_id must be provided"
        ):
            AllocationTransferRequest(new_bed_id=None, new_room_id=None)

    def test_allocation_transfer_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            AllocationTransferRequest(new_bed_id=uuid4(), rogue_param=42)  # type: ignore[call-arg]

    def test_allocation_vacate_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            AllocationVacateRequest(reason="Moving out", bogus="test")  # type: ignore[call-arg]


# =============================================================================
# 6. Billing and Finance Schemas Negative Validation
# =============================================================================


class TestBillingSchemasValidation:
    """Negative validation tests for fee structures, invoices, and payments."""

    def test_fee_structure_create_negative_and_zero_amount(self) -> None:
        # Negative amount
        with pytest.raises(ValidationError):
            FeeStructureCreate(
                hostel_id=uuid4(), room_type=RoomType.SINGLE, amount=Decimal("-100.00")
            )
        # Zero amount
        with pytest.raises(ValidationError):
            FeeStructureCreate(hostel_id=uuid4(), room_type=RoomType.SINGLE, amount=Decimal("0.00"))

    def test_fee_structure_create_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            FeeStructureCreate(
                hostel_id=uuid4(),
                room_type=RoomType.SINGLE,
                amount=Decimal("100.00"),
                unrecognized="nope",  # type: ignore[call-arg]
            )

    def test_payment_create_negative_and_zero_amount(self) -> None:
        with pytest.raises(ValidationError):
            PaymentCreate(amount=Decimal("-50.00"), method=PaymentMethod.CASH)
        with pytest.raises(ValidationError):
            PaymentCreate(amount=Decimal("0.00"), method=PaymentMethod.CASH)

    def test_payment_create_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            PaymentCreate(
                amount=Decimal("50.00"),
                method=PaymentMethod.CASH,
                fake_key=True,  # type: ignore[call-arg]
            )

    def test_invoice_generate_invalid_dates(self) -> None:
        today = date.today()
        # period_end < period_start
        with pytest.raises(
            ValidationError, match="period_end must be greater than or equal to period_start"
        ):
            InvoiceGenerateRequest(
                hostel_id=uuid4(),
                period_start=today,
                period_end=today - timedelta(days=1),
                due_date=today + timedelta(days=7),
            )
        # due_date < period_start
        with pytest.raises(
            ValidationError, match="due_date must be greater than or equal to period_start"
        ):
            InvoiceGenerateRequest(
                hostel_id=uuid4(),
                period_start=today,
                period_end=today + timedelta(days=30),
                due_date=today - timedelta(days=1),
            )

    def test_invoice_generate_extra_fields(self) -> None:
        today = date.today()
        with pytest.raises(ValidationError, match="extra_forbidden"):
            InvoiceGenerateRequest(
                hostel_id=uuid4(),
                period_start=today,
                period_end=today + timedelta(days=30),
                due_date=today + timedelta(days=7),
                bypass_validation=True,  # type: ignore[call-arg]
            )


# =============================================================================
# 7. Operations Schemas Negative Validation (Attendance, Leave, Visitors)
# =============================================================================


class TestOperationsSchemasValidation:
    """Negative validation tests for Operations request schemas."""

    def test_attendance_action_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            AttendanceActionRequest(student_id=uuid4(), fake_biometric="hash")  # type: ignore[call-arg]

    def test_leave_request_chronological_dates(self) -> None:
        today = date.today()
        # to_date < from_date
        with pytest.raises(
            ValidationError, match="to_date must be greater than or equal to from_date"
        ):
            LeaveRequestCreate(
                from_date=today,
                to_date=today - timedelta(days=1),
                reason="Medical leave",
            )

    def test_leave_request_reason_boundaries(self) -> None:
        today = date.today()
        # empty reason
        with pytest.raises(ValidationError):
            LeaveRequestCreate(
                from_date=today,
                to_date=today + timedelta(days=2),
                reason="",
            )
        # reason > 500 chars
        with pytest.raises(ValidationError):
            LeaveRequestCreate(
                from_date=today,
                to_date=today + timedelta(days=2),
                reason="L" * 501,
            )

    def test_visitor_create_string_boundaries_and_extras(self) -> None:
        # Extra fields
        with pytest.raises(ValidationError, match="extra_forbidden"):
            VisitorCreate(
                student_id=uuid4(),
                name="John Doe",
                phone="+1234567890",
                relation="Father",
                untracked_extra="fail",  # type: ignore[call-arg]
            )
        # Empty name
        with pytest.raises(ValidationError):
            VisitorCreate(
                student_id=uuid4(),
                name="",
                phone="+1234567890",
                relation="Father",
            )
        # Name > 100
        with pytest.raises(ValidationError):
            VisitorCreate(
                student_id=uuid4(),
                name="N" * 101,
                phone="+1234567890",
                relation="Father",
            )


# =============================================================================
# 8. Complaints Schemas Negative Validation
# =============================================================================


class TestComplaintSchemasValidation:
    """Negative validation tests for Complaint schemas."""

    def test_complaint_create_string_boundaries(self) -> None:
        # Empty title
        with pytest.raises(ValidationError):
            ComplaintCreate(
                title="",
                description="Valid description",
                category=ComplaintCategory.PLUMBING,
            )
        # Title > 150
        with pytest.raises(ValidationError):
            ComplaintCreate(
                title="T" * 151,
                description="Valid description",
                category=ComplaintCategory.PLUMBING,
            )
        # Empty description
        with pytest.raises(ValidationError):
            ComplaintCreate(
                title="Valid Title",
                description="",
                category=ComplaintCategory.PLUMBING,
            )
        # Description > 1000
        with pytest.raises(ValidationError):
            ComplaintCreate(
                title="Valid Title",
                description="D" * 1001,
                category=ComplaintCategory.PLUMBING,
            )

    def test_complaint_create_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            ComplaintCreate(
                title="Leaking Tap",
                description="Water is dripping",
                category=ComplaintCategory.PLUMBING,
                internal_notes="Secret",  # type: ignore[call-arg]
            )

    def test_complaint_comment_create_boundaries_and_extras(self) -> None:
        with pytest.raises(ValidationError):
            ComplaintCommentCreate(body="")
        with pytest.raises(ValidationError):
            ComplaintCommentCreate(body="C" * 1001)
        with pytest.raises(ValidationError, match="extra_forbidden"):
            ComplaintCommentCreate(body="Comment", extra_val="no")  # type: ignore[call-arg]


# =============================================================================
# 9. Mess and Menu Schemas Negative Validation
# =============================================================================


class TestMessSchemasValidation:
    """Negative validation tests for Mess and Menu schemas."""

    def test_mess_menu_item_create_boundaries(self) -> None:
        # Day of week < 0
        with pytest.raises(ValidationError):
            MessMenuItemCreate(day_of_week=-1, meal_type=MealType.BREAKFAST, items=["Eggs"])
        # Day of week > 6
        with pytest.raises(ValidationError):
            MessMenuItemCreate(day_of_week=7, meal_type=MealType.BREAKFAST, items=["Eggs"])
        # Empty food items list
        with pytest.raises(ValidationError):
            MessMenuItemCreate(day_of_week=0, meal_type=MealType.BREAKFAST, items=[])

    def test_mess_menu_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            MessMenuItemCreate(
                day_of_week=0,
                meal_type=MealType.LUNCH,
                items=["Rice"],
                nutrition="high",  # type: ignore[call-arg]
            )

    def test_meal_opt_out_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            MealOptOutCreate(
                date=date.today(),
                meal_type=MealType.DINNER,
                reason="Out with family",  # type: ignore[call-arg]
            )


# =============================================================================
# 10. Notice Schemas Negative Validation
# =============================================================================


class TestNoticeSchemasValidation:
    """Negative validation tests for Notice schemas."""

    def test_notice_create_invalid_dates(self) -> None:
        now = datetime.now(UTC)
        # expires_at <= published_at
        with pytest.raises(ValidationError, match="expires_at must be strictly after published_at"):
            NoticeCreate(
                title="Annual Meeting",
                body="Details inside",
                published_at=now,
                expires_at=now - timedelta(hours=1),
            )
        # expires_at == published_at
        with pytest.raises(ValidationError, match="expires_at must be strictly after published_at"):
            NoticeCreate(
                title="Annual Meeting",
                body="Details inside",
                published_at=now,
                expires_at=now,
            )

    def test_notice_create_string_boundaries(self) -> None:
        # Empty title
        with pytest.raises(ValidationError):
            NoticeCreate(title="", body="Content")
        # Title > 255
        with pytest.raises(ValidationError):
            NoticeCreate(title="T" * 256, body="Content")
        # Empty body
        with pytest.raises(ValidationError):
            NoticeCreate(title="Title", body="")

    def test_notice_create_and_update_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            NoticeCreate(title="Title", body="Body", unauthorized_attr="fail")  # type: ignore[call-arg]
        with pytest.raises(ValidationError, match="extra_forbidden"):
            NoticeUpdate(title="New Title", bad_param="fail")  # type: ignore[call-arg]
