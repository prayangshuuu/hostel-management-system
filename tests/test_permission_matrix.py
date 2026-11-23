"""FastAPI Dynamic Permission Matrix Test Suite.

Introspects all registered API routes dynamically from `app.routes` and validates
permissions across 6 canonical security roles:
1. anonymous: unauthenticated client (no token) -> 401 Unauthorized on protected routes,
   non-401 on public routes (/health, /auth/login, /auth/refresh).
2. admin: system administrator superuser -> permitted on management, operational,
   reporting, and shared endpoints (never 401 or 403). Receives 403 only on student-only
   self-service endpoints (/students/me/*).
3. warden-own: assigned warden for Hostel A -> permitted on operations, room management,
   allocations, billing, complaints, attendance, leaves, visitors, mess, reports, and notices
   scoped to their assigned hostel. Receives 403 on admin-only and student-only endpoints.
4. warden-other: assigned warden for Hostel B (unassigned to Hostel A) -> strictly forbidden
   (403) when attempting to access Hostel A's resources and admin-only endpoints.
5. student-self: student allocated in Hostel A -> permitted on self endpoints (/students/me/*),
   own student profile, own allocation, own invoice, own complaint, own leave, own visitor,
   hostel menu, and public listings. Strictly forbidden (403) on admin/warden management endpoints.
6. student-other: student allocated in Hostel B -> strictly forbidden (403) when attempting
   to access Student A's profile, allocation, invoice, payment, complaint, leave, visitor,
   meal opt-out, or other hostel menu.
"""

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models.allocation import Allocation, AllocationStatus
from app.models.billing import FeePeriod, FeeStructure, Invoice, InvoiceStatus
from app.models.complaint import (
    Complaint,
    ComplaintCategory,
    ComplaintPriority,
    ComplaintStatus,
)
from app.models.hostel import Block, GenderType, Hostel, WardenAssignment
from app.models.mess import MealOptOut, MealType
from app.models.notice import Notice, NoticeAudience
from app.models.operations import LeaveRequest, LeaveStatus, Visitor
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole


def get_all_api_routes(app: FastAPI) -> list[tuple[str, str, APIRoute]]:
    """Dynamically introspect all registered API routes from app.routes.

    Recursively traverses Starlette/FastAPI route trees and included routers.
    Returns list of (HTTP method, full URL path, APIRoute).
    """
    discovered: list[tuple[str, str, APIRoute]] = []

    def _walk(router_or_app: Any, prefix: str = "") -> None:
        routes = getattr(router_or_app, "routes", [])
        for route in routes:
            if isinstance(route, APIRoute):
                full_path = prefix + route.path
                if not full_path.startswith("/api"):
                    continue
                methods = route.methods or set()
                for method in sorted(methods):
                    if method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                        discovered.append((method, full_path, route))
            elif hasattr(route, "routes"):
                _walk(route, prefix)
            elif hasattr(route, "original_router"):
                ctx = getattr(route, "include_context", None)
                p = getattr(ctx, "prefix", "") if ctx else ""
                _walk(route.original_router, prefix + p)

    _walk(app)
    return discovered


