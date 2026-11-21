"""Student profile request and response schemas."""

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.hostel import GenderType

PHONE_REGEX = r"^\+?[1-9]\d{1,14}$"
phone_pattern = re.compile(PHONE_REGEX)


def validate_phone_number(v: str | None) -> str | None:
    """Validate phone number against E.164-compatible regex."""
    if v is None:
        return None
    cleaned = v.strip()
    if not phone_pattern.match(cleaned):
        raise ValueError(f"Invalid phone number format: '{v}'. Must match pattern {PHONE_REGEX}")
    return cleaned


def validate_required_phone_number(v: str) -> str:
    """Validate required phone number against E.164-compatible regex."""
    cleaned = v.strip()
    if not phone_pattern.match(cleaned):
        raise ValueError(f"Invalid phone number format: '{v}'. Must match pattern {PHONE_REGEX}")
    return cleaned


class StudentCreate(BaseModel):
    """Payload for creating a new student account and associated profile."""

    email: EmailStr
    full_name: str
    phone: str | None = None
    password: str | None = None
    student_no: str
    gender: GenderType
    department: str
    year: int = Field(ge=1, le=6, description="Academic year (1 to 6)")
    guardian_name: str
    guardian_phone: str
    emergency_contact: str

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        """Normalize email address to lowercase stripped string."""
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("student_no", mode="before")
    @classmethod
    def strip_student_no(cls, v: str) -> str:
        """Strip leading and trailing whitespace from student number."""
        return v.strip() if isinstance(v, str) else v

    @field_validator("phone", mode="before")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        """Validate student phone number if provided."""
        return validate_phone_number(v)

    @field_validator("guardian_phone", "emergency_contact", mode="before")
    @classmethod
    def check_required_phone(cls, v: str) -> str:
        """Validate required phone numbers."""
        return validate_required_phone_number(v)

    @field_validator("password")
    @classmethod
    def check_password_policy(cls, v: str | None) -> str | None:
        """Validate password strength if provided."""
        if v is not None:
            if len(v) < 8:
                raise ValueError("Password must be at least 8 characters long")
            if not any(c.isalpha() for c in v):
                raise ValueError("Password must contain at least one letter")
            if not any(c.isdigit() for c in v):
                raise ValueError("Password must contain at least one number")
        return v


class StudentUpdate(BaseModel):
    """Payload for updating student profile and user details by admin or warden."""

    department: str | None = None
    year: int | None = Field(default=None, ge=1, le=6)
    guardian_name: str | None = None
    guardian_phone: str | None = None
    emergency_contact: str | None = None
    full_name: str | None = None
    phone: str | None = None
    is_active: bool | None = None

    @field_validator("phone", "guardian_phone", "emergency_contact", mode="before")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        """Validate phone numbers if provided."""
        return validate_phone_number(v)


class StudentProfileRead(BaseModel):
    """Public student profile response schema with flattened user fields."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    student_no: str
    gender: GenderType
    department: str
    year: int
    guardian_name: str
    guardian_phone: str
    emergency_contact: str
    is_deleted: bool
    created_at: datetime
    updated_at: datetime

    # Flattened User fields
    full_name: str
    email: EmailStr
    phone: str | None = None
    is_active: bool

    # Allocation placeholder (PROMPT_7)
    current_allocation: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def extract_user_fields(cls, data: Any) -> Any:
        """Extract flattened user fields and temporary password from ORM or dict."""
        if isinstance(data, dict):
            return data

        user = getattr(data, "user", None)
        payload: dict[str, Any] = {
            "id": getattr(data, "id", None),
            "user_id": getattr(data, "user_id", None),
            "student_no": getattr(data, "student_no", None),
            "gender": getattr(data, "gender", None),
            "department": getattr(data, "department", None),
            "year": getattr(data, "year", None),
            "guardian_name": getattr(data, "guardian_name", None),
            "guardian_phone": getattr(data, "guardian_phone", None),
            "emergency_contact": getattr(data, "emergency_contact", None),
            "is_deleted": getattr(data, "is_deleted", False),
            "created_at": getattr(data, "created_at", None),
            "updated_at": getattr(data, "updated_at", None),
            "full_name": (
                getattr(user, "full_name", None) if user else getattr(data, "full_name", None)
            ),
            "email": getattr(user, "email", None) if user else getattr(data, "email", None),
            "phone": getattr(user, "phone", None) if user else getattr(data, "phone", None),
            "is_active": (
                getattr(user, "is_active", True) if user else getattr(data, "is_active", True)
            ),
            "current_allocation": getattr(data, "current_allocation", None),
        }
        if hasattr(data, "temporary_password"):
            payload["temporary_password"] = getattr(data, "temporary_password", None)
        return payload


class StudentCreatedResponse(StudentProfileRead):
    """Response schema for newly created student including optional generated password."""

    temporary_password: str | None = None
