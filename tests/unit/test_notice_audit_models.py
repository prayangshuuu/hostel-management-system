"""Unit tests for Notice, NoticeRead, and AuditLog database models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Table, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.audit import AuditLog
from app.models.hostel import GenderType, Hostel
from app.models.notice import Notice, NoticeAudience, NoticeRead
from app.models.user import User, UserRole


def test_notice_audience_enum_values() -> None:
    """Verify NoticeAudience enum members and string values."""
    assert NoticeAudience.ALL.value == "all"
    assert NoticeAudience.STUDENTS.value == "students"
    assert NoticeAudience.WARDENS.value == "wardens"


def test_notice_model_attributes() -> None:
    """Verify Notice model table structure, columns, foreign keys, and indexes."""
    table = Notice.__table__
    assert isinstance(table, Table)
    columns = table.columns

    assert "id" in columns
    assert "hostel_id" in columns
    assert "title" in columns
    assert "body" in columns
    assert "audience" in columns
    assert "is_pinned" in columns
    assert "published_at" in columns
    assert "expires_at" in columns
    assert "created_by_id" in columns
    assert "created_at" in columns
    assert "updated_at" in columns

    assert columns["id"].primary_key is True
    assert columns["hostel_id"].nullable is True
    assert columns["title"].nullable is False
    assert columns["body"].nullable is False
    assert columns["audience"].nullable is False
    assert columns["is_pinned"].nullable is False
    assert columns["published_at"].nullable is False
    assert columns["expires_at"].nullable is True
    assert columns["created_by_id"].nullable is True

    fk_by_col = {fk.parent.name: fk for fk in table.foreign_keys}
    assert "hostel_id" in fk_by_col
    assert fk_by_col["hostel_id"].target_fullname == "hostels.id"
    assert fk_by_col["hostel_id"].ondelete == "CASCADE"
    assert "created_by_id" in fk_by_col
    assert fk_by_col["created_by_id"].target_fullname == "users.id"
    assert fk_by_col["created_by_id"].ondelete == "SET NULL"

    index_names = {idx.name for idx in table.indexes}
    assert "ix_notices_hostel_id" in index_names
    assert "ix_notices_audience" in index_names
    assert "ix_notices_is_pinned" in index_names
    assert "ix_notices_published_at" in index_names
    assert "ix_notices_expires_at" in index_names
    assert "ix_notices_created_by_id" in index_names
    assert "ix_notices_published_expires" in index_names
    assert "ix_notices_hostel_audience" in index_names


def test_notice_read_model_attributes() -> None:
    """Verify NoticeRead model table structure, columns, constraints, and indexes."""
    table = NoticeRead.__table__
    assert isinstance(table, Table)
    columns = table.columns

    assert "id" in columns
    assert "notice_id" in columns
    assert "user_id" in columns
    assert "read_at" in columns

    assert columns["id"].primary_key is True
    assert columns["notice_id"].nullable is False
    assert columns["user_id"].nullable is False
    assert columns["read_at"].nullable is False

    fk_by_col = {fk.parent.name: fk for fk in table.foreign_keys}
    assert "notice_id" in fk_by_col
    assert fk_by_col["notice_id"].target_fullname == "notices.id"
    assert fk_by_col["notice_id"].ondelete == "CASCADE"
    assert "user_id" in fk_by_col
    assert fk_by_col["user_id"].target_fullname == "users.id"
    assert fk_by_col["user_id"].ondelete == "CASCADE"

    index_names = {idx.name for idx in table.indexes}
    assert "ix_notice_reads_user_notice" in index_names

    uq_names = {uq.name for uq in table.constraints if type(uq).__name__ == "UniqueConstraint"}
    assert "uq_notice_reads_notice_user" in uq_names


def test_audit_log_model_attributes() -> None:
    """Verify AuditLog model table structure, columns, foreign keys, and indexes."""
    table = AuditLog.__table__
    assert isinstance(table, Table)
    columns = table.columns

    assert "id" in columns
    assert "actor_id" in columns
    assert "action" in columns
    assert "entity" in columns
    assert "entity_id" in columns
    assert "payload" in columns
    assert "created_at" in columns

    assert columns["id"].primary_key is True
    assert columns["actor_id"].nullable is True
    assert columns["action"].nullable is False
    assert columns["entity"].nullable is False
    assert columns["entity_id"].nullable is False
    assert columns["payload"].nullable is False
    assert columns["created_at"].nullable is False

    fk_by_col = {fk.parent.name: fk for fk in table.foreign_keys}
    assert "actor_id" in fk_by_col
    assert fk_by_col["actor_id"].target_fullname == "users.id"
    assert fk_by_col["actor_id"].ondelete == "SET NULL"

    index_names = {idx.name for idx in table.indexes}
    assert "ix_audit_logs_actor_id" in index_names
    assert "ix_audit_logs_action" in index_names
    assert "ix_audit_logs_created_at" in index_names
    assert "ix_audit_logs_entity_entity_id" in index_names


@pytest.mark.asyncio
async def test_notice_crud_and_defaults(db_session: AsyncSession) -> None:
    """Verify Notice creation with defaults (global notice, ALL audience)."""
    notice = Notice(
        title="Campus Renovation Announcement",
        body="Renovations begin on block A tomorrow.",
        published_at=datetime.now(UTC),
    )
    db_session.add(notice)
    await db_session.commit()
    await db_session.refresh(notice)

    assert notice.id is not None
    assert notice.hostel_id is None
    assert notice.audience == NoticeAudience.ALL
    assert notice.is_pinned is False
    assert notice.expires_at is None
    assert notice.created_at is not None
    assert notice.updated_at is not None


@pytest.mark.asyncio
async def test_hostel_notice_with_creator(db_session: AsyncSession) -> None:
    """Verify hostel-specific pinned notice linked to creator user."""
    admin = User(
        email=f"admin_{uuid.uuid4().hex[:6]}@example.com",
        full_name="Hostel Admin",
        hashed_password="hash",
        role=UserRole.ADMIN,
    )
    hostel = Hostel(
        name="Mandela Hall",
        code=f"MH_{uuid.uuid4().hex[:4]}",
        gender_type=GenderType.MIXED,
    )
    db_session.add_all([admin, hostel])
    await db_session.commit()
    await db_session.refresh(admin)
    await db_session.refresh(hostel)

    pub_date = datetime.now(UTC)
    exp_date = datetime.now(UTC)
    notice = Notice(
        hostel_id=hostel.id,
        created_by_id=admin.id,
        title="Hostel Gate Curfew",
        body="Curfew is 10:00 PM for all students.",
        audience=NoticeAudience.STUDENTS,
        is_pinned=True,
        published_at=pub_date,
        expires_at=exp_date,
    )
    db_session.add(notice)
    await db_session.commit()

    result = await db_session.execute(
        select(Notice)
        .options(selectinload(Notice.hostel), selectinload(Notice.created_by))
        .where(Notice.id == notice.id)
    )
    fetched = result.scalar_one()

    assert fetched.hostel is not None
    assert fetched.hostel.id == hostel.id
    assert fetched.created_by is not None
    assert fetched.created_by.id == admin.id
    assert fetched.is_pinned is True
    assert fetched.audience == NoticeAudience.STUDENTS


@pytest.mark.asyncio
async def test_notice_reads_and_unique_constraint(db_session: AsyncSession) -> None:
    """Verify NoticeRead relationship and duplicate unique constraint enforcement."""
    user = User(
        email=f"student_{uuid.uuid4().hex[:6]}@example.com",
        full_name="Alice Student",
        hashed_password="hash",
        role=UserRole.STUDENT,
    )
    notice = Notice(
        title="General Guidelines",
        body="Read campus rules.",
        published_at=datetime.now(UTC),
    )
    db_session.add_all([user, notice])
    await db_session.commit()
    await db_session.refresh(user)
    await db_session.refresh(notice)

    read_log = NoticeRead(
        notice_id=notice.id,
        user_id=user.id,
    )
    db_session.add(read_log)
    await db_session.commit()

    # Query notice with reads loaded
    result = await db_session.execute(
        select(Notice).options(selectinload(Notice.reads)).where(Notice.id == notice.id)
    )
    loaded_notice = result.scalar_one()
    assert len(loaded_notice.reads) == 1
    assert loaded_notice.reads[0].user_id == user.id

    # Verify duplicate notice_id and user_id raises IntegrityError
    duplicate_read = NoticeRead(
        notice_id=notice.id,
        user_id=user.id,
    )
    db_session.add(duplicate_read)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_notice_reads_cascade_delete(db_session: AsyncSession) -> None:
    """Verify that deleting a notice cascade-deletes associated notice reads."""
    user = User(
        email=f"reader_{uuid.uuid4().hex[:6]}@example.com",
        full_name="Reader User",
        hashed_password="hash",
        role=UserRole.STUDENT,
    )
    notice = Notice(
        title="Temporary Notice",
        body="This will be deleted.",
        published_at=datetime.now(UTC),
    )
    db_session.add_all([user, notice])
    await db_session.commit()
    await db_session.refresh(user)
    await db_session.refresh(notice)

    read_log = NoticeRead(
        notice_id=notice.id,
        user_id=user.id,
    )
    db_session.add(read_log)
    await db_session.commit()
    await db_session.refresh(read_log)
    read_id = read_log.id

    # Delete notice
    await db_session.delete(notice)
    await db_session.commit()

    # Verify NoticeRead is gone
    res = await db_session.execute(select(NoticeRead).where(NoticeRead.id == read_id))
    assert res.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_audit_log_crud_and_json_payload(db_session: AsyncSession) -> None:
    """Verify AuditLog creation, JSON payload persistence, and actor relationship."""
    actor = User(
        email=f"actor_{uuid.uuid4().hex[:6]}@example.com",
        full_name="Warden Actor",
        hashed_password="hash",
        role=UserRole.WARDEN,
    )
    db_session.add(actor)
    await db_session.commit()
    await db_session.refresh(actor)

    entity_id = uuid.uuid4()
    payload = {"room_id": str(uuid.uuid4()), "status": "approved", "notes": "Verified"}

    audit = AuditLog(
        actor_id=actor.id,
        action="room.transfer",
        entity="allocation",
        entity_id=entity_id,
        payload=payload,
    )
    db_session.add(audit)
    await db_session.commit()
    await db_session.refresh(audit)

    assert audit.id is not None
    assert audit.actor_id == actor.id
    assert audit.action == "room.transfer"
    assert audit.entity == "allocation"
    assert audit.entity_id == entity_id
    assert audit.payload == payload
    assert audit.created_at is not None

    result = await db_session.execute(
        select(AuditLog).options(selectinload(AuditLog.actor)).where(AuditLog.id == audit.id)
    )
    fetched = result.scalar_one()
    assert fetched.actor is not None
    assert fetched.actor.id == actor.id


@pytest.mark.asyncio
async def test_audit_log_system_action_without_actor(db_session: AsyncSession) -> None:
    """Verify AuditLog with actor_id=None for system-triggered events."""
    entity_id = uuid.uuid4()
    audit = AuditLog(
        actor_id=None,
        action="invoice.overdue_check",
        entity="invoice",
        entity_id=entity_id,
        payload={"previous_status": "unpaid", "new_status": "overdue"},
    )
    db_session.add(audit)
    await db_session.commit()
    await db_session.refresh(audit)

    assert audit.id is not None
    assert audit.actor_id is None
    assert audit.action == "invoice.overdue_check"
