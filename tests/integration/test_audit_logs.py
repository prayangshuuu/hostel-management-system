"""Integration tests for Audit Logs REST API endpoint."""

from __future__ import annotations

from httpx import AsyncClient


async def test_audit_logs_rbac_and_filtering(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_headers: dict[str, str],
    student_headers: dict[str, str],
) -> None:
    """Verify admin-only access to audit logs and query filter support."""
    # 1. Unauthenticated -> 401
    res_unauth = await client.get("/api/v1/audit-logs")
    assert res_unauth.status_code == 401

    # 2. Student -> 403 Forbidden
    res_student = await client.get("/api/v1/audit-logs", headers=student_headers)
    assert res_student.status_code == 403

    # 3. Warden -> 403 Forbidden
    res_warden = await client.get("/api/v1/audit-logs", headers=warden_headers)
    assert res_warden.status_code == 403

    # 4. Trigger an audited action as admin: create user
    res_user = await client.post(
        "/api/v1/users",
        json={
            "email": "audit_endpoint_test@example.com",
            "full_name": "Audit Endpoint User",
            "phone": "+9876543210",
            "password": "ValidPassword123!",
            "role": "student",
        },
        headers=admin_headers,
    )
    assert res_user.status_code == 201
    user_id = res_user.json()["id"]

    # 5. Admin lists audit logs
    res_logs = await client.get("/api/v1/audit-logs", headers=admin_headers)
    assert res_logs.status_code == 200
    data = res_logs.json()
    assert "items" in data
    assert data["total"] >= 1

    # 6. Filter by action
    res_filtered = await client.get(
        "/api/v1/audit-logs?action=user.create",
        headers=admin_headers,
    )
    assert res_filtered.status_code == 200
    filtered_items = res_filtered.json()["items"]
    assert any(log["entity_id"] == user_id for log in filtered_items)
    # Ensure password key is NOT present in any logged payload
    for log in filtered_items:
        assert "password" not in log["payload"] or log["payload"]["password"] == "[REDACTED]"
