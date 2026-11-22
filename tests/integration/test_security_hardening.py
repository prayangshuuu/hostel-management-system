"""Integration tests for security hardening features.

Validates:
1. Rate limiting (429 Too Many Requests on threshold exceed).
2. Account lockout after consecutive failed logins and automatic unlock after cooldown.
3. Refresh token rotation, reuse detection (family revocation), and logout invalidation.
4. Production startup validation on weak/insecure SECRET_KEY.
5. Defensive security headers (X-Content-Type-Options, X-Frame-Options, Referrer-Policy, HSTS).
6. API docs (/docs, /redoc, /openapi.json) disabled in production unless ENABLE_DOCS=True.
7. Request payload size limit enforcement (413 Payload Too Large).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.rate_limit import limiter
from app.core.security import hash_password
from app.db.session import get_db
from app.main import create_app
from app.models.user import User, UserRole


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> None:
    """Reset the in-memory slowapi limiter between test runs."""
    limiter.reset()


@pytest.mark.asyncio
async def test_rate_limiting_login_returns_429(
    client: AsyncClient,
    test_engine: AsyncEngine,
) -> None:
    """Verify that exceeding login rate limit (5/min per IP+email) returns unified 429."""
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        user = User(
            id=uuid4(),
            email="ratelimit_target@example.com",
            full_name="Rate Limit User",
            hashed_password=hash_password("Password123"),
            role=UserRole.STUDENT,
            is_active=True,
        )
        session.add(user)
        await session.commit()

    # Reset limiter storage
    limiter.reset()

    # First 5 login attempts are evaluated (all return 401 due to wrong password)
    for _ in range(5):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "ratelimit_target@example.com", "password": "WrongPassword123"},
        )
        assert resp.status_code == 401

    # 6th attempt should exceed 5/min rate limit and trigger unified 429 response
    resp_rate_limited = await client.post(
        "/api/v1/auth/login",
        json={"email": "ratelimit_target@example.com", "password": "WrongPassword123"},
    )
    assert resp_rate_limited.status_code == 429
    body = resp_rate_limited.json()
    assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Too many requests" in body["error"]["message"]


@pytest.mark.asyncio
async def test_account_lockout_and_auto_unlock_after_cooldown(
    client: AsyncClient,
    test_engine: AsyncEngine,
) -> None:
    """Verify account lockout after 5 failed logins and automatic unlock after cooldown."""
    limiter.reset()

    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    user_id = uuid4()
    async with session_factory() as session:
        user = User(
            id=user_id,
            email="lockout_user@example.com",
            full_name="Lockout Test User",
            hashed_password=hash_password("CorrectPass123"),
            role=UserRole.STUDENT,
            is_active=True,
            failed_login_attempts=0,
            locked_until=None,
        )
        session.add(user)
        await session.commit()

    # 1. First 4 failed logins: 401 INVALID_CREDENTIALS, increment failed counter
    for i in range(1, 5):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": f"lockout_{i}@example.com", "password": "BadPassword123"},
        )
        # Use different emails for slowapi limiter but direct DB check on user
    limiter.reset()

    # Deliver 5 failed logins directly to lockout_user email
    for _ in range(5):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "lockout_user@example.com", "password": "BadPassword123"},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"

    # Verify user record in database has failed_login_attempts >= 5 and locked_until set
    async with session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        db_user = result.scalar_one()
        assert db_user.failed_login_attempts >= 5
        assert db_user.locked_until is not None
        locked_time = (
            db_user.locked_until
            if db_user.locked_until.tzinfo is not None
            else db_user.locked_until.replace(tzinfo=UTC)
        )
        assert locked_time > datetime.now(UTC)

    limiter.reset()

    # 6th login with correct password should be rejected with 401 ACCOUNT_LOCKED
    resp_locked = await client.post(
        "/api/v1/auth/login",
        json={"email": "lockout_user@example.com", "password": "CorrectPass123"},
    )
    assert resp_locked.status_code == 401
    assert resp_locked.json()["error"]["code"] == "ACCOUNT_LOCKED"
    assert "locked" in resp_locked.json()["error"]["message"].lower()

    # Fast-forward time past lockout cooldown
    async with session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        db_user = result.scalar_one()
        db_user.locked_until = datetime.now(UTC) - timedelta(minutes=1)
        session.add(db_user)
        await session.commit()

    limiter.reset()

    # Login after cooldown with correct password succeeds and clears lockout
    resp_unlocked = await client.post(
        "/api/v1/auth/login",
        json={"email": "lockout_user@example.com", "password": "CorrectPass123"},
    )
    assert resp_unlocked.status_code == 200
    assert "access_token" in resp_unlocked.json()

    # Verify user record is reset in DB
    async with session_factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        db_user = result.scalar_one()
        assert db_user.failed_login_attempts == 0
        assert db_user.locked_until is None


@pytest.mark.asyncio
async def test_refresh_token_rotation_and_family_reuse_detection(
    client: AsyncClient,
    test_engine: AsyncEngine,
) -> None:
    """Verify refresh token rotation and family revocation on reuse attempt."""
    limiter.reset()

    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        user = User(
            id=uuid4(),
            email="rotation_test@example.com",
            full_name="Rotation Test User",
            hashed_password=hash_password("RotationPass123"),
            role=UserRole.STUDENT,
            is_active=True,
        )
        session.add(user)
        await session.commit()

    # 1. Initial login -> Pair 1
    resp1 = await client.post(
        "/api/v1/auth/login",
        json={"email": "rotation_test@example.com", "password": "RotationPass123"},
    )
    assert resp1.status_code == 200
    token1 = resp1.json()
    r1 = token1["refresh_token"]

    # 2. Refresh Token 1 -> Pair 2 (Token 1 rotated and marked revoked)
    resp2 = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": r1},
    )
    assert resp2.status_code == 200
    token2 = resp2.json()
    r2 = token2["refresh_token"]
    assert r2 != r1

    # 3. Refresh Token 2 -> Pair 3 (Token 2 rotated)
    resp3 = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": r2},
    )
    assert resp3.status_code == 200
    token3 = resp3.json()
    r3 = token3["refresh_token"]
    assert r3 != r2

    # 4. Token Reuse Attack: Attacker tries to use already-rotated Token 1
    resp_reuse = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": r1},
    )
    assert resp_reuse.status_code == 401
    assert resp_reuse.json()["error"]["code"] == "TOKEN_REVOKED"

    # 5. Token Family Revocation: Legitimate Token 3 should now also be revoked
    resp_family_revoked = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": r3},
    )
    assert resp_family_revoked.status_code == 401
    assert resp_family_revoked.json()["error"]["code"] == "TOKEN_REVOKED"


@pytest.mark.asyncio
async def test_logout_invalidates_refresh_token_family(
    client: AsyncClient,
    test_engine: AsyncEngine,
) -> None:
    """Verify that logging out revokes the refresh token family."""
    limiter.reset()

    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        user = User(
            id=uuid4(),
            email="logout_test@example.com",
            full_name="Logout Test User",
            hashed_password=hash_password("LogoutPass123"),
            role=UserRole.STUDENT,
            is_active=True,
        )
        session.add(user)
        await session.commit()

    # Login
    resp_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "logout_test@example.com", "password": "LogoutPass123"},
    )
    tokens = resp_login.json()
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    # Logout with refresh_token in payload
    resp_logout = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refresh_token},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp_logout.status_code == 200
    assert resp_logout.json()["message"] == "Logged out successfully"

    # Attempting to refresh with the logged-out token must fail
    resp_after_logout = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert resp_after_logout.status_code == 401


def test_production_config_rejects_weak_secret_key() -> None:
    """Verify Settings raises ValidationError in production when SECRET_KEY is weak."""
    # Short key (<32 chars)
    with pytest.raises(ValidationError) as exc1:
        Settings(APP_ENV="production", SECRET_KEY="short-key")
    assert "at least 32 characters" in str(exc1.value)

    # Insecure default key
    with pytest.raises(ValidationError) as exc2:
        Settings(
            APP_ENV="production",
            SECRET_KEY="insecure-dev-secret-key-change-in-production",
        )
    assert "cannot contain 'insecure'" in str(exc2.value)

    # Valid strong production secret key
    valid_settings = Settings(
        APP_ENV="production",
        SECRET_KEY="production-super-strong-secret-key-with-high-entropy-123456",
    )
    assert valid_settings.APP_ENV == "production"
    assert len(valid_settings.SECRET_KEY) >= 32


@pytest.mark.asyncio
async def test_security_headers_present_on_responses(client: AsyncClient) -> None:
    """Verify presence of security headers on all API responses."""
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    headers = resp.headers

    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


@pytest.mark.asyncio
async def test_hsts_header_in_production(test_engine: AsyncEngine) -> None:
    """Verify Strict-Transport-Security header is emitted when APP_ENV=production."""
    mock_settings = Settings(
        APP_ENV="production",
        SECRET_KEY="production-super-strong-secret-key-with-high-entropy-123456",
    )
    with (
        patch("app.main.settings", mock_settings),
        patch("app.core.security_middleware.settings", mock_settings),
    ):
        prod_app = create_app()

        session_factory = async_sessionmaker(
            bind=test_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async def _override_db() -> Any:
            async with session_factory() as session:
                yield session

        prod_app.dependency_overrides[get_db] = _override_db
        transport = ASGITransport(app=prod_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/v1/health")
            assert resp.status_code == 200
            assert "Strict-Transport-Security" in resp.headers
            assert "includeSubDomains" in resp.headers["Strict-Transport-Security"]


@pytest.mark.asyncio
async def test_docs_disabled_in_production_unless_enable_docs(test_engine: AsyncEngine) -> None:
    """Verify /docs, /redoc, /openapi.json are disabled in production unless ENABLE_DOCS=True."""
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def _override_db() -> Any:
        async with session_factory() as session:
            yield session

    # Case 1: APP_ENV=production, ENABLE_DOCS=False -> Endpoints return 404
    prod_settings_no_docs = Settings(
        APP_ENV="production",
        SECRET_KEY="production-super-strong-secret-key-with-high-entropy-123456",
        ENABLE_DOCS=False,
    )
    with patch("app.main.settings", prod_settings_no_docs):
        app_no_docs = create_app()
        app_no_docs.dependency_overrides[get_db] = _override_db
        transport = ASGITransport(app=app_no_docs)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp_docs = await ac.get("/docs")
            assert resp_docs.status_code == 404

            resp_redoc = await ac.get("/redoc")
            assert resp_redoc.status_code == 404

            resp_openapi = await ac.get("/openapi.json")
            assert resp_openapi.status_code == 404

    # Case 2: APP_ENV=production, ENABLE_DOCS=True -> Endpoints return 200
    prod_settings_with_docs = Settings(
        APP_ENV="production",
        SECRET_KEY="production-super-strong-secret-key-with-high-entropy-123456",
        ENABLE_DOCS=True,
    )
    with patch("app.main.settings", prod_settings_with_docs):
        app_with_docs = create_app()
        app_with_docs.dependency_overrides[get_db] = _override_db
        transport = ASGITransport(app=app_with_docs)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp_docs = await ac.get("/docs")
            assert resp_docs.status_code == 200

            resp_openapi = await ac.get("/openapi.json")
            assert resp_openapi.status_code == 200


@pytest.mark.asyncio
async def test_request_body_size_limit_exceeded(client: AsyncClient) -> None:
    """Verify that requests with payload > 5MB are rejected with 413 Payload Too Large."""
    # 6MB body
    large_payload = "a" * (6 * 1024 * 1024)
    resp = await client.post(
        "/api/v1/auth/login",
        content=large_payload,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 413
    body = resp.json()
    assert body["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert "Request payload exceeds maximum allowed size" in body["error"]["message"]
