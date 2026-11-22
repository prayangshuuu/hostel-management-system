"""Notice and notice read database models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.hostel import Hostel
    from app.models.user import User


class NoticeAudience(enum.StrEnum):
    """Target audience for hostel notices."""

    ALL = "all"
    STUDENTS = "students"
    WARDENS = "wardens"


class Notice(Base, UUIDPkMixin, TimestampMixin):
    """Hostel and campus announcement notice."""

    __tablename__ = "notices"
    __table_args__ = (
        Index("ix_notices_published_expires", "published_at", "expires_at"),
        Index("ix_notices_hostel_audience", "hostel_id", "audience"),
        Index("ix_notices_published_at_audience", "published_at", "audience"),
    )

    hostel_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("hostels.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    audience: Mapped[NoticeAudience] = mapped_column(
        Enum(NoticeAudience, native_enum=False, length=20),
        nullable=False,
        default=NoticeAudience.ALL,
        index=True,
    )
    is_pinned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    hostel: Mapped[Hostel | None] = relationship(
        "Hostel",
        lazy="selectin",
    )
    created_by: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[created_by_id],
        lazy="selectin",
    )
    reads: Mapped[list[NoticeRead]] = relationship(
        "NoticeRead",
        back_populates="notice",
        cascade="all, delete-orphan",
    )


class NoticeRead(Base, UUIDPkMixin):
    """Tracking read status per user per notice."""

    __tablename__ = "notice_reads"
    __table_args__ = (
        UniqueConstraint("notice_id", "user_id", name="uq_notice_reads_notice_user"),
        Index("ix_notice_reads_user_notice", "user_id", "notice_id"),
    )

    notice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notices.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )

    notice: Mapped[Notice] = relationship(
        "Notice",
        back_populates="reads",
    )
    user: Mapped[User] = relationship(
        "User",
        foreign_keys=[user_id],
        lazy="selectin",
    )