@dataclass
class MatrixDataset:
    """Encapsulates test entities across two distinct hostels."""

    admin_user: User
    warden_own: User
    warden_other: User
    student_self_user: User
    student_other_user: User

    hostel_a: Hostel
    block_a: Block
    room_a: Room
    bed_a: Bed
    student_self_profile: StudentProfile
    allocation_a: Allocation
    fee_structure_a: FeeStructure
    invoice_a: Invoice
    complaint_a: Complaint
    leave_a: LeaveRequest
    visitor_a: Visitor
    opt_out_a: MealOptOut
    notice_a: Notice

    hostel_b: Hostel
    block_b: Block
    room_b: Room
    bed_b: Bed
    student_other_profile: StudentProfile
    allocation_b: Allocation

    tokens: dict[str, str]

    def resolve_path(self, path_template: str) -> str:
        """Resolve route URL path parameters to target Hostel A / Student A entities."""
        resolved = path_template
        # Dual-parameter endpoint: /hostels/{id}/wardens/{user_id}
        if "{id}" in resolved and "{user_id}" in resolved:
            resolved = resolved.replace("{id}", str(self.hostel_a.id))
            resolved = resolved.replace("{user_id}", str(self.warden_own.id))
            return resolved

        if "/hostels/{id}" in resolved:
            resolved = resolved.replace("{id}", str(self.hostel_a.id))
        elif "/blocks/{id}" in resolved:
            resolved = resolved.replace("{id}", str(self.block_a.id))
        elif "/rooms/{id}" in resolved:
            resolved = resolved.replace("{id}", str(self.room_a.id))
        elif "/students/{id}" in resolved:
            resolved = resolved.replace("{id}", str(self.student_self_profile.id))
        elif "/allocations/{id}" in resolved:
            resolved = resolved.replace("{id}", str(self.allocation_a.id))
        elif "/fee-structures/{id}" in resolved:
            resolved = resolved.replace("{id}", str(self.fee_structure_a.id))
        elif "/invoices/{id}" in resolved:
            resolved = resolved.replace("{id}", str(self.invoice_a.id))
        elif "/complaints/{id}" in resolved:
            resolved = resolved.replace("{id}", str(self.complaint_a.id))
        elif "/leaves/{id}" in resolved:
            resolved = resolved.replace("{id}", str(self.leave_a.id))
        elif "/visitors/{id}" in resolved:
            resolved = resolved.replace("{id}", str(self.visitor_a.id))
        elif "/meals/opt-outs/{id}" in resolved:
            resolved = resolved.replace("{id}", str(self.opt_out_a.id))
        elif "/notices/{id}" in resolved:
            resolved = resolved.replace("{id}", str(self.notice_a.id))
        elif "/users/{id}" in resolved:
            resolved = resolved.replace("{id}", str(self.student_self_user.id))
        else:
            resolved = resolved.replace("{id}", str(uuid4()))

        return resolved

    def get_probe_body(self, method: str, path: str) -> dict[str, Any] | None:
        """Return valid dummy schema payload for POST/PUT/PATCH routes."""
        if method not in ("POST", "PUT", "PATCH"):
            return None

        today = date.today()

        if "/menu" in path and method == "PUT":
            return {"entries": []}
        if "/rooms" in path and method == "POST":
            return {
                "number": "999",
                "floor": 1,
                "room_type": "single",
                "capacity": 1,
                "monthly_rent": "100.00",
            }
        if "/rooms" in path and method == "PATCH":
            return {"capacity": 1}
        if "/payments" in path:
            return {"amount": "100.00", "method": "cash"}
        if "/assign" in path:
            return {"assigned_to": str(self.admin_user.id)}
        if "/status" in path:
            return {"status": "in_progress"}
        if "/comments" in path:
            return {"body": "Test comment body"}
        if "/notices" in path and method == "PATCH":
            return {"title": "Updated Notice Title"}
        if "/notices" in path and method == "POST" and not path.endswith("/read"):
            return {
                "title": "Probe Notice Title",
                "body": "Probe Notice Content",
                "audience": "all",
            }
        if "/complaints" in path and method == "POST":
            return {
                "title": "Tap Leak",
                "description": "Leak in bathroom tap",
                "category": "plumbing",
                "priority": "low",
            }
        if (
            "/leaves" in path
            and method == "POST"
            and not any(p in path for p in ("/approve", "/reject", "/cancel"))
        ):
            return {
                "from_date": str(today + timedelta(days=20)),
                "to_date": str(today + timedelta(days=22)),
                "reason": "Family gathering",
            }
        if "/visitors" in path and method == "POST" and not path.endswith("/check-out"):
            return {"name": "Test Visitor", "phone": "+1999999999", "relation": "Father"}
        if "/users" in path and method == "POST":
            return {
                "email": "probe_user@hostel.example.com",
                "full_name": "Probe User",
                "role": "student",
                "password": "PassWord123!",
            }
        if "/users" in path and method == "PATCH":
            return {"full_name": "Updated Name"}
        if "/hostels" in path and method == "POST":
            return {"name": "New Probe Hostel", "code": "HPROBE", "gender_type": "male"}
        if "/hostels" in path and method == "PATCH":
            return {"name": "Updated Hostel Name"}
        if "/blocks" in path and method == "POST":
            return {"name": "New Block Probe"}
        if "/blocks" in path and method == "PATCH":
            return {"name": "Updated Block Name"}
        if "/wardens" in path and method == "POST":
            return {"user_id": str(self.warden_own.id)}
        if "/students" in path and method == "POST":
            return {
                "email": "probe_st@hostel.example.com",
                "full_name": "Probe Student",
                "student_no": "ST-PROBE-01",
                "gender": "male",
                "department": "Engineering",
                "year": 1,
                "guardian_name": "Guardian Name",
                "guardian_phone": "+1234567890",
                "emergency_contact": "+1234567891",
            }
        if "/students" in path and method == "PATCH":
            return {"department": "Updated Department"}
        if (
            "/allocations" in path
            and method == "POST"
            and not any(p in path for p in ("/vacate", "/transfer", "/cancel"))
        ):
            return {
                "student_id": str(self.student_self_profile.id),
                "room_id": str(self.room_a.id),
                "start_date": str(today),
            }
        if "/allocations" in path and path.endswith("/vacate"):
            return {"end_date": str(today), "reason": "Graduated"}
        if "/allocations" in path and path.endswith("/transfer"):
            return {"new_room_id": str(self.room_a.id)}
        if "/allocations" in path and path.endswith("/cancel"):
            return {"reason": "Cancelled by admin"}
        if "/fee-structures" in path and method == "POST":
            return {
                "hostel_id": str(self.hostel_a.id),
                "room_type": "single",
                "period": "monthly",
                "amount": "2000.00",
            }
        if "/fee-structures" in path and method == "PATCH":
            return {"amount": "2500.00"}
        if "/invoices/generate" in path:
            return {
                "hostel_id": str(self.hostel_a.id),
                "period_start": str(today),
                "period_end": str(today + timedelta(days=30)),
                "due_date": str(today + timedelta(days=15)),
            }

        return {}


