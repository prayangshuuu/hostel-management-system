"""SQLAlchemy base classes and common mixins."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

POSTGRES_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base declarative class with explicit naming conventions."""

    metadata = MetaData(naming_convention=POSTGRES_NAMING_CONVENTION)


class UUIDPkMixin:
    """Mixin that adds a UUID primary key to a model."""

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    """Mixin that adds timezone-aware created_at and updated_at timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        server_default=func.now(),
        onupdate=func.now(),
    )


class SoftDeleteMixin:
    """Mixin for models requiring soft deletion support."""

    is_deleted: Mapped[bool] = mapped_column(
        default=False,
        server_default="false",
    )
