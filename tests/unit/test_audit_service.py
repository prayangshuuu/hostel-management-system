"""Unit tests for AuditService, payload sanitization, and AuditLogRepository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError
from app.models.audit import AuditLog
from app.models.user import User, UserRole
from app.repositories.audit_repository import AuditLogRepository
from app.schemas.common import PaginationParams
from app.services.audit_service import AuditService


def test_sanitize_payload_redacts_sensitive_keys() -> None:
    """Verify recursive payload sanitization of passwords, tokens, secrets."""
    payload = {
        "email": "student@example.com",
        "password": "SuperSecretPassword123!",
        "hashed_password": "$argon2id$v=19$m=65536,t=3,p=4$...",
        "access_token": "eyJhbGciOiJIUzI1NiIs...",
        "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
        "user_secret": "my-secret-key",
        "authorization": "Bearer token",
        "metadata": {
            "token": "nested-token",
            "safe_key": "safe_value",
            "nested_list": [
                {"secret": "hidden_in_list", "count": 10},
                "plain_string",
            ],
        },
    }

    sanitized = AuditService.sanitize_payload(payload)

    assert sanitized["email"] == "student@example.com"
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["hashed_password"] == "[REDACTED]"
    assert sanitized["access_token"] == "[REDACTED]"
    assert sanitized["refresh_token"] == "[REDACTED]"
    assert sanitized["user_secret"] == "[REDACTED]"
    assert sanitized["authorization"] == "[REDACTED]"

    assert sanitized["metadata"]["safe_key"] == "safe_value"
    assert sanitized["metadata"]["token"] == "[REDACTED]"
    assert sanitized["metadata"]["nested_list"][0]["secret"] == "[REDACTED]"
    assert sanitized["metadata"]["nested_list"][0]["count"] == 10
    assert sanitized["metadata"]["nested_list"][1] == "plain_string"


async def test_audit_service_record_and_atomic_session(db_session: AsyncSession) -> None:
    """Verify AuditService.record adds entry within the active session."""
    actor_id = uuid4()
    entity_id = uuid4()

    log = await AuditService.record(
        session=db_session,
        actor_id=actor_id,
        action="test.action",
        entity="TestEntity",
        entity_id=entity_id,
        payload={"field": "value", "password": "confidential"},
    )

    assert log.id is not None
    assert log.actor_id == actor_id
    assert log.action == "test.action"
    assert log.entity == "TestEntity"
    assert log.entity_id == entity_id
    assert log.payload["field"] == "value"
    assert log.payload["password"] == "[REDACTED]"


async def test_audit_log_repository_and_service_filters(db_session: AsyncSession) -> None:
    """Test filtering audit logs by actor, entity, action, and date range."""
    repo = AuditLogRepository(db_session)
    service = AuditService(db_session)

    actor1 = User(
        id=uuid4(),
        email="audit_admin@example.com",
        full_name="Audit Admin",
        phone="555",
        hashed_password="hash",
        role=UserRole.ADMIN,
        is_active=True,
    )
    actor2 = User(
        id=uuid4(),
        email="audit_warden@example.com",
        full_name="Audit Warden",
        phone="666",
        hashed_password="hash",
        role=UserRole.WARDEN,
        is_active=True,
    )
    db_session.add_all([actor1, actor2])
    await db_session.flush()

    now = datetime.now(UTC)
    entity_id_1 = uuid4()
    entity_id_2 = uuid4()

    log1 = AuditLog(
        id=uuid4(),
        actor_id=actor1.id,
        action="user.create",
        entity="User",
        entity_id=entity_id_1,
        payload={"email": "u1@example.com"},
        created_at=now - timedelta(days=2),
    )
    log2 = AuditLog(
        id=uuid4(),
        actor_id=actor2.id,
        action="room.maintenance_toggle",
        entity="Room",
        entity_id=entity_id_2,
        payload={"status": "maintenance"},
        created_at=now - timedelta(days=1),
    )
    log3 = AuditLog(
        id=uuid4(),
        actor_id=actor1.id,
        action="allocation.create",
        entity="Allocation",
        entity_id=uuid4(),
        payload={"student_id": str(uuid4())},
        created_at=now,
    )
    db_session.add_all([log1, log2, log3])
    await db_session.flush()

    params = PaginationParams(page=1, size=10)

    # Filter by entity
    items, total = await repo.list(params, entity="Room")
    assert total == 1
    assert items[0].id == log2.id

    # Filter by actor_id
    _items_actor, total_actor = await repo.list(params, actor_id=actor1.id)
    assert total_actor == 2

    # Filter by action
    items_action, total_action = await repo.list(params, action="allocation.create")
    assert total_action == 1
    assert items_action[0].id == log3.id

    # Filter by date range
    items_date, total_date = await repo.list(
        params,
        date_from=now - timedelta(days=1, hours=12),
        date_to=now - timedelta(hours=1),
    )
    assert total_date == 1
    assert items_date[0].id == log2.id

    # Service call with Admin user succeeds
    page = await service.list_audit_logs(params=params, current_user=actor1)
    assert page.total == 3
    assert page.items[0].actor_name == "Audit Admin" or page.items[0].actor_email is not None

    # Service call with Non-admin raises ForbiddenError
    with pytest.raises(ForbiddenError):
        await service.list_audit_logs(params=params, current_user=actor2)
