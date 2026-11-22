"""Security utilities for password hashing and JWT token management."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import settings
from app.core.exceptions import UnauthorizedError, ValidationAppError

# Initialize PasswordHash with Argon2
password_hash = PasswordHash((Argon2Hasher(),))


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2."""
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its Argon2 hash."""
    return password_hash.verify(plain_password, hashed_password)


def validate_password_policy(password: str) -> None:
    """Validate password according to policy (min 8 chars, >= 1 letter, >= 1 digit)."""
    if len(password) < 8:
        raise ValidationAppError(
            "Password must be at least 8 characters long",
            code="WEAK_PASSWORD",
        )
    if not any(c.isalpha() for c in password):
        raise ValidationAppError(
            "Password must contain at least one letter",
            code="WEAK_PASSWORD",
        )
    if not any(c.isdigit() for c in password):
        raise ValidationAppError(
            "Password must contain at least one number",
            code="WEAK_PASSWORD",
        )


def create_access_token(
    user_id: UUID,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Generate a signed JWT access token."""
    now = datetime.now(UTC)
    expires = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "jti": uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(
    user_id: UUID,
    role: str,
    expires_delta: timedelta | None = None,
    jti: str | None = None,
    family_id: UUID | None = None,
) -> str:
    """Generate a signed JWT refresh token with jti and family_id claims."""
    now = datetime.now(UTC)
    expires = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    token_jti = jti if jti is not None else uuid4().hex
    token_family_id = family_id if family_id is not None else uuid4()
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "type": "refresh",
        "jti": token_jti,
        "family_id": str(token_family_id),
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, expected_type: str | None = None) -> dict[str, Any]:
    """Decode and validate a JWT token signature, expiration, and token type."""
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError as err:
        raise UnauthorizedError("Token has expired", code="TOKEN_EXPIRED") from err
    except jwt.InvalidTokenError as err:
        raise UnauthorizedError("Invalid token", code="INVALID_TOKEN") from err

    if expected_type is not None and payload.get("type") != expected_type:
        raise UnauthorizedError(
            f"Invalid token type: expected {expected_type}",
            code="INVALID_TOKEN_TYPE",
        )

    if not payload.get("sub"):
        raise UnauthorizedError("Token missing subject claim", code="INVALID_TOKEN")

    return payload
