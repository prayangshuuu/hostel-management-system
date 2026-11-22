"""Unit tests for NoticeService business logic and permission enforcement."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleError, ForbiddenError, NotFoundError
from app.models.hostel import GenderType, Hostel, WardenAssignment
from app.models.notice import NoticeAudience
from app.models.user import User, UserRole
from app.schemas.common import PaginationParams
from app.schemas.notice import NoticeCreate, NoticeUpdate
from app.services.notice_service import NoticeService


@pytest.fixture
async def service_hostel_1(db_session: AsyncSession) -> Hostel:
    """Fixture creating test hostel 1."""
    hostel = Hostel(
        id=uuid4(),
        name="Hostel One",
        code="H1",
        gender_type=GenderType.MIXED,
        address="Campus",
        total_capacity=50,
    )
    db_session.add(hostel)
    await db_session.flush()
    return hostel


@pytest.fixture
async def service_hostel_2(db_session: AsyncSession) -> Hostel:
    """Fixture creating test hostel 2."""
    hostel = Hostel(
        id=uuid4(),
        name="Hostel Two",
        code="H2",
        gender_type=GenderType.MIXED,
        address="Campus",
        total_capacity=50,
    )
    db_session.add(hostel)
    await db_session.flush()
    return hostel


@pytest.fixture
async def service_admin(db_session: AsyncSession) -> User:
    """Fixture creating admin user."""
    user = User(
        id=uuid4(),
        email="svc_admin@example.com",
        full_name="Admin",
        phone="000",
        hashed_password="hash",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def service_warden(
    db_session: AsyncSession,
    service_hostel_1: Hostel,
) -> User:
    """Fixture creating warden assigned only to hostel 1."""
    warden = User(
        id=uuid4(),
        email="svc_warden@example.com",
        full_name="Warden 1",
        phone="111",
        hashed_password="hash",
        role=UserRole.WARDEN,
        is_active=True,
    )
    db_session.add(warden)
    await db_session.flush()

    assignment = WardenAssignment(
        user_id=warden.id,
        hostel_id=service_hostel_1.id,
    )
    db_session.add(assignment)
    await db_session.flush()
    return warden


@pytest.fixture
async def service_student(db_session: AsyncSession) -> User:
    """Fixture creating student user."""
    student = User(
        id=uuid4(),
        email="svc_student@example.com",
        full_name="Student",
        phone="222",
        hashed_password="hash",
        role=UserRole.STUDENT,
        is_active=True,
    )
    db_session.add(student)
    await db_session.flush()
    return student


async def test_create_notice_rules(
    db_session: AsyncSession,
    service_admin: User,
    service_warden: User,
    service_student: User,
    service_hostel_1: Hostel,
    service_hostel_2: Hostel,
) -> None:
    """Verify notice creation permission and date constraints."""
    service = NoticeService(db_session)

    # 1. Admin can create global notice
    global_notice = await service.create_notice(
        current_user=service_admin,
        payload=NoticeCreate(
            title="Global Campus Event",
            body="All campus event on Friday.",
            audience=NoticeAudience.ALL,
        ),
    )
    assert global_notice.hostel_id is None
    assert global_notice.title == "Global Campus Event"

    # 2. Warden cannot create global notice (403 FORBIDDEN)
    with pytest.raises(ForbiddenError) as exc_w_glob:
        await service.create_notice(
            current_user=service_warden,
            payload=NoticeCreate(
                title="Warden Global Attempt",
                body="Should fail.",
                audience=NoticeAudience.ALL,
            ),
        )
    assert "Only administrators can create global notices" in str(exc_w_glob.value)

    # 3. Warden cannot create notice for unassigned hostel (Hostel 2)
    with pytest.raises(ForbiddenError) as exc_w_unassigned:
        await service.create_notice(
            current_user=service_warden,
            payload=NoticeCreate(
                hostel_id=service_hostel_2.id,
                title="Warden Hostel 2 Attempt",
                body="Should fail.",
                audience=NoticeAudience.ALL,
            ),
        )
    assert "not assigned" in str(exc_w_unassigned.value).lower()

    # 4. Warden can create notice for assigned hostel (Hostel 1)
    warden_notice = await service.create_notice(
        current_user=service_warden,
        payload=NoticeCreate(
            hostel_id=service_hostel_1.id,
            title="Hostel 1 Dinner Meeting",
            body="Dinner meeting tonight.",
            audience=NoticeAudience.STUDENTS,
        ),
    )
    assert warden_notice.hostel_id == service_hostel_1.id

    # 5. Student cannot create notices
    with pytest.raises(ForbiddenError):
        await service.create_notice(
            current_user=service_student,
            payload=NoticeCreate(
                title="Student Notice",
                body="Should fail.",
            ),
        )

    # 6. Expiration date in past / before published rejected
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        NoticeCreate(
            title="Bad Date Notice",
            body="Invalid date.",
            published_at=now,
            expires_at=now - timedelta(hours=1),
        )

    with pytest.raises(BusinessRuleError) as exc_date:
        await service.update_notice(
            current_user=service_admin,
            notice_id=global_notice.id,
            payload=NoticeUpdate(
                expires_at=now - timedelta(days=5),
            ),
        )
    assert exc_date.value.code == "INVALID_EXPIRY"


async def test_update_and_delete_notice_rules(
    db_session: AsyncSession,
    service_admin: User,
    service_warden: User,
    service_hostel_1: Hostel,
    service_hostel_2: Hostel,
) -> None:
    """Verify update and delete permission rules for admin and wardens."""
    service = NoticeService(db_session)

    # Admin creates global notice
    global_n = await service.create_notice(
        current_user=service_admin,
        payload=NoticeCreate(title="Global 1", body="Body"),
    )

    # Warden cannot update global notice
    with pytest.raises(ForbiddenError):
        await service.update_notice(
            current_user=service_warden,
            notice_id=global_n.id,
            payload=NoticeUpdate(title="Hacked Global"),
        )

    # Warden cannot delete global notice
    with pytest.raises(ForbiddenError):
        await service.delete_notice(
            current_user=service_warden,
            notice_id=global_n.id,
        )

    # Admin creates notice for Hostel 2 (where warden is NOT assigned)
    h2_n = await service.create_notice(
        current_user=service_admin,
        payload=NoticeCreate(
            hostel_id=service_hostel_2.id,
            title="Hostel 2 Announcement",
            body="Body",
        ),
    )

    # Warden cannot update or delete notice in Hostel 2
    with pytest.raises(ForbiddenError):
        await service.update_notice(
            current_user=service_warden,
            notice_id=h2_n.id,
            payload=NoticeUpdate(title="Warden update H2"),
        )
    with pytest.raises(ForbiddenError):
        await service.delete_notice(
            current_user=service_warden,
            notice_id=h2_n.id,
        )

    # Warden creates notice in assigned Hostel 1
    h1_n = await service.create_notice(
        current_user=service_warden,
        payload=NoticeCreate(
            hostel_id=service_hostel_1.id,
            title="Hostel 1 Announcement",
            body="Body",
        ),
    )

    # Warden CAN update and delete notice in assigned Hostel 1
    updated = await service.update_notice(
        current_user=service_warden,
        notice_id=h1_n.id,
        payload=NoticeUpdate(title="Hostel 1 Announcement Updated"),
    )
    assert updated.title == "Hostel 1 Announcement Updated"

    await service.delete_notice(
        current_user=service_warden,
        notice_id=h1_n.id,
    )
    with pytest.raises(NotFoundError):
        await service.get_notice(service_admin, h1_n.id)


async def test_get_and_mark_read_and_unread_counts(
    db_session: AsyncSession,
    service_admin: User,
    service_student: User,
) -> None:
    """Test get_notice, mark_as_read, and get_unread_count via NoticeService."""
    service = NoticeService(db_session)

    # Create active global notice for students
    n = await service.create_notice(
        current_user=service_admin,
        payload=NoticeCreate(
            title="Student Announcement",
            body="Exam timetable released.",
            audience=NoticeAudience.STUDENTS,
        ),
    )

    # Check unread count for student before read
    count_before = await service.get_unread_count(service_student)
    assert count_before.unread_count >= 1

    # Get notice as student
    notice_read = await service.get_notice(service_student, n.id)
    assert notice_read.title == "Student Announcement"
    assert notice_read.is_read is False

    # Mark notice as read
    marked = await service.mark_as_read(service_student, n.id)
    assert marked.is_read is True

    # Check notice again
    notice_read2 = await service.get_notice(service_student, n.id)
    assert notice_read2.is_read is True

    # List notices includes is_read = True
    params = PaginationParams(page=1, size=20)
    page = await service.list_notices(params, service_student)
    matching = next((item for item in page.items if item.id == n.id), None)
    assert matching is not None
    assert matching.is_read is True
