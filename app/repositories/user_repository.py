"""User repository for database operations."""

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.schemas.common import PaginationParams


class UserRepository:
    """Repository handling database operations for the User entity."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        """Fetch a single user by primary key UUID."""
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Fetch a user by email using case-insensitive matching."""
        normalized_email = email.strip().lower()
        stmt = select(User).where(func.lower(User.email) == normalized_email)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, user: User) -> User:
        """Add and flush a new user record."""
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def update(self, user: User) -> User:
        """Flush changes to an existing user record."""
        await self.session.flush()
        await self.session.refresh(user)
        return user

    async def list(
        self,
        params: PaginationParams,
        role: UserRole | None = None,
        is_active: bool | None = None,
        search: str | None = None,
    ) -> tuple[list[User], int]:
        """Fetch a paginated list of users matching optional filters and search string."""
        stmt = select(User)
        count_stmt = select(func.count(User.id))

        if role is not None:
            stmt = stmt.where(User.role == role)
            count_stmt = count_stmt.where(User.role == role)

        if is_active is not None:
            stmt = stmt.where(User.is_active == is_active)
            count_stmt = count_stmt.where(User.is_active == is_active)

        if search:
            search_pattern = f"%{search.strip().lower()}%"
            search_filter = or_(
                func.lower(User.full_name).like(search_pattern),
                func.lower(User.email).like(search_pattern),
            )
            stmt = stmt.where(search_filter)
            count_stmt = count_stmt.where(search_filter)

        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        stmt = stmt.order_by(User.created_at.desc()).offset(params.offset).limit(params.limit)
        items_result = await self.session.execute(stmt)
        users = list(items_result.scalars().all())

        return users, total
