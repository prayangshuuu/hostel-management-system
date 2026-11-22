"""Billing, fee structure, invoice, and payment REST endpoints."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db, require_role
from app.models.billing import InvoiceStatus
from app.models.user import User, UserRole
from app.schemas.billing import (
    FeeStructureCreate,
    FeeStructureRead,
    FeeStructureUpdate,
    InvoiceDetailRead,
    InvoiceGenerateRequest,
    InvoiceGenerateResponse,
    InvoiceRead,
    PaymentCreate,
    PaymentRead,
    StudentBalanceRead,
)
from app.schemas.common import Page, PaginationParams
from app.services.billing_service import BillingService

router = APIRouter(tags=["billing"])


# =============================================================================
# Fee Structure Endpoints
# =============================================================================


@router.post(
    "/fee-structures",
    response_model=FeeStructureRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
    summary="Create a new fee structure (admin only)",
)
async def create_fee_structure(
    body: FeeStructureCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> FeeStructureRead:
    """Configure a new fee structure for a hostel and room type."""
    service = BillingService(session)
    fs = await service.create_fee_structure(body)
    return FeeStructureRead.model_validate(fs)


@router.get(
    "/fee-structures",
    response_model=list[FeeStructureRead],
    summary="List fee structures (authenticated)",
)
async def list_fee_structures(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    hostel_id: Annotated[UUID | None, Query(description="Filter by hostel ID")] = None,
    is_active: Annotated[bool | None, Query(description="Filter by active status")] = None,
) -> list[FeeStructureRead]:
    """Retrieve list of fee structures optionally filtered by hostel."""
    service = BillingService(session)
    items = await service.list_fee_structures(hostel_id=hostel_id, is_active=is_active)
    return [FeeStructureRead.model_validate(fs) for fs in items]


@router.get(
    "/fee-structures/{id}",
    response_model=FeeStructureRead,
    summary="Get fee structure by ID (authenticated)",
)
async def get_fee_structure(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> FeeStructureRead:
    """Retrieve single fee structure configuration."""
    service = BillingService(session)
    fs = await service.get_fee_structure(id)
    return FeeStructureRead.model_validate(fs)


@router.patch(
    "/fee-structures/{id}",
    response_model=FeeStructureRead,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
    summary="Update fee structure (admin only)",
)
async def update_fee_structure(
    id: UUID,
    body: FeeStructureUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> FeeStructureRead:
    """Update fee structure amount or active status."""
    service = BillingService(session)
    fs = await service.update_fee_structure(id=id, data=body)
    return FeeStructureRead.model_validate(fs)


@router.delete(
    "/fee-structures/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
    summary="Delete fee structure (admin only)",
)
async def delete_fee_structure(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete a fee structure configuration."""
    service = BillingService(session)
    await service.delete_fee_structure(id)


# =============================================================================
# Invoice Generation & Management Endpoints
# =============================================================================


@router.post(
    "/invoices/generate",
    response_model=InvoiceGenerateResponse,
    summary="Generate fee invoices in bulk (admin or assigned warden)",
)
async def generate_invoices(
    body: InvoiceGenerateRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
) -> InvoiceGenerateResponse:
    """Bulk generate invoices for hostel occupants with proration and idempotency."""
    service = BillingService(session)
    return await service.generate_invoices(
        hostel_id=body.hostel_id,
        period_start=body.period_start,
        period_end=body.period_end,
        due_date=body.due_date,
        current_user=current_user,
    )


@router.post(
    "/invoices/mark-overdue",
    dependencies=[Depends(require_role(UserRole.ADMIN))],
    summary="Mark past-due unpaid invoices as overdue (admin only)",
)
async def mark_overdue_invoices(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, int]:
    """Transition past-due unpaid and partial invoices to overdue status."""
    service = BillingService(session)
    count = await service.mark_overdue()
    return {"updated_count": count}


