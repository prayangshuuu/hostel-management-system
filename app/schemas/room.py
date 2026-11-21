"""Room and Bed request/response schemas and validation."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.exceptions import ValidationAppError
from app.models.room import RoomStatus, RoomType


def validate_capacity_for_room_type(room_type: RoomType, capacity: int) -> None:
    """Enforce capacity rules per room type: single=1, double=2, triple=3, dorm>=4."""
    if room_type == RoomType.SINGLE and capacity != 1:
        raise ValidationAppError(
            "Capacity does not match room type",
            code="INVALID_CAPACITY_FOR_ROOM_TYPE",
            status_code=422,
        )
    if room_type == RoomType.DOUBLE and capacity != 2:
        raise ValidationAppError(
            "Capacity does not match room type",
            code="INVALID_CAPACITY_FOR_ROOM_TYPE",
            status_code=422,
        )
    if room_type == RoomType.TRIPLE and capacity != 3:
        raise ValidationAppError(
            "Capacity does not match room type",
            code="INVALID_CAPACITY_FOR_ROOM_TYPE",
            status_code=422,
        )
    if room_type == RoomType.DORM and capacity < 4:
        raise ValidationAppError(
            "Capacity does not match room type",
            code="INVALID_CAPACITY_FOR_ROOM_TYPE",
            status_code=422,
        )


class RoomBase(BaseModel):
    """Base fields shared across room schemas."""

    number: str = Field(min_length=1, max_length=50)
    floor: int = Field(default=1)
    room_type: RoomType
    capacity: int = Field(gt=0)
    monthly_rent: Decimal = Field(gt=0, max_digits=12, decimal_places=2)

    @field_validator("number", mode="before")
    @classmethod
    def strip_whitespace(cls, v: Any) -> Any:
        """Strip leading and trailing whitespace from room number."""
        if isinstance(v, str):
            return v.strip()
        return v

    @model_validator(mode="after")
    def validate_capacity(self) -> Self:
        """Validate room_type and capacity consistency."""
        validate_capacity_for_room_type(self.room_type, self.capacity)
        return self


class RoomCreate(RoomBase):
    """Payload for creating a room."""


class RoomUpdate(BaseModel):
    """Payload for updating room details."""

    number: str | None = Field(default=None, min_length=1, max_length=50)
    floor: int | None = None
    room_type: RoomType | None = None
    capacity: int | None = Field(default=None, gt=0)
    monthly_rent: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    status: RoomStatus | None = None

    @field_validator("number", mode="before")
    @classmethod
    def strip_whitespace(cls, v: Any) -> Any:
        """Strip leading and trailing whitespace from room number."""
        if isinstance(v, str):
            return v.strip()
        return v

    @model_validator(mode="after")
    def validate_capacity_consistency(self) -> Self:
        """Validate room_type and capacity consistency if both are provided."""
        if self.room_type is not None and self.capacity is not None:
            validate_capacity_for_room_type(self.room_type, self.capacity)
        return self


class BedRead(BaseModel):
    """Public bed response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    room_id: UUID
    label: str
    is_occupied: bool
    created_at: datetime
    updated_at: datetime


class RoomRead(BaseModel):
    """Public room response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    block_id: UUID
    number: str
    floor: int
    room_type: RoomType
    capacity: int
    monthly_rent: Decimal
    status: RoomStatus
    is_deleted: bool
    occupied_beds_count: int = 0
    available_beds_count: int = 0
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def populate_bed_counts(cls, data: Any) -> Any:
        """Ensure occupied and available bed counts are populated if beds relation is present."""
        if isinstance(data, dict):
            return data
        beds = getattr(data, "beds", None)
        if beds is not None:
            occupied = sum(1 for b in beds if getattr(b, "is_occupied", False))
            available = sum(1 for b in beds if not getattr(b, "is_occupied", False))
            data._occupied_beds_count = occupied
            data._available_beds_count = available
        return data


class RoomWithBedsRead(RoomRead):
    """Public room response schema including list of beds."""

    beds: list[BedRead] = Field(default_factory=list)


__all__ = [
    "BedRead",
    "RoomBase",
    "RoomCreate",
    "RoomRead",
    "RoomStatus",
    "RoomType",
    "RoomUpdate",
    "RoomWithBedsRead",
    "validate_capacity_for_room_type",
]
