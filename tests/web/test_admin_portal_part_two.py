"""Comprehensive tests for Admin Portal II: Students, Allocations, Billing.

Covers:
- Template filters and web authentication / CSRF dependencies
- Authentication web routes (login / logout)
- Student management (list, search, filter, modal, create, detail tabs, edit, deactivate)
- Allocation flows (bed picker modal, allocate, 422 business error, transfer, vacate, cancel)
- Room detail and unallocated student assignment
- Fee structure CRUD (admin only vs warden restrictions)
- Invoice generation wizard (form, preview, confirm, idempotency check)
- Invoices list, status filtering, detail, payment recording, overpayment blocking, voiding
- Printable receipts
- Payments list
- Warden scoping and student role 403 access control
- CSRF validation on forms
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.models.user import User
from app.web.deps import (
    format_currency,
    format_date,
    format_datetime,
    status_badge_class,
    user_initials,
)

# =========================================================================
# 1. Template Filters & Helper Unit Tests
# =========================================================================


def test_template_filters():
    """Verify custom Jinja2 template filters behave as specified."""
    # Currency
    assert format_currency(Decimal("1234.50")) == "$1,234.50"
    assert format_currency(100) == "$100.00"
    assert format_currency(None) == "$0.00"

    # Date
    d = date(2025, 3, 15)
    assert format_date(d) == "2025-03-15"
    assert format_date("2025-03-15") == "2025-03-15"
    assert format_date(None) == "-"

    # Datetime
    dt = datetime(2025, 3, 15, 14, 30)
    assert format_datetime(dt) == "2025-03-15 14:30"
    assert format_datetime(None) == "-"

    # Initials
    assert user_initials("John Doe") == "JD"
    assert user_initials("Alice") == "AL"
    assert user_initials(None) == "U"
    assert user_initials("") == "U"

    # Status color
    assert "emerald" in status_badge_class("active")
    assert "emerald" in status_badge_class("paid")
    assert "amber" in status_badge_class("partial")
    assert "rose" in status_badge_class("overdue")
    assert "zinc" in status_badge_class("cancelled")
    assert "zinc" in status_badge_class("closed")


# =========================================================================
# 2. Test Setup & Helpers
# =========================================================================


CSRF_TOKEN = "test-csrf-token-1234567890abcdef"


def get_web_cookies(token: str) -> dict[str, str]:
    return {"access_token": token, CSRF_COOKIE_NAME: CSRF_TOKEN}


def get_web_headers() -> dict[str, str]:
    return {CSRF_HEADER_NAME: CSRF_TOKEN}


async def setup_hostel_structure(
    client: AsyncClient, admin_headers: dict[str, str]
) -> dict[str, str]:
    """Create a full test hostel structure: hostel, block, room with beds."""
    code = f"H-{uuid4().hex[:6]}"
    resp = await client.post(
        "/api/v1/hostels",
        json={"name": f"Hostel {code}", "code": code, "gender_type": "mixed", "address": "Campus"},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    hostel_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/hostels/{hostel_id}/blocks",
        json={"name": "Block 1", "floor_count": 2},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    block_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/blocks/{block_id}/rooms",
        json={
            "number": f"R-{uuid4().hex[:4]}",
            "floor": 1,
            "room_type": "double",
            "capacity": 2,
            "monthly_rent": "5000.00",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    room = resp.json()
    room_id = room["id"]
    bed_id = room["beds"][0]["id"]
    bed_id_2 = room["beds"][1]["id"]

    return {
        "hostel_id": hostel_id,
        "block_id": block_id,
        "room_id": room_id,
        "bed_id": bed_id,
        "bed_id_2": bed_id_2,
    }


async def setup_student(
    client: AsyncClient, admin_headers: dict[str, str], gender: str = "male"
) -> dict[str, str]:
    """Create a student via API."""
    unique_id = uuid4().hex[:6]
    resp = await client.post(
        "/api/v1/students",
        json={
            "email": f"student_{unique_id}@example.com",
            "password": "Password123",
            "full_name": f"Student {unique_id}",
            "phone": "+1987654320",
            "student_no": f"STU-{unique_id}",
            "gender": gender,
            "department": "Computer Science",
            "year": 2,
            "guardian_name": "Parent Name",
            "guardian_phone": "+1987654321",
            "emergency_contact": "+1987654322",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# =========================================================================
# 3. Web Auth Routes Tests
# =========================================================================


@pytest.mark.asyncio
async def test_web_auth_login_and_logout(client: AsyncClient, admin_user: User):
    """Test login page GET, invalid POST, valid POST, and logout GET."""
    # 1. GET /login
    resp = await client.get("/login")
    assert resp.status_code == 200
    assert "Hostel Management System" in resp.text
    assert "Sign in" in resp.text

    # 2. POST /login without CSRF -> 403
    resp = await client.post(
        "/login",
        data={"email": admin_user.email, "password": "AdminPass123"},
    )
    assert resp.status_code == 403

    # 3. POST /login with invalid password
    resp = await client.post(
        "/login",
        data={
            "email": admin_user.email,
            "password": "WrongPassword",
            "csrf_token": CSRF_TOKEN,
        },
        cookies={CSRF_COOKIE_NAME: CSRF_TOKEN},
    )
    assert resp.status_code == 401
    assert "Invalid email or password" in resp.text

    # 4. POST /login valid credentials -> redirect to /admin/students
    resp = await client.post(
        "/login",
        data={
            "email": admin_user.email,
            "password": "AdminPass123",
            "csrf_token": CSRF_TOKEN,
        },
        cookies={CSRF_COOKIE_NAME: CSRF_TOKEN},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    assert resp.headers["location"] == "/admin/students"
    assert "access_token" in resp.cookies

    # 5. POST /logout
    resp = await client.post(
        "/logout",
        data={"csrf_token": CSRF_TOKEN},
        cookies={CSRF_COOKIE_NAME: CSRF_TOKEN},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    assert resp.headers["location"] == "/login"


# =========================================================================
# 4. Student Management Tests
# =========================================================================


@pytest.mark.asyncio
async def test_admin_students_crud_lifecycle(
    client: AsyncClient, admin_token: str, admin_headers: dict[str, str]
):
    """Test student listing, filter, modal, create, detail, edit, deactivate."""
    cookies = get_web_cookies(admin_token)
    headers = get_web_headers()

    # 1. List students page
    resp = await client.get("/admin/students", cookies=cookies)
    assert resp.status_code == 200
    assert "Students" in resp.text

    # 2. Get student create modal
    resp = await client.get("/admin/students/new", cookies=cookies)
    assert resp.status_code == 200
    assert "Add New Student" in resp.text

    # 3. POST create student form
    uid = uuid4().hex[:6]
    form_data = {
        "full_name": f"Alice Student {uid}",
        "email": f"alice_{uid}@example.com",
        "phone": "+1987654320",
        "password": "StudentPass123",
        "student_no": f"STU-{uid}",
        "gender": "female",
        "department": "Mechanical",
        "year": "1",
        "guardian_name": "Mom Alice",
        "guardian_phone": "+1987654321",
        "emergency_contact": "+1987654322",
        "csrf_token": CSRF_TOKEN,
    }
    resp = await client.post(
        "/admin/students",
        data=form_data,
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    # 4. List with search & filter
    resp = await client.get(
        f"/admin/students?search={uid}&department=Mechanical&year=1&gender=female",
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert f"STU-{uid}" in resp.text

    # Seed an API student to get exact ID
    stu = await setup_student(client, admin_headers, gender="female")
    stu_id = stu["id"]

    # 5. Detail page with tabs
    for tab in ("profile", "allocation", "invoices", "attendance", "leaves", "complaints"):
        resp = await client.get(f"/admin/students/{stu_id}?tab={tab}", cookies=cookies)
        assert resp.status_code == 200
        assert stu["student_no"] in resp.text

    # 6. Edit modal
    resp = await client.get(f"/admin/students/{stu_id}/edit", cookies=cookies)
    assert resp.status_code == 200
    assert "Edit Student Profile" in resp.text

    # 7. Edit submit
    edit_data = {
        "full_name": "Alice Updated",
        "phone": "+1987654399",
        "department": "Civil",
        "year": "2",
        "guardian_name": "Guardian",
        "guardian_phone": "+1987654398",
        "emergency_contact": "+1987654397",
        "csrf_token": CSRF_TOKEN,
    }
    resp = await client.post(
        f"/admin/students/{stu_id}/edit",
        data=edit_data,
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    # 8. Deactivate submit
    resp = await client.post(
        f"/admin/students/{stu_id}/deactivate",
        data={"csrf_token": CSRF_TOKEN},
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)


# =========================================================================
# 5. Allocations & Bed Picker Flow Tests
# =========================================================================


@pytest.mark.asyncio
async def test_admin_allocations_flow(
    client: AsyncClient, admin_token: str, admin_headers: dict[str, str]
):
    """Test allocations list, allocate modal, bed-picker partial,
    allocate submit, transfer, vacate, cancel.
    """
    cookies = get_web_cookies(admin_token)
    headers = get_web_headers()

    struct = await setup_hostel_structure(client, admin_headers)
    student = await setup_student(client, admin_headers, gender="male")
    stu_id = student["id"]

    # 1. Allocations list page
    resp = await client.get("/admin/allocations", cookies=cookies)
    assert resp.status_code == 200
    assert "Bed Allocations" in resp.text

    # 2. Allocate modal
    resp = await client.get(
        f"/admin/allocations/modal/allocate?student_id={stu_id}",
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert "Allocate Bed" in resp.text

    # 3. Bed picker partial via HTMX
    resp = await client.get(
        f"/admin/allocations/rooms-for-hostel?hostel_id={struct['hostel_id']}&student_id={stu_id}",
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert "Bed" in resp.text
    assert struct["bed_id"] in resp.text

    # 4. Allocate submit (HTMX request)
    today = date.today().isoformat()
    resp = await client.post(
        "/admin/allocations/allocate",
        data={
            "student_id": stu_id,
            "bed_id": struct["bed_id"],
            "start_date": today,
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "HX-Redirect" in resp.headers

    # 5. Inline 422 error test: duplicate allocation attempt
    resp = await client.post(
        "/admin/allocations/allocate",
        data={
            "student_id": stu_id,
            "bed_id": struct["bed_id_2"],
            "start_date": today,
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers=headers,
    )
    assert resp.status_code == 422
    assert "error" in resp.text or "already has an active allocation" in resp.text.lower()

    # Get active allocation ID for transfer / vacate / cancel
    resp = await client.get(f"/api/v1/allocations?student_id={stu_id}", headers=admin_headers)
    allocations = resp.json()["items"]
    assert len(allocations) >= 1
    alloc_id = allocations[0]["id"]

    # 6. Transfer modal
    resp = await client.get(f"/admin/allocations/{alloc_id}/modal/transfer", cookies=cookies)
    assert resp.status_code == 200
    assert "Transfer Student" in resp.text

    # 7. Transfer submit
    resp = await client.post(
        f"/admin/allocations/{alloc_id}/transfer",
        data={
            "target_bed_id": struct["bed_id_2"],
            "transfer_date": today,
            "reason": "Moved to window side",
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "HX-Redirect" in resp.headers

    # Fetch current active allocation after transfer
    resp = await client.get(
        f"/api/v1/allocations?student_id={stu_id}&status=active", headers=admin_headers
    )
    active_allocs = resp.json()["items"]
    assert len(active_allocs) >= 1
    new_alloc_id = active_allocs[0]["id"]

    # 8. Vacate modal
    resp = await client.get(f"/admin/allocations/{new_alloc_id}/modal/vacate", cookies=cookies)
    assert resp.status_code == 200
    assert "Vacate Bed" in resp.text

    # 9. Vacate submit
    resp = await client.post(
        f"/admin/allocations/{new_alloc_id}/vacate",
        data={
            "vacate_date": today,
            "reason": "Graduated",
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "HX-Redirect" in resp.headers

    # 10. Cancel modal & submit on a fresh allocation (must start in future)
    stu2 = await setup_student(client, admin_headers, gender="male")
    future_date = (date.today() + timedelta(days=5)).isoformat()
    alloc_resp = await client.post(
        "/api/v1/allocations",
        json={"student_id": stu2["id"], "bed_id": struct["bed_id"], "start_date": future_date},
        headers=admin_headers,
    )
    alloc2_id = alloc_resp.json()["id"]

    resp = await client.get(f"/admin/allocations/{alloc2_id}/modal/cancel", cookies=cookies)
    assert resp.status_code == 200
    assert "Cancel Allocation" in resp.text

    resp = await client.post(
        f"/admin/allocations/{alloc2_id}/cancel",
        data={"reason": "Cancelled by student", "csrf_token": CSRF_TOKEN},
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
    )
    assert resp.status_code == 200


# =========================================================================
# 6. Room Detail & Unallocated Student Search
# =========================================================================


@pytest.mark.asyncio
async def test_admin_room_assign_flow(
    client: AsyncClient, admin_token: str, admin_headers: dict[str, str]
):
    """Test room detail view, assign modal, and autocomplete for unallocated students."""
    cookies = get_web_cookies(admin_token)
    headers = get_web_headers()

    struct = await setup_hostel_structure(client, admin_headers)
    room_id = struct["room_id"]
    student = await setup_student(client, admin_headers)

    # 1. Room detail page
    resp = await client.get(f"/admin/rooms/{room_id}", cookies=cookies, headers=headers)
    assert resp.status_code == 200
    assert "Beds & Occupancy" in resp.text

    # 2. Assign student modal
    resp = await client.get(f"/admin/rooms/{room_id}/modal/assign", cookies=cookies)
    assert resp.status_code == 200
    assert "Assign Student to Room" in resp.text

    # 3. Autocomplete search endpoint
    resp = await client.get(
        f"/admin/allocations/assign-student-search?q={student['student_no']}",
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert student["student_no"] in resp.text


# =========================================================================
# 7. Fee Structures CRUD Tests
# =========================================================================


@pytest.mark.asyncio
async def test_admin_fee_structures_crud(
    client: AsyncClient, admin_token: str, admin_headers: dict[str, str]
):
    """Test fee structures list, create modal, create submit, edit modal, edit submit, delete."""
    cookies = get_web_cookies(admin_token)
    headers = get_web_headers()

    struct = await setup_hostel_structure(client, admin_headers)
    hostel_id = struct["hostel_id"]

    # 1. List fees
    resp = await client.get("/admin/billing/fees", cookies=cookies)
    assert resp.status_code == 200
    assert "Fee Structures" in resp.text

    # 2. Create modal
    resp = await client.get("/admin/billing/fees/new", cookies=cookies)
    assert resp.status_code == 200
    assert "Add Fee Structure" in resp.text

    # 3. Create submit
    resp = await client.post(
        "/admin/billing/fees",
        data={
            "hostel_id": hostel_id,
            "room_type": "double",
            "academic_year": "2025-2026",
            "amount": "4500.00",
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "HX-Redirect" in resp.headers

    # Fetch fee via API to get ID
    resp = await client.get(f"/api/v1/fee-structures?hostel_id={hostel_id}", headers=admin_headers)
    fee_list = resp.json()
    assert len(fee_list) >= 1
    fee_id = fee_list[0]["id"]

    # 4. Edit modal
    resp = await client.get(f"/admin/billing/fees/{fee_id}/edit", cookies=cookies)
    assert resp.status_code == 200
    assert "Edit Fee Structure" in resp.text

    # 5. Edit submit
    resp = await client.post(
        f"/admin/billing/fees/{fee_id}/edit",
        data={"amount": "4800.00", "is_active": "true", "csrf_token": CSRF_TOKEN},
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
    )
    assert resp.status_code == 200

    # 6. Delete submit
    resp = await client.post(
        f"/admin/billing/fees/{fee_id}/delete",
        data={"csrf_token": CSRF_TOKEN},
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302, 303)


# =========================================================================
# 8. Invoice Generation Wizard & Idempotency Tests
# =========================================================================


@pytest.mark.asyncio
async def test_admin_invoice_generation_wizard_and_idempotency(
    client: AsyncClient, admin_token: str, admin_headers: dict[str, str]
):
    """Test invoice generation form, preview card, confirm generation,
    and idempotency on duplicate run.
    """
    cookies = get_web_cookies(admin_token)
    headers = get_web_headers()

    struct = await setup_hostel_structure(client, admin_headers)
    hostel_id = struct["hostel_id"]
    student = await setup_student(client, admin_headers)

    # Create fee structure
    await client.post(
        "/api/v1/fee-structures",
        json={"hostel_id": hostel_id, "room_type": "double", "amount": "4000.00"},
        headers=admin_headers,
    )

    # Allocate student
    today = date.today()
    p_start = today.replace(day=1)
    p_end = (p_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    due = today + timedelta(days=10)

    await client.post(
        "/api/v1/allocations",
        json={
            "student_id": student["id"],
            "bed_id": struct["bed_id"],
            "start_date": p_start.isoformat(),
        },
        headers=admin_headers,
    )

    # 1. Render generation page
    resp = await client.get("/admin/billing/generate", cookies=cookies)
    assert resp.status_code == 200
    assert "Generate Invoices" in resp.text

    # 2. Preview step
    preview_data = {
        "hostel_id": hostel_id,
        "period_start": p_start.isoformat(),
        "period_end": p_end.isoformat(),
        "due_date": due.isoformat(),
        "csrf_token": CSRF_TOKEN,
    }
    resp = await client.post(
        "/admin/billing/generate/preview",
        data=preview_data,
        cookies=cookies,
        headers=headers,
    )
    assert resp.status_code == 200
    assert "Invoice Generation Preview" in resp.text
    assert "New Invoices" in resp.text

    # 3. Confirm step (First run -> should create 1 invoice)
    resp = await client.post(
        "/admin/billing/generate/confirm",
        data=preview_data,
        cookies=cookies,
        headers=headers,
    )
    assert resp.status_code == 200
    assert "Invoices Successfully Generated" in resp.text

    # 4. Idempotency test (Second run with same params -> should generate 0, skip 1)
    resp = await client.post(
        "/admin/billing/generate/confirm",
        data=preview_data,
        cookies=cookies,
        headers=headers,
    )
    assert resp.status_code == 200
    assert "Invoices Successfully Generated" in resp.text
    assert "skipped" in resp.text.lower()


# =========================================================================
# 9. Invoice Detail, Record Payment, Overpayment Block & Printable Receipt
# =========================================================================


@pytest.mark.asyncio
async def test_admin_invoice_detail_payments_and_receipt(
    client: AsyncClient, admin_token: str, admin_headers: dict[str, str]
):
    """Test invoice detail, recording partial payments, overpayment rejection,
    voiding, and printable receipt.
    """
    cookies = get_web_cookies(admin_token)
    headers = get_web_headers()

    struct = await setup_hostel_structure(client, admin_headers)
    student = await setup_student(client, admin_headers)

    # Create fee structure & allocate
    await client.post(
        "/api/v1/fee-structures",
        json={"hostel_id": struct["hostel_id"], "room_type": "double", "amount": "5000.00"},
        headers=admin_headers,
    )
    today = date.today()
    p_start = today.replace(day=1)
    p_end = (p_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    due = today + timedelta(days=10)

    await client.post(
        "/api/v1/allocations",
        json={
            "student_id": student["id"],
            "bed_id": struct["bed_id"],
            "start_date": p_start.isoformat(),
        },
        headers=admin_headers,
    )

    # Generate invoice via API
    gen_resp = await client.post(
        "/api/v1/invoices/generate",
        json={
            "hostel_id": struct["hostel_id"],
            "period_start": p_start.isoformat(),
            "period_end": p_end.isoformat(),
            "due_date": due.isoformat(),
        },
        headers=admin_headers,
    )
    assert gen_resp.status_code == 200, gen_resp.text
    invoices = gen_resp.json()["invoices"]
    inv_id = invoices[0]["id"]

    # 1. Invoices list page with tabs
    resp = await client.get("/admin/billing/invoices?status_tab=unpaid", cookies=cookies)
    assert resp.status_code == 200
    assert "Invoices" in resp.text

    # 2. Invoice detail page
    resp = await client.get(f"/admin/billing/invoices/{inv_id}", cookies=cookies)
    assert resp.status_code == 200
    assert "Printable Receipt" in resp.text
    assert "Payments Recorded" in resp.text

    # 3. Payment modal
    resp = await client.get(f"/admin/billing/invoices/{inv_id}/modal/payment", cookies=cookies)
    assert resp.status_code == 200
    assert "Record Payment" in resp.text

    # 4. Overpayment rejection (attempting to pay 6000 on a 5000 invoice)
    resp = await client.post(
        f"/admin/billing/invoices/{inv_id}/payment",
        data={
            "amount": "6000.00",
            "method": "cash",
            "reference": "TXN-OVER-01",
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers=headers,
    )
    assert resp.status_code == 422
    assert "exceeds" in resp.text.lower() or "error" in resp.text.lower()

    # 5. First partial payment (2000)
    resp = await client.post(
        f"/admin/billing/invoices/{inv_id}/payment",
        data={
            "amount": "2000.00",
            "method": "cash",
            "reference": "TXN-01",
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "HX-Redirect" in resp.headers

    # 6. Second partial payment completing balance (3000) -> Status PAID
    resp = await client.post(
        f"/admin/billing/invoices/{inv_id}/payment",
        data={
            "amount": "3000.00",
            "method": "bank",
            "reference": "TXN-02",
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
    )
    assert resp.status_code == 200

    # 7. Printable receipt page
    resp = await client.get(f"/admin/billing/invoices/{inv_id}/receipt", cookies=cookies)
    assert resp.status_code == 200
    assert "Billing Receipt" in resp.text
    assert "no-print" in resp.text
    assert "@media print" in resp.text

    # 8. Payments list page
    resp = await client.get("/admin/billing/payments", cookies=cookies)
    assert resp.status_code == 200
    assert "Payments" in resp.text

    # 9. Void invoice test on a fresh invoice
    stu_void = await setup_student(client, admin_headers, gender="female")
    await client.post(
        "/api/v1/allocations",
        json={
            "student_id": stu_void["id"],
            "bed_id": struct["bed_id_2"],
            "start_date": p_start.isoformat(),
        },
        headers=admin_headers,
    )
    gen_resp2 = await client.post(
        "/api/v1/invoices/generate",
        json={
            "hostel_id": struct["hostel_id"],
            "period_start": p_start.isoformat(),
            "period_end": p_end.isoformat(),
            "due_date": due.isoformat(),
        },
        headers=admin_headers,
    )
    invoices2 = [inv for inv in gen_resp2.json()["invoices"] if inv["student_id"] == stu_void["id"]]
    inv_id2 = invoices2[0]["id"]

    resp = await client.post(
        f"/admin/billing/invoices/{inv_id2}/void",
        data={"csrf_token": CSRF_TOKEN},
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302, 303)

    # 10. Mark overdue test
    resp = await client.post(
        "/admin/billing/invoices/mark-overdue",
        data={"csrf_token": CSRF_TOKEN},
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302, 303)


# =========================================================================
# 10. Role Scoping, Warden Scoping & Security Matrix
# =========================================================================


@pytest.mark.asyncio
async def test_admin_portal_permissions_and_scoping(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_user: User,
    warden_token: str,
    student_user: User,
    student_token: str,
):
    """Test warden scoping restrictions and student 403 access control."""
    warden_cookies = get_web_cookies(warden_token)
    student_cookies = get_web_cookies(student_token)
    headers = get_web_headers()

    struct = await setup_hostel_structure(client, admin_headers)
    hostel_id = struct["hostel_id"]

    # 1. Student accessing admin portal receives 403 Forbidden
    resp = await client.get("/admin/students", cookies=student_cookies)
    assert resp.status_code == 403

    resp = await client.get("/admin/allocations", cookies=student_cookies)
    assert resp.status_code == 403

    resp = await client.get("/admin/billing/invoices", cookies=student_cookies)
    assert resp.status_code == 403

    # 2. Warden attempting to access unassigned hostel billing/invoices receives 403
    resp = await client.get(
        f"/admin/billing/invoices?hostel_id={hostel_id}",
        cookies=warden_cookies,
    )
    assert resp.status_code == 403

    # 3. Warden attempting to create fee structure (admin-only) receives 403
    resp = await client.get("/admin/billing/fees/new", cookies=warden_cookies)
    assert resp.status_code == 403

    resp = await client.post(
        "/admin/billing/fees",
        data={
            "hostel_id": hostel_id,
            "room_type": "single",
            "academic_year": "2025-2026",
            "amount": "5000.00",
            "csrf_token": CSRF_TOKEN,
        },
        cookies=warden_cookies,
        headers=headers,
    )
    assert resp.status_code == 403

    # 4. Warden attempting to mark overdue receives 403
    resp = await client.post(
        "/admin/billing/invoices/mark-overdue",
        data={"csrf_token": CSRF_TOKEN},
        cookies=warden_cookies,
        headers=headers,
    )
    assert resp.status_code == 403

    # 5. Unauthenticated request redirects to /login
    resp = await client.get("/admin/students", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers["location"].startswith("/login")


# =========================================================================
# 11. CSRF Security Enforcement Tests
# =========================================================================


@pytest.mark.asyncio
async def test_admin_portal_csrf_enforcement(
    client: AsyncClient, admin_token: str, admin_headers: dict[str, str]
):
    """Test CSRF enforcement: missing cookie or mismatched token returns 403."""
    cookies_no_csrf = {"access_token": admin_token}
    struct = await setup_hostel_structure(client, admin_headers)

    # 1. POST without any CSRF cookie or form field -> 403
    resp = await client.post(
        "/admin/billing/fees",
        data={
            "hostel_id": struct["hostel_id"],
            "room_type": "single",
            "academic_year": "2025-2026",
            "amount": "6000.00",
        },
        cookies=cookies_no_csrf,
    )
    assert resp.status_code == 403

    # 2. POST with cookie but mismatched form token -> 403
    resp = await client.post(
        "/admin/billing/fees",
        data={
            "hostel_id": struct["hostel_id"],
            "room_type": "single",
            "academic_year": "2025-2026",
            "amount": "6000.00",
            "csrf_token": "wrong-token-value",
        },
        cookies={"access_token": admin_token, CSRF_COOKIE_NAME: "correct-cookie-value"},
    )
    assert resp.status_code == 403
