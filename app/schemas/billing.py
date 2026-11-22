"""Billing, fee structure, invoice, and payment schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.billing import FeePeriod, InvoiceStatus, PaymentMethod
from app.models.room import RoomType


class FeeStructureCreate(BaseModel):
    """Payload for configuring a fee structure for a hostel and room type."""

    model_config = ConfigDict(extra="forbid")

    hostel_id: UUID
    room_type: RoomType
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    period: FeePeriod = FeePeriod.MONTHLY


class FeeStructureUpdate(BaseModel):
    """Payload for modifying an existing fee structure."""

    model_config = ConfigDict(extra="forbid")

    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    is_active: bool | None = None


class FeeStructureRead(BaseModel):
    """Public fee structure response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    hostel_id: UUID
    room_type: RoomType
    amount: Decimal
    period: FeePeriod
    is_active: bool
    created_at: datetime
    updated_at: datetime


class InvoiceGenerateRequest(BaseModel):
    """Request payload for bulk invoice generation."""

    model_config = ConfigDict(extra="forbid")

    hostel_id: UUID
    period_start: date
    period_end: date
    due_date: date

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        """Enforce chronological validity of billing period and due date."""
        if self.period_end < self.period_start:
            raise ValueError("period_end must be greater than or equal to period_start")
        if self.due_date < self.period_start:
            raise ValueError("due_date must be greater than or equal to period_start")
        return self


class InvoiceRead(BaseModel):
    """Public invoice response schema with enriched student and hostel details."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_id: UUID
    allocation_id: UUID
    period_start: date
    period_end: date
    amount: Decimal
    paid_amount: Decimal
    balance: Decimal
    due_date: date
    status: InvoiceStatus
    created_at: datetime
    updated_at: datetime

    student_name: str | None = None
    student_no: str | None = None
    hostel_id: UUID | None = None
    hostel_name: str | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_enriched_fields(cls, data: Any) -> Any:
        """Extract enriched contextual details from related ORM attributes if available."""
        if isinstance(data, dict):
            if "balance" not in data and "amount" in data:
                paid = data.get("paid_amount") or Decimal("0.00")
                data["balance"] = data["amount"] - paid
            return data

        amount = getattr(data, "amount", Decimal("0.00"))
        paid_amount = getattr(data, "paid_amount", Decimal("0.00"))
        balance = getattr(data, "balance", None)
        if balance is None:
            balance = amount - paid_amount

        d = getattr(data, "__dict__", {})
        student = d.get("student")
        user = getattr(student, "__dict__", {}).get("user") if student else None
        allocation = d.get("allocation")
        bed = getattr(allocation, "__dict__", {}).get("bed") if allocation else None
        room = getattr(bed, "__dict__", {}).get("room") if bed else None
        block = getattr(room, "__dict__", {}).get("block") if room else None
        hostel = getattr(block, "__dict__", {}).get("hostel") if block else None

        res: dict[str, Any] = {
            "id": getattr(data, "id", None),
            "student_id": getattr(data, "student_id", None),
            "allocation_id": getattr(data, "allocation_id", None),
            "period_start": getattr(data, "period_start", None),
            "period_end": getattr(data, "period_end", None),
            "amount": amount,
            "paid_amount": paid_amount,
            "balance": balance,
            "due_date": getattr(data, "due_date", None),
            "status": getattr(data, "status", None),
            "created_at": getattr(data, "created_at", None),
            "updated_at": getattr(data, "updated_at", None),
            "student_name": getattr(user, "full_name", getattr(data, "student_name", None)),
            "student_no": getattr(student, "student_no", getattr(data, "student_no", None)),
            "hostel_id": getattr(
                hostel,
                "id",
                getattr(block, "hostel_id", getattr(data, "hostel_id", None)),
            ),
            "hostel_name": getattr(hostel, "name", getattr(data, "hostel_name", None)),
        }
        payments = d.get("payments")
        if payments is not None:
            res["payments"] = payments
        return res


class InvoiceGenerateResponse(BaseModel):
    """Result of batch invoice generation."""

    generated_count: int
    skipped_count: int
    invoices: list[InvoiceRead]


class PaymentCreate(BaseModel):
    """Payload for recording a payment against an invoice."""

    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    method: PaymentMethod
    reference: str | None = Field(default=None, max_length=100)


class PaymentRead(BaseModel):
    """Public payment response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    invoice_id: UUID
    amount: Decimal
    method: PaymentMethod
    reference: str | None = None
    paid_at: datetime
    created_at: datetime


class InvoiceDetailRead(InvoiceRead):
    """Invoice detail response schema including payment history."""

    payments: list[PaymentRead] = Field(default_factory=list)


class StudentBalanceRead(BaseModel):
    """Aggregated financial balance for a student."""

    student_id: UUID
    total_billed: Decimal
    total_paid: Decimal
    current_balance: Decimal
    overdue_amount: Decimal
    unpaid_invoices_count: int


__all__ = [
    "FeePeriod",
    "FeeStructureCreate",
    "FeeStructureRead",
    "FeeStructureUpdate",
    "InvoiceDetailRead",
    "InvoiceGenerateRequest",
    "InvoiceGenerateResponse",
    "InvoiceRead",
    "InvoiceStatus",
    "PaymentCreate",
    "PaymentMethod",
    "PaymentRead",
    "StudentBalanceRead",
]
