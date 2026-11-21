"""Hostel, block, and warden assignment schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.hostel import GenderType


class HostelBase(BaseModel):
    """Base fields shared by hostel schemas."""

    name: str = Field(min_length=1, max_length=255)
    code: str = Field(min_length=1, max_length=50)
    gender_type: GenderType = GenderType.MIXED
    address: str | None = Field(default=None, max_length=500)

    @field_validator("name", "code", mode="before")
    @classmethod
    def strip_whitespace(cls, v: Any) -> Any:
        """Strip whitespace from strings."""
        if isinstance(v, str):
            return v.strip()
        return v


class HostelCreate(HostelBase):
    """Payload for creating a new hostel."""


class HostelUpdate(BaseModel):
    """Payload for updating hostel details."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(default=None, min_length=1, max_length=50)
    gender_type: GenderType | None = None
    address: str | None = Field(default=None, max_length=500)

    @field_validator("name", "code", mode="before")
    @classmethod
    def strip_whitespace(cls, v: Any) -> Any:
        """Strip whitespace from strings."""
        if isinstance(v, str):
            return v.strip()
        return v


class HostelRead(BaseModel):
    """Public hostel response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str
    gender_type: GenderType
    address: str | None
    is_deleted: bool
    total_capacity: int = 0
    created_at: datetime
    updated_at: datetime


class BlockBase(BaseModel):
    """Base fields shared by block schemas."""

    name: str = Field(min_length=1, max_length=100)
    floor_count: int = Field(default=1, ge=1)

    @field_validator("name", mode="before")
    @classmethod
    def strip_whitespace(cls, v: Any) -> Any:
        """Strip whitespace from strings."""
        if isinstance(v, str):
            return v.strip()
        return v


class BlockCreate(BlockBase):
    """Payload for creating a new block in a hostel."""


class BlockUpdate(BaseModel):
    """Payload for updating block details."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    floor_count: int | None = Field(default=None, ge=1)

    @field_validator("name", mode="before")
    @classmethod
    def strip_whitespace(cls, v: Any) -> Any:
        """Strip whitespace from strings."""
        if isinstance(v, str):
            return v.strip()
        return v


class BlockRead(BaseModel):
    """Public block response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    hostel_id: UUID
    name: str
    floor_count: int
    created_at: datetime
    updated_at: datetime


class WardenAssignRequest(BaseModel):
    """Payload for assigning a warden to a hostel."""

    user_id: UUID


class WardenAssignmentRead(BaseModel):
    """Public warden assignment response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    hostel_id: UUID
    user_email: str | None = None
    user_full_name: str | None = None
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def populate_user_fields(cls, data: Any) -> Any:
        """Extract user details if data is an ORM model or contains user relation."""
        if isinstance(data, dict):
            return data
        user = getattr(data, "user", None)
        return {
            "id": getattr(data, "id", None),
            "user_id": getattr(data, "user_id", None),
            "hostel_id": getattr(data, "hostel_id", None),
            "user_email": (
                getattr(user, "email", None) if user else getattr(data, "user_email", None)
            ),
            "user_full_name": (
                getattr(user, "full_name", None) if user else getattr(data, "user_full_name", None)
            ),
            "created_at": getattr(data, "created_at", None),
        }
