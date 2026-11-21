"""Room and Bed database models."""

from __future__ import annotations

import enum
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPkMixin

if TYPE_CHECKING:
    from app.models.hostel import Block


class RoomType(enum.StrEnum):
    """Room occupancy types."""

    SINGLE = "single"
    DOUBLE = "double"
    TRIPLE = "triple"
    DORM = "dorm"


class RoomStatus(enum.StrEnum):
    """Room operational statuses."""

    AVAILABLE = "available"
    FULL = "full"
    MAINTENANCE = "maintenance"


class Room(Base, UUIDPkMixin, TimestampMixin, SoftDeleteMixin):
    """Room entity within a hostel block."""

    __tablename__ = "rooms"
    __table_args__ = (UniqueConstraint("block_id", "number", name="uq_rooms_block_id_number"),)

    block_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("blocks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    number: Mapped[str] = mapped_column(String(50), nullable=False)
    floor: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    room_type: Mapped[RoomType] = mapped_column(
        Enum(RoomType, native_enum=False, length=20),
        nullable=False,
    )
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_rent: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[RoomStatus] = mapped_column(
        Enum(RoomStatus, native_enum=False, length=20),
        nullable=False,
        default=RoomStatus.AVAILABLE,
        index=True,
    )

    block: Mapped[Block] = relationship("Block", back_populates="rooms")
    beds: Mapped[list[Bed]] = relationship(
        "Bed",
        back_populates="room",
        cascade="all, delete-orphan",
        order_by="Bed.label",
    )

    @property
    def occupied_beds_count(self) -> int:
        """Count of occupied beds in this room."""
        if hasattr(self, "_occupied_beds_count") and self._occupied_beds_count is not None:
            return self._occupied_beds_count
        from sqlalchemy import inspect

        insp = inspect(self)
        if "beds" in insp.unloaded:
            return 0
        return sum(1 for b in self.beds if b.is_occupied)

    @occupied_beds_count.setter
    def occupied_beds_count(self, value: int) -> None:
        self._occupied_beds_count = value

    @property
    def available_beds_count(self) -> int:
        """Count of available beds in this room."""
        if hasattr(self, "_available_beds_count") and self._available_beds_count is not None:
            return self._available_beds_count
        from sqlalchemy import inspect

        insp = inspect(self)
        if "beds" in insp.unloaded:
            return max(0, self.capacity - self.occupied_beds_count)
        return sum(1 for b in self.beds if not b.is_occupied)

    @available_beds_count.setter
    def available_beds_count(self, value: int) -> None:
        self._available_beds_count = value

    def __repr__(self) -> str:
        return f"<Room id={self.id} number={self.number} block_id={self.block_id}>"


class Bed(Base, UUIDPkMixin, TimestampMixin):
    """Bed entity belonging to a room."""

    __tablename__ = "beds"
    __table_args__ = (UniqueConstraint("room_id", "label", name="uq_beds_room_id_label"),)

    room_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(20), nullable=False)
    is_occupied: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        index=True,
    )

    room: Mapped[Room] = relationship("Room", back_populates="beds")

    def __repr__(self) -> str:
        return f"<Bed id={self.id} room_id={self.room_id} label={self.label}>"
