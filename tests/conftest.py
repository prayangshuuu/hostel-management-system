"""Pytest test configuration and fixtures."""

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models.user import User, UserRole


@pytest.fixture
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create in-memory SQLite engine for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional database session rolled back per test."""
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def pg_session_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Provide an async session factory connected to Postgres for concurrency tests."""
    from app.core.config import settings

    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_size=10,
        max_overflow=20,
    )
    try:
        async with engine.connect() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL not reachable at {settings.DATABASE_URL}: {exc}")

    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    yield factory

    await engine.dispose()


@pytest.fixture
async def client(test_engine: AsyncEngine) -> AsyncGenerator[AsyncClient, None]:
    """Async test client fixture for FastAPI application with test DB override."""
    app = create_app()

    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def admin_user(test_engine: AsyncEngine) -> User:
    """Fixture creating an active administrator user in test DB."""
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        user = User(
            id=uuid4(),
            email="admin@hostel.example.com",
            full_name="System Administrator",
            phone="+1000000000",
            hashed_password=hash_password("AdminPass123"),
            role=UserRole.ADMIN,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.fixture
async def warden_user(test_engine: AsyncEngine) -> User:
    """Fixture creating an active warden user in test DB."""
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        user = User(
            id=uuid4(),
            email="warden@hostel.example.com",
            full_name="Hostel Warden",
            phone="+1111111111",
            hashed_password=hash_password("WardenPass123"),
            role=UserRole.WARDEN,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.fixture
async def student_user(test_engine: AsyncEngine) -> User:
    """Fixture creating an active student user in test DB."""
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        user = User(
            id=uuid4(),
            email="student@hostel.example.com",
            full_name="Hostel Student",
            phone="+1222222222",
            hashed_password=hash_password("StudentPass123"),
            role=UserRole.STUDENT,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


@pytest.fixture
def admin_token(admin_user: User) -> str:
    """Bearer access token for admin user."""
    return create_access_token(user_id=admin_user.id, role="admin")


@pytest.fixture
def warden_token(warden_user: User) -> str:
    """Bearer access token for warden user."""
    return create_access_token(user_id=warden_user.id, role="warden")


@pytest.fixture
def student_token(student_user: User) -> str:
    """Bearer access token for student user."""
    return create_access_token(user_id=student_user.id, role="student")


@pytest.fixture
def admin_headers(admin_token: str) -> dict[str, str]:
    """Authorization headers for admin user."""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def warden_headers(warden_token: str) -> dict[str, str]:
    """Authorization headers for warden user."""
    return {"Authorization": f"Bearer {warden_token}"}


@pytest.fixture
def student_headers(student_token: str) -> dict[str, str]:
    """Authorization headers for student user."""
    return {"Authorization": f"Bearer {student_token}"}


@pytest.fixture
async def admin_client(client: AsyncClient, admin_headers: dict[str, str]) -> AsyncClient:
    """Authenticated client for admin user."""
    client.headers.update(admin_headers)
    return client


@pytest.fixture
async def warden_client(client: AsyncClient, warden_headers: dict[str, str]) -> AsyncClient:
    """Authenticated client for warden user."""
    client.headers.update(warden_headers)
    return client


@pytest.fixture
async def student_client(client: AsyncClient, student_headers: dict[str, str]) -> AsyncClient:
    """Authenticated client for student user."""
    client.headers.update(student_headers)
    return client
