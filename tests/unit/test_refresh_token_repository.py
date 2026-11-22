"""Unit tests for RefreshTokenRepository."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.auth import RefreshToken
from app.models.user import User, UserRole
from app.repositories.auth_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository


@pytest.mark.asyncio
async def test_refresh_token_repository_lifecycle(db_session: AsyncSession) -> None:
    """Test full lifecycle of refresh token repository: create, get, revoke."""
    user_repo = UserRepository(db_session)
    user = User(
        id=uuid4(),
        email="token_repo@example.com",
        full_name="Token Repo User",
        hashed_password=hash_password("ValidPassword123"),
        role=UserRole.STUDENT,
        is_active=True,
    )
    await user_repo.create(user)

    repo = RefreshTokenRepository(db_session)
    family_id = uuid4()
    jti = f"jti-{uuid4().hex}"
    expires_at = datetime.now(UTC) + timedelta(days=7)

    # 1. Create with kwargs
    token = await repo.create(
        user_id=user.id,
        jti=jti,
        family_id=family_id,
        expires_at=expires_at,
    )
    assert token.id is not None
    assert token.user_id == user.id
    assert token.jti == jti
    assert token.family_id == family_id
    assert token.is_revoked is False

    # 2. Get by JTI
    fetched = await repo.get_by_jti(jti)
    assert fetched is not None
    assert fetched.id == token.id

    # Non-existent JTI
    non_existent = await repo.get_by_jti("non-existent-jti")
    assert non_existent is None

    # 3. Revoke single token
    revoked = await repo.revoke_token(jti)
    assert revoked is True

    # Re-fetch and verify revoked
    fetched_after = await repo.get_by_jti(jti)
    assert fetched_after is not None
    assert fetched_after.is_revoked is True

    # Second revoke returns False (already revoked)
    revoked_again = await repo.revoke_token(jti)
    assert revoked_again is False


@pytest.mark.asyncio
async def test_refresh_token_repository_revoke_family(db_session: AsyncSession) -> None:
    """Test revoking all tokens belonging to the same token family."""
    user_repo = UserRepository(db_session)
    user = User(
        id=uuid4(),
        email="family_repo@example.com",
        full_name="Family Repo User",
        hashed_password=hash_password("ValidPassword123"),
        role=UserRole.STUDENT,
        is_active=True,
    )
    await user_repo.create(user)

    repo = RefreshTokenRepository(db_session)
    family_id = uuid4()
    expires_at = datetime.now(UTC) + timedelta(days=7)

    # Create 3 tokens in the same family
    jti1 = f"jti-fam-1-{uuid4().hex}"
    jti2 = f"jti-fam-2-{uuid4().hex}"
    jti3 = f"jti-fam-3-{uuid4().hex}"

    await repo.create(user_id=user.id, jti=jti1, family_id=family_id, expires_at=expires_at)
    await repo.create(user_id=user.id, jti=jti2, family_id=family_id, expires_at=expires_at)
    await repo.create(user_id=user.id, jti=jti3, family_id=family_id, expires_at=expires_at)

    # Revoke family
    count = await repo.revoke_family(family_id)
    assert count == 3

    t1 = await repo.get_by_jti(jti1)
    t2 = await repo.get_by_jti(jti2)
    t3 = await repo.get_by_jti(jti3)

    assert t1 is not None and t1.is_revoked is True
    assert t2 is not None and t2.is_revoked is True
    assert t3 is not None and t3.is_revoked is True


@pytest.mark.asyncio
async def test_refresh_token_repository_create_with_instance(db_session: AsyncSession) -> None:
    """Test creating a token by passing a RefreshToken entity directly."""
    user_repo = UserRepository(db_session)
    user = User(
        id=uuid4(),
        email="instance_repo@example.com",
        full_name="Instance Repo User",
        hashed_password=hash_password("ValidPassword123"),
        role=UserRole.STUDENT,
        is_active=True,
    )
    await user_repo.create(user)

    repo = RefreshTokenRepository(db_session)
    jti = f"jti-inst-{uuid4().hex}"
    token_obj = RefreshToken(
        id=uuid4(),
        user_id=user.id,
        jti=jti,
        family_id=uuid4(),
        expires_at=datetime.now(UTC) + timedelta(days=7),
        is_revoked=False,
    )
    created = await repo.create(token_obj)
    assert created.id == token_obj.id
    assert created.jti == jti
    assert jti in repr(created)

    # Test error when missing required attributes
    with pytest.raises(ValueError, match="Must provide either a RefreshToken instance"):
        await repo.create()


@pytest.mark.asyncio
async def test_refresh_token_repository_revoke_by_user_id(db_session: AsyncSession) -> None:
    """Test revoking all active refresh tokens for a user."""
    user_repo = UserRepository(db_session)
    user = User(
        id=uuid4(),
        email="user_revoke@example.com",
        full_name="User Revoke",
        hashed_password=hash_password("ValidPassword123"),
        role=UserRole.STUDENT,
        is_active=True,
    )
    await user_repo.create(user)

    repo = RefreshTokenRepository(db_session)
    family_id = uuid4()
    expires_at = datetime.now(UTC) + timedelta(days=7)
    jti1 = f"jti-u1-{uuid4().hex}"
    jti2 = f"jti-u2-{uuid4().hex}"

    await repo.create(user_id=user.id, jti=jti1, family_id=family_id, expires_at=expires_at)
    await repo.create(user_id=user.id, jti=jti2, family_id=family_id, expires_at=expires_at)

    revoked_count = await repo.revoke_by_user_id(user.id)
    assert revoked_count == 2

    t1 = await repo.get_by_jti(jti1)
    t2 = await repo.get_by_jti(jti2)
    assert t1 is not None and t1.is_revoked is True
    assert t2 is not None and t2.is_revoked is True
