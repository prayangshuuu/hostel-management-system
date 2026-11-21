"""CLI script to bootstrap the initial system administrator account."""

import argparse
import asyncio
import os
import sys

from app.core.exceptions import ValidationAppError
from app.core.security import hash_password, validate_password_policy
from app.db.session import async_session_maker
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository


async def create_admin(email: str, password: str, name: str, phone: str | None = None) -> None:
    """Create an administrator account if it does not already exist."""
    normalized_email = email.strip().lower()

    try:
        validate_password_policy(password)
    except ValidationAppError as err:
        print(
            f"Error: Password does not meet security requirements: {err.message}",
            file=sys.stderr,
        )
        sys.exit(1)

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        existing = await user_repo.get_by_email(normalized_email)
        if existing is not None:
            print(
                f"User with email '{normalized_email}' already exists (role={existing.role}).",
                file=sys.stderr,
            )
            sys.exit(0)

        hashed = hash_password(password)
        admin_user = User(
            email=normalized_email,
            full_name=name.strip(),
            phone=phone.strip() if phone else None,
            hashed_password=hashed,
            role=UserRole.ADMIN,
            is_active=True,
        )
        await user_repo.create(admin_user)
        await session.commit()
        print(f"Admin user created successfully: {admin_user.email} (id={admin_user.id})")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments with environment variable fallbacks."""
    parser = argparse.ArgumentParser(description="Create initial system administrator user.")
    parser.add_argument(
        "--email",
        default=os.getenv("ADMIN_EMAIL"),
        help="Admin email address (defaults to ADMIN_EMAIL env var)",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("ADMIN_PASSWORD"),
        help="Admin password (defaults to ADMIN_PASSWORD env var)",
    )
    parser.add_argument(
        "--name",
        default=os.getenv("ADMIN_NAME", "System Administrator"),
        help="Admin full name (defaults to ADMIN_NAME env var or 'System Administrator')",
    )
    parser.add_argument(
        "--phone",
        default=os.getenv("ADMIN_PHONE"),
        help="Admin phone number (optional)",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point for CLI execution."""
    args = parse_args()

    email = args.email
    password = args.password
    name = args.name
    phone = args.phone

    if not email:
        email = input("Admin Email: ").strip()
    if not password:
        import getpass

        password = getpass.getpass("Admin Password: ").strip()

    if not email or not password:
        print("Error: Both email and password are required.", file=sys.stderr)
        sys.exit(1)

    asyncio.run(create_admin(email=email, password=password, name=name, phone=phone))


if __name__ == "__main__":
    main()