@router.get(
    "/invoices",
    response_model=Page[InvoiceRead],
    summary="List invoices with filters and warden scoping (admin or warden)",
)
async def list_invoices(
    params: Annotated[PaginationParams, Depends()],
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
    invoice_status: Annotated[
        InvoiceStatus | None,
        Query(alias="status", description="Filter by invoice status"),
    ] = None,
    student_id: Annotated[UUID | None, Query(description="Filter by student profile ID")] = None,
    hostel_id: Annotated[UUID | None, Query(description="Filter by hostel ID")] = None,
    period_start: Annotated[date | None, Query(description="Filter by period start date")] = None,
    period_end: Annotated[date | None, Query(description="Filter by period end date")] = None,
) -> Page[InvoiceRead]:
    """Retrieve paginated invoices enforcing warden access scoping."""
    service = BillingService(session)
    return await service.list_invoices(
        params=params,
        current_user=current_user,
        status=invoice_status,
        student_id=student_id,
        hostel_id=hostel_id,
        period_start=period_start,
        period_end=period_end,
    )


@router.get(
    "/invoices/{id}",
    response_model=InvoiceDetailRead,
    summary="Get invoice details with payments (admin, assigned warden, or student self)",
)
async def get_invoice(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> InvoiceDetailRead:
    """Retrieve detailed invoice record including payment ledger."""
    service = BillingService(session)
    invoice = await service.get_invoice(invoice_id=id, current_user=current_user)
    return InvoiceDetailRead.model_validate(invoice)


@router.delete(
    "/invoices/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
    summary="Delete an invoice (admin only, guarded against payments)",
)
async def delete_invoice(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete an invoice that has no recorded payments."""
    service = BillingService(session)
    await service.delete_invoice(id)


@router.post(
    "/invoices/{id}/void",
    response_model=InvoiceRead,
    summary="Void an invoice (admin only)",
)
async def void_invoice(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> InvoiceRead:
    """Void an invoice entity."""
    service = BillingService(session)
    invoice = await service.void_invoice(id, current_user=current_user)
    return InvoiceRead.model_validate(invoice)


@router.post(
    "/invoices/{id}/payments",
    response_model=PaymentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record payment against invoice (student for self, admin, or assigned warden)",
)
async def record_payment(
    id: UUID,
    body: PaymentCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> PaymentRead:
    """Record a payment, enforcing non-overpayment and recalculating status."""
    service = BillingService(session)
    payment = await service.record_payment(invoice_id=id, data=body, current_user=current_user)
    return PaymentRead.model_validate(payment)


# =============================================================================
# Payment Ledger & Student Financials Endpoints
# =============================================================================


@router.get(
    "/payments",
    response_model=Page[PaymentRead],
    summary="List payments with warden scoping (admin or warden)",
)
async def list_payments(
    params: Annotated[PaginationParams, Depends()],
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
) -> Page[PaymentRead]:
    """Retrieve paginated payments ledger."""
    service = BillingService(session)
    return await service.list_payments(params=params, current_user=current_user)


@router.get(
    "/students/me/invoices",
    response_model=list[InvoiceRead],
    summary="Get current student invoices (student self-service)",
)
async def get_my_invoices(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.STUDENT))],
) -> list[InvoiceRead]:
    """Retrieve billing invoices issued to the authenticated student."""
    service = BillingService(session)
    invoices = await service.get_my_invoices(current_user=current_user)
    return [InvoiceRead.model_validate(inv) for inv in invoices]


@router.get(
    "/students/me/balance",
    response_model=StudentBalanceRead,
    summary="Get current student financial balance summary (student self-service)",
)
async def get_my_balance(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.STUDENT))],
) -> StudentBalanceRead:
    """Retrieve financial summary and outstanding balances for authenticated student."""
    service = BillingService(session)
    return await service.get_my_balance(current_user=current_user)


@router.get(
    "/students/{id}/balance",
    response_model=StudentBalanceRead,
    summary="Get student financial balance by ID (admin or assigned warden)",
)
async def get_student_balance(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
) -> StudentBalanceRead:
    """Retrieve financial summary for a student profile with warden scoping."""
    service = BillingService(session)
    return await service.get_student_balance_scoped(student_id=id, current_user=current_user)
