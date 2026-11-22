"""User and role database models."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.auth import RefreshToken
    from app.models.student import StudentProfile


class UserRole(enum.StrEnum):
    """User roles for access control."""

    ADMIN = "admin"
    WARDEN = "warden"
    STUDENT = "student"


class User(Base, UUIDPkMixin, TimestampMixin):
    """User account entity."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    phone: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=20),
        nullable=False,
        default=UserRole.STUDENT,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    student_profile: Mapped[StudentProfile | None] = relationship(
        "StudentProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} role={self.role}>"
