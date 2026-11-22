"""Unit tests for Notice schemas validation and serialization."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.notice import NoticeAudience
from app.schemas.notice import (
    NoticeCreate,
    NoticeRead,
    NoticeUnreadCount,
    NoticeUpdate,
)


def test_notice_create_valid() -> None:
    """Verify valid NoticeCreate schema with defaults."""
    schema = NoticeCreate(
        title="Hostel Annual Maintenance",
        body="Water supply will be temporarily suspended tomorrow.",
    )
    assert schema.title == "Hostel Annual Maintenance"
    assert schema.audience == NoticeAudience.ALL
    assert schema.is_pinned is False
    assert schema.hostel_id is None
    assert schema.published_at is None
    assert schema.expires_at is None


def test_notice_create_date_validation() -> None:
    """Verify expiration date must be strictly after published date."""
    now = datetime.now(UTC)
    schema = NoticeCreate(
        title="Valid Notice",
        body="Body content",
        published_at=now,
        expires_at=now + timedelta(days=2),
    )
    assert schema.expires_at is not None
    assert schema.published_at is not None
    assert schema.expires_at > schema.published_at

    with pytest.raises(ValidationError) as exc:
        NoticeCreate(
            title="Invalid Notice",
            body="Body content",
            published_at=now,
            expires_at=now - timedelta(hours=1),
        )
    assert "expires_at must be strictly after published_at" in str(exc.value)

    with pytest.raises(ValidationError) as exc_eq:
        NoticeCreate(
            title="Invalid Notice Same Time",
            body="Body content",
            published_at=now,
            expires_at=now,
        )
    assert "expires_at must be strictly after published_at" in str(exc_eq.value)


def test_notice_update_validation() -> None:
    """Verify NoticeUpdate partial fields and date validation."""
    now = datetime.now(UTC)
    update_valid = NoticeUpdate(
        title="New Title",
        published_at=now,
        expires_at=now + timedelta(days=1),
    )
    assert update_valid.title == "New Title"

    with pytest.raises(ValidationError) as exc:
        NoticeUpdate(
            published_at=now,
            expires_at=now - timedelta(days=1),
        )
    assert "expires_at must be strictly after published_at" in str(exc.value)


def test_notice_read_enrichment() -> None:
    """Verify NoticeRead populates enriched relationship attributes and unread status."""
    notice_id = uuid4()
    now = datetime.now(UTC)

    class MockUser:
        full_name = "Warden Jane"

    class MockHostel:
        name = "Mandela Hall"

    class MockNotice:
        id = notice_id
        hostel_id = uuid4()
        title = "Curfew Notice"
        body = "Gate closes at 10 PM."
        audience = NoticeAudience.STUDENTS
        is_pinned = True
        published_at = now
        expires_at = now + timedelta(days=5)
        created_by_id = uuid4()
        created_at = now
        updated_at = now
        hostel = MockHostel()
        created_by = MockUser()

    read_schema = NoticeRead.model_validate(MockNotice())
    assert read_schema.id == notice_id
    assert read_schema.hostel_name == "Mandela Hall"
    assert read_schema.created_by_name == "Warden Jane"
    assert read_schema.is_read is False


def test_notice_unread_count_schema() -> None:
    """Verify NoticeUnreadCount structure."""
    unread = NoticeUnreadCount(unread_count=5)
    assert unread.unread_count == 5
