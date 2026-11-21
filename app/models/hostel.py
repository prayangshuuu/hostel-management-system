"""Hostel, block, and warden assignment database models."""

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPkMixin
from app.models.user import User

if TYPE_CHECKING:
    from app.models.room import Room


class GenderType(enum.StrEnum):
    """Hostel gender segregation types."""

    MALE = "male"
    FEMALE = "female"
    MIXED = "mixed"


class Hostel(Base, UUIDPkMixin, TimestampMixin, SoftDeleteMixin):
    """Hostel entity."""

    __tablename__ = "hostels"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    gender_type: Mapped[GenderType] = mapped_column(
        Enum(GenderType, native_enum=False, length=20),
        nullable=False,
        default=GenderType.MIXED,
    )
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)

    blocks: Mapped[list["Block"]] = relationship(
        "Block",
        back_populates="hostel",
        cascade="all, delete-orphan",
    )
    warden_assignments: Mapped[list["WardenAssignment"]] = relationship(
        "WardenAssignment",
        back_populates="hostel",
        cascade="all, delete-orphan",
    )

    @property
    def total_capacity(self) -> int:
        """Total capacity across all active rooms in this hostel."""
        from sqlalchemy import inspect

        insp = inspect(self)
        if "blocks" in insp.unloaded:
            return 0
        total = 0
        for block in self.blocks:
            b_insp = inspect(block)
            if "rooms" in b_insp.unloaded:
                continue
            for room in block.rooms:
                if not room.is_deleted:
                    total += room.capacity
        return total

    def __repr__(self) -> str:
        return f"<Hostel id={self.id} code={self.code} name={self.name}>"


class Block(Base, UUIDPkMixin, TimestampMixin):
    """Hostel block entity."""

    __tablename__ = "blocks"
    __table_args__ = (UniqueConstraint("hostel_id", "name", name="uq_blocks_hostel_id_name"),)

    hostel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("hostels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    floor_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )

    hostel: Mapped["Hostel"] = relationship("Hostel", back_populates="blocks")
    rooms: Mapped[list["Room"]] = relationship(
        "Room",
        back_populates="block",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Block id={self.id} hostel_id={self.hostel_id} name={self.name}>"


class WardenAssignment(Base, UUIDPkMixin, TimestampMixin):
    """Hostel warden assignment association entity."""

    __tablename__ = "warden_assignments"
    __table_args__ = (
        UniqueConstraint("user_id", "hostel_id", name="uq_warden_assignments_user_id_hostel_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hostel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("hostels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    user: Mapped[User] = relationship("User")
    hostel: Mapped[Hostel] = relationship("Hostel", back_populates="warden_assignments")

    def __repr__(self) -> str:
        return f"<WardenAssignment id={self.id} user_id={self.user_id} hostel_id={self.hostel_id}>"
