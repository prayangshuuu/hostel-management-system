"""Web routes for Staff/Admin Billing, Invoices, Fees, and Payments."""

import logging
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.csrf import verify_csrf
from app.core.exceptions import AppException
from app.models.billing import InvoiceStatus, PaymentMethod
from app.models.room import RoomType
from app.models.user import User, UserRole
from app.repositories.allocation_repository import AllocationRepository
from app.repositories.billing_repository import (
    FeeStructureRepository,
    InvoiceRepository,
)
from app.repositories.hostel_repository import HostelRepository
from app.repositories.student_repository import StudentRepository
from app.schemas.billing import FeeStructureCreate, FeeStructureUpdate, PaymentCreate
from app.schemas.common import PaginationParams
from app.services.billing_service import BillingService
from app.web.deps import render_template, require_admin_web, require_staff_web

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/billing", tags=["web-admin-billing"])


# =========================================================================
# 1. Fee Structures (Admin Only)
# =========================================================================


@router.get("/fees", response_class=HTMLResponse)
async def list_fee_structures(
    request: Request,
    hostel_id: UUID | None = None,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """List fee structures (CRUD page pattern)."""
    user, _ = current_staff
    billing_service = BillingService(db)

    fees = await billing_service.list_fee_structures(hostel_id=hostel_id)
    hostel_repo = HostelRepository(db)
    hostels, _ = await hostel_repo.list(PaginationParams(page=1, size=100))

    return render_template(
        request,
        "admin/billing/fees/index.html",
        {
            "current_user": user,
            "active_nav": "fees",
            "fees": fees,
            "hostels": hostels,
            "filters": {
                "hostel_id": str(hostel_id) if hostel_id else "",
            },
        },
    )


@router.get("/fees/new", response_class=HTMLResponse)
async def new_fee_modal(
    request: Request,
    admin: User = Depends(require_admin_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render new fee structure modal."""
    hostel_repo = HostelRepository(db)
    hostels, _ = await hostel_repo.list(PaginationParams(page=1, size=100))
    return render_template(
        request,
        "admin/billing/fees/create_modal.html",
        {"hostels": hostels, "room_types": list(RoomType), "error": None},
    )


@router.post("/fees", response_class=HTMLResponse)
async def create_fee_submit(
    request: Request,
    hostel_id: UUID = Form(...),
    room_type: str = Form(...),
    academic_year: str = Form(...),
    amount: Decimal = Form(...),
    description: str | None = Form(None),
    csrf_token: str | None = Form(None),
    admin: User = Depends(require_admin_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Create fee structure."""
    verify_csrf(request, form_csrf=csrf_token)
    billing_service = BillingService(db)

    try:
        room_type_enum = RoomType(room_type.lower())
        payload = FeeStructureCreate(
            hostel_id=hostel_id,
            room_type=room_type_enum,
            amount=amount,
        )
        await billing_service.create_fee_structure(payload)
        if request.headers.get("HX-Request") == "true":
            response = Response(status_code=status.HTTP_200_OK)
            response.headers["HX-Redirect"] = "/admin/billing/fees"
            return response
        return RedirectResponse(url="/admin/billing/fees", status_code=status.HTTP_303_SEE_OTHER)
    except AppException as e:
        logger.warning("Error creating fee structure: %s", e.message)
        hostel_repo = HostelRepository(db)
        hostels, _ = await hostel_repo.list(PaginationParams(page=1, size=100))
        return render_template(
            request,
            "admin/billing/fees/create_modal.html",
            {
                "hostels": hostels,
                "room_types": list(RoomType),
                "error": e.message,
                "form_data": {
                    "hostel_id": hostel_id,
                    "room_type": room_type,
                    "academic_year": academic_year,
                    "amount": amount,
                    "description": description,
                },
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


@router.get("/fees/{id}/edit", response_class=HTMLResponse)
async def edit_fee_modal(
    request: Request,
    id: UUID,
    admin: User = Depends(require_admin_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render edit fee structure modal."""
    billing_service = BillingService(db)
    fee = await billing_service.get_fee_structure(id)
    return render_template(
        request,
        "admin/billing/fees/edit_modal.html",
        {"fee": fee, "error": None},
    )


@router.post("/fees/{id}/edit", response_class=HTMLResponse)
async def edit_fee_submit(
    request: Request,
    id: UUID,
    amount: Decimal = Form(...),
    description: str | None = Form(None),
    is_active: bool = Form(True),
    csrf_token: str | None = Form(None),
    admin: User = Depends(require_admin_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Update fee structure."""
    verify_csrf(request, form_csrf=csrf_token)
    billing_service = BillingService(db)

    try:
        payload = FeeStructureUpdate(
            amount=amount,
            is_active=is_active,
        )
        await billing_service.update_fee_structure(id, payload)
        if request.headers.get("HX-Request") == "true":
            response = Response(status_code=status.HTTP_200_OK)
            response.headers["HX-Redirect"] = "/admin/billing/fees"
            return response
        return RedirectResponse(url="/admin/billing/fees", status_code=status.HTTP_303_SEE_OTHER)
    except AppException as e:
        fee = await billing_service.get_fee_structure(id)
        return render_template(
            request,
            "admin/billing/fees/edit_modal.html",
            {"fee": fee, "error": e.message},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


@router.post("/fees/{id}/delete")
async def delete_fee_submit(
    request: Request,
    id: UUID,
    csrf_token: str | None = Form(None),
    admin: User = Depends(require_admin_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a fee structure."""
    verify_csrf(request, form_csrf=csrf_token)
    billing_service = BillingService(db)
    await billing_service.delete_fee_structure(id)
    return RedirectResponse(url="/admin/billing/fees", status_code=status.HTTP_303_SEE_OTHER)


# =========================================================================
# 2. Generate Invoices Flow (Preview -> Confirm)
# =========================================================================


@router.get("/generate", response_class=HTMLResponse)
async def generate_invoices_page(
    request: Request,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render invoice generation wizard form."""
    user, warden_hostels = current_staff
    hostel_repo = HostelRepository(db)
    hostels, _ = await hostel_repo.list(PaginationParams(page=1, size=100))
    if user.role == UserRole.WARDEN:
        hostels = [h for h in hostels if h.id in warden_hostels]

    return render_template(
        request,
        "admin/billing/generate/index.html",
        {
            "current_user": user,
            "active_nav": "generate_invoices",
            "hostels": hostels,
            "today": date.today(),
        },
    )


@router.post("/generate/preview", response_class=HTMLResponse)
async def generate_invoices_preview(
    request: Request,
    hostel_id: UUID = Form(...),
    period_start: date = Form(...),
    period_end: date = Form(...),
    due_date: date = Form(...),
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Preview step: calculate candidate invoices count and total amount without committing."""
    verify_csrf(request, form_csrf=csrf_token)
    _user, _ = current_staff

    alloc_repo = AllocationRepository(db)
    fee_repo = FeeStructureRepository(db)
    invoice_repo = InvoiceRepository(db)

    fee_structures = await fee_repo.list_by_hostel(hostel_id, is_active=True)
    fee_map = {fs.room_type: fs.amount for fs in fee_structures}

    allocations = await alloc_repo.get_overlapping_for_hostel(
        hostel_id=hostel_id,
        period_start=period_start,
        period_end=period_end,
    )

    n_days = (period_end - period_start).days + 1
    total_amount = Decimal("0.00")
    candidate_count = 0
    skipped_count = 0

    for a in allocations:
        existing = await invoice_repo.get_existing_for_allocation_period(
            allocation_id=a.id,
            period_start=period_start,
            period_end=period_end,
        )
        if existing is not None:
            skipped_count += 1
            continue

        room = a.bed.room
        base_fee = (
            fee_map.get(room.room_type) or getattr(room, "monthly_rent", None) or Decimal("0.00")
        )
        eff_start = max(a.start_date, period_start)
        eff_end = min(a.end_date, period_end) if a.end_date else period_end
        d_days = (eff_end - eff_start).days + 1
        if d_days <= 0:
            skipped_count += 1
            continue

        if d_days >= n_days:
            amount = base_fee
        else:
            amount = (base_fee * Decimal(d_days) / Decimal(n_days)).quantize(Decimal("0.01"))
        total_amount += amount
        candidate_count += 1

    return render_template(
        request,
        "admin/billing/generate/preview_card.html",
        {
            "hostel_id": hostel_id,
            "period_start": period_start,
            "period_end": period_end,
            "due_date": due_date,
            "candidate_count": candidate_count,
            "skipped_count": skipped_count,
            "total_amount": total_amount,
        },
    )


@router.post("/generate/confirm", response_class=HTMLResponse)
async def generate_invoices_confirm(
    request: Request,
    hostel_id: UUID = Form(...),
    period_start: date = Form(...),
    period_end: date = Form(...),
    due_date: date = Form(...),
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Execute invoice generation and return result summary."""
    verify_csrf(request, form_csrf=csrf_token)
    user, _ = current_staff
    billing_service = BillingService(db)

    try:
        result = await billing_service.generate_invoices(
            hostel_id=hostel_id,
            period_start=period_start,
            period_end=period_end,
            due_date=due_date,
            current_user=user,
        )
        total_generated_amount = sum((inv.amount for inv in result.invoices), Decimal("0.00"))
        return render_template(
            request,
            "admin/billing/generate/result_card.html",
            {
                "generated_count": result.generated_count,
                "skipped_count": result.skipped_count,
                "total_amount": total_generated_amount,
            },
        )
    except AppException as e:
        return render_template(
            request,
            "admin/billing/generate/preview_card.html",
            {"error": e.message},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


# =========================================================================
# 3. Invoices List, Detail, Payment, Void & Printable Receipt
# =========================================================================


@router.get("/invoices", response_class=HTMLResponse)
async def list_invoices(
    request: Request,
    page: int = 1,
    size: int = 15,
    hostel_id: UUID | None = None,
    student_id: UUID | None = None,
    status_tab: str | None = "all",
    search: str | None = None,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render invoices list with status tabs and totals footer."""
    user, warden_hostels = current_staff
    billing_service = BillingService(db)

    # Scoping for warden
    if user.role == UserRole.WARDEN:
        if hostel_id and hostel_id not in warden_hostels:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Hostel not assigned")
        if not hostel_id and warden_hostels:
            hostel_id = warden_hostels[0]

    status_enum: InvoiceStatus | None = None
    if status_tab and status_tab.upper() in InvoiceStatus.__members__:
        status_enum = InvoiceStatus[status_tab.upper()]

    params = PaginationParams(page=page, size=size)
    paged = await billing_service.list_invoices(
        params=params,
        current_user=user,
        hostel_id=hostel_id,
        student_id=student_id,
        status=status_enum,
    )

    # Compute totals for the current filter view
    total_billed = sum((inv.amount for inv in paged.items), Decimal("0.00"))
    total_collected = sum((inv.paid_amount for inv in paged.items), Decimal("0.00"))
    total_outstanding = sum((inv.balance for inv in paged.items), Decimal("0.00"))

    hostel_repo = HostelRepository(db)
    hostels, _ = await hostel_repo.list(PaginationParams(page=1, size=100))
    if user.role == UserRole.WARDEN:
        hostels = [h for h in hostels if h.id in warden_hostels]

    query_parts = []
    if hostel_id:
        query_parts.append(f"hostel_id={hostel_id}")
    if status_tab and status_tab != "all":
        query_parts.append(f"status_tab={status_tab}")
    query_string_suffix = ("&" + "&".join(query_parts)) if query_parts else ""

    return render_template(
        request,
        "admin/billing/invoices/index.html",
        {
            "current_user": user,
            "active_nav": "invoices",
            "active_tab": status_tab or "all",
            "invoices": paged.items,
            "total_items": paged.total,
            "current_page": paged.page,
            "total_pages": paged.pages,
            "query_string_suffix": query_string_suffix,
            "hostels": hostels,
            "total_billed": total_billed,
            "total_collected": total_collected,
            "total_outstanding": total_outstanding,
            "filters": {
                "hostel_id": str(hostel_id) if hostel_id else "",
                "status_tab": status_tab or "all",
            },
        },
    )


@router.post("/invoices/mark-overdue")
async def mark_invoices_overdue(
    request: Request,
    csrf_token: str | None = Form(None),
    admin: User = Depends(require_admin_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Admin action to mark overdue unpaid/partial invoices."""
    verify_csrf(request, form_csrf=csrf_token)
    billing_service = BillingService(db)
    await billing_service.mark_overdue()
    return RedirectResponse(
        url="/admin/billing/invoices?status_tab=overdue",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/invoices/{id}", response_class=HTMLResponse)
async def invoice_detail(
    request: Request,
    id: UUID,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render invoice detail with amounts, payments timeline, and action modals."""
    user, _ = current_staff
    billing_service = BillingService(db)
    invoice = await billing_service.get_invoice(id, current_user=user)

    student_repo = StudentRepository(db)
    student = await student_repo.get_by_id(invoice.student_id)

    return render_template(
        request,
        "admin/billing/invoices/detail.html",
        {
            "current_user": user,
            "active_nav": "invoices",
            "invoice": invoice,
            "student": student,
        },
    )


@router.get("/invoices/{id}/modal/payment", response_class=HTMLResponse)
async def record_payment_modal(
    request: Request,
    id: UUID,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render record payment modal showing remaining balance."""
    user, _ = current_staff
    billing_service = BillingService(db)
    invoice = await billing_service.get_invoice(id, current_user=user)

    return render_template(
        request,
        "admin/billing/invoices/payment_modal.html",
        {
            "invoice": invoice,
            "payment_methods": list(PaymentMethod),
            "error": None,
        },
    )


@router.post("/invoices/{id}/payment", response_class=HTMLResponse)
async def record_payment_submit(
    request: Request,
    id: UUID,
    amount: Decimal = Form(...),
    method: str = Form(...),
    reference: str | None = Form(None),
    notes: str | None = Form(None),
    csrf_token: str | None = Form(None),
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Record payment with overpayment inline blocking."""
    verify_csrf(request, form_csrf=csrf_token)
    user, _ = current_staff
    billing_service = BillingService(db)

    try:
        try:
            method_enum = PaymentMethod(method.lower())
        except ValueError as err:
            raise AppException(
                message=f"Invalid payment method: {method}",
                code="INVALID_PAYMENT_METHOD",
                status_code=422,
            ) from err
        payload = PaymentCreate(
            amount=amount,
            method=method_enum,
            reference=reference.strip() if reference else None,
        )
        await billing_service.record_payment(id, payload, current_user=user)
        if request.headers.get("HX-Request") == "true":
            response = Response(status_code=status.HTTP_200_OK)
            response.headers["HX-Redirect"] = f"/admin/billing/invoices/{id}"
            return response
        return RedirectResponse(
            url=f"/admin/billing/invoices/{id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except AppException as e:
        logger.warning("Payment recording error: %s", e.message)
        invoice = await billing_service.get_invoice(id, current_user=user)
        return render_template(
            request,
            "admin/billing/invoices/payment_modal.html",
            {
                "invoice": invoice,
                "payment_methods": list(PaymentMethod),
                "error": e.message,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


@router.post("/invoices/{id}/void")
async def void_invoice_submit(
    request: Request,
    id: UUID,
    csrf_token: str | None = Form(None),
    admin: User = Depends(require_admin_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Void an invoice (Admin only)."""
    verify_csrf(request, form_csrf=csrf_token)
    billing_service = BillingService(db)
    await billing_service.void_invoice(id, current_user=admin)
    return RedirectResponse(
        url=f"/admin/billing/invoices/{id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/invoices/{id}/receipt", response_class=HTMLResponse)
async def printable_receipt(
    request: Request,
    id: UUID,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Printable receipt/invoice page with print stylesheet."""
    user, _ = current_staff
    billing_service = BillingService(db)
    invoice = await billing_service.get_invoice(id, current_user=user)

    student_repo = StudentRepository(db)
    student = await student_repo.get_by_id(invoice.student_id)

    return render_template(
        request,
        "admin/billing/invoices/receipt.html",
        {
            "invoice": invoice,
            "student": student,
            "today": date.today(),
        },
    )


# =========================================================================
# 4. Payments List
# =========================================================================


@router.get("/payments", response_class=HTMLResponse)
async def list_payments(
    request: Request,
    page: int = 1,
    size: int = 15,
    method: str | None = None,
    current_staff: tuple[User, list[UUID]] = Depends(require_staff_web),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Render payments history list with filters."""
    user, _ = current_staff
    billing_service = BillingService(db)

    params = PaginationParams(page=page, size=size)
    paged = await billing_service.list_payments(
        params=params,
        current_user=user,
    )

    query_parts = []
    if method:
        query_parts.append(f"method={method}")
    query_string_suffix = ("&" + "&".join(query_parts)) if query_parts else ""

    return render_template(
        request,
        "admin/billing/payments/index.html",
        {
            "current_user": user,
            "active_nav": "payments",
            "payments": paged.items,
            "total_items": paged.total,
            "current_page": paged.page,
            "total_pages": paged.pages,
            "query_string_suffix": query_string_suffix,
            "payment_methods": list(PaymentMethod),
            "filters": {
                "method": method or "",
            },
        },
    )
