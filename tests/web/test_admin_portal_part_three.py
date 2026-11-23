"""Comprehensive tests for Admin Portal III: Operations, Notices, Audit, Reports.

Covers:
- Gate Attendance (mobile screen, student search, check-in, check-out, double check-in 422)
- Present Now screen & historical attendance logs
- Student Leaves lifecycle (pending tab, review modal, approve with remarks, reject with remarks)
- Visitors management (register modal, active visitors, checkout, visiting hours validation)
- Complaints management (status tabs, assign staff, status flow, staff notes, resolution time)
- Mess Weekly Menu (7x3 grid/accordion, batch update idempotency, headcount cards)
- Notices management (CRUD, audience, pin, live/scheduled/expired status badges)
- Audit log (Admin-only access, expandable JSON payload inspection, Warden 403 block)
- Reports (Occupancy, Revenue, Defaulters, Complaints, Attendance) + CSV downloads
- Role Scoping & CSRF protection
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.models.user import User

CSRF_TOKEN = "test-csrf-token-ops-34567890abcdef"


def get_web_cookies(token: str) -> dict[str, str]:
    return {"access_token": token, CSRF_COOKIE_NAME: CSRF_TOKEN}


def get_web_headers() -> dict[str, str]:
    return {CSRF_HEADER_NAME: CSRF_TOKEN}


async def setup_hostel_structure(
    client: AsyncClient, admin_headers: dict[str, str]
) -> dict[str, str]:
    """Create test hostel, block, room, and beds."""
    code = f"OPS-{uuid4().hex[:6]}"
    resp = await client.post(
        "/api/v1/hostels",
        json={"name": f"Hostel {code}", "code": code, "gender_type": "mixed", "address": "Campus"},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    hostel_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/hostels/{hostel_id}/blocks",
        json={"name": "Block Ops"},
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
            "monthly_rent": "3000.00",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    room = resp.json()
    room_id = room["id"]
    beds = room["beds"]

    return {
        "hostel_id": hostel_id,
        "block_id": block_id,
        "room_id": room_id,
        "bed_id": beds[0]["id"],
        "bed_id_2": beds[1]["id"],
    }


async def setup_student(
    client: AsyncClient,
    admin_headers: dict[str, str],
    gender: str = "male",
) -> dict[str, str]:
    """Create a student user and student profile."""
    tag = uuid4().hex[:6]
    resp = await client.post(
        "/api/v1/students",
        json={
            "email": f"st.ops.{tag}@hostel.example.com",
            "password": "StudentPass123",
            "full_name": f"Ops Student {tag}",
            "student_no": f"ST-OPS-{tag.upper()}",
            "gender": gender,
            "department": "Engineering",
            "year": 2,
            "guardian_name": "Guardian Ops",
            "guardian_phone": "+1987654321",
            "emergency_contact": "+1987654320",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# =========================================================================
# 1. Gate Attendance Flow Tests
# =========================================================================


@pytest.mark.asyncio
async def test_admin_attendance_gate_flow(
    client: AsyncClient, admin_token: str, admin_headers: dict[str, str]
):
    """Test mobile gate screen, HTMX search, check-in, double check-in, check-out, and logs."""
    cookies = get_web_cookies(admin_token)
    headers = get_web_headers()

    struct = await setup_hostel_structure(client, admin_headers)
    student = await setup_student(client, admin_headers)

    # Allocate student so check-in is valid
    today = date.today().isoformat()
    await client.post(
        "/api/v1/allocations",
        json={"student_id": student["id"], "bed_id": struct["bed_id"], "start_date": today},
        headers=admin_headers,
    )

    # 1. Render Gate screen
    resp = await client.get("/admin/attendance/gate", cookies=cookies)
    assert resp.status_code == 200
    assert "Gate Attendance" in resp.text
    assert "Recent Gate Activity" in resp.text

    # 2. HTMX Student search
    resp = await client.get(
        f"/admin/attendance/gate/search?q={student['student_no']}",
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert student["student_no"] in resp.text
    assert "CHECK IN STUDENT" in resp.text

    # 3. Check-In action
    resp = await client.post(
        "/admin/attendance/gate/action",
        data={
            "student_id": student["id"],
            "action": "check_in",
            "remarks": "Returned from library",
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "CHECK OUT STUDENT" in resp.text or "INSIDE HOSTEL" in resp.text

    # 4. Double Check-In error (inline 422 alert)
    resp = await client.post(
        "/admin/attendance/gate/action",
        data={
            "student_id": student["id"],
            "action": "check_in",
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
    )
    assert resp.status_code == 422
    assert "already checked in" in resp.text.lower() or "blocked" in resp.text.lower()

    # 5. Check-Out action
    resp = await client.post(
        "/admin/attendance/gate/action",
        data={
            "student_id": student["id"],
            "action": "check_out",
            "remarks": "Weekend outing",
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "CHECK IN STUDENT" in resp.text or "OUTSIDE HOSTEL" in resp.text

    # 6. Present Now screen
    resp = await client.get(
        f"/admin/attendance/present?hostel_id={struct['hostel_id']}",
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert "Present Now" in resp.text

    # 7. Attendance logs screen
    resp = await client.get(
        f"/admin/attendance?hostel_id={struct['hostel_id']}",
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert "Attendance Logs" in resp.text
    assert student["student_no"] in resp.text


# =========================================================================
# 2. Leaves Lifecycle Tests
# =========================================================================


@pytest.mark.asyncio
async def test_admin_leaves_lifecycle(
    client: AsyncClient, admin_token: str, admin_headers: dict[str, str]
):
    """Test leaves listing, review modal, approval with remarks, and rejection with remarks."""
    cookies = get_web_cookies(admin_token)
    headers = get_web_headers()

    struct = await setup_hostel_structure(client, admin_headers)
    student = await setup_student(client, admin_headers)

    # Allocate student
    today = date.today()
    await client.post(
        "/api/v1/allocations",
        json={
            "student_id": student["id"],
            "bed_id": struct["bed_id"],
            "start_date": today.isoformat(),
        },
        headers=admin_headers,
    )

    # Login as student to create a leave request
    login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": student["email"], "password": "StudentPass123"},
    )
    stu_token = login_resp.json()["access_token"]
    stu_headers = {"Authorization": f"Bearer {stu_token}"}

    # Create Leave Request 1
    leave_resp = await client.post(
        "/api/v1/leaves",
        json={
            "from_date": (today + timedelta(days=2)).isoformat(),
            "to_date": (today + timedelta(days=5)).isoformat(),
            "reason": "Family wedding ceremony",
        },
        headers=stu_headers,
    )
    assert leave_resp.status_code == 201, leave_resp.text
    leave_id = leave_resp.json()["id"]

    # 1. Admin leaves list (pending queue default)
    resp = await client.get("/admin/leaves?status_tab=pending", cookies=cookies)
    assert resp.status_code == 200
    assert "Student Leaves" in resp.text
    assert student["student_no"] in resp.text

    # 2. Render review modal
    resp = await client.get(
        f"/admin/leaves/{leave_id}/modal/review?action=approve", cookies=cookies
    )
    assert resp.status_code == 200
    assert "Approve Leave Request" in resp.text

    # 3. Approve leave submit
    resp = await client.post(
        f"/admin/leaves/{leave_id}/approve",
        data={"remarks": "Granted. Be back by Sunday.", "csrf_token": CSRF_TOKEN},
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert "HX-Redirect" in resp.headers

    # Verify approved tab
    resp = await client.get("/admin/leaves?status_tab=approved", cookies=cookies)
    assert resp.status_code == 200
    assert student["student_no"] in resp.text

    # Create Leave Request 2 for rejection test
    leave_resp2 = await client.post(
        "/api/v1/leaves",
        json={
            "from_date": (today + timedelta(days=10)).isoformat(),
            "to_date": (today + timedelta(days=12)).isoformat(),
            "reason": "Weekend leisure trip",
        },
        headers=stu_headers,
    )
    leave_id2 = leave_resp2.json()["id"]

    # Reject leave submit
    resp = await client.post(
        f"/admin/leaves/{leave_id2}/reject",
        data={"remarks": "Exams scheduled during this period.", "csrf_token": CSRF_TOKEN},
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
    )
    assert resp.status_code == 200

    # Verify rejected tab
    resp = await client.get("/admin/leaves?status_tab=rejected", cookies=cookies)
    assert resp.status_code == 200
    assert student["student_no"] in resp.text


# =========================================================================
# 3. Visitors Management Tests
# =========================================================================


@pytest.mark.asyncio
async def test_admin_visitors_flow(
    client: AsyncClient, admin_token: str, admin_headers: dict[str, str]
):
    """Test visitor registration modal, active visitors list, and visitor checkout."""
    cookies = get_web_cookies(admin_token)
    headers = get_web_headers()

    struct = await setup_hostel_structure(client, admin_headers)
    student = await setup_student(client, admin_headers)

    # Allocate student
    today = date.today().isoformat()
    await client.post(
        "/api/v1/allocations",
        json={"student_id": student["id"], "bed_id": struct["bed_id"], "start_date": today},
        headers=admin_headers,
    )

    # 1. Render Visitors page
    resp = await client.get("/admin/visitors", cookies=cookies)
    assert resp.status_code == 200
    assert "Hostel Visitors" in resp.text

    # 2. Render Register Visitor modal
    resp = await client.get(
        f"/admin/visitors/modal/register?student_id={student['id']}",
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert "Register Hostel Visitor" in resp.text

    # 3. Register visitor submit (or test visiting hours check)
    resp = await client.post(
        "/admin/visitors/register",
        data={
            "student_id": student["id"],
            "name": "Sarah Connor",
            "phone": "+1987654329",
            "relation": "Mother",
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
    )
    # If within visiting hours: 200 (HX-Redirect). If outside hours: 422 with clear message
    assert resp.status_code in (200, 422)
    if resp.status_code == 422:
        assert "visiting hours" in resp.text.lower()
    else:
        # Check active visitors list
        resp = await client.get("/admin/visitors", cookies=cookies)
        assert resp.status_code == 200
        assert "Sarah Connor" in resp.text


# =========================================================================
# 4. Complaints Lifecycle & Comments Tests
# =========================================================================


@pytest.mark.asyncio
async def test_admin_complaints_lifecycle(
    client: AsyncClient, admin_token: str, admin_headers: dict[str, str], admin_user: User
):
    """Test complaint listing, detail view, staff assignment, comments thread, and status flow."""
    cookies = get_web_cookies(admin_token)
    headers = get_web_headers()

    struct = await setup_hostel_structure(client, admin_headers)
    student = await setup_student(client, admin_headers)

    # Allocate student
    today = date.today().isoformat()
    await client.post(
        "/api/v1/allocations",
        json={"student_id": student["id"], "bed_id": struct["bed_id"], "start_date": today},
        headers=admin_headers,
    )

    # Login student to create complaint
    login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": student["email"], "password": "StudentPass123"},
    )
    stu_token = login_resp.json()["access_token"]
    stu_headers = {"Authorization": f"Bearer {stu_token}"}

    comp_resp = await client.post(
        "/api/v1/complaints",
        json={
            "title": "Water heater leaking heavily",
            "description": "Bathroom geyser valve is dripping continuously.",
            "category": "plumbing",
            "priority": "urgent",
        },
        headers=stu_headers,
    )
    assert comp_resp.status_code == 201, comp_resp.text
    comp_id = comp_resp.json()["id"]

    # 1. Complaints list page
    resp = await client.get("/admin/complaints?status_tab=open", cookies=cookies)
    assert resp.status_code == 200
    assert "Complaints & Tickets" in resp.text
    assert "Water heater leaking" in resp.text

    # 2. Complaint detail page
    resp = await client.get(f"/admin/complaints/{comp_id}", cookies=cookies)
    assert resp.status_code == 200
    assert "Water heater leaking" in resp.text
    assert "Update Status" in resp.text

    # 3. Assign Staff member (Admin assigns self)
    resp = await client.post(
        f"/admin/complaints/{comp_id}/assign",
        data={"assigned_to": str(admin_user.id), "csrf_token": CSRF_TOKEN},
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
    )
    assert resp.status_code == 200

    # 4. Add Internal Comment
    resp = await client.post(
        f"/admin/complaints/{comp_id}/comment",
        data={
            "comment": "Plumber dispatched with replacement valve gasket.",
            "is_internal": "true",
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
    )
    assert resp.status_code == 200

    # Verify comment shows in detail
    resp = await client.get(f"/admin/complaints/{comp_id}", cookies=cookies)
    assert resp.status_code == 200
    assert "Plumber dispatched" in resp.text
    assert "Internal Staff Only" in resp.text

    # 5. Resolve Ticket
    resp = await client.post(
        f"/admin/complaints/{comp_id}/status",
        data={
            "status": "resolved",
            "resolution_notes": "Replaced valve washer and tested under pressure.",
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
    )
    assert resp.status_code == 200

    # 6. Close Ticket
    resp = await client.post(
        f"/admin/complaints/{comp_id}/status",
        data={
            "status": "closed",
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
    )
    assert resp.status_code == 200


# =========================================================================
# 5. Mess Weekly Menu & Headcount Tests
# =========================================================================


@pytest.mark.asyncio
async def test_admin_mess_menu_and_headcount(
    client: AsyncClient, admin_token: str, admin_headers: dict[str, str]
):
    """Test weekly menu 7x3 editor, batch menu save idempotency, and headcount projection."""
    cookies = get_web_cookies(admin_token)
    headers = get_web_headers()

    struct = await setup_hostel_structure(client, admin_headers)
    hostel_id = struct["hostel_id"]

    # 1. Render Menu screen
    resp = await client.get(f"/admin/mess?hostel_id={hostel_id}", cookies=cookies)
    assert resp.status_code == 200
    assert "Mess Menu Planner" in resp.text

    # 2. Save full week menu
    menu_data = {
        "hostel_id": hostel_id,
        "csrf_token": CSRF_TOKEN,
        "items_0_breakfast": "Pancakes, Syrup, Fruit",
        "items_0_lunch": "Grilled Chicken, Rice, Salad",
        "items_0_dinner": "Pasta Primavera, Garlic Bread",
        "items_1_breakfast": "Oatmeal, Honey, Banana",
        "items_1_lunch": "Fish Curry, Steamed Rice",
        "items_1_dinner": "Vegetable Stir-fry, Noodles",
    }
    resp = await client.post(
        "/admin/mess/update",
        data=menu_data,
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
    )
    assert resp.status_code == 200

    # 3. Idempotency test: save again
    resp = await client.post(
        "/admin/mess/update",
        data=menu_data,
        cookies=cookies,
        headers={**headers, "HX-Request": "true"},
    )
    assert resp.status_code == 200

    # 4. Headcount screen
    today = date.today().isoformat()
    resp = await client.get(
        f"/admin/mess/headcount?hostel_id={hostel_id}&target_date={today}",
        cookies=cookies,
    )
    assert resp.status_code == 200
    assert "Kitchen Headcount Projection" in resp.text
    assert "Breakfast" in resp.text
    assert "Expected Diners" in resp.text


# =========================================================================
# 6. Notices Management CRUD Tests
# =========================================================================


@pytest.mark.asyncio
async def test_admin_notices_crud_and_status(
    client: AsyncClient, admin_token: str, admin_headers: dict[str, str]
):
    """Test notices index, create form, create submit, live status badge, edit, and delete."""
    cookies = get_web_cookies(admin_token)
    headers = get_web_headers()

    struct = await setup_hostel_structure(client, admin_headers)
    hostel_id = struct["hostel_id"]

    # 1. Notices list
    resp = await client.get("/admin/notices", cookies=cookies)
    assert resp.status_code == 200
    assert "Notice Board" in resp.text

    # 2. Create form
    resp = await client.get("/admin/notices/new", cookies=cookies)
    assert resp.status_code == 200
    assert "Create Notice Announcement" in resp.text
    assert "Live Preview" in resp.text

    # 3. Create submit
    now = datetime.now(UTC)
    resp = await client.post(
        "/admin/notices",
        data={
            "title": "Annual Fire Safety Drill",
            "body": "Mandatory fire safety drill scheduled for Friday 10:00 AM.",
            "audience": "all",
            "hostel_id": hostel_id,
            "is_pinned": "true",
            "published_at": (now - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M"),
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    # 4. Verify listed with Live status
    resp = await client.get("/admin/notices", cookies=cookies)
    assert resp.status_code == 200
    assert "Annual Fire Safety Drill" in resp.text
    assert "Live" in resp.text

    # Fetch notice ID via API
    api_notices = await client.get("/api/v1/notices", headers=admin_headers)
    items = api_notices.json()["items"]
    target = next((n for n in items if n["title"] == "Annual Fire Safety Drill"), None)
    assert target is not None
    notice_id = target["id"]

    # 5. Edit form
    resp = await client.get(f"/admin/notices/{notice_id}/edit", cookies=cookies)
    assert resp.status_code == 200
    assert "Edit Notice Announcement" in resp.text

    # 6. Edit submit
    resp = await client.post(
        f"/admin/notices/{notice_id}/edit",
        data={
            "title": "Annual Fire Safety Drill (Updated Timing)",
            "body": "Updated: Drill moved to 11:30 AM due to maintenance.",
            "audience": "all",
            "is_pinned": "true",
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    # 7. Delete submit
    resp = await client.post(
        f"/admin/notices/{notice_id}/delete",
        data={"csrf_token": CSRF_TOKEN},
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)


# =========================================================================
# 7. Audit Log Tests
# =========================================================================


@pytest.mark.asyncio
async def test_admin_audit_logs_screen(
    client: AsyncClient, admin_token: str, admin_headers: dict[str, str], warden_token: str
):
    """Test admin access to audit logs with expandable JSON payloads and warden 403 block."""
    admin_cookies = get_web_cookies(admin_token)
    warden_cookies = get_web_cookies(warden_token)

    # First perform an audited action so an audit record with JSON payload exists
    code = f"aud.{uuid4().hex[:6]}"
    u_resp = await client.post(
        "/api/v1/users",
        json={
            "email": f"{code}@example.com",
            "password": "Password123",
            "full_name": "Audited Test User",
            "role": "student",
        },
        headers=admin_headers,
    )
    assert u_resp.status_code == 201

    # Admin access -> 200
    resp = await client.get("/admin/audit", cookies=admin_cookies)
    assert resp.status_code == 200
    assert "System Audit Trail" in resp.text
    assert "Audited Test User" in resp.text or "student" in resp.text

    # Warden access -> 403 Forbidden
    resp = await client.get("/admin/audit", cookies=warden_cookies)
    assert resp.status_code == 403


# =========================================================================
# 8. Analytical Reports & CSV Export Tests
# =========================================================================


@pytest.mark.asyncio
async def test_admin_reports_and_csv_exports(
    client: AsyncClient, admin_token: str, admin_headers: dict[str, str]
):
    """Test reports directory hub, sub-report pages, and CSV download endpoints."""
    cookies = get_web_cookies(admin_token)

    # 1. Reports hub
    resp = await client.get("/admin/reports", cookies=cookies)
    assert resp.status_code == 200
    assert "Reports & Analytics Hub" in resp.text

    # 2. Occupancy report & CSV
    resp = await client.get("/admin/reports/occupancy", cookies=cookies)
    assert resp.status_code == 200
    assert "Hostel Occupancy Report" in resp.text

    csv_resp = await client.get("/admin/reports/occupancy/csv", cookies=cookies)
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert "attachment; filename=" in csv_resp.headers.get("content-disposition", "")
    assert "Hostel Name" in csv_resp.text

    # 3. Revenue report & CSV
    resp = await client.get("/admin/reports/revenue", cookies=cookies)
    assert resp.status_code == 200
    assert "Revenue & Collections Report" in resp.text

    csv_resp = await client.get("/admin/reports/revenue/csv", cookies=cookies)
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert "Total Revenue" in csv_resp.text

    # 4. Defaulters report & CSV
    resp = await client.get("/admin/reports/defaulters", cookies=cookies)
    assert resp.status_code == 200
    assert "Overdue Invoice Defaulters" in resp.text

    csv_resp = await client.get("/admin/reports/defaulters/csv", cookies=cookies)
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert "Student Name" in csv_resp.text

    # 5. Complaints report & CSV
    resp = await client.get("/admin/reports/complaints", cookies=cookies)
    assert resp.status_code == 200
    assert "Complaints & Upkeep Analytics" in resp.text

    csv_resp = await client.get("/admin/reports/complaints/csv", cookies=cookies)
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert "Category" in csv_resp.text

    # 6. Attendance report & CSV
    resp = await client.get("/admin/reports/attendance", cookies=cookies)
    assert resp.status_code == 200
    assert "Attendance & Residency Analytics" in resp.text

    csv_resp = await client.get("/admin/reports/attendance/csv", cookies=cookies)
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert "Target Date" in csv_resp.text


# =========================================================================
# 9. Scoping & CSRF Security Matrix Tests
# =========================================================================


@pytest.mark.asyncio
async def test_admin_portal_three_security_matrix(
    client: AsyncClient,
    admin_token: str,
    warden_token: str,
    student_token: str,
):
    """Verify role barriers and CSRF enforcement across operations routes."""
    student_cookies = get_web_cookies(student_token)

    # 1. Student strictly forbidden (403) from staff operations
    for path in [
        "/admin/attendance/gate",
        "/admin/attendance",
        "/admin/leaves",
        "/admin/visitors",
        "/admin/complaints",
        "/admin/mess",
        "/admin/notices",
        "/admin/reports",
        "/admin/audit",
    ]:
        resp = await client.get(path, cookies=student_cookies)
        assert resp.status_code == 403, f"Student expected 403 on {path}, got {resp.status_code}"

    # Warden forbidden (403) from Superuser Audit logs
    warden_cookies = get_web_cookies(warden_token)
    audit_resp = await client.get("/admin/audit", cookies=warden_cookies)
    assert audit_resp.status_code == 403

    # 2. CSRF rejection (403) on mutating POST endpoints without CSRF token
    dummy_id = str(uuid4())
    mutations = [
        ("/admin/attendance/gate/action", {"student_id": dummy_id, "action": "check_in"}),
        (f"/admin/leaves/{dummy_id}/approve", {}),
        (f"/admin/leaves/{dummy_id}/reject", {}),
        (
            "/admin/visitors/register",
            {"student_id": dummy_id, "name": "Visitor", "phone": "123", "relation": "Friend"},
        ),
        (f"/admin/visitors/{dummy_id}/checkout", {}),
        (f"/admin/complaints/{dummy_id}/status", {"status": "in_progress"}),
        (f"/admin/complaints/{dummy_id}/assign", {"assigned_to": dummy_id}),
        (f"/admin/complaints/{dummy_id}/comment", {"comment": "Work note"}),
        ("/admin/mess/update", {"hostel_id": dummy_id}),
        ("/admin/notices", {"title": "Test", "body": "Body", "audience": "all"}),
    ]

    for endpoint, data in mutations:
        # Request with session cookie but NO CSRF token
        resp = await client.post(
            endpoint,
            data=data,
            cookies={"access_token": admin_token},
            follow_redirects=False,
        )
        assert resp.status_code == 403, f"Expected CSRF 403 on {endpoint}, got {resp.status_code}"


# =========================================================================
# 10. Extended Scenarios: Standard Redirects, Scoping & Advanced Filters
# =========================================================================


@pytest.mark.asyncio
async def test_admin_portal_three_extended_scenarios(
    client: AsyncClient,
    admin_token: str,
    admin_headers: dict[str, str],
    warden_token: str,
    warden_user: User,
    admin_user: User,
):
    """Test standard 303 redirects, warden scoping, and advanced filtering."""
    cookies = get_web_cookies(admin_token)
    headers = get_web_headers()
    warden_cookies = get_web_cookies(warden_token)

    struct = await setup_hostel_structure(client, admin_headers)
    student = await setup_student(client, admin_headers)
    hostel_id = struct["hostel_id"]

    # Assign warden to this hostel
    await client.post(
        f"/api/v1/hostels/{hostel_id}/wardens",
        json={"user_id": str(warden_user.id)},
        headers=admin_headers,
    )

    # 1. Gate attendance standard redirect (non-HX)
    today = date.today().isoformat()
    await client.post(
        "/api/v1/allocations",
        json={"student_id": student["id"], "bed_id": struct["bed_id"], "start_date": today},
        headers=admin_headers,
    )
    resp = await client.post(
        "/admin/attendance/gate/action",
        data={"student_id": student["id"], "action": "check_in", "csrf_token": CSRF_TOKEN},
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/admin/attendance/gate" in resp.headers["location"]

    # Gate screen with search query
    resp = await client.get(
        f"/admin/attendance/gate?q={student['student_no']}",
        cookies=cookies,
    )
    assert resp.status_code == 200

    # Gate check-out standard redirect
    resp = await client.post(
        "/admin/attendance/gate/action",
        data={"student_id": student["id"], "action": "check_out", "csrf_token": CSRF_TOKEN},
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Gate invalid action test
    resp = await client.post(
        "/admin/attendance/gate/action",
        data={"student_id": student["id"], "action": "invalid_action", "csrf_token": CSRF_TOKEN},
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code == 422

    # Gate attendance with date & type filter
    resp = await client.get(
        f"/admin/attendance?hostel_id={hostel_id}&type=check_in&date_from={today}&date_to={today}",
        cookies=cookies,
    )
    assert resp.status_code == 200

    # 2. Warden scoping views (hostel filtering)
    for path in [
        f"/admin/attendance?hostel_id={hostel_id}",
        f"/admin/leaves?hostel_id={hostel_id}&status_tab=all",
        f"/admin/visitors?hostel_id={hostel_id}",
        f"/admin/complaints?hostel_id={hostel_id}&priority=medium&category=other",
        f"/admin/mess?hostel_id={hostel_id}",
        f"/admin/mess/headcount?hostel_id={hostel_id}",
        f"/admin/notices?hostel_id={hostel_id}&audience=all",
        f"/admin/reports/occupancy?hostel_id={hostel_id}",
        f"/admin/reports/revenue?hostel_id={hostel_id}",
        f"/admin/reports/defaulters?hostel_id={hostel_id}",
        f"/admin/reports/complaints?hostel_id={hostel_id}",
        f"/admin/reports/attendance?hostel_id={hostel_id}",
    ]:
        resp = await client.get(path, cookies=warden_cookies)
        assert resp.status_code == 200, f"Warden failed on {path}: {resp.status_code}"

    # Present now screen with default hostel (admin and warden)
    resp = await client.get("/admin/attendance/present", cookies=cookies)
    assert resp.status_code == 200
    resp = await client.get("/admin/attendance/present", cookies=warden_cookies)
    assert resp.status_code == 200

    # Leaves default screen (admin and warden)
    resp = await client.get("/admin/leaves", cookies=cookies)
    assert resp.status_code == 200
    resp = await client.get("/admin/leaves", cookies=warden_cookies)
    assert resp.status_code == 200

    # Students list screen with multi-query filter parts
    resp = await client.get(
        "/admin/students?allocated=yes&department=Engineering&year=2&gender=male&search=Ops",
        cookies=cookies,
    )
    assert resp.status_code == 200
    resp = await client.get("/admin/students?allocated=no", cookies=cookies)
    assert resp.status_code == 200

    # Room detail web screen view
    resp = await client.get(f"/admin/rooms/{struct['room_id']}", cookies=cookies)
    assert resp.status_code == 200
    assert "Room" in resp.text

    resp = await client.get(f"/admin/rooms/{struct['room_id']}/modal/assign", cookies=cookies)
    assert resp.status_code == 200

    student2 = await setup_student(client, admin_headers)
    resp = await client.post(
        f"/admin/rooms/{struct['room_id']}/assign",
        data={
            "student_id": student2["id"],
            "bed_id": struct["bed_id_2"],
            "start_date": today,
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Error handling branch in room assign: double allocation 422
    resp = await client.post(
        f"/admin/rooms/{struct['room_id']}/assign",
        data={
            "student_id": student2["id"],
            "bed_id": struct["bed_id_2"],
            "start_date": today,
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers=headers,
    )
    assert resp.status_code == 422

    # Leaves list screen with pending tab
    resp = await client.get("/admin/leaves?status_tab=pending", cookies=cookies)
    assert resp.status_code == 200

    # 3. Notice Delete and Status computed
    now = datetime.now(UTC)
    resp = await client.post(
        "/admin/notices",
        data={
            "title": "Temp Delete Notice",
            "body": "To be removed",
            "audience": "all",
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303
    api_notices = await client.get("/api/v1/notices", headers=admin_headers)
    items = api_notices.json()["items"]
    temp_target = next((n for n in items if n["title"] == "Temp Delete Notice"), None)
    if temp_target:
        resp = await client.post(
            f"/admin/notices/{temp_target['id']}/delete",
            data={"csrf_token": CSRF_TOKEN},
            cookies=cookies,
            headers=headers,
            follow_redirects=False,
        )
        assert resp.status_code == 303

    # Scheduled and Expired notice status computation
    await client.post(
        "/admin/notices",
        data={
            "title": "Scheduled Future Notice",
            "body": "Future body",
            "audience": "all",
            "published_at": (now + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M"),
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers=headers,
    )
    await client.post(
        "/admin/notices",
        data={
            "title": "Past Expired Notice",
            "body": "Expired body",
            "audience": "all",
            "published_at": (now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M"),
            "expires_at": (now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers=headers,
    )
    resp = await client.get("/admin/notices", cookies=cookies)
    assert resp.status_code == 200
    assert "Scheduled" in resp.text
    assert "Expired" in resp.text

    # 4. Mess update standard redirect (non-HX)
    resp = await client.post(
        "/admin/mess/update",
        data={"hostel_id": hostel_id, "csrf_token": CSRF_TOKEN, "items_0_breakfast": "Toast"},
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # 5. Audit log query filters
    resp = await client.get(
        f"/admin/audit?entity=Hostel&action=create&date_from={today}&date_to={today}",
        cookies=cookies,
    )
    assert resp.status_code == 200

    # 6. Leaves standard non-HX redirects
    login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": student["email"], "password": "StudentPass123"},
    )
    stu_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    leave_1 = await client.post(
        "/api/v1/leaves",
        json={"from_date": "2026-12-01", "to_date": "2026-12-03", "reason": "Family visit"},
        headers=stu_headers,
    )
    leave_id = leave_1.json()["id"]
    resp = await client.post(
        f"/admin/leaves/{leave_id}/approve",
        data={"remarks": "Granted", "csrf_token": CSRF_TOKEN},
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303

    leave_2 = await client.post(
        "/api/v1/leaves",
        json={"from_date": "2026-12-05", "to_date": "2026-12-07", "reason": "Trip"},
        headers=stu_headers,
    )
    leave_id_2 = leave_2.json()["id"]
    resp = await client.post(
        f"/admin/leaves/{leave_id_2}/reject",
        data={"remarks": "Denied", "csrf_token": CSRF_TOKEN},
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # 7. Complaints standard non-HX redirects
    comp_resp = await client.post(
        "/api/v1/complaints",
        json={
            "title": "Broken window latch",
            "description": "Window cannot close properly.",
            "category": "furniture",
            "priority": "medium",
        },
        headers=stu_headers,
    )
    comp_id = comp_resp.json()["id"]

    resp = await client.post(
        f"/admin/complaints/{comp_id}/assign",
        data={"assigned_to": str(admin_user.id), "csrf_token": CSRF_TOKEN},
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303

    resp = await client.post(
        f"/admin/complaints/{comp_id}/comment",
        data={"comment": "Carpenter arriving at 2 PM", "csrf_token": CSRF_TOKEN},
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303

    resp = await client.post(
        f"/admin/complaints/{comp_id}/status",
        data={
            "status": "resolved",
            "resolution_notes": "Latch replaced",
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code == 303

    resp = await client.get(f"/admin/complaints/{comp_id}", cookies=cookies)
    assert resp.status_code == 200

    # 8. Visitors standard non-HX register and modal
    resp = await client.get("/admin/visitors/modal/register", cookies=cookies)
    assert resp.status_code == 200

    resp = await client.post(
        "/admin/visitors/register",
        data={
            "student_id": student["id"],
            "name": "Invalid Phone",
            "phone": "invalid-phone",
            "relation": "Friend",
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers=headers,
    )
    assert resp.status_code == 422

    resp = await client.post(
        "/admin/visitors/register",
        data={
            "student_id": student["id"],
            "name": "Uncle Bob",
            "phone": "+1987654321",
            "relation": "Uncle",
            "csrf_token": CSRF_TOKEN,
        },
        cookies=cookies,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code in (303, 422)

    # 9. Gate attendance with query parameter
    resp = await client.get(
        f"/admin/attendance/gate?q={student['student_no']}",
        cookies=cookies,
    )
    assert resp.status_code == 200

    # 10. Filter complaints with assigned_to_me, priority, and category
    resp = await client.get(
        "/admin/complaints?status_tab=open&priority=urgent&category=furniture&assigned_to_me=true",
        cookies=cookies,
    )
    assert resp.status_code == 200

    # 11. Present screen as warden with hostel_id
    resp = await client.get(
        f"/admin/attendance/present?hostel_id={hostel_id}",
        cookies=warden_cookies,
    )
    assert resp.status_code == 200

    # 12. Notice delete standard redirect (non-HX)
    not_resp = await client.post(
        "/api/v1/notices",
        json={"title": "Notice To Delete Direct", "content": "Will be deleted via 303"},
        headers=headers,
    )
    if not_resp.status_code == 201:
        del_nid = not_resp.json()["id"]
        resp = await client.post(
            f"/admin/notices/{del_nid}/delete",
            data={"csrf_token": CSRF_TOKEN},
            cookies=cookies,
            headers=headers,
            follow_redirects=False,
        )
        assert resp.status_code == 303
