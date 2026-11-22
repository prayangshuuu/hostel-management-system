"""Unit tests for NoticeRepository and NoticeReadRepository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hostel import GenderType, Hostel
from app.models.notice import Notice, NoticeAudience
from app.models.user import User, UserRole
from app.repositories.notice_repository import (
    NoticeReadRepository,
    NoticeRepository,
)
from app.schemas.common import PaginationParams


@pytest.fixture
async def sample_hostel_a(db_session: AsyncSession) -> Hostel:
    """Fixture creating test hostel A."""
    hostel = Hostel(
        id=uuid4(),
        name="Hostel Alpha",
        code="HA-01",
        gender_type=GenderType.MIXED,
        address="Campus North",
        total_capacity=100,
    )
    db_session.add(hostel)
    await db_session.flush()
    return hostel


@pytest.fixture
async def sample_hostel_b(db_session: AsyncSession) -> Hostel:
    """Fixture creating test hostel B."""
    hostel = Hostel(
        id=uuid4(),
        name="Hostel Beta",
        code="HB-02",
        gender_type=GenderType.MIXED,
        address="Campus South",
        total_capacity=100,
    )
    db_session.add(hostel)
    await db_session.flush()
    return hostel


@pytest.fixture
async def sample_creator(db_session: AsyncSession) -> User:
    """Fixture creating test notice author."""
    user = User(
        id=uuid4(),
        email="author@example.com",
        full_name="Admin Author",
        phone="+123456789",
        hashed_password="hash",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def test_notice_repository_crud(
    db_session: AsyncSession,
    sample_hostel_a: Hostel,
    sample_creator: User,
) -> None:
    """Test NoticeRepository create, get_by_id, update, delete."""
    repo = NoticeRepository(db_session)
    now = datetime.now(UTC)

    notice = Notice(
        id=uuid4(),
        hostel_id=sample_hostel_a.id,
        title="Fire Drill",
        body="Fire drill tomorrow at 10 AM.",
        audience=NoticeAudience.ALL,
        is_pinned=True,
        published_at=now,
        expires_at=now + timedelta(days=2),
        created_by_id=sample_creator.id,
    )
    created = await repo.create(notice)
    assert created.id == notice.id

    fetched = await repo.get_by_id(notice.id)
    assert fetched is not None
    assert fetched.title == "Fire Drill"
    assert fetched.is_pinned is True
    assert fetched.hostel is not None
    assert fetched.hostel.name == "Hostel Alpha"
    assert fetched.created_by is not None
    assert fetched.created_by.full_name == "Admin Author"

    fetched.title = "Updated Fire Drill"
    updated = await repo.update(fetched)
    assert updated.title == "Updated Fire Drill"

    await repo.delete(updated)
    assert await repo.get_by_id(notice.id) is None


async def test_notice_repository_visibility_matrix(
    db_session: AsyncSession,
    sample_hostel_a: Hostel,
    sample_hostel_b: Hostel,
    sample_creator: User,
) -> None:
    """Test visibility rules for admin, warden, and student with pin ordering."""
    repo = NoticeRepository(db_session)
    now = datetime.now(UTC)

    # 1. Global notice for ALL (active, pinned)
    n1 = await repo.create(
        Notice(
            id=uuid4(),
            hostel_id=None,
            title="Global All Pinned",
            body="Body 1",
            audience=NoticeAudience.ALL,
            is_pinned=True,
            published_at=now - timedelta(hours=2),
            created_by_id=sample_creator.id,
        )
    )

    # 2. Global notice for STUDENTS (active, unpinned)
    n2 = await repo.create(
        Notice(
            id=uuid4(),
            hostel_id=None,
            title="Global Students",
            body="Body 2",
            audience=NoticeAudience.STUDENTS,
            is_pinned=False,
            published_at=now - timedelta(hours=1),
            created_by_id=sample_creator.id,
        )
    )

    # 3. Global notice for WARDENS (active)
    n3 = await repo.create(
        Notice(
            id=uuid4(),
            hostel_id=None,
            title="Global Wardens",
            body="Body 3",
            audience=NoticeAudience.WARDENS,
            is_pinned=False,
            published_at=now - timedelta(hours=1),
            created_by_id=sample_creator.id,
        )
    )

    # 4. Hostel A notice for STUDENTS (active)
    n4 = await repo.create(
        Notice(
            id=uuid4(),
            hostel_id=sample_hostel_a.id,
            title="Hostel A Students",
            body="Body 4",
            audience=NoticeAudience.STUDENTS,
            is_pinned=False,
            published_at=now - timedelta(hours=1),
            created_by_id=sample_creator.id,
        )
    )

    # 5. Hostel B notice for STUDENTS (active)
    await repo.create(
        Notice(
            id=uuid4(),
            hostel_id=sample_hostel_b.id,
            title="Hostel B Students",
            body="Body 5",
            audience=NoticeAudience.STUDENTS,
            is_pinned=False,
            published_at=now - timedelta(hours=1),
            created_by_id=sample_creator.id,
        )
    )

    # 6. Hostel A notice expired in past
    await repo.create(
        Notice(
            id=uuid4(),
            hostel_id=sample_hostel_a.id,
            title="Hostel A Expired",
            body="Body 6",
            audience=NoticeAudience.ALL,
            is_pinned=False,
            published_at=now - timedelta(days=5),
            expires_at=now - timedelta(days=1),
            created_by_id=sample_creator.id,
        )
    )

    # 7. Hostel A notice scheduled in future (draft)
    await repo.create(
        Notice(
            id=uuid4(),
            hostel_id=sample_hostel_a.id,
            title="Hostel A Future",
            body="Body 7",
            audience=NoticeAudience.ALL,
            is_pinned=False,
            published_at=now + timedelta(days=2),
            created_by_id=sample_creator.id,
        )
    )

    params = PaginationParams(page=1, size=20)

    # Admin: sees all 7 notices
    admin_notices, total_admin = await repo.list_visible(
        params=params,
        user_role=UserRole.ADMIN,
        user_id=sample_creator.id,
    )
    assert total_admin == 7
    # Pinned first
    assert admin_notices[0].id == n1.id

    # Student residing in Hostel A:
    # Sees: n1 (global all), n2 (global students), n4 (hostel A students)
    # Excludes: n3 (wardens), n5 (hostel B), n6 (expired), n7 (future)
    student_id = uuid4()
    student_notices, total_student = await repo.list_visible(
        params=params,
        user_role=UserRole.STUDENT,
        user_id=student_id,
        user_hostel_id=sample_hostel_a.id,
    )
    assert total_student == 3
    visible_ids = {n.id for n in student_notices}
    assert visible_ids == {n1.id, n2.id, n4.id}
    # Pinned first
    assert student_notices[0].id == n1.id

    # Warden assigned to Hostel A:
    # Sees: n1 (global all), n3 (global wardens)
    # Excludes: n2 (students), n4 (students), n5 (hostel B students), n6 (expired), n7 (future)
    warden_id = uuid4()
    warden_notices, total_warden = await repo.list_visible(
        params=params,
        user_role=UserRole.WARDEN,
        user_id=warden_id,
        warden_hostel_ids=[sample_hostel_a.id],
        include_drafts_expired=False,
    )
    assert total_warden == 2
    assert {n.id for n in warden_notices} == {n1.id, n3.id}

    # Warden with include_drafts_expired=True:
    # Sees: n1, n3, plus n6 (expired) and n7 (future) in Hostel A
    _warden_drafts, total_warden_drafts = await repo.list_visible(
        params=params,
        user_role=UserRole.WARDEN,
        user_id=warden_id,
        warden_hostel_ids=[sample_hostel_a.id],
        include_drafts_expired=True,
    )
    assert total_warden_drafts == 4


async def test_notice_read_repository_mark_and_counts(
    db_session: AsyncSession,
    sample_hostel_a: Hostel,
    sample_creator: User,
) -> None:
    """Test NoticeReadRepository idempotent read marking and unread counting."""
    notice_repo = NoticeRepository(db_session)
    read_repo = NoticeReadRepository(db_session)
    now = datetime.now(UTC)

    n1 = await notice_repo.create(
        Notice(
            id=uuid4(),
            hostel_id=None,
            title="Notice 1",
            body="Body 1",
            audience=NoticeAudience.ALL,
            published_at=now - timedelta(hours=1),
            created_by_id=sample_creator.id,
        )
    )
    n2 = await notice_repo.create(
        Notice(
            id=uuid4(),
            hostel_id=sample_hostel_a.id,
            title="Notice 2",
            body="Body 2",
            audience=NoticeAudience.STUDENTS,
            published_at=now - timedelta(hours=1),
            created_by_id=sample_creator.id,
        )
    )

    user_id = uuid4()

    # Initial unread count for student in Hostel A is 2
    unread_before = await read_repo.get_unread_count(
        user_role=UserRole.STUDENT,
        user_id=user_id,
        user_hostel_id=sample_hostel_a.id,
    )
    assert unread_before == 2

    # Mark n1 as read
    read_entry1 = await read_repo.mark_read(notice_id=n1.id, user_id=user_id)
    assert read_entry1.notice_id == n1.id

    # Idempotent call returns same
    read_entry2 = await read_repo.mark_read(notice_id=n1.id, user_id=user_id)
    assert read_entry2.id == read_entry1.id

    # Check unread count after marking 1 read -> now 1
    unread_after = await read_repo.get_unread_count(
        user_role=UserRole.STUDENT,
        user_id=user_id,
        user_hostel_id=sample_hostel_a.id,
    )
    assert unread_after == 1

    # Check get_read_notice_ids_for_user
    read_ids = await read_repo.get_read_notice_ids_for_user(user_id, [n1.id, n2.id])
    assert read_ids == {n1.id}
