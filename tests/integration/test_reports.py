"""Integration tests for reports and dashboard API endpoints."""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.models.user import User


@pytest.mark.asyncio
async def test_dashboard_summary_api(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_headers: dict[str, str],
    student_headers: dict[str, str],
) -> None:
    """Verify GET /api/v1/dashboard/summary RBAC, scoping, and data structure."""
    # 1. Unauthenticated -> 401
    resp_unauth = await client.get("/api/v1/dashboard/summary")
    assert resp_unauth.status_code == 401

    # 2. Student -> 403 Forbidden
    resp_student = await client.get("/api/v1/dashboard/summary", headers=student_headers)
    assert resp_student.status_code == 403

    # 3. Admin -> 200 OK
    resp_admin = await client.get("/api/v1/dashboard/summary", headers=admin_headers)
    assert resp_admin.status_code == 200
    data = resp_admin.json()
    assert "total_hostels" in data
    assert "total_rooms" in data
    assert "total_beds" in data
    assert "occupied_beds" in data
    assert "occupancy_rate" in data
    assert "active_students" in data
    assert "open_complaints" in data
    assert "pending_leaves" in data
    assert "present_now" in data
    assert "invoices_due_this_month" in data
    assert "collected_this_month" in data
    assert "outstanding_total" in data

    # 4. Warden -> 200 OK
    resp_warden = await client.get("/api/v1/dashboard/summary", headers=warden_headers)
    assert resp_warden.status_code == 200

    # 5. Non-existent hostel query -> 404 HOSTEL_NOT_FOUND
    random_id = str(uuid4())
    resp_not_found = await client.get(
        f"/api/v1/dashboard/summary?hostel_id={random_id}", headers=admin_headers
    )
    assert resp_not_found.status_code == 404
    assert resp_not_found.json()["error"]["code"] == "HOSTEL_NOT_FOUND"


@pytest.mark.asyncio
async def test_occupancy_report_api_and_csv(
    client: AsyncClient,
    admin_headers: dict[str, str],
    student_headers: dict[str, str],
) -> None:
    """Verify GET /api/v1/reports/occupancy JSON and CSV streaming format."""
    # Student -> 403
    resp_student = await client.get("/api/v1/reports/occupancy", headers=student_headers)
    assert resp_student.status_code == 403

    # Admin JSON format -> 200
    resp_json = await client.get("/api/v1/reports/occupancy?format=json", headers=admin_headers)
    assert resp_json.status_code == 200
    assert isinstance(resp_json.json(), list)

    # Admin CSV format -> 200 text/csv
    resp_csv = await client.get("/api/v1/reports/occupancy?format=csv", headers=admin_headers)
    assert resp_csv.status_code == 200
    assert "text/csv" in resp_csv.headers["content-type"]
    assert 'attachment; filename="occupancy_report.csv"' in resp_csv.headers["content-disposition"]
    # Check CSV header row
    csv_text = resp_csv.text
    assert "Hostel ID,Hostel Name,Block ID,Block Name,Room Type" in csv_text


@pytest.mark.asyncio
async def test_revenue_report_api_and_csv(
    client: AsyncClient,
    admin_headers: dict[str, str],
    student_headers: dict[str, str],
) -> None:
    """Verify GET /api/v1/reports/revenue groupings, date validation, and CSV export."""
    # Student -> 403
    resp_student = await client.get("/api/v1/reports/revenue", headers=student_headers)
    assert resp_student.status_code == 403

    # Date range error: from > to -> 422
    today = date.today()
    resp_invalid_dates = await client.get(
        f"/api/v1/reports/revenue?from={today}&to={today - timedelta(days=5)}",
        headers=admin_headers,
    )
    assert resp_invalid_dates.status_code == 422
    assert resp_invalid_dates.json()["error"]["code"] == "INVALID_DATE_RANGE"

    # Valid query group_by=month
    resp_month = await client.get("/api/v1/reports/revenue?group_by=month", headers=admin_headers)
    assert resp_month.status_code == 200
    assert isinstance(resp_month.json(), list)

    # Valid CSV streaming group_by=hostel
    resp_csv = await client.get(
        "/api/v1/reports/revenue?group_by=hostel&format=csv", headers=admin_headers
    )
    assert resp_csv.status_code == 200
    assert "text/csv" in resp_csv.headers["content-type"]
    assert (
        'attachment; filename="revenue_report_hostel.csv"'
        in resp_csv.headers["content-disposition"]
    )
    assert "Group Key,Total Revenue,Transaction Count" in resp_csv.text


@pytest.mark.asyncio
async def test_defaulters_report_api_and_csv(
    client: AsyncClient,
    admin_headers: dict[str, str],
    student_headers: dict[str, str],
) -> None:
    """Verify GET /api/v1/reports/defaulters JSON and CSV export."""
    # Student -> 403
    resp_student = await client.get("/api/v1/reports/defaulters", headers=student_headers)
    assert resp_student.status_code == 403

    # Admin JSON -> 200
    resp_json = await client.get("/api/v1/reports/defaulters?format=json", headers=admin_headers)
    assert resp_json.status_code == 200
    assert isinstance(resp_json.json(), list)

    # Admin CSV -> 200
    resp_csv = await client.get("/api/v1/reports/defaulters?format=csv", headers=admin_headers)
    assert resp_csv.status_code == 200
    assert "text/csv" in resp_csv.headers["content-type"]
    assert 'attachment; filename="defaulters_report.csv"' in resp_csv.headers["content-disposition"]
    assert "Student ID,Student No,Student Name,Hostel Name" in resp_csv.text


