"""Locust load test suite for realistic user workflows.

Simulates:
1. Admin/Warden user:
   - Login -> fetch dashboard summary -> list rooms -> record payment.
2. Student user:
   - Login -> fetch student dashboard -> view mess menu.
"""

from __future__ import annotations

import secrets
from typing import Any

from locust import HttpUser, between, task


class AdminWardenUser(HttpUser):
    """Admin or Warden user workflow."""

    weight = 1
    wait_time = between(0.2, 1.0)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.headers: dict[str, str] = {}

    def on_start(self) -> None:
        """Authenticate as Admin or Warden upon user startup."""
        users = [
            ("admin@hostel.example.com", "AdminPass123"),
            ("warden.boys@hostel.example.com", "WardenPass123"),
            ("warden.girls@hostel.example.com", "WardenPass123"),
        ]
        email, password = secrets.choice(users)

        resp = self.client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
            name="/api/v1/auth/login [admin/warden]",
        )
        if resp.status_code == 200:
            payload: dict[str, Any] = resp.json()
            token = payload.get("access_token")
            if token:
                self.headers = {"Authorization": f"Bearer {token}"}
        else:
            self.headers = {}

    @task(3)
    def fetch_dashboard_summary(self) -> None:
        """Retrieve executive dashboard metrics."""
        if not self.headers:
            return
        self.client.get(
            "/api/v1/dashboard/summary",
            headers=self.headers,
            name="/api/v1/dashboard/summary",
        )

    @task(2)
    def list_rooms(self) -> None:
        """List available rooms with pagination."""
        if not self.headers:
            return
        self.client.get(
            "/api/v1/rooms/available?page=1&size=20",
            headers=self.headers,
            name="/api/v1/rooms/available",
        )

    @task(1)
    def record_payment_workflow(self) -> None:
        """Fetch invoices and attempt to record a payment."""
        if not self.headers:
            return

        inv_resp = self.client.get(
            "/api/v1/invoices?page=1&size=10",
            headers=self.headers,
            name="/api/v1/invoices",
        )
        if inv_resp.status_code != 200:
            return

        body = inv_resp.json()
        items = body.get("items", [])
        if not items:
            return

        candidates = [inv for inv in items if inv.get("status") in ("unpaid", "partial", "overdue")]
        target_inv = candidates[0] if candidates else items[0]
        inv_id = target_inv.get("id")
        if not inv_id:
            return

        ref_id = secrets.randbelow(9000) + 1000
        with self.client.post(
            f"/api/v1/invoices/{inv_id}/payments",
            json={
                "amount": "10.00",
                "method": "online",
                "reference": f"LOCUST-{ref_id}",
            },
            headers=self.headers,
            catch_response=True,
            name="/api/v1/invoices/{id}/payments",
        ) as pay_resp:
            is_valid_resp = pay_resp.status_code in (200, 201, 429) or (
                pay_resp.status_code in (400, 409)
                and any(
                    err in pay_resp.text
                    for err in (
                        "ALREADY_PAID",
                        "AMOUNT",
                        "DUPLICATE",
                        "OVERPAYMENT",
                        "INVOICE_ALREADY_PAID",
                        "OVERPAYMENT_NOT_ALLOWED",
                    )
                )
            )
            if is_valid_resp:
                pay_resp.success()
            else:
                pay_resp.failure(
                    f"Unexpected status code {pay_resp.status_code}: {pay_resp.text[:100]}"
                )


class StudentUser(HttpUser):
    """Student user workflow."""

    weight = 3
    wait_time = between(0.2, 1.0)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.headers: dict[str, str] = {}

    def on_start(self) -> None:
        """Authenticate as one of the seeded students upon user startup."""
        idx = secrets.randbelow(40) + 1
        gender_prefix = secrets.choice(["b", "g"])
        email = f"student.{gender_prefix}{idx:03d}@hostel.example.com"
        password = "StudentPass123"

        resp = self.client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
            name="/api/v1/auth/login [student]",
        )
        if resp.status_code == 200:
            payload: dict[str, Any] = resp.json()
            token = payload.get("access_token")
            if token:
                self.headers = {"Authorization": f"Bearer {token}"}
        else:
            self.headers = {}

    @task(3)
    def fetch_my_dashboard(self) -> None:
        """Fetch current student dashboard."""
        if not self.headers:
            return
        self.client.get(
            "/api/v1/students/me/dashboard",
            headers=self.headers,
            name="/api/v1/students/me/dashboard",
        )

    @task(2)
    def view_menu(self) -> None:
        """View today's mess menu."""
        if not self.headers:
            return
        with self.client.get(
            "/api/v1/students/me/menu/today",
            headers=self.headers,
            catch_response=True,
            name="/api/v1/students/me/menu/today",
        ) as resp:
            if resp.status_code in (200, 404, 429) or (
                resp.status_code == 400 and "NO_ACTIVE_ALLOCATION" in resp.text
            ):
                resp.success()
            else:
                resp.failure(f"Unexpected status code {resp.status_code}: {resp.text[:100]}")