@pytest.fixture
async def matrix_env() -> AsyncGenerator[tuple[AsyncClient, MatrixDataset, FastAPI], None]:
    """Create isolated SQLite in-memory database populated with matrix dataset."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    app = create_app()

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db

    now = datetime.now(UTC)
    today = date.today()

    async with session_factory() as session:
        # 1. Admin
        admin = User(
            id=uuid4(),
            email="matrix_admin@hostel.example.com",
            full_name="Matrix Admin",
            hashed_password=hash_password("AdminPass123"),
            role=UserRole.ADMIN,
            is_active=True,
        )
        session.add(admin)

        # 2. Hostels
        h_a = Hostel(
            id=uuid4(),
            name="Matrix Hostel Alpha",
            code="MH-A",
            gender_type=GenderType.MALE,
        )
        h_b = Hostel(
            id=uuid4(),
            name="Matrix Hostel Beta",
            code="MH-B",
            gender_type=GenderType.MALE,
        )
        session.add_all([h_a, h_b])

        # 3. Wardens
        w_a = User(
            id=uuid4(),
            email="warden_a@hostel.example.com",
            full_name="Warden Alpha",
            hashed_password=hash_password("WardenPass123"),
            role=UserRole.WARDEN,
            is_active=True,
        )
        w_b = User(
            id=uuid4(),
            email="warden_b@hostel.example.com",
            full_name="Warden Beta",
            hashed_password=hash_password("WardenPass123"),
            role=UserRole.WARDEN,
            is_active=True,
        )
        session.add_all([w_a, w_b])
        await session.flush()

        assign_a = WardenAssignment(id=uuid4(), user_id=w_a.id, hostel_id=h_a.id)
        assign_b = WardenAssignment(id=uuid4(), user_id=w_b.id, hostel_id=h_b.id)
        session.add_all([assign_a, assign_b])

        # 4. Blocks, Rooms, Beds
        b_a = Block(id=uuid4(), hostel_id=h_a.id, name="Block Alpha")
        b_b = Block(id=uuid4(), hostel_id=h_b.id, name="Block Beta")
        session.add_all([b_a, b_b])
        await session.flush()

        r_a = Room(
            id=uuid4(),
            block_id=b_a.id,
            number="101",
            floor=1,
            room_type=RoomType.DOUBLE,
            capacity=2,
            monthly_rent=Decimal("1500.00"),
            status=RoomStatus.AVAILABLE,
        )
        r_b = Room(
            id=uuid4(),
            block_id=b_b.id,
            number="201",
            floor=2,
            room_type=RoomType.DOUBLE,
            capacity=2,
            monthly_rent=Decimal("1500.00"),
            status=RoomStatus.AVAILABLE,
        )
        session.add_all([r_a, r_b])
        await session.flush()

        bed_a = Bed(id=uuid4(), room_id=r_a.id, label="A", is_occupied=True)
        bed_b = Bed(id=uuid4(), room_id=r_b.id, label="A", is_occupied=True)
        session.add_all([bed_a, bed_b])
        await session.flush()

        # 5. Students
        u_s_a = User(
            id=uuid4(),
            email="student_a@hostel.example.com",
            full_name="Student Alpha",
            hashed_password=hash_password("StudentPass123"),
            role=UserRole.STUDENT,
            is_active=True,
        )
        u_s_b = User(
            id=uuid4(),
            email="student_b@hostel.example.com",
            full_name="Student Beta",
            hashed_password=hash_password("StudentPass123"),
            role=UserRole.STUDENT,
            is_active=True,
        )
        session.add_all([u_s_a, u_s_b])
        await session.flush()

        sp_a = StudentProfile(
            id=uuid4(),
            user_id=u_s_a.id,
            student_no="ST-ALPHA-01",
            gender=GenderType.MALE,
            department="Computer Science",
            year=2,
            guardian_name="Guardian Alpha",
            guardian_phone="+1111111111",
            emergency_contact="+1111111112",
        )
        sp_b = StudentProfile(
            id=uuid4(),
            user_id=u_s_b.id,
            student_no="ST-BETA-02",
            gender=GenderType.MALE,
            department="Electrical Engineering",
            year=2,
            guardian_name="Guardian Beta",
            guardian_phone="+2222222221",
            emergency_contact="+2222222222",
        )
        session.add_all([sp_a, sp_b])
        await session.flush()

        # Allocations
        alloc_a = Allocation(
            id=uuid4(),
            student_id=sp_a.id,
            bed_id=bed_a.id,
            start_date=today - timedelta(days=10),
            status=AllocationStatus.ACTIVE,
        )
        alloc_b = Allocation(
            id=uuid4(),
            student_id=sp_b.id,
            bed_id=bed_b.id,
            start_date=today - timedelta(days=10),
            status=AllocationStatus.ACTIVE,
        )
        session.add_all([alloc_a, alloc_b])
        await session.flush()

        # Fee & Invoices
        fs_a = FeeStructure(
            id=uuid4(),
            hostel_id=h_a.id,
            room_type=RoomType.DOUBLE,
            period=FeePeriod.MONTHLY,
            amount=Decimal("1500.00"),
        )
        session.add(fs_a)
        await session.flush()

        inv_a = Invoice(
            id=uuid4(),
            student_id=sp_a.id,
            allocation_id=alloc_a.id,
            period_start=today,
            period_end=today + timedelta(days=30),
            amount=Decimal("1500.00"),
            paid_amount=Decimal("0.00"),
            due_date=today + timedelta(days=15),
            status=InvoiceStatus.UNPAID,
        )
        session.add(inv_a)

        # Complaints
        c_a = Complaint(
            id=uuid4(),
            student_id=sp_a.id,
            room_id=r_a.id,
            title="Desk light broken",
            description="The study desk light fixture is not turning on.",
            category=ComplaintCategory.ELECTRICAL,
            priority=ComplaintPriority.LOW,
            status=ComplaintStatus.OPEN,
        )
        session.add(c_a)

        # Leaves
        l_a = LeaveRequest(
            id=uuid4(),
            student_id=sp_a.id,
            from_date=today + timedelta(days=5),
            to_date=today + timedelta(days=7),
            reason="Visiting family for wedding",
            status=LeaveStatus.PENDING,
        )
        session.add(l_a)

        # Visitors
        v_a = Visitor(
            id=uuid4(),
            student_id=sp_a.id,
            name="Mr. Alpha Senior",
            phone="+1234567890",
            relation="Father",
            check_in_at=now,
        )
        session.add(v_a)

        # Opt-outs
        opt_a = MealOptOut(
            id=uuid4(),
            student_id=sp_a.id,
            date=today + timedelta(days=3),
            meal_type=MealType.DINNER,
        )
        session.add(opt_a)

        # Notices
        n_a = Notice(
            id=uuid4(),
            hostel_id=h_a.id,
            title="Hostel Alpha Pinned Notice",
            body="Important curfew guidelines for residents.",
            audience=NoticeAudience.ALL,
            is_pinned=True,
            published_at=now,
            created_by_id=admin.id,
        )
        session.add(n_a)

        await session.commit()

    tokens = {
        "admin": create_access_token(user_id=admin.id, role="admin"),
        "warden-own": create_access_token(user_id=w_a.id, role="warden"),
        "warden-other": create_access_token(user_id=w_b.id, role="warden"),
        "student-self": create_access_token(user_id=u_s_a.id, role="student"),
        "student-other": create_access_token(user_id=u_s_b.id, role="student"),
    }

    dataset = MatrixDataset(
        admin_user=admin,
        warden_own=w_a,
        warden_other=w_b,
        student_self_user=u_s_a,
        student_other_user=u_s_b,
        hostel_a=h_a,
        block_a=b_a,
        room_a=r_a,
        bed_a=bed_a,
        student_self_profile=sp_a,
        allocation_a=alloc_a,
        fee_structure_a=fs_a,
        invoice_a=inv_a,
        complaint_a=c_a,
        leave_a=l_a,
        visitor_a=v_a,
        opt_out_a=opt_a,
        notice_a=n_a,
        hostel_b=h_b,
        block_b=b_b,
        room_b=r_b,
        bed_b=bed_b,
        student_other_profile=sp_b,
        allocation_b=alloc_b,
        tokens=tokens,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, dataset, app

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


PUBLIC_PATHS = {
    "/api/v1/health",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    # logout is stateless-friendly: accepts optional token, returns 200 with no creds
    "/api/v1/auth/logout",
}

STUDENT_ONLY_PREFIXES = (
    "/api/v1/students/me",
    "/api/v1/meals/opt-outs",
)


@pytest.mark.asyncio
async def test_permission_matrix_introspection(
    matrix_env: tuple[AsyncClient, MatrixDataset, FastAPI],
) -> None:
    """Verify that all FastAPI endpoints are dynamically introspected from app.routes."""
    _, _, app = matrix_env
    discovered = get_all_api_routes(app)

    assert len(discovered) >= 108, f"Expected at least 108 route methods, found {len(discovered)}"

    methods = {m for m, _, _ in discovered}
    assert methods == {"GET", "POST", "PUT", "PATCH", "DELETE"}

    all_paths = {p for _, p, _ in discovered}
    assert "/api/v1/health" in all_paths
    assert "/api/v1/auth/login" in all_paths
    assert "/api/v1/users" in all_paths
    assert "/api/v1/hostels" in all_paths
    assert "/api/v1/rooms/{id}" in all_paths
    assert "/api/v1/allocations" in all_paths
    assert "/api/v1/invoices" in all_paths
    assert "/api/v1/complaints" in all_paths
    assert "/api/v1/attendance" in all_paths
    assert "/api/v1/leaves" in all_paths
    assert "/api/v1/visitors" in all_paths
    assert "/api/v1/dashboard/summary" in all_paths
    assert "/api/v1/audit-logs" in all_paths


@pytest.mark.asyncio
async def test_permission_matrix_anonymous_role(
    matrix_env: tuple[AsyncClient, MatrixDataset, FastAPI],
) -> None:
    """Verify anonymous access against every introspected route.

    Protected endpoints must strictly return 401 Unauthorized.
    Public endpoints (/health, /auth/login, /auth/refresh) must permit request (status != 401).
    """
    client, dataset, app = matrix_env
    discovered = get_all_api_routes(app)

    violations = []
    for method, path_tmpl, _ in discovered:
        resolved_path = dataset.resolve_path(path_tmpl)
        body = dataset.get_probe_body(method, resolved_path)
        resp = await client.request(method, resolved_path, json=body)

        if resolved_path in PUBLIC_PATHS:
            if resp.status_code == 401:
                violations.append(f"Public route {method} {resolved_path} rejected with 401")
        else:
            if resp.status_code != 401:
                violations.append(
                    f"Protected route {method} {resolved_path} returned {resp.status_code} "
                    f"instead of 401"
                )

    assert not violations, "\n".join(violations)


@pytest.mark.asyncio
async def test_permission_matrix_admin_role(
    matrix_env: tuple[AsyncClient, MatrixDataset, FastAPI],
) -> None:
    """Verify superuser admin access across all routes.

    Admin must NEVER receive 401 Unauthorized.
    Admin is permitted on all administrative, operational, reporting, and shared endpoints.
    Only student self-service routes (/students/me/*) return 403 as designed.
    """
    client, dataset, app = matrix_env
    discovered = get_all_api_routes(app)
    admin_headers = {"Authorization": f"Bearer {dataset.tokens['admin']}"}

    violations = []
    for method, path_tmpl, _ in discovered:
        resolved_path = dataset.resolve_path(path_tmpl)
        body = dataset.get_probe_body(method, resolved_path)
        resp = await client.request(method, resolved_path, headers=admin_headers, json=body)

        # Admin must never be unauthenticated
        if resp.status_code == 401:
            violations.append(f"Admin received 401 on {method} {resolved_path}")

        # Check permission rules
        is_student_self = any(resolved_path.startswith(pfx) for pfx in STUDENT_ONLY_PREFIXES)
        is_complaint_create = method == "POST" and resolved_path == "/api/v1/complaints"

        if is_student_self or is_complaint_create:
            # Student-only self service requires STUDENT role
            if resp.status_code != 403:
                violations.append(
                    f"Admin expected 403 on student-only route {method} {resolved_path}, "
                    f"got {resp.status_code}"
                )
        else:
            # On all other routes, admin must be permitted (not 403)
            if resp.status_code == 403:
                violations.append(
                    f"Admin unexpectedly received 403 Forbidden on {method} {resolved_path}: "
                    f"{resp.text}"
                )

    assert not violations, "\n".join(violations)


@pytest.mark.asyncio
async def test_permission_matrix_warden_own_role(
    matrix_env: tuple[AsyncClient, MatrixDataset, FastAPI],
) -> None:
    """Verify warden-own access on assigned hostel resources vs admin-only endpoints.

    Permitted on:
    - Hostel A blocks, rooms, allocations, attendance, complaints, leaves, visitors, reports.
    Forbidden (403) on:
    - Admin-only routes (/users*, /hostels POST/PATCH/DELETE, /fee-structures, /audit-logs).
    - Student-only self service routes (/students/me/*).
    """
    client, dataset, _ = matrix_env
    warden_headers = {"Authorization": f"Bearer {dataset.tokens['warden-own']}"}

    # 1. Permitted operational routes for assigned hostel
    permitted_probes = [
        ("GET", f"/api/v1/hostels/{dataset.hostel_a.id}/blocks"),
        ("GET", f"/api/v1/hostels/{dataset.hostel_a.id}/wardens"),
        ("GET", f"/api/v1/blocks/{dataset.block_a.id}"),
        ("GET", f"/api/v1/blocks/{dataset.block_a.id}/rooms"),
        ("GET", f"/api/v1/rooms/{dataset.room_a.id}"),
        ("GET", f"/api/v1/rooms/{dataset.room_a.id}/beds"),
        ("GET", f"/api/v1/rooms/{dataset.room_a.id}/occupants"),
        ("GET", f"/api/v1/students/{dataset.student_self_profile.id}"),
        ("GET", f"/api/v1/allocations/{dataset.allocation_a.id}"),
        ("GET", f"/api/v1/invoices/{dataset.invoice_a.id}"),
        ("GET", f"/api/v1/complaints/{dataset.complaint_a.id}"),
        ("GET", f"/api/v1/leaves/{dataset.leave_a.id}"),
        ("GET", f"/api/v1/visitors/{dataset.visitor_a.id}"),
        ("GET", f"/api/v1/hostels/{dataset.hostel_a.id}/menu"),
        ("GET", f"/api/v1/notices/{dataset.notice_a.id}"),
        ("GET", "/api/v1/dashboard/summary"),
        ("GET", "/api/v1/reports/occupancy"),
        ("GET", "/api/v1/reports/revenue"),
        ("GET", "/api/v1/reports/defaulters"),
        ("GET", "/api/v1/reports/complaints"),
        ("GET", "/api/v1/reports/attendance"),
    ]

    for method, path in permitted_probes:
        body = dataset.get_probe_body(method, path)
        resp = await client.request(method, path, headers=warden_headers, json=body)
        assert resp.status_code not in (401, 403), (
            f"Warden-own failed authorization on {method} {path}: "
            f"code={resp.status_code}, body={resp.text}"
        )

    # 2. Admin-only endpoints must return 403
    forbidden_admin_probes = [
        ("POST", "/api/v1/users"),
        ("GET", "/api/v1/users"),
        ("GET", f"/api/v1/users/{dataset.admin_user.id}"),
        ("PATCH", f"/api/v1/users/{dataset.admin_user.id}"),
        ("POST", f"/api/v1/users/{dataset.admin_user.id}/deactivate"),
        ("POST", "/api/v1/hostels"),
        ("PATCH", f"/api/v1/hostels/{dataset.hostel_a.id}"),
        ("DELETE", f"/api/v1/hostels/{dataset.hostel_a.id}"),
        ("POST", f"/api/v1/hostels/{dataset.hostel_a.id}/wardens"),
        ("DELETE", f"/api/v1/hostels/{dataset.hostel_a.id}/wardens/{dataset.warden_own.id}"),
        ("PATCH", f"/api/v1/blocks/{dataset.block_a.id}"),
        ("DELETE", f"/api/v1/blocks/{dataset.block_a.id}"),
        ("POST", "/api/v1/fee-structures"),
        ("PATCH", f"/api/v1/fee-structures/{dataset.fee_structure_a.id}"),
        ("DELETE", f"/api/v1/fee-structures/{dataset.fee_structure_a.id}"),
        ("POST", "/api/v1/invoices/mark-overdue"),
        ("DELETE", f"/api/v1/invoices/{dataset.invoice_a.id}"),
        ("POST", f"/api/v1/invoices/{dataset.invoice_a.id}/void"),
        ("GET", "/api/v1/audit-logs"),
    ]

    for method, path in forbidden_admin_probes:
        body = dataset.get_probe_body(method, path)
        resp = await client.request(method, path, headers=warden_headers, json=body)
        assert resp.status_code == 403, (
            f"Warden-own expected 403 on admin-only {method} {path}, got {resp.status_code}"
        )

    # 3. Student-only endpoints must return 403
    student_only_probes = [
        ("GET", "/api/v1/students/me"),
        ("PATCH", "/api/v1/students/me"),
        ("GET", "/api/v1/students/me/dashboard"),
        ("GET", "/api/v1/students/me/allocation"),
        ("GET", "/api/v1/students/me/invoices"),
        ("GET", "/api/v1/students/me/balance"),
        ("GET", "/api/v1/students/me/attendance"),
        ("GET", "/api/v1/students/me/leaves"),
        ("GET", "/api/v1/students/me/visitors"),
        ("GET", "/api/v1/students/me/menu/today"),
        ("POST", "/api/v1/meals/opt-outs"),
        ("DELETE", f"/api/v1/meals/opt-outs/{dataset.opt_out_a.id}"),
        ("GET", "/api/v1/students/me/opt-outs"),
        ("POST", "/api/v1/complaints"),
    ]

    for method, path in student_only_probes:
        body = dataset.get_probe_body(method, path)
        resp = await client.request(method, path, headers=warden_headers, json=body)
        assert resp.status_code == 403, (
            f"Warden-own expected 403 on student-only {method} {path}, got {resp.status_code}"
        )


@pytest.mark.asyncio
async def test_permission_matrix_warden_other_role(
    matrix_env: tuple[AsyncClient, MatrixDataset, FastAPI],
) -> None:
    """Verify warden-other (assigned to Hostel B) receives 403 on Hostel A resources."""
    client, dataset, _ = matrix_env
    warden_other_headers = {"Authorization": f"Bearer {dataset.tokens['warden-other']}"}

    scoped_hostel_a_probes = [
        ("GET", f"/api/v1/hostels/{dataset.hostel_a.id}/blocks"),
        ("GET", f"/api/v1/hostels/{dataset.hostel_a.id}/wardens"),
        ("POST", f"/api/v1/hostels/{dataset.hostel_a.id}/blocks"),
        ("PUT", f"/api/v1/hostels/{dataset.hostel_a.id}/menu"),
        ("GET", f"/api/v1/blocks/{dataset.block_a.id}"),
        ("GET", f"/api/v1/blocks/{dataset.block_a.id}/rooms"),
        ("POST", f"/api/v1/blocks/{dataset.block_a.id}/rooms"),
        ("GET", f"/api/v1/rooms/{dataset.room_a.id}"),
        ("PATCH", f"/api/v1/rooms/{dataset.room_a.id}"),
        ("DELETE", f"/api/v1/rooms/{dataset.room_a.id}"),
        ("POST", f"/api/v1/rooms/{dataset.room_a.id}/maintenance"),
        ("POST", f"/api/v1/rooms/{dataset.room_a.id}/available"),
        ("GET", f"/api/v1/rooms/{dataset.room_a.id}/beds"),
        ("GET", f"/api/v1/rooms/{dataset.room_a.id}/occupants"),
        ("GET", f"/api/v1/students/{dataset.student_self_profile.id}"),
        ("PATCH", f"/api/v1/students/{dataset.student_self_profile.id}"),
        ("DELETE", f"/api/v1/students/{dataset.student_self_profile.id}"),
        ("GET", f"/api/v1/allocations/{dataset.allocation_a.id}"),
        ("POST", f"/api/v1/allocations/{dataset.allocation_a.id}/vacate"),
        ("POST", f"/api/v1/allocations/{dataset.allocation_a.id}/transfer"),
        ("POST", f"/api/v1/allocations/{dataset.allocation_a.id}/cancel"),
        ("GET", f"/api/v1/invoices/{dataset.invoice_a.id}"),
        ("POST", f"/api/v1/invoices/{dataset.invoice_a.id}/payments"),
        ("GET", f"/api/v1/students/{dataset.student_self_profile.id}/balance"),
        ("GET", f"/api/v1/complaints/{dataset.complaint_a.id}"),
        ("POST", f"/api/v1/complaints/{dataset.complaint_a.id}/assign"),
        ("POST", f"/api/v1/complaints/{dataset.complaint_a.id}/status"),
        ("POST", f"/api/v1/complaints/{dataset.complaint_a.id}/comments"),
        ("GET", f"/api/v1/leaves/{dataset.leave_a.id}"),
        ("POST", f"/api/v1/leaves/{dataset.leave_a.id}/approve"),
        ("POST", f"/api/v1/leaves/{dataset.leave_a.id}/reject"),
        ("GET", f"/api/v1/visitors/{dataset.visitor_a.id}"),
        ("POST", f"/api/v1/visitors/{dataset.visitor_a.id}/check-out"),
        ("PATCH", f"/api/v1/notices/{dataset.notice_a.id}"),
        ("DELETE", f"/api/v1/notices/{dataset.notice_a.id}"),
    ]

    violations = []
    for method, path in scoped_hostel_a_probes:
        body = dataset.get_probe_body(method, path)
        resp = await client.request(method, path, headers=warden_other_headers, json=body)
        if resp.status_code != 403:
            violations.append(
                f"Warden-other accessed Hostel A resource {method} {path} with status "
                f"{resp.status_code} instead of 403 Forbidden"
            )

    assert not violations, "\n".join(violations)


@pytest.mark.asyncio
async def test_permission_matrix_student_self_role(
    matrix_env: tuple[AsyncClient, MatrixDataset, FastAPI],
) -> None:
    """Verify student-self access on self-service endpoints vs forbidden admin/warden routes."""
    client, dataset, _ = matrix_env
    student_self_headers = {"Authorization": f"Bearer {dataset.tokens['student-self']}"}

    # 1. Permitted self endpoints and own resources
    permitted_self_probes = [
        ("GET", "/api/v1/auth/me"),
        ("POST", "/api/v1/auth/change-password"),
        ("GET", "/api/v1/students/me"),
        ("PATCH", "/api/v1/students/me"),
        ("GET", "/api/v1/students/me/dashboard"),
        ("GET", "/api/v1/students/me/allocation"),
        ("GET", "/api/v1/students/me/invoices"),
        ("GET", "/api/v1/students/me/balance"),
        ("GET", "/api/v1/students/me/attendance"),
        ("GET", "/api/v1/students/me/leaves"),
        ("GET", "/api/v1/students/me/visitors"),
        ("GET", "/api/v1/students/me/menu/today"),
        ("GET", "/api/v1/students/me/opt-outs"),
        ("DELETE", f"/api/v1/meals/opt-outs/{dataset.opt_out_a.id}"),
        ("GET", f"/api/v1/students/{dataset.student_self_profile.id}"),
        ("GET", f"/api/v1/allocations/{dataset.allocation_a.id}"),
        ("GET", f"/api/v1/invoices/{dataset.invoice_a.id}"),
        ("GET", f"/api/v1/complaints/{dataset.complaint_a.id}"),
        ("GET", f"/api/v1/leaves/{dataset.leave_a.id}"),
        ("POST", f"/api/v1/leaves/{dataset.leave_a.id}/cancel"),
        ("GET", f"/api/v1/visitors/{dataset.visitor_a.id}"),
        ("GET", "/api/v1/hostels"),
        ("GET", f"/api/v1/hostels/{dataset.hostel_a.id}"),
        ("GET", f"/api/v1/hostels/{dataset.hostel_a.id}/menu"),
        ("GET", "/api/v1/rooms/available"),
        ("GET", "/api/v1/fee-structures"),
        ("GET", f"/api/v1/fee-structures/{dataset.fee_structure_a.id}"),
        ("GET", "/api/v1/notices"),
        ("GET", "/api/v1/notices/unread-count"),
        ("GET", f"/api/v1/notices/{dataset.notice_a.id}"),
        ("POST", f"/api/v1/notices/{dataset.notice_a.id}/read"),
    ]

    for method, path in permitted_self_probes:
        body = dataset.get_probe_body(method, path)
        resp = await client.request(method, path, headers=student_self_headers, json=body)
        assert resp.status_code not in (401, 403), (
            f"Student-self failed authorization on {method} {path}: "
            f"status={resp.status_code}, body={resp.text}"
        )

    # 2. Forbidden admin and warden management endpoints
    forbidden_probes = [
        ("POST", "/api/v1/users"),
        ("GET", "/api/v1/users"),
        ("GET", f"/api/v1/users/{dataset.admin_user.id}"),
        ("PATCH", f"/api/v1/users/{dataset.admin_user.id}"),
        ("POST", f"/api/v1/users/{dataset.admin_user.id}/deactivate"),
        ("POST", "/api/v1/hostels"),
        ("PATCH", f"/api/v1/hostels/{dataset.hostel_a.id}"),
        ("DELETE", f"/api/v1/hostels/{dataset.hostel_a.id}"),
        ("POST", f"/api/v1/hostels/{dataset.hostel_a.id}/blocks"),
        ("GET", f"/api/v1/hostels/{dataset.hostel_a.id}/blocks"),
        ("POST", f"/api/v1/hostels/{dataset.hostel_a.id}/wardens"),
        ("DELETE", f"/api/v1/hostels/{dataset.hostel_a.id}/wardens/{dataset.warden_own.id}"),
        ("GET", f"/api/v1/hostels/{dataset.hostel_a.id}/wardens"),
        ("PUT", f"/api/v1/hostels/{dataset.hostel_a.id}/menu"),
        ("GET", f"/api/v1/blocks/{dataset.block_a.id}"),
        ("PATCH", f"/api/v1/blocks/{dataset.block_a.id}"),
        ("DELETE", f"/api/v1/blocks/{dataset.block_a.id}"),
        ("POST", f"/api/v1/blocks/{dataset.block_a.id}/rooms"),
        ("GET", f"/api/v1/blocks/{dataset.block_a.id}/rooms"),
        ("GET", f"/api/v1/rooms/{dataset.room_a.id}"),
        ("PATCH", f"/api/v1/rooms/{dataset.room_a.id}"),
        ("DELETE", f"/api/v1/rooms/{dataset.room_a.id}"),
        ("POST", f"/api/v1/rooms/{dataset.room_a.id}/maintenance"),
        ("POST", f"/api/v1/rooms/{dataset.room_a.id}/available"),
        ("GET", f"/api/v1/rooms/{dataset.room_a.id}/beds"),
        ("GET", f"/api/v1/rooms/{dataset.room_a.id}/occupants"),
        ("POST", "/api/v1/students"),
        ("GET", "/api/v1/students"),
        ("PATCH", f"/api/v1/students/{dataset.student_self_profile.id}"),
        ("DELETE", f"/api/v1/students/{dataset.student_self_profile.id}"),
        ("POST", "/api/v1/allocations"),
        ("GET", "/api/v1/allocations"),
        ("POST", f"/api/v1/allocations/{dataset.allocation_a.id}/vacate"),
        ("POST", f"/api/v1/allocations/{dataset.allocation_a.id}/transfer"),
        ("POST", f"/api/v1/allocations/{dataset.allocation_a.id}/cancel"),
        ("POST", "/api/v1/fee-structures"),
        ("PATCH", f"/api/v1/fee-structures/{dataset.fee_structure_a.id}"),
        ("DELETE", f"/api/v1/fee-structures/{dataset.fee_structure_a.id}"),
        ("POST", "/api/v1/invoices/generate"),
        ("POST", "/api/v1/invoices/mark-overdue"),
        ("GET", "/api/v1/invoices"),
        ("DELETE", f"/api/v1/invoices/{dataset.invoice_a.id}"),
        ("POST", f"/api/v1/invoices/{dataset.invoice_a.id}/void"),
        ("GET", "/api/v1/payments"),
        ("GET", f"/api/v1/students/{dataset.student_self_profile.id}/balance"),
        ("POST", f"/api/v1/complaints/{dataset.complaint_a.id}/assign"),
        ("POST", "/api/v1/attendance/check-in"),
        ("POST", "/api/v1/attendance/check-out"),
        ("GET", "/api/v1/attendance/present"),
        ("GET", "/api/v1/attendance"),
        ("GET", "/api/v1/leaves"),
        ("POST", f"/api/v1/leaves/{dataset.leave_a.id}/approve"),
        ("POST", f"/api/v1/leaves/{dataset.leave_a.id}/reject"),
        ("POST", "/api/v1/visitors"),
        ("GET", "/api/v1/visitors"),
        ("POST", f"/api/v1/visitors/{dataset.visitor_a.id}/check-out"),
        ("GET", "/api/v1/meals/headcount"),
        ("POST", "/api/v1/notices"),
        ("PATCH", f"/api/v1/notices/{dataset.notice_a.id}"),
        ("DELETE", f"/api/v1/notices/{dataset.notice_a.id}"),
        ("GET", "/api/v1/dashboard/summary"),
        ("GET", "/api/v1/reports/occupancy"),
        ("GET", "/api/v1/reports/revenue"),
        ("GET", "/api/v1/reports/defaulters"),
        ("GET", "/api/v1/reports/complaints"),
        ("GET", "/api/v1/reports/attendance"),
        ("GET", "/api/v1/audit-logs"),
    ]

    violations = []
    for method, path in forbidden_probes:
        body = dataset.get_probe_body(method, path)
        resp = await client.request(method, path, headers=student_self_headers, json=body)
        if resp.status_code != 403:
            violations.append(
                f"Student-self accessed forbidden {method} {path} with status {resp.status_code}"
            )

    assert not violations, "\n".join(violations)


@pytest.mark.asyncio
async def test_permission_matrix_student_other_role(
    matrix_env: tuple[AsyncClient, MatrixDataset, FastAPI],
) -> None:
    """Verify student-other (Student B) receives 403 when accessing Student A's data."""
    client, dataset, _ = matrix_env
    student_other_headers = {"Authorization": f"Bearer {dataset.tokens['student-other']}"}

    student_a_private_data_probes = [
        ("GET", f"/api/v1/students/{dataset.student_self_profile.id}"),
        ("PATCH", f"/api/v1/students/{dataset.student_self_profile.id}"),
        ("DELETE", f"/api/v1/students/{dataset.student_self_profile.id}"),
        ("GET", f"/api/v1/allocations/{dataset.allocation_a.id}"),
        ("GET", f"/api/v1/invoices/{dataset.invoice_a.id}"),
        ("POST", f"/api/v1/invoices/{dataset.invoice_a.id}/payments"),
        ("GET", f"/api/v1/students/{dataset.student_self_profile.id}/balance"),
        ("GET", f"/api/v1/complaints/{dataset.complaint_a.id}"),
        ("POST", f"/api/v1/complaints/{dataset.complaint_a.id}/comments"),
        ("GET", f"/api/v1/leaves/{dataset.leave_a.id}"),
        ("POST", f"/api/v1/leaves/{dataset.leave_a.id}/cancel"),
        ("GET", f"/api/v1/visitors/{dataset.visitor_a.id}"),
        ("DELETE", f"/api/v1/meals/opt-outs/{dataset.opt_out_a.id}"),
        ("GET", f"/api/v1/hostels/{dataset.hostel_a.id}/menu"),
    ]

    violations = []
    for method, path in student_a_private_data_probes:
        body = dataset.get_probe_body(method, path)
        resp = await client.request(method, path, headers=student_other_headers, json=body)
        if resp.status_code != 403:
            violations.append(
                f"Student-other accessed Student A's private data {method} {path} "
                f"with status {resp.status_code} instead of 403 Forbidden"
            )

    assert not violations, "\n".join(violations)


@pytest.mark.asyncio
async def test_permission_matrix_comprehensive_summary(
    matrix_env: tuple[AsyncClient, MatrixDataset, FastAPI],
) -> None:
    """Verify full permission matrix coverage over all 108 route endpoints."""
    _, _, app = matrix_env
    discovered = get_all_api_routes(app)

    assert len(discovered) >= 108

    # Ensure all routers are present
    route_paths = [path for _, path, _ in discovered]
    prefixes = [
        "/api/v1/health",
        "/api/v1/auth",
        "/api/v1/users",
        "/api/v1/hostels",
        "/api/v1/blocks",
        "/api/v1/rooms",
        "/api/v1/students",
        "/api/v1/allocations",
        "/api/v1/fee-structures",
        "/api/v1/invoices",
        "/api/v1/payments",
        "/api/v1/complaints",
        "/api/v1/attendance",
        "/api/v1/leaves",
        "/api/v1/visitors",
        "/api/v1/meals",
        "/api/v1/notices",
        "/api/v1/dashboard",
        "/api/v1/reports",
        "/api/v1/audit-logs",
    ]

    for pfx in prefixes:
        matching = [p for p in route_paths if p.startswith(pfx)]
        assert matching, f"Missing routes for expected module prefix {pfx}"