@pytest.mark.asyncio
async def test_complaints_report_api(
    client: AsyncClient,
    admin_headers: dict[str, str],
    student_headers: dict[str, str],
) -> None:
    """Verify GET /api/v1/reports/complaints response structure."""
    # Student -> 403
    resp_student = await client.get("/api/v1/reports/complaints", headers=student_headers)
    assert resp_student.status_code == 403

    # Admin -> 200
    resp_admin = await client.get("/api/v1/reports/complaints", headers=admin_headers)
    assert resp_admin.status_code == 200
    data = resp_admin.json()
    assert "total_complaints" in data
    assert "by_status" in data
    assert "by_category" in data
    assert "avg_resolution_hours" in data


@pytest.mark.asyncio
async def test_attendance_report_api(
    client: AsyncClient,
    admin_headers: dict[str, str],
    student_headers: dict[str, str],
) -> None:
    """Verify GET /api/v1/reports/attendance response structure."""
    # Student -> 403
    resp_student = await client.get("/api/v1/reports/attendance", headers=student_headers)
    assert resp_student.status_code == 403

    # Admin -> 200
    resp_admin = await client.get("/api/v1/reports/attendance", headers=admin_headers)
    assert resp_admin.status_code == 200
    data = resp_admin.json()
    assert "target_date" in data
    assert "total_active_students" in data
    assert "present_count" in data
    assert "absent_count" in data
    assert "on_leave_count" in data


@pytest.mark.asyncio
async def test_student_dashboard_api_privacy_and_rbac(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_headers: dict[str, str],
    student_headers: dict[str, str],
) -> None:
    """Verify GET /api/v1/students/me/dashboard privacy and RBAC."""
    # Admin -> 403 (Only STUDENT role can access)
    resp_admin = await client.get("/api/v1/students/me/dashboard", headers=admin_headers)
    assert resp_admin.status_code == 403

    # Warden -> 403 (Only STUDENT role can access)
    resp_warden = await client.get("/api/v1/students/me/dashboard", headers=warden_headers)
    assert resp_warden.status_code == 403

    # Student -> 200 OK
    resp_student = await client.get("/api/v1/students/me/dashboard", headers=student_headers)
    assert resp_student.status_code == 200
    data = resp_student.json()

    # Privacy check: roommates must be list of strings (names only, no email/phone/financial info)
    assert isinstance(data["roommates"], list)
    for rm in data["roommates"]:
        assert isinstance(rm, str)

    # Operational/Billing metrics
    assert "balance" in data
    assert "unread_notices_count" in data
    assert "open_complaints_count" in data


@pytest.mark.asyncio
async def test_warden_scoping_enforcement_in_reports(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_headers: dict[str, str],
    warden_user: User,
) -> None:
    """Verify warden cannot access reports for unassigned hostels."""
    # 1. Create Hostel 1 & 2
    h1_name = f"Scope Hostel 1 {uuid4().hex[:4]}"
    h1_code = f"SC1-{uuid4().hex[:4]}"
    h1_resp = await client.post(
        "/api/v1/hostels",
        json={"name": h1_name, "code": h1_code, "gender_type": "mixed"},
        headers=admin_headers,
    )
    h1_id = h1_resp.json()["id"]

    h2_name = f"Scope Hostel 2 {uuid4().hex[:4]}"
    h2_code = f"SC2-{uuid4().hex[:4]}"
    h2_resp = await client.post(
        "/api/v1/hostels",
        json={"name": h2_name, "code": h2_code, "gender_type": "mixed"},
        headers=admin_headers,
    )
    h2_id = h2_resp.json()["id"]

    # 2. Assign warden to Hostel 1 only
    assign_resp = await client.post(
        f"/api/v1/hostels/{h1_id}/wardens",
        json={"user_id": str(warden_user.id)},
        headers=admin_headers,
    )
    assert assign_resp.status_code == 201

    # 3. Warden requests summary for assigned Hostel 1 -> 200
    w_h1_resp = await client.get(
        f"/api/v1/dashboard/summary?hostel_id={h1_id}",
        headers=warden_headers,
    )
    assert w_h1_resp.status_code == 200

    # 4. Warden requests summary for unassigned Hostel 2 -> 403 Forbidden!
    w_h2_resp = await client.get(
        f"/api/v1/dashboard/summary?hostel_id={h2_id}",
        headers=warden_headers,
    )
    assert w_h2_resp.status_code == 403
    assert w_h2_resp.json()["error"]["code"] == "FORBIDDEN"

    # 5. Warden requests occupancy report for unassigned Hostel 2 -> 403 Forbidden!
    w_occ_resp = await client.get(
        f"/api/v1/reports/occupancy?hostel_id={h2_id}",
        headers=warden_headers,
    )
    assert w_occ_resp.status_code == 403
    assert w_occ_resp.json()["error"]["code"] == "FORBIDDEN"

    # 6. Warden requests complaints report for unassigned Hostel 2 -> 403 Forbidden!
    w_comp_resp = await client.get(
        f"/api/v1/reports/complaints?hostel_id={h2_id}",
        headers=warden_headers,
    )
    assert w_comp_resp.status_code == 403
    assert w_comp_resp.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_attendance_report_with_explicit_date(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Verify attendance report accepts explicit ?date= query parameter."""
    target = date(2026, 11, 20)
    resp = await client.get(f"/api/v1/reports/attendance?date={target}", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["target_date"] == "2026-11-20"
