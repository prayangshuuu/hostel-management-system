"""Unit tests for auth and user schema validations."""

import pytest
from pydantic import ValidationError

from app.schemas.auth import ChangePasswordRequest, LoginRequest
from app.schemas.user import UserCreate


def test_login_request_normalizes_email() -> None:
    """Verify LoginRequest normalizes email to lowercase and strips whitespace."""
    req = LoginRequest(email="  USER@EXAMPLE.COM  ", password="Password123")
    assert req.email == "user@example.com"


def test_change_password_schema_validation() -> None:
    """Verify ChangePasswordRequest enforces password complexity."""
    # Too short
    with pytest.raises(ValidationError):
        ChangePasswordRequest(current_password="Password123", new_password="short")

    # No letters
    with pytest.raises(ValidationError):
        ChangePasswordRequest(current_password="Password123", new_password="123456789")

    # No numbers
    with pytest.raises(ValidationError):
        ChangePasswordRequest(current_password="Password123", new_password="LettersOnlyHere")

    # Valid
    req = ChangePasswordRequest(current_password="Password123", new_password="ValidPassword123")
    assert req.new_password == "ValidPassword123"


def test_user_create_schema_validation() -> None:
    """Verify UserCreate enforces email normalization and password complexity."""
    # No letters
    with pytest.raises(ValidationError):
        UserCreate(email="user@example.com", full_name="User", password="123456789")

    # No numbers
    with pytest.raises(ValidationError):
        UserCreate(email="user@example.com", full_name="User", password="LettersOnly")

    # Valid
    user = UserCreate(email="  Mixed@Example.COM ", full_name="User", password="Password123")
    assert user.email == "mixed@example.com"
