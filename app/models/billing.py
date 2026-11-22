"""Billing, fee structure, invoice, and payment database models."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPkMixin
from app.models.room import RoomType

if TYPE_CHECKING:
    from app.models.allocation import Allocation
    from app.models.hostel import Hostel
    from app.models.student import StudentProfile


class FeePeriod(enum.StrEnum):
    """Fee charging frequency/period."""

    MONTHLY = "monthly"
    SEMESTER = "semester"


class InvoiceStatus(enum.StrEnum):
    """Invoice payment lifecycle status."""

    UNPAID = "unpaid"
    PARTIAL = "partial"
    PAID = "paid"
    OVERDUE = "overdue"
    VOID = "void"


class PaymentMethod(enum.StrEnum):
    """Supported payment methods."""

    CASH = "cash"
    CARD = "card"
    BANK = "bank"
    ONLINE = "online"


class FeeStructure(Base, UUIDPkMixin, TimestampMixin):
    """Fee structure entity per hostel and room type."""

    __tablename__ = "fee_structures"
    __table_args__ = (
        UniqueConstraint(
            "hostel_id",
            "room_type",
            "period",
            name="uq_fee_structures_hostel_room_period",
        ),
    )

    hostel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("hostels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    room_type: Mapped[RoomType] = mapped_column(
        Enum(RoomType, native_enum=False, length=20),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )
    period: Mapped[FeePeriod] = mapped_column(
        Enum(FeePeriod, native_enum=False, length=20),
        nullable=False,
        default=FeePeriod.MONTHLY,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    hostel: Mapped[Hostel] = relationship(
        "Hostel",
        back_populates="fee_structures",
    )

    def __repr__(self) -> str:
        return (
            f"<FeeStructure id={self.id} hostel_id={self.hostel_id} "
            f"room_type={self.room_type} period={self.period} amount={self.amount}>"
        )


class Invoice(Base, UUIDPkMixin, TimestampMixin):
    """Student fee invoice entity."""

    __tablename__ = "invoices"
    __table_args__ = (
        Index(
            "uq_invoices_allocation_period",
            "allocation_id",
            "period_start",
            "period_end",
            unique=True,
            postgresql_where=text("status != 'void'"),
            sqlite_where=text("status != 'void'"),
        ),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    allocation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("allocations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus, native_enum=False, length=20),
        nullable=False,
        default=InvoiceStatus.UNPAID,
        index=True,
    )

    student: Mapped[StudentProfile] = relationship(
        "StudentProfile",
        back_populates="invoices",
    )
    allocation: Mapped[Allocation] = relationship(
        "Allocation",
        back_populates="invoices",
    )
    payments: Mapped[list[Payment]] = relationship(
        "Payment",
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="Payment.paid_at",
    )

    def __repr__(self) -> str:
        return (
            f"<Invoice id={self.id} student_id={self.student_id} "
            f"allocation_id={self.allocation_id} amount={self.amount} status={self.status}>"
        )


class Payment(Base, UUIDPkMixin, TimestampMixin):
    """Payment transaction entity against an invoice."""

    __tablename__ = "payments"
    __table_args__ = (
        Index(
            "uq_payments_reference",
            "reference",
            unique=True,
            postgresql_where=text("reference IS NOT NULL"),
            sqlite_where=text("reference IS NOT NULL"),
        ),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    method: Mapped[PaymentMethod] = mapped_column(
        Enum(PaymentMethod, native_enum=False, length=20),
        nullable=False,
    )
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )

    invoice: Mapped[Invoice] = relationship(
        "Invoice",
        back_populates="payments",
    )

    def __repr__(self) -> str:
        return (
            f"<Payment id={self.id} invoice_id={self.invoice_id} "
            f"amount={self.amount} method={self.method}>"
        )
