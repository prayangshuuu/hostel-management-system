"""User service managing user lifecycle and queries."""

from uuid import UUID

from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import hash_password, validate_password_policy
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.common import Page, PaginationParams
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.audit_service import AuditService


class UserService:
    """Service handling business logic for user management."""

    def __init__(self, user_repo: UserRepository) -> None:
        self.user_repo = user_repo
        self.session = user_repo.session

    async def create_user(
        self,
        user_create: UserCreate,
        current_user: User | None = None,
    ) -> User:
        """Create a new user ensuring email uniqueness and password policy compliance."""
        existing_user = await self.user_repo.get_by_email(user_create.email)
        if existing_user is not None:
            raise ConflictError("User with this email already exists", code="EMAIL_EXISTS")

        validate_password_policy(user_create.password)
        hashed_password = hash_password(user_create.password)

        user = User(
            email=user_create.email.strip().lower(),
            full_name=user_create.full_name,
            phone=user_create.phone,
            hashed_password=hashed_password,
            role=user_create.role,
            is_active=True,
        )
        created_user = await self.user_repo.create(user)

        role_val = (
            created_user.role.value
            if hasattr(created_user.role, "value")
            else str(created_user.role)
        )
        await AuditService.record(
            self.session,
            current_user.id if current_user else None,
            "user.create",
            "User",
            created_user.id,
            {"email": created_user.email, "role": role_val},
        )
        return created_user

    async def get_user(self, user_id: UUID) -> User:
        """Retrieve a user by ID or raise NotFoundError."""
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found", code="USER_NOT_FOUND")
        return user

    async def update_user(self, user_id: UUID, user_update: UserUpdate) -> User:
        """Update user properties."""
        user = await self.get_user(user_id)
        update_data = user_update.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(user, field, value)

        return await self.user_repo.update(user)

    async def deactivate_user(
        self,
        user_id: UUID,
        current_user: User | None = None,
    ) -> User:
        """Deactivate a user account."""
        user = await self.get_user(user_id)
        user.is_active = False
        updated_user = await self.user_repo.update(user)

        await AuditService.record(
            self.session,
            current_user.id if current_user else None,
            "user.deactivate",
            "User",
            updated_user.id,
            {"email": updated_user.email, "is_active": False},
        )
        return updated_user

    async def list_users(
        self,
        params: PaginationParams,
        role: UserRole | None = None,
        is_active: bool | None = None,
        search: str | None = None,
    ) -> Page[UserRead]:
        """Return a paginated list of users matching query filters."""
        users, total = await self.user_repo.list(
            params=params,
            role=role,
            is_active=is_active,
            search=search,
        )
        items = [UserRead.model_validate(u) for u in users]
        return Page.create(items=items, total=total, params=params)
