"""Billing and financial service handling fee structures and invoices."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.models.billing import (
    FeeStructure,
    Invoice,
    InvoiceStatus,
)
from app.models.user import User, UserRole
from app.repositories.allocation_repository import AllocationRepository
from app.repositories.billing_repository import (
    FeeStructureRepository,
    InvoiceRepository,
)
from app.repositories.hostel_repository import (
    HostelRepository,
    WardenAssignmentRepository,
)
from app.repositories.student_repository import StudentRepository
from app.schemas.billing import (
    FeeStructureCreate,
    FeeStructureUpdate,
    InvoiceGenerateResponse,
    InvoiceRead,
)
from app.schemas.common import Page, PaginationParams
from app.services.hostel_service import ensure_hostel_access


class BillingService:
    """Service managing fee structures and bulk invoice generation."""

    def __init__(
        self,
        session: AsyncSession,
        fee_repo: FeeStructureRepository | None = None,
        invoice_repo: InvoiceRepository | None = None,
        hostel_repo: HostelRepository | None = None,
        warden_repo: WardenAssignmentRepository | None = None,
        allocation_repo: AllocationRepository | None = None,
        student_repo: StudentRepository | None = None,
    ) -> None:
        self.session = session
        self.fee_repo = fee_repo or FeeStructureRepository(session)
        self.invoice_repo = invoice_repo or InvoiceRepository(session)
        self.hostel_repo = hostel_repo or HostelRepository(session)
        self.warden_repo = warden_repo or WardenAssignmentRepository(session)
        self.allocation_repo = allocation_repo or AllocationRepository(session)
        self.student_repo = student_repo or StudentRepository(session)

    # -------------------------------------------------------------------------
    # Fee Structure Operations
    # -------------------------------------------------------------------------

    async def create_fee_structure(self, data: FeeStructureCreate) -> FeeStructure:
        """Create a new fee structure configuration for a hostel and room type."""
        hostel = await self.hostel_repo.get_by_id(data.hostel_id)
        if hostel is None or hostel.is_deleted:
            raise NotFoundError("Hostel not found", code="HOSTEL_NOT_FOUND")

        existing = await self.fee_repo.get_by_hostel_room_period(
            hostel_id=data.hostel_id,
            room_type=data.room_type,
            period=data.period,
        )
        if existing is not None:
            raise ConflictError(
                "Fee structure already exists for this hostel, room type, and period",
                code="FEE_STRUCTURE_ALREADY_EXISTS",
            )

        fee_structure = FeeStructure(
            hostel_id=data.hostel_id,
            room_type=data.room_type,
            amount=data.amount,
            period=data.period,
        )
        return await self.fee_repo.create(fee_structure)

    async def get_fee_structure(self, id: UUID) -> FeeStructure:
        """Retrieve a single fee structure by ID."""
        fs = await self.fee_repo.get_by_id(id)
        if fs is None:
            raise NotFoundError("Fee structure not found", code="FEE_STRUCTURE_NOT_FOUND")
        return fs

    async def update_fee_structure(self, id: UUID, data: FeeStructureUpdate) -> FeeStructure:
        """Update fee structure amount or active status."""
        fs = await self.get_fee_structure(id)
        if data.amount is not None:
            fs.amount = data.amount
        if data.is_active is not None:
            fs.is_active = data.is_active
        return await self.fee_repo.update(fs)

    async def delete_fee_structure(self, id: UUID) -> None:
        """Delete an existing fee structure."""
        fs = await self.get_fee_structure(id)
        await self.fee_repo.delete(fs)

    async def list_fee_structures(
        self, hostel_id: UUID | None = None, is_active: bool | None = None
    ) -> list[FeeStructure]:
        """List fee structures optionally filtered by hostel and active state."""
        return await self.fee_repo.list_by_hostel(hostel_id=hostel_id, is_active=is_active)

    # -------------------------------------------------------------------------
    # Invoice Generation Operations
    # -------------------------------------------------------------------------

    async def generate_invoices(
        self,
        hostel_id: UUID,
        period_start: date,
        period_end: date,
        due_date: date,
        current_user: User,
    ) -> InvoiceGenerateResponse:
        """Bulk generate fee invoices for active allocations with proration and idempotency."""
        await ensure_hostel_access(self.session, current_user, hostel_id)

        hostel = await self.hostel_repo.get_by_id(hostel_id)
        if hostel is None or hostel.is_deleted:
            raise NotFoundError("Hostel not found", code="HOSTEL_NOT_FOUND")

        fee_structures = await self.fee_repo.list_by_hostel(hostel_id, is_active=True)
        fee_map = {fs.room_type: fs.amount for fs in fee_structures}

        allocations = await self.allocation_repo.get_overlapping_for_hostel(
            hostel_id=hostel_id,
            period_start=period_start,
            period_end=period_end,
        )

        n_days = (period_end - period_start).days + 1
        generated_invoices: list[Invoice] = []
        skipped_count = 0
        generated_count = 0

        for allocation in allocations:
            # Idempotency check: non-void invoice exists for this allocation and period
            existing = await self.invoice_repo.get_existing_for_allocation_period(
                allocation_id=allocation.id,
                period_start=period_start,
                period_end=period_end,
            )
            if existing is not None:
                skipped_count += 1
                continue

            room = allocation.bed.room
            base_fee = fee_map.get(room.room_type)
            if base_fee is None:
                base_fee = getattr(room, "monthly_rent", None)

            if base_fee is None:
                raise BusinessRuleError(
                    f"No active fee structure found for room type {room.room_type.value}",
                    code="FEE_STRUCTURE_NOT_FOUND",
                )

            # Proration calculation
            eff_start = max(allocation.start_date, period_start)
            eff_end = (
                min(allocation.end_date, period_end)
                if allocation.end_date is not None
                else period_end
            )
            d_days = (eff_end - eff_start).days + 1
            if d_days <= 0:
                skipped_count += 1
                continue

            if d_days >= n_days:
                amount = base_fee
            else:
                amount = (base_fee * Decimal(d_days) / Decimal(n_days)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )

            invoice = Invoice(
                student_id=allocation.student_id,
                allocation_id=allocation.id,
                period_start=period_start,
                period_end=period_end,
                amount=amount,
                paid_amount=Decimal("0.00"),
                due_date=due_date,
                status=InvoiceStatus.UNPAID,
            )
            created_inv = await self.invoice_repo.create(invoice)
            generated_invoices.append(created_inv)
            generated_count += 1

        invoices_read: list[InvoiceRead] = []
        for inv in generated_invoices:
            loaded = await self.invoice_repo.get_by_id(inv.id, load_payments=False)
            if loaded is not None:
                invoices_read.append(InvoiceRead.model_validate(loaded))

        return InvoiceGenerateResponse(
            generated_count=generated_count,
            skipped_count=skipped_count,
            invoices=invoices_read,
        )

    async def get_invoice(self, invoice_id: UUID, current_user: User) -> Invoice:
        """Fetch single invoice enforcing role permissions and warden/student scoping."""
        invoice = await self.invoice_repo.get_by_id(invoice_id, load_payments=True)
        if invoice is None:
            raise NotFoundError("Invoice not found", code="INVOICE_NOT_FOUND")

        user_role = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if user_role == UserRole.STUDENT.value:
            if invoice.student.user_id != current_user.id:
                raise ForbiddenError("You cannot view this invoice", code="FORBIDDEN")
        elif user_role == UserRole.WARDEN.value:
            hostel_id = invoice.allocation.bed.room.block.hostel_id
            await ensure_hostel_access(self.session, current_user, hostel_id)
        elif user_role != UserRole.ADMIN.value:
            raise ForbiddenError("Access forbidden", code="FORBIDDEN")

        return invoice

    async def list_invoices(
        self,
        params: PaginationParams,
        current_user: User,
        status: InvoiceStatus | None = None,
        student_id: UUID | None = None,
        hostel_id: UUID | None = None,
        period_start: date | None = None,
        period_end: date | None = None,
    ) -> Page[InvoiceRead]:
        """Fetch paginated invoices with filters and warden scoping."""
        user_role = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if user_role not in (UserRole.ADMIN.value, UserRole.WARDEN.value):
            raise ForbiddenError("Only admin and warden can list invoices", code="FORBIDDEN")

        warden_hostel_ids: list[UUID] | None = None
        if user_role == UserRole.WARDEN.value:
            warden_hostel_ids = await self.warden_repo.list_hostel_ids_for_warden(current_user.id)
            if hostel_id is not None and hostel_id not in warden_hostel_ids:
                raise ForbiddenError("You are not assigned to this hostel", code="FORBIDDEN")

        invoices, total = await self.invoice_repo.list(
            params=params,
            status=status,
            student_id=student_id,
            hostel_id=hostel_id,
            period_start=period_start,
            period_end=period_end,
            warden_hostel_ids=warden_hostel_ids,
        )

        items = [InvoiceRead.model_validate(inv) for inv in invoices]
        return Page.create(items=items, total=total, params=params)
