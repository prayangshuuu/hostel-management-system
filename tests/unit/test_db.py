"""Unit tests for database base models, mixins, and session."""

import uuid

import pytest
from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column

from app.api.deps import get_db as deps_get_db
from app.core.config import Settings
from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPkMixin
from app.db.session import get_db


def test_deps_re_exports_get_db() -> None:
    """Verify that app.api.deps exports get_db."""
    assert deps_get_db is get_db


class DummyModel(Base, UUIDPkMixin, TimestampMixin, SoftDeleteMixin):
    """Test model inheriting mixins."""

    __tablename__ = "dummy_items"

    name: Mapped[str] = mapped_column(String(50))


def test_metadata_naming_conventions() -> None:
    """Verify that metadata naming convention matches requirement."""
    convention = Base.metadata.naming_convention
    assert convention["ix"] == "ix_%(column_0_label)s"
    assert convention["uq"] == "uq_%(table_name)s_%(column_0_name)s"
    assert convention["ck"] == "ck_%(table_name)s_%(constraint_name)s"
    assert convention["fk"] == "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
    assert convention["pk"] == "pk_%(table_name)s"


def test_model_mixins_columns() -> None:
    """Verify that models with mixins have id, created_at, updated_at, is_deleted."""
    columns = DummyModel.__table__.columns
    assert "id" in columns
    assert "created_at" in columns
    assert "updated_at" in columns
    assert "is_deleted" in columns

    assert columns["id"].primary_key is True


@pytest.mark.asyncio
async def test_in_memory_crud_and_mixins() -> None:
    """Verify in-memory SQLite schema creation, inserts, and defaults."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    test_session_maker = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    item_id = uuid.uuid4()
    async with test_session_maker() as session:
        item = DummyModel(id=item_id, name="Test Item")
        session.add(item)
        await session.commit()

    async with test_session_maker() as session:
        result = await session.execute(select(DummyModel).where(DummyModel.id == item_id))
        fetched = result.scalar_one()
        assert fetched.id == item_id
        assert fetched.name == "Test Item"
        assert fetched.is_deleted is False
        assert fetched.created_at is not None

    await test_engine.dispose()


@pytest.mark.asyncio
async def test_get_db_yields_session_and_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify get_db generator yields active session and commits on exit."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    test_session_maker = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    monkeypatch.setattr("app.db.session.AsyncSessionLocal", test_session_maker)

    item_id = uuid.uuid4()
    gen = get_db()
    session = await anext(gen)
    assert isinstance(session, AsyncSession)

    item = DummyModel(id=item_id, name="Auto Commited Item")
    session.add(item)

    # Finishing the generator triggers session.commit()
    with pytest.raises(StopAsyncIteration):
        await anext(gen)

    async with test_session_maker() as verify_session:
        res = await verify_session.execute(select(DummyModel).where(DummyModel.id == item_id))
        assert res.scalar_one_or_none() is not None

    await test_engine.dispose()


@pytest.mark.asyncio
async def test_get_db_rolls_back_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify get_db rolls back the transaction when an exception is raised."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    test_session_maker = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    monkeypatch.setattr("app.db.session.AsyncSessionLocal", test_session_maker)

    item_id = uuid.uuid4()
    gen = get_db()
    session = await anext(gen)

    item = DummyModel(id=item_id, name="Rollback Item")
    session.add(item)

    with pytest.raises(RuntimeError, match="Simulated Error"):
        await gen.athrow(RuntimeError("Simulated Error"))

    async with test_session_maker() as verify_session:
        res = await verify_session.execute(select(DummyModel).where(DummyModel.id == item_id))
        assert res.scalar_one_or_none() is None

    await test_engine.dispose()


def test_cors_settings_parsing() -> None:
    """Verify CORS origins parsing for JSON string and comma-separated string."""
    s1 = Settings(CORS_ORIGINS='["http://localhost:3000"]')
    assert s1.CORS_ORIGINS == ["http://localhost:3000"]

    s2 = Settings(CORS_ORIGINS="http://localhost:3000, http://localhost:8000")
    assert s2.CORS_ORIGINS == ["http://localhost:3000", "http://localhost:8000"]

    s3 = Settings(CORS_ORIGINS=["http://example.com"])
    assert s3.CORS_ORIGINS == ["http://example.com"]

    s4 = Settings(CORS_ORIGINS="[invalid-json")
    assert s4.CORS_ORIGINS == ["[invalid-json"]

    s5 = Settings.model_validate({"CORS_ORIGINS": 123})
    assert s5.CORS_ORIGINS == ["*"]
