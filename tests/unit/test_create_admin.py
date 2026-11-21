"""Unit tests for create_admin script."""

import sys
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.user import UserRole
from app.repositories.user_repository import UserRepository
from scripts.create_admin import create_admin, parse_args


@pytest.mark.asyncio
async def test_create_admin_script(db_session: AsyncSession) -> None:
    """Verify create_admin creates user in session."""
    session_maker = async_sessionmaker(
        bind=db_session.bind,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    with patch("scripts.create_admin.async_session_maker", return_value=session_maker()):
        await create_admin(
            email="new_cli_admin@hostel.example.com",
            password="AdminPassword123",
            name="CLI Admin",
            phone="+12345678",
        )

    repo = UserRepository(db_session)
    admin = await repo.get_by_email("new_cli_admin@hostel.example.com")
    assert admin is not None
    assert admin.role == UserRole.ADMIN
    assert admin.full_name == "CLI Admin"


@pytest.mark.asyncio
async def test_create_admin_script_existing(db_session: AsyncSession) -> None:
    """Verify create_admin exits cleanly if user already exists."""
    session_maker = async_sessionmaker(
        bind=db_session.bind,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    with patch("scripts.create_admin.async_session_maker", return_value=session_maker()):
        await create_admin(
            email="existing_cli@hostel.example.com",
            password="AdminPassword123",
            name="Existing Admin",
        )

        with pytest.raises(SystemExit) as exc:
            await create_admin(
                email="existing_cli@hostel.example.com",
                password="AdminPassword123",
                name="Existing Admin",
            )
        assert exc.value.code == 0


@pytest.mark.asyncio
async def test_create_admin_script_weak_password() -> None:
    """Verify create_admin exits with code 1 if password policy fails."""
    with pytest.raises(SystemExit) as exc:
        await create_admin(
            email="weak_cli@hostel.example.com",
            password="short",
            name="Weak Admin",
        )
    assert exc.value.code == 1


def test_create_admin_parse_args() -> None:
    """Verify command line arguments parser."""
    test_args = [
        "create_admin.py",
        "--email",
        "custom@hostel.example.com",
        "--password",
        "Pass1234",
        "--name",
        "Custom Name",
        "--phone",
        "+111222",
    ]
    with patch.object(sys, "argv", test_args):
        args = parse_args()
        assert args.email == "custom@hostel.example.com"
        assert args.password == "Pass1234"
        assert args.name == "Custom Name"
        assert args.phone == "+111222"
