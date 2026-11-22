"""Integration tests for Notices REST API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models.allocation import Allocation, AllocationStatus
from app.models.hostel import Block, GenderType, Hostel, WardenAssignment
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User


@pytest.fixture
async def setup_hostels_and_users(
    test_engine: AsyncEngine,
    admin_user: User,
    warden_user: User,
    student_user: User,
) -> tuple[Hostel, Hostel]:
    """Setup test hostels, student active allocation, and warden assignment."""
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        hostel1 = Hostel(
            id=uuid4(),
            name="Alpha Hostel",
            code="AH",
            gender_type=GenderType.MIXED,
            address="North Campus",
            total_capacity=100,
        )
        hostel2 = Hostel(
            id=uuid4(),
            name="Beta Hostel",
            code="BH",
            gender_type=GenderType.MIXED,
            address="South Campus",
            total_capacity=100,
        )
        session.add_all([hostel1, hostel2])
        await session.commit()

        # Assign warden to hostel1 only
        assignment = WardenAssignment(user_id=warden_user.id, hostel_id=hostel1.id)
        session.add(assignment)

        # Allocate student to hostel1
        block = Block(id=uuid4(), hostel_id=hostel1.id, name="Block 1", floor_count=1)
        room = Room(
            id=uuid4(),
            block_id=block.id,
            number="101",
            floor=1,
            room_type=RoomType.SINGLE,
            capacity=1,
            monthly_rent=Decimal("500.00"),
            status=RoomStatus.FULL,
        )
        bed = Bed(id=uuid4(), room_id=room.id, label="A", is_occupied=True)
        student_profile = StudentProfile(
            id=uuid4(),
            user_id=student_user.id,
            student_no="STU-NOTICE-01",
            gender=GenderType.MIXED,
            department="CS",
            year=1,
            guardian_name="Guardian",
            guardian_phone="999",
            emergency_contact="888",
        )
        alloc = Allocation(
            id=uuid4(),
            student_id=student_profile.id,
            bed_id=bed.id,
            start_date=datetime.now(UTC).date(),
            status=AllocationStatus.ACTIVE,
        )
        session.add_all([block, room, bed, student_profile, alloc])
        await session.commit()

        return hostel1, hostel2


async def test_notice_lifecycle_and_endpoints(
    client: AsyncClient,
    admin_headers: dict[str, str],
    warden_headers: dict[str, str],
    student_headers: dict[str, str],
    setup_hostels_and_users: tuple[Hostel, Hostel],
) -> None:
    """Test full notice CRUD, visibility, unread count, and read tracking."""
    hostel1, hostel2 = setup_hostels_and_users

    # 1. Admin creates global notice (201)
    res_global = await client.post(
        "/api/v1/notices",
        json={
            "title": "Global Notice for All",
            "body": "Welcome to the new academic year.",
            "audience": "all",
            "is_pinned": True,
        },
        headers=admin_headers,
    )
    assert res_global.status_code == 201
    global_id = res_global.json()["id"]
    assert res_global.json()["hostel_id"] is None
    assert res_global.json()["is_pinned"] is True

    # 2. Warden tries to create global notice -> 403 FORBIDDEN
    res_w_glob = await client.post(
        "/api/v1/notices",
        json={
            "title": "Warden Global",
            "body": "Not allowed.",
            "audience": "all",
        },
        headers=warden_headers,
    )
    assert res_w_glob.status_code == 403

    # 3. Warden tries to create notice in unassigned hostel2 -> 403 FORBIDDEN
    res_w_h2 = await client.post(
        "/api/v1/notices",
        json={
            "hostel_id": str(hostel2.id),
            "title": "Hostel 2 Notice",
            "body": "Warden not assigned here.",
        },
        headers=warden_headers,
    )
    assert res_w_h2.status_code == 403

    # 4. Warden creates notice in assigned hostel1 -> 201 CREATED
    res_w_h1 = await client.post(
        "/api/v1/notices",
        json={
            "hostel_id": str(hostel1.id),
            "title": "Hostel 1 Cleanliness Drive",
            "body": "Please keep your rooms clean.",
            "audience": "students",
        },
        headers=warden_headers,
    )
    assert res_w_h1.status_code == 201
    h1_notice_id = res_w_h1.json()["id"]

    # 5. Student tries to create notice -> 403 FORBIDDEN
    res_stu_post = await client.post(
        "/api/v1/notices",
        json={"title": "Student post", "body": "Body"},
        headers=student_headers,
    )
    assert res_stu_post.status_code == 403

    # 6. Invalid dates -> 400
    now = datetime.now(UTC)
    res_bad_date = await client.post(
        "/api/v1/notices",
        json={
            "title": "Bad Expiry",
            "body": "Body",
            "published_at": now.isoformat(),
            "expires_at": (now - timedelta(days=1)).isoformat(),
        },
        headers=admin_headers,
    )
    assert res_bad_date.status_code == 422 or res_bad_date.status_code == 400

    # 7. Check unread count for student
    res_unread = await client.get("/api/v1/notices/unread-count", headers=student_headers)
    assert res_unread.status_code == 200
    initial_unread = res_unread.json()["unread_count"]
    assert initial_unread >= 2

    # 8. List notices as student
    res_list = await client.get("/api/v1/notices", headers=student_headers)
    assert res_list.status_code == 200
    items = res_list.json()["items"]
    item_ids = [item["id"] for item in items]
    assert global_id in item_ids
    assert h1_notice_id in item_ids

    # 9. Mark global notice as read
    res_read = await client.post(f"/api/v1/notices/{global_id}/read", headers=student_headers)
    assert res_read.status_code == 200
    assert res_read.json()["is_read"] is True

    # 10. Check unread count decreased by 1
    res_unread_after = await client.get("/api/v1/notices/unread-count", headers=student_headers)
    assert res_unread_after.json()["unread_count"] == initial_unread - 1

    # 11. Patch notice
    res_patch = await client.patch(
        f"/api/v1/notices/{global_id}",
        json={"title": "Updated Global Notice"},
        headers=admin_headers,
    )
    assert res_patch.status_code == 200
    assert res_patch.json()["title"] == "Updated Global Notice"

    # 12. Delete notice
    res_del = await client.delete(f"/api/v1/notices/{h1_notice_id}", headers=warden_headers)
    assert res_del.status_code == 204

    # Get deleted notice -> 404
    res_get_del = await client.get(f"/api/v1/notices/{h1_notice_id}", headers=admin_headers)
    assert res_get_del.status_code == 404
