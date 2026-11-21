"""Unit tests for security functions, hashing, tokens, and password policy."""

from datetime import timedelta
from uuid import uuid4

import jwt
import pytest

from app.core.config import settings
from app.core.exceptions import UnauthorizedError, ValidationAppError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    validate_password_policy,
    verify_password,
)


def test_password_hash_and_verify() -> None:
    """Verify password hashing with Argon2 and subsequent verification."""
    password = "SuperSecurePassword123"
    hashed = hash_password(password)

    assert hashed != password
    assert hashed.startswith("$argon2")
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword123", hashed) is False


def test_password_policy_valid() -> None:
    """Verify password policy accepts passwords with >=8 chars, letters, and numbers."""
    validate_password_policy("Valid123")
    validate_password_policy("complex_pass_word_99")


def test_password_policy_too_short() -> None:
    """Verify password policy rejects passwords shorter than 8 characters."""
    with pytest.raises(ValidationAppError) as exc_info:
        validate_password_policy("Sh1")
    assert exc_info.value.code == "WEAK_PASSWORD"
    assert "at least 8 characters" in exc_info.value.message


def test_password_policy_no_letter() -> None:
    """Verify password policy rejects passwords without letters."""
    with pytest.raises(ValidationAppError) as exc_info:
        validate_password_policy("12345678")
    assert exc_info.value.code == "WEAK_PASSWORD"
    assert "at least one letter" in exc_info.value.message


def test_password_policy_no_number() -> None:
    """Verify password policy rejects passwords without numbers."""
    with pytest.raises(ValidationAppError) as exc_info:
        validate_password_policy("lettersOnly")
    assert exc_info.value.code == "WEAK_PASSWORD"
    assert "at least one number" in exc_info.value.message


def test_create_and_decode_access_token() -> None:
    """Verify access token creation and decoding of all claims."""
    user_id = uuid4()
    token = create_access_token(user_id=user_id, role="admin")

    payload = decode_token(token, expected_type="access")
    assert payload["sub"] == str(user_id)
    assert payload["role"] == "admin"
    assert payload["type"] == "access"
    assert "jti" in payload
    assert "exp" in payload
    assert "iat" in payload


def test_create_and_decode_refresh_token() -> None:
    """Verify refresh token creation and decoding of all claims."""
    user_id = uuid4()
    token = create_refresh_token(user_id=user_id, role="student")

    payload = decode_token(token, expected_type="refresh")
    assert payload["sub"] == str(user_id)
    assert payload["role"] == "student"
    assert payload["type"] == "refresh"
    assert "jti" in payload


def test_decode_token_expired() -> None:
    """Verify expired token raises UnauthorizedError with TOKEN_EXPIRED code."""
    user_id = uuid4()
    # Create token expired 10 seconds ago
    token = create_access_token(
        user_id=user_id, role="student", expires_delta=timedelta(seconds=-10)
    )

    with pytest.raises(UnauthorizedError) as exc_info:
        decode_token(token)
    assert exc_info.value.code == "TOKEN_EXPIRED"


def test_decode_token_wrong_type() -> None:
    """Verify decode_token enforces expected token type."""
    user_id = uuid4()
    access_token = create_access_token(user_id=user_id, role="admin")

    with pytest.raises(UnauthorizedError) as exc_info:
        decode_token(access_token, expected_type="refresh")
    assert exc_info.value.code == "INVALID_TOKEN_TYPE"


def test_decode_token_invalid_signature() -> None:
    """Verify invalid token signature or malformed token raises UnauthorizedError."""
    with pytest.raises(UnauthorizedError) as exc_info:
        decode_token("not.a.valid.jwt.token")
    assert exc_info.value.code == "INVALID_TOKEN"


def test_decode_token_missing_subject() -> None:
    """Verify token missing sub claim raises UnauthorizedError."""
    token = jwt.encode(
        {"role": "admin", "type": "access"},
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(UnauthorizedError) as exc_info:
        decode_token(token)
    assert exc_info.value.code == "INVALID_TOKEN"
