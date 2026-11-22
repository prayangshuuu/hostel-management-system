"""Billing and financial service handling fee structures, invoices, payments, and balances."""

from datetime import UTC, date, datetime
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
    Payment,
)
from app.models.user import User, UserRole
from app.repositories.allocation_repository import AllocationRepository
from app.repositories.billing_repository import (
    FeeStructureRepository,
    InvoiceRepository,
    PaymentRepository,
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
    PaymentCreate,
    PaymentRead,
    StudentBalanceRead,
)
from app.schemas.common import Page, PaginationParams
from app.services.hostel_service import ensure_hostel_access


class BillingService:
    """Service managing fee structures, invoice generation, payments, and balances."""

    def __init__(
        self,
        session: AsyncSession,
        fee_repo: FeeStructureRepository | None = None,
        invoice_repo: InvoiceRepository | None = None,
        payment_repo: PaymentRepository | None = None,
        hostel_repo: HostelRepository | None = None,
        warden_repo: WardenAssignmentRepository | None = None,
        allocation_repo: AllocationRepository | None = None,
        student_repo: StudentRepository | None = None,
    ) -> None:
        self.session = session
        self.fee_repo = fee_repo or FeeStructureRepository(session)
        self.invoice_repo = invoice_repo or InvoiceRepository(session)
        self.payment_repo = payment_repo or PaymentRepository(session)
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

    # -------------------------------------------------------------------------
    # Invoice Lifecycle & Payment Operations
    # -------------------------------------------------------------------------

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

    async def record_payment(
        self,
        invoice_id: UUID,
        data: PaymentCreate,
        current_user: User,
    ) -> Payment:
        """Record a payment against an invoice enforcing row locks, limits, and idempotency."""
        invoice = await self.invoice_repo.get_by_id_for_update(invoice_id)
        if invoice is None:
            raise NotFoundError("Invoice not found", code="INVOICE_NOT_FOUND")

        user_role = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if user_role == UserRole.STUDENT.value:
            if invoice.student.user_id != current_user.id:
                raise ForbiddenError("You cannot pay another student's invoice", code="FORBIDDEN")
        elif user_role == UserRole.WARDEN.value:
            hostel_id = invoice.allocation.bed.room.block.hostel_id
            await ensure_hostel_access(self.session, current_user, hostel_id)
        elif user_role != UserRole.ADMIN.value:
            raise ForbiddenError("Access forbidden", code="FORBIDDEN")

        if invoice.status == InvoiceStatus.VOID:
            raise BusinessRuleError("Cannot pay void invoice", code="INVOICE_VOID")
        if invoice.status == InvoiceStatus.PAID:
            raise BusinessRuleError("Invoice already fully paid", code="INVOICE_ALREADY_PAID")

        if data.amount <= Decimal("0.00"):
            raise BusinessRuleError(
                "Payment amount must be greater than zero",
                code="INVALID_PAYMENT_AMOUNT",
            )

        remaining_balance = invoice.amount - invoice.paid_amount
        if data.amount > remaining_balance:
            raise BusinessRuleError(
                "Payment exceeds remaining invoice balance",
                code="OVERPAYMENT_NOT_ALLOWED",
                status_code=400,
            )

        if data.reference:
            existing_payment = await self.payment_repo.get_by_reference(data.reference)
            if existing_payment is not None:
                raise ConflictError(
                    "Payment reference already exists",
                    code="DUPLICATE_PAYMENT_REFERENCE",
                )

        payment = Payment(
            invoice_id=invoice.id,
            amount=data.amount,
            method=data.method,
            reference=data.reference,
            paid_at=datetime.now(UTC),
        )
        created_payment = await self.payment_repo.create(payment)

        new_paid = invoice.paid_amount + data.amount
        invoice.paid_amount = new_paid
        if new_paid == invoice.amount:
            invoice.status = InvoiceStatus.PAID
        else:
            invoice.status = InvoiceStatus.PARTIAL

        await self.invoice_repo.update(invoice)
        return created_payment

    async def mark_overdue(self, today: date | None = None) -> int:
        """Transition past-due unpaid/partial invoices to OVERDUE status."""
        check_date = today or date.today()
        invoices = await self.invoice_repo.get_unpaid_or_partial_past_due(check_date)
        count = 0
        for inv in invoices:
            inv.status = InvoiceStatus.OVERDUE
            await self.invoice_repo.update(inv)
            count += 1
        return count

    async def get_student_balance(self, student_id: UUID) -> StudentBalanceRead:
        """Calculate aggregated billing totals and overdue amount for a student."""
        invoices = await self.invoice_repo.get_student_invoices(student_id)
        valid_invoices = [inv for inv in invoices if inv.status != InvoiceStatus.VOID]

        total_billed = sum((inv.amount for inv in valid_invoices), Decimal("0.00"))
        total_paid = sum((inv.paid_amount for inv in valid_invoices), Decimal("0.00"))
        current_balance = total_billed - total_paid

        today = date.today()
        overdue_amount = sum(
            (
                inv.amount - inv.paid_amount
                for inv in valid_invoices
                if inv.status == InvoiceStatus.OVERDUE
                or (
                    inv.status in (InvoiceStatus.UNPAID, InvoiceStatus.PARTIAL)
                    and inv.due_date < today
                )
            ),
            Decimal("0.00"),
        )
        unpaid_invoices_count = sum(
            1
            for inv in valid_invoices
            if inv.status in (InvoiceStatus.UNPAID, InvoiceStatus.PARTIAL, InvoiceStatus.OVERDUE)
        )

        return StudentBalanceRead(
            student_id=student_id,
            total_billed=total_billed,
            total_paid=total_paid,
            current_balance=current_balance,
            overdue_amount=overdue_amount,
            unpaid_invoices_count=unpaid_invoices_count,
        )

    async def get_student_balance_scoped(
        self, student_id: UUID, current_user: User
    ) -> StudentBalanceRead:
        """Fetch student balance enforcing admin access or warden hostel assignment."""
        user_role = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if user_role not in (UserRole.ADMIN.value, UserRole.WARDEN.value):
            raise ForbiddenError("Access forbidden", code="FORBIDDEN")

        student = await self.student_repo.get_by_id(student_id)
        if student is None or student.is_deleted:
            raise NotFoundError("Student not found", code="STUDENT_NOT_FOUND")

        if user_role == UserRole.WARDEN.value:
            warden_hostels = await self.warden_repo.list_hostel_ids_for_warden(current_user.id)
            active_alloc = await self.allocation_repo.get_active_by_student_id(student.id)
            if active_alloc is not None:
                hostel_id = active_alloc.bed.room.block.hostel_id
                if hostel_id not in warden_hostels:
                    raise ForbiddenError(
                        "You cannot access balance for students outside your assigned hostels",
                        code="FORBIDDEN",
                    )

        return await self.get_student_balance(student.id)

    async def get_my_invoices(self, current_user: User) -> list[Invoice]:
        """Fetch list of invoices for authenticated student."""
        profile = await self.student_repo.get_by_user_id(current_user.id)
        if profile is None or profile.is_deleted:
            raise NotFoundError("Student profile not found", code="PROFILE_NOT_FOUND")
        return await self.invoice_repo.get_student_invoices(profile.id)

    async def get_my_balance(self, current_user: User) -> StudentBalanceRead:
        """Fetch balance summary for authenticated student."""
        profile = await self.student_repo.get_by_user_id(current_user.id)
        if profile is None or profile.is_deleted:
            raise NotFoundError("Student profile not found", code="PROFILE_NOT_FOUND")
        return await self.get_student_balance(profile.id)

    async def delete_invoice(self, invoice_id: UUID) -> None:
        """Delete an invoice entity guarded against recorded payments."""
        invoice = await self.invoice_repo.get_by_id(invoice_id, load_payments=True)
        if invoice is None:
            raise NotFoundError("Invoice not found", code="INVOICE_NOT_FOUND")
        if len(invoice.payments) > 0 or invoice.paid_amount > Decimal("0.00"):
            raise ConflictError(
                "Cannot delete invoice with recorded payments. Void the invoice instead.",
                code="INVOICE_HAS_PAYMENTS",
            )
        await self.invoice_repo.delete(invoice)

    async def void_invoice(self, invoice_id: UUID) -> Invoice:
        """Void an existing invoice."""
        invoice = await self.invoice_repo.get_by_id(invoice_id, load_payments=True)
        if invoice is None:
            raise NotFoundError("Invoice not found", code="INVOICE_NOT_FOUND")
        invoice.status = InvoiceStatus.VOID
        await self.invoice_repo.update(invoice)
        loaded = await self.invoice_repo.get_by_id(invoice.id, load_payments=True)
        return loaded or invoice

    async def list_payments(
        self,
        params: PaginationParams,
        current_user: User,
    ) -> Page[PaymentRead]:
        """Fetch paginated payments with optional warden scoping."""
        user_role = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if user_role not in (UserRole.ADMIN.value, UserRole.WARDEN.value):
            raise ForbiddenError("Only admin and warden can list payments", code="FORBIDDEN")

        warden_hostel_ids: list[UUID] | None = None
        if user_role == UserRole.WARDEN.value:
            warden_hostel_ids = await self.warden_repo.list_hostel_ids_for_warden(current_user.id)

        payments, total = await self.payment_repo.list(
            params=params,
            warden_hostel_ids=warden_hostel_ids,
        )
        items = [PaymentRead.model_validate(p) for p in payments]
        return Page.create(items=items, total=total, params=params)
