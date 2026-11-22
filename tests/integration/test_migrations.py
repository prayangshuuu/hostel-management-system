"""Alembic migration reversibility test against PostgreSQL."""

import asyncio
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from app.core.config import get_settings
from scripts.seed import seed_data

ALEMBIC_INI_PATH = str(Path(__file__).resolve().parent.parent.parent / "alembic.ini")


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_alembic_migrations_reversibility() -> None:
    """Verify Alembic migration reversibility against PostgreSQL.

    Executes:
    1. downgrade base (all migrations reverted)
    2. upgrade head (all migrations reapplied)
    3. downgrade base (re-verification of clean rollback)
    4. upgrade head (final schema state restoration)
    5. reseeds database to verify constraints and relationships on freshly migrated schema.
    """
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL not reachable at {settings.DATABASE_URL}: {exc}")

    await engine.dispose()

    def _run_reversibility_cycle() -> None:
        cfg = Config(ALEMBIC_INI_PATH)
        # Downgrade all the way to base
        command.downgrade(cfg, "base")
        # Upgrade all the way to head
        command.upgrade(cfg, "head")
        # Downgrade again to confirm reversibility is idempotent
        command.downgrade(cfg, "base")
        # Re-upgrade to head
        command.upgrade(cfg, "head")

    # Run in thread because Alembic's env.py invokes asyncio.run()
    await asyncio.to_thread(_run_reversibility_cycle)

    # Reseed to guarantee test suite and demo environment remain fully functional
    await seed_data(reset=True)
