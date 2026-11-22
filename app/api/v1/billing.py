"""Billing, fee structure, and invoice REST endpoints."""

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
