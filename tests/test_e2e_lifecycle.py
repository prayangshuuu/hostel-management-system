"""End-to-End Lifecycle Scenario Integration Test.

Tests the full lifecycle of a university hostel management workflow:
1. Create hostel
2. Create block
3. Create room & auto-generate beds
4. Register student
5. Allocate bed to student
6. Configure fee structure and generate invoice
7. Record partial payment
8. Record remaining payment (full settlement)
9. Submit student maintenance complaint
10. Review, progress, and resolve complaint
11. Transfer student to another bed
12. Vacate allocation on completion
13. Verify dashboard and analytics reports reflect the full lifecycle
"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_full_hostel_lifecycle_e2e(
    client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """Execute end-to-end integration scenario across all core domains."""
    today = date.today()

    # -------------------------------------------------------------------------
    # 1. Create Hostel
    # -------------------------------------------------------------------------
    hostel_payload = {
        "name": "Grand Phoenix Hostel",
        "code": f"GPH-{uuid4().hex[:6].upper()}",
        "gender_type": "mixed",
        "address": "100 University Boulevard, Tech Campus",
    }
    resp = await client.post("/api/v1/hostels", json=hostel_payload, headers=admin_headers)
    assert resp.status_code == 201, resp.text
    hostel_data = resp.json()
    hostel_id = hostel_data["id"]
    assert hostel_data["name"] == "Grand Phoenix Hostel"
    assert hostel_data["gender_type"] == "mixed"

    # -------------------------------------------------------------------------
    # 2. Create Block
    # -------------------------------------------------------------------------
    block_payload = {
        "name": "Emerald Block A",
        "floor_count": 3,
    }
    resp = await client.post(
        f"/api/v1/hostels/{hostel_id}/blocks",
        json=block_payload,
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    block_data = resp.json()
    block_id = block_data["id"]
    assert block_data["name"] == "Emerald Block A"

    # -------------------------------------------------------------------------
    # 3. Create Rooms & Labeled Beds
    # -------------------------------------------------------------------------
    # Room 1: Double room with 2 beds
    room_101_payload = {
        "number": "R-101",
        "floor": 1,
        "room_type": "double",
        "capacity": 2,
        "monthly_rent": "650.00",
    }
    resp = await client.post(
        f"/api/v1/blocks/{block_id}/rooms",
        json=room_101_payload,
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    room_101 = resp.json()
    room_101_id = room_101["id"]
    beds_101 = room_101["beds"]
    assert len(beds_101) == 2
    bed_101_a = beds_101[0]
    bed_101_b = beds_101[1]
    assert bed_101_a["label"] == "A"
    assert bed_101_b["label"] == "B"
    assert not bed_101_a["is_occupied"]
    assert not bed_101_b["is_occupied"]

    # Room 2: Single room with 1 bed (for later transfer)
    room_102_payload = {
        "number": "R-102",
        "floor": 1,
        "room_type": "single",
        "capacity": 1,
        "monthly_rent": "800.00",
    }
    resp = await client.post(
        f"/api/v1/blocks/{block_id}/rooms",
        json=room_102_payload,
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    room_102 = resp.json()
    room_102_id = room_102["id"]
    beds_102 = room_102["beds"]
    assert len(beds_102) == 1
    bed_102_a = beds_102[0]

    # -------------------------------------------------------------------------
    # 4. Register Student
    # -------------------------------------------------------------------------
    student_payload = {
        "email": f"student_{uuid4().hex[:6]}@hostel.example.com",
        "full_name": "Alexander Sterling",
        "password": "SecurePassword123",
        "student_no": f"STU-{uuid4().hex[:6].upper()}",
        "gender": "male",
        "department": "Software Engineering",
        "year": 3,
        "guardian_name": "Eleanor Sterling",
        "guardian_phone": "+1555123456",
        "emergency_contact": "+1555987654",
    }
    resp = await client.post("/api/v1/students", json=student_payload, headers=admin_headers)
    assert resp.status_code == 201, resp.text
    student_data = resp.json()
    student_id = student_data["id"]
    assert student_data["full_name"] == "Alexander Sterling"

    # Authenticate as student
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": student_payload["email"], "password": "SecurePassword123"},
    )
    assert login_resp.status_code == 200, login_resp.text
    student_token = login_resp.json()["access_token"]
    student_headers = {"Authorization": f"Bearer {student_token}"}

    # -------------------------------------------------------------------------
    # 5. Allocate Bed
    # -------------------------------------------------------------------------
    alloc_payload = {
        "student_id": student_id,
        "bed_id": bed_101_a["id"],
        "start_date": str(today),
    }
    resp = await client.post("/api/v1/allocations", json=alloc_payload, headers=admin_headers)
    assert resp.status_code == 201, resp.text
    alloc_data = resp.json()
    allocation_id = alloc_data["id"]
    assert alloc_data["status"] == "active"
    assert alloc_data["bed_id"] == bed_101_a["id"]

    # Verify bed is now marked occupied
    resp = await client.get(f"/api/v1/rooms/{room_101_id}", headers=admin_headers)
    assert resp.status_code == 200
    r101_detail = resp.json()
    bed_a_refreshed = next(b for b in r101_detail["beds"] if b["id"] == bed_101_a["id"])
    assert bed_a_refreshed["is_occupied"] is True

    # Invariant: Duplicate allocation for the same student must be rejected
    dup_alloc_resp = await client.post(
        "/api/v1/allocations",
        json={"student_id": student_id, "bed_id": bed_101_b["id"]},
        headers=admin_headers,
    )
    assert dup_alloc_resp.status_code == 400
    assert dup_alloc_resp.json()["error"]["code"] == "STUDENT_ALREADY_ALLOCATED"

    # -------------------------------------------------------------------------
    # 6. Configure Fee Structure & Generate Invoice
    # -------------------------------------------------------------------------
    fee_payload = {
        "hostel_id": hostel_id,
        "room_type": "double",
        "amount": "650.00",
        "period": "monthly",
    }
    resp = await client.post("/api/v1/fee-structures", json=fee_payload, headers=admin_headers)
    assert resp.status_code == 201, resp.text

    gen_payload = {
        "hostel_id": hostel_id,
        "period_start": str(today),
        "period_end": str(today + timedelta(days=30)),
        "due_date": str(today + timedelta(days=10)),
    }
    resp = await client.post("/api/v1/invoices/generate", json=gen_payload, headers=admin_headers)
    assert resp.status_code == 200, resp.text
    gen_result = resp.json()
    assert gen_result["generated_count"] == 1
    invoice = gen_result["invoices"][0]
    invoice_id = invoice["id"]
    assert Decimal(str(invoice["amount"])) == Decimal("650.00")
    assert Decimal(str(invoice["paid_amount"])) == Decimal("0.00")
    assert Decimal(str(invoice["balance"])) == Decimal("650.00")
    assert invoice["status"] == "unpaid"

    # -------------------------------------------------------------------------
    # 7. Record Partial Payment (250.00)
    # -------------------------------------------------------------------------
    p1_payload = {
        "amount": "250.00",
        "method": "online",
        "reference": f"TXN-E2E-PARTIAL-{uuid4().hex[:6]}",
    }
    resp = await client.post(
        f"/api/v1/invoices/{invoice_id}/payments",
        json=p1_payload,
        headers=student_headers,
    )
    assert resp.status_code == 201, resp.text
    payment_1 = resp.json()
    assert Decimal(str(payment_1["amount"])) == Decimal("250.00")

    # Verify invoice status transition to PARTIAL
    resp = await client.get(f"/api/v1/invoices/{invoice_id}", headers=student_headers)
    assert resp.status_code == 200
    inv_partial = resp.json()
    assert Decimal(str(inv_partial["paid_amount"])) == Decimal("250.00")
    assert Decimal(str(inv_partial["balance"])) == Decimal("400.00")
    assert inv_partial["status"] == "partial"

    # Overpayment prevention check: 400.01 should fail
    resp_over = await client.post(
        f"/api/v1/invoices/{invoice_id}/payments",
        json={"amount": "400.01", "method": "card"},
        headers=student_headers,
    )
    assert resp_over.status_code == 400
    assert resp_over.json()["error"]["code"] == "OVERPAYMENT_NOT_ALLOWED"

    # -------------------------------------------------------------------------
    # 8. Record Full Payment (Remaining 400.00)
    # -------------------------------------------------------------------------
    p2_payload = {
        "amount": "400.00",
        "method": "card",
        "reference": f"TXN-E2E-FULL-{uuid4().hex[:6]}",
    }
    resp = await client.post(
        f"/api/v1/invoices/{invoice_id}/payments",
        json=p2_payload,
        headers=student_headers,
    )
    assert resp.status_code == 201, resp.text

    # Verify invoice status transition to PAID
    resp = await client.get(f"/api/v1/invoices/{invoice_id}", headers=student_headers)
    assert resp.status_code == 200
    inv_paid = resp.json()
    assert Decimal(str(inv_paid["paid_amount"])) == Decimal("650.00")
    assert Decimal(str(inv_paid["balance"])) == Decimal("0.00")
    assert inv_paid["status"] == "paid"

    # -------------------------------------------------------------------------
    # 9. Submit Complaint by Student
    # -------------------------------------------------------------------------
    complaint_payload = {
        "title": "Study Lamp Flickering",
        "description": "Desk lighting in Room 101 flickers intermittently.",
        "category": "electrical",
        "priority": "medium",
    }
    resp = await client.post("/api/v1/complaints", json=complaint_payload, headers=student_headers)
    assert resp.status_code == 201, resp.text
    complaint_data = resp.json()
    complaint_id = complaint_data["id"]
    assert complaint_data["status"] == "open"
    assert complaint_data["category"] == "electrical"

    # -------------------------------------------------------------------------
    # 10. Progress & Resolve Complaint by Admin
    # -------------------------------------------------------------------------
    # Transition to IN_PROGRESS
    resp = await client.post(
        f"/api/v1/complaints/{complaint_id}/status",
        json={"status": "in_progress", "resolution_notes": "Electrician dispatched"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "in_progress"

    # Transition to RESOLVED
    resp = await client.post(
        f"/api/v1/complaints/{complaint_id}/status",
        json={"status": "resolved", "resolution_notes": "Bulb and starter replaced"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "resolved"

    # -------------------------------------------------------------------------
    # 11. Bed Transfer: Move Student to Room 102 Bed A
    # -------------------------------------------------------------------------
    transfer_payload = {
        "new_bed_id": bed_102_a["id"],
        "reason": "Relocating to quiet single room for study term",
    }
    resp = await client.post(
        f"/api/v1/allocations/{allocation_id}/transfer",
        json=transfer_payload,
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    transferred = resp.json()
    new_allocation_id = transferred["id"]
    assert transferred["bed_id"] == bed_102_a["id"]
    assert transferred["status"] == "active"

    # Verify old bed 101-A is freed, new bed 102-A is occupied
    resp_r101 = await client.get(f"/api/v1/rooms/{room_101_id}", headers=admin_headers)
    bed_101_a_after = next(b for b in resp_r101.json()["beds"] if b["id"] == bed_101_a["id"])
    assert bed_101_a_after["is_occupied"] is False

    resp_r102 = await client.get(f"/api/v1/rooms/{room_102_id}", headers=admin_headers)
    bed_102_a_after = next(b for b in resp_r102.json()["beds"] if b["id"] == bed_102_a["id"])
    assert bed_102_a_after["is_occupied"] is True

    # -------------------------------------------------------------------------
    # 12. Vacate Allocation
    # -------------------------------------------------------------------------
    vacate_payload = {
        "end_date": str(today),
        "reason": "Graduation checkout completed",
    }
    resp = await client.post(
        f"/api/v1/allocations/{new_allocation_id}/vacate",
        json=vacate_payload,
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    vacated = resp.json()
    assert vacated["status"] == "ended"

    # Verify bed 102-A is now freed
    resp_r102_freed = await client.get(f"/api/v1/rooms/{room_102_id}", headers=admin_headers)
    bed_102_a_freed = next(b for b in resp_r102_freed.json()["beds"] if b["id"] == bed_102_a["id"])
    assert bed_102_a_freed["is_occupied"] is False

    # -------------------------------------------------------------------------
    # 13. Verify Dashboard & Reports Reflect Full Lifecycle
    # -------------------------------------------------------------------------
    # Dashboard summary
    resp = await client.get(
        f"/api/v1/dashboard/summary?hostel_id={hostel_id}",
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    summary = resp.json()
    assert summary["total_beds"] == 3  # 2 in R-101 + 1 in R-102
    assert summary["occupied_beds"] == 0  # vacated
    assert summary["occupancy_rate"] == 0.0
    assert summary["open_complaints"] == 0

    # Occupancy report (list of rows per hostel/block/room-type)
    resp = await client.get(
        f"/api/v1/reports/occupancy?hostel_id={hostel_id}",
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    occupancy_rows = resp.json()
    assert sum(row["total_beds"] for row in occupancy_rows) == 3
    assert sum(row["occupied_beds"] for row in occupancy_rows) == 0

    # Revenue report (list of grouped revenue rows)
    resp = await client.get(
        f"/api/v1/reports/revenue?hostel_id={hostel_id}",
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    revenue_rows = resp.json()
    total_rev = sum(Decimal(str(row["total_revenue"])) for row in revenue_rows)
    assert total_rev == Decimal("650.00")

    # Complaints report
    resp = await client.get(
        f"/api/v1/reports/complaints?hostel_id={hostel_id}",
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    complaints_report = resp.json()
    assert complaints_report["total_complaints"] >= 1
    assert complaints_report["by_status"].get("resolved", 0) >= 1
    assert complaints_report["by_category"].get("electrical", 0) >= 1

    # Defaulters report (0 since invoice is fully paid)
    resp = await client.get(
        f"/api/v1/reports/defaulters?hostel_id={hostel_id}",
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    defaulter_rows = resp.json()
    assert len(defaulter_rows) == 0

    # Student personal dashboard reflects vacated status and zero balance
    resp = await client.get("/api/v1/students/me/dashboard", headers=student_headers)
    assert resp.status_code == 200, resp.text
    student_dashboard = resp.json()
    assert Decimal(str(student_dashboard["balance"])) == Decimal("0.00")
    assert student_dashboard["open_complaints_count"] == 0
