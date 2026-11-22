"""Unit tests for billing, fee structure, invoice, and payment Pydantic schemas."""

from datetime import UTC, date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.billing import FeePeriod, InvoiceStatus, PaymentMethod
from app.models.room import RoomType
from app.schemas.billing import (
    FeeStructureCreate,
    FeeStructureUpdate,
    InvoiceGenerateRequest,
    InvoiceRead,
    PaymentCreate,
)


def test_fee_structure_create_schema() -> None:
    """Test FeeStructureCreate validation rules."""
    valid = FeeStructureCreate(
        hostel_id=uuid4(),
        room_type=RoomType.SINGLE,
        amount=Decimal("5000.00"),
        period=FeePeriod.MONTHLY,
    )
    assert valid.amount == Decimal("5000.00")

    # Amount <= 0 fails
    with pytest.raises(ValidationError):
        FeeStructureCreate(
            hostel_id=uuid4(),
            room_type=RoomType.SINGLE,
            amount=Decimal("0.00"),
        )

    with pytest.raises(ValidationError):
        FeeStructureCreate(
            hostel_id=uuid4(),
            room_type=RoomType.SINGLE,
            amount=Decimal("-10.00"),
        )


def test_fee_structure_update_schema() -> None:
    """Test FeeStructureUpdate validation rules."""
    update = FeeStructureUpdate(amount=Decimal("5500.00"), is_active=False)
    assert update.amount == Decimal("5500.00")
    assert update.is_active is False

    with pytest.raises(ValidationError):
        FeeStructureUpdate(amount=Decimal("0.00"))


def test_invoice_generate_request_validation() -> None:
    """Test InvoiceGenerateRequest chronological date validators."""
    # Valid
    req = InvoiceGenerateRequest(
        hostel_id=uuid4(),
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        due_date=date(2026, 11, 15),
    )
    assert req.period_start == date(2026, 11, 1)

    # period_end < period_start fails
    with pytest.raises(ValidationError):
        InvoiceGenerateRequest(
            hostel_id=uuid4(),
            period_start=date(2026, 11, 30),
            period_end=date(2026, 11, 1),
            due_date=date(2026, 12, 5),
        )

    # due_date < period_start fails
    with pytest.raises(ValidationError):
        InvoiceGenerateRequest(
            hostel_id=uuid4(),
            period_start=date(2026, 11, 1),
            period_end=date(2026, 11, 30),
            due_date=date(2026, 10, 31),
        )


def test_payment_create_schema() -> None:
    """Test PaymentCreate validation rules."""
    valid = PaymentCreate(
        amount=Decimal("1500.00"),
        method=PaymentMethod.ONLINE,
        reference="PAY-123",
    )
    assert valid.amount == Decimal("1500.00")

    with pytest.raises(ValidationError):
        PaymentCreate(
            amount=Decimal("0.00"),
            method=PaymentMethod.CASH,
        )


def test_invoice_read_balance_calculation() -> None:
    """Test InvoiceRead computes balance from amount and paid_amount."""
    from datetime import datetime

    data = {
        "id": uuid4(),
        "student_id": uuid4(),
        "allocation_id": uuid4(),
        "period_start": date(2026, 11, 1),
        "period_end": date(2026, 11, 30),
        "amount": Decimal("2500.00"),
        "paid_amount": Decimal("1000.00"),
        "due_date": date(2026, 11, 15),
        "status": InvoiceStatus.PARTIAL,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    inv = InvoiceRead.model_validate(data)
    assert inv.balance == Decimal("1500.00")
