"""Billing repositories for fee structures, invoices, and payments."""

import builtins
from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.base import ExecutableOption

from app.models.allocation import Allocation
from app.models.billing import (
    FeePeriod,
    FeeStructure,
    Invoice,
    InvoiceStatus,
    Payment,
)
from app.models.hostel import Block
from app.models.room import Bed, Room, RoomType
from app.models.student import StudentProfile
from app.schemas.common import PaginationParams


class FeeStructureRepository:
    """Repository managing fee structures per hostel and room type."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, id: UUID) -> FeeStructure | None:
        """Fetch fee structure by primary key UUID."""
        stmt = select(FeeStructure).where(FeeStructure.id == id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_hostel_room_period(
        self, hostel_id: UUID, room_type: RoomType, period: FeePeriod
    ) -> FeeStructure | None:
        """Fetch fee structure for specific hostel, room type, and period."""
        stmt = select(FeeStructure).where(
            FeeStructure.hostel_id == hostel_id,
            FeeStructure.room_type == room_type,
            FeeStructure.period == period,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, fee_structure: FeeStructure) -> FeeStructure:
        """Add and flush a new fee structure."""
        self.session.add(fee_structure)
        await self.session.flush()
        await self.session.refresh(fee_structure)
        return fee_structure

    async def update(self, fee_structure: FeeStructure) -> FeeStructure:
        """Flush changes to an existing fee structure."""
        await self.session.flush()
        await self.session.refresh(fee_structure)
        return fee_structure

    async def delete(self, fee_structure: FeeStructure) -> None:
        """Delete a fee structure record."""
        await self.session.delete(fee_structure)
        await self.session.flush()

    async def list_by_hostel(
        self, hostel_id: UUID | None = None, is_active: bool | None = None
    ) -> builtins.list[FeeStructure]:
        """List fee structures optionally filtered by hostel and active state."""
        stmt = select(FeeStructure)
        if hostel_id is not None:
            stmt = stmt.where(FeeStructure.hostel_id == hostel_id)
        if is_active is not None:
            stmt = stmt.where(FeeStructure.is_active == is_active)
        stmt = stmt.order_by(FeeStructure.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class InvoiceRepository:
    """Repository managing invoice persistence, updates, and queries."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _eager_load_options(self, load_payments: bool = True) -> builtins.list[ExecutableOption]:
        """Return eager loading options for related entities."""
        options: builtins.list[ExecutableOption] = [
            selectinload(Invoice.student).selectinload(StudentProfile.user),
            selectinload(Invoice.allocation)
            .selectinload(Allocation.bed)
            .selectinload(Bed.room)
            .selectinload(Room.block)
            .selectinload(Block.hostel),
        ]
        if load_payments:
            options.append(selectinload(Invoice.payments))
        return options

    async def get_by_id(self, id: UUID, load_payments: bool = True) -> Invoice | None:
        """Fetch invoice by primary key UUID with relational context."""
        stmt = (
            select(Invoice)
            .options(*self._eager_load_options(load_payments=load_payments))
            .where(Invoice.id == id)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_id_for_update(self, id: UUID) -> Invoice | None:
        """Fetch invoice by primary key UUID, locking the row on PostgreSQL."""
        stmt = (
            select(Invoice)
            .options(*self._eager_load_options(load_payments=True))
            .where(Invoice.id == id)
        )
        bind = self.session.bind
        if bind and getattr(bind.dialect, "name", "") == "postgresql":
            stmt = stmt.with_for_update()
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_existing_for_allocation_period(
        self, allocation_id: UUID, period_start: date, period_end: date
    ) -> Invoice | None:
        """Fetch non-void invoice for a specific allocation and billing period."""
        stmt = select(Invoice).where(
            Invoice.allocation_id == allocation_id,
            Invoice.period_start == period_start,
            Invoice.period_end == period_end,
            Invoice.status != InvoiceStatus.VOID,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, invoice: Invoice) -> Invoice:
        """Add and flush a new invoice."""
        self.session.add(invoice)
        await self.session.flush()
        await self.session.refresh(
            invoice,
            attribute_names=[
                "id",
                "student_id",
                "allocation_id",
                "period_start",
                "period_end",
                "amount",
                "paid_amount",
                "due_date",
                "status",
                "created_at",
                "updated_at",
            ],
        )
        return invoice

    async def update(self, invoice: Invoice) -> Invoice:
        """Flush changes to an existing invoice."""
        await self.session.flush()
        await self.session.refresh(
            invoice,
            attribute_names=[
                "id",
                "student_id",
                "allocation_id",
                "period_start",
                "period_end",
                "amount",
                "paid_amount",
                "due_date",
                "status",
                "created_at",
                "updated_at",
            ],
        )
        return invoice

    async def delete(self, invoice: Invoice) -> None:
        """Delete an invoice entity."""
        await self.session.delete(invoice)
        await self.session.flush()

    async def list(
        self,
        params: PaginationParams,
        status: InvoiceStatus | None = None,
        student_id: UUID | None = None,
        hostel_id: UUID | None = None,
        period_start: date | None = None,
        period_end: date | None = None,
        warden_hostel_ids: builtins.list[UUID] | None = None,
    ) -> tuple[builtins.list[Invoice], int]:
        """Query paginated invoices with filters and warden scoping."""
        stmt = select(Invoice).options(*self._eager_load_options(load_payments=False))
        count_stmt = select(func.count(Invoice.id))

        needs_allocation_join = hostel_id is not None or warden_hostel_ids is not None
        if needs_allocation_join:
            stmt = (
                stmt.join(Allocation, Invoice.allocation_id == Allocation.id)
                .join(Bed, Allocation.bed_id == Bed.id)
                .join(Room, Bed.room_id == Room.id)
                .join(Block, Room.block_id == Block.id)
            )
            count_stmt = (
                count_stmt.join(Allocation, Invoice.allocation_id == Allocation.id)
                .join(Bed, Allocation.bed_id == Bed.id)
                .join(Room, Bed.room_id == Room.id)
                .join(Block, Room.block_id == Block.id)
            )
            if hostel_id is not None:
                stmt = stmt.where(Block.hostel_id == hostel_id)
                count_stmt = count_stmt.where(Block.hostel_id == hostel_id)
            if warden_hostel_ids is not None:
                stmt = stmt.where(Block.hostel_id.in_(warden_hostel_ids))
                count_stmt = count_stmt.where(Block.hostel_id.in_(warden_hostel_ids))

        if status is not None:
            stmt = stmt.where(Invoice.status == status)
            count_stmt = count_stmt.where(Invoice.status == status)

        if student_id is not None:
            stmt = stmt.where(Invoice.student_id == student_id)
            count_stmt = count_stmt.where(Invoice.student_id == student_id)

        if period_start is not None:
            stmt = stmt.where(Invoice.period_start >= period_start)
            count_stmt = count_stmt.where(Invoice.period_start >= period_start)

        if period_end is not None:
            stmt = stmt.where(Invoice.period_end <= period_end)
            count_stmt = count_stmt.where(Invoice.period_end <= period_end)

        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        stmt = stmt.order_by(Invoice.created_at.desc()).offset(params.offset).limit(params.limit)
        result = await self.session.execute(stmt)
        invoices = list(result.scalars().all())

        return invoices, total

    async def get_unpaid_or_partial_past_due(self, today: date) -> builtins.list[Invoice]:
        """Fetch invoices with status UNPAID or PARTIAL where due_date < today."""
        stmt = (
            select(Invoice)
            .where(
                Invoice.status.in_([InvoiceStatus.UNPAID, InvoiceStatus.PARTIAL]),
                Invoice.due_date < today,
            )
            .order_by(Invoice.due_date.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_student_invoices(self, student_id: UUID) -> builtins.list[Invoice]:
        """Fetch all invoices for a given student profile."""
        stmt = (
            select(Invoice)
            .options(*self._eager_load_options(load_payments=True))
            .where(Invoice.student_id == student_id)
            .order_by(Invoice.period_start.desc(), Invoice.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class PaymentRepository:
    """Repository managing queries and persistence for Payment records."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, payment: Payment) -> Payment:
        """Add and flush a new payment record."""
        self.session.add(payment)
        await self.session.flush()
        await self.session.refresh(payment)
        return payment

    async def get_by_reference(self, reference: str) -> Payment | None:
        """Fetch payment by unique external reference."""
        stmt = select(Payment).where(Payment.reference == reference)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_invoice(self, invoice_id: UUID) -> builtins.list[Payment]:
        """Fetch all payments for a given invoice ordered chronologically."""
        stmt = (
            select(Payment).where(Payment.invoice_id == invoice_id).order_by(Payment.paid_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list(
        self,
        params: PaginationParams,
        warden_hostel_ids: builtins.list[UUID] | None = None,
    ) -> tuple[builtins.list[Payment], int]:
        """Query paginated payments with optional warden scoping."""
        stmt = select(Payment)
        count_stmt = select(func.count(Payment.id))

        if warden_hostel_ids is not None:
            stmt = (
                stmt.join(Invoice, Payment.invoice_id == Invoice.id)
                .join(Allocation, Invoice.allocation_id == Allocation.id)
                .join(Bed, Allocation.bed_id == Bed.id)
                .join(Room, Bed.room_id == Room.id)
                .join(Block, Room.block_id == Block.id)
                .where(Block.hostel_id.in_(warden_hostel_ids))
            )
            count_stmt = (
                count_stmt.join(Invoice, Payment.invoice_id == Invoice.id)
                .join(Allocation, Invoice.allocation_id == Allocation.id)
                .join(Bed, Allocation.bed_id == Bed.id)
                .join(Room, Bed.room_id == Room.id)
                .join(Block, Room.block_id == Block.id)
                .where(Block.hostel_id.in_(warden_hostel_ids))
            )

        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        stmt = stmt.order_by(Payment.paid_at.desc()).offset(params.offset).limit(params.limit)
        result = await self.session.execute(stmt)
        payments = list(result.scalars().all())

        return payments, total
