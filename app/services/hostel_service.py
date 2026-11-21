"""Hostel, block, and warden assignment domain service."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationAppError
from app.models.hostel import Block, GenderType, Hostel, WardenAssignment
from app.models.user import User, UserRole
from app.repositories.hostel_repository import (
    BlockRepository,
    HostelRepository,
    WardenAssignmentRepository,
)
from app.repositories.user_repository import UserRepository
from app.schemas.common import Page, PaginationParams
from app.schemas.hostel import (
    BlockCreate,
    BlockUpdate,
    HostelCreate,
    HostelRead,
    HostelUpdate,
)


class HostelService:
    """Service handling business logic for hostels, blocks, and warden scoping."""

    def __init__(
        self,
        session: AsyncSession,
        hostel_repo: HostelRepository | None = None,
        block_repo: BlockRepository | None = None,
        warden_repo: WardenAssignmentRepository | None = None,
        user_repo: UserRepository | None = None,
    ) -> None:
        self.session = session
        self.hostel_repo = hostel_repo or HostelRepository(session)
        self.block_repo = block_repo or BlockRepository(session)
        self.warden_repo = warden_repo or WardenAssignmentRepository(session)
        self.user_repo = user_repo or UserRepository(session)

    async def ensure_hostel_access(self, user: User, hostel_id: UUID) -> bool:
        """Enforce access rules: admin passes, warden must be assigned, others forbidden."""
        role = user.role.value if isinstance(user.role, UserRole) else str(user.role)
        if role == UserRole.ADMIN.value:
            return True
        if role == UserRole.WARDEN.value:
            is_assigned = await self.warden_repo.is_warden_assigned(user.id, hostel_id)
            if is_assigned:
                return True
            raise ForbiddenError("You are not assigned to this hostel", code="FORBIDDEN")
        raise ForbiddenError("Insufficient permissions to access hostel", code="FORBIDDEN")

    async def _ensure_can_delete_hostel(self, hostel_id: UUID) -> None:
        """Guard hook to prevent deleting hostels with active allocations (PROMPT_7)."""
        return None

    async def create_hostel(self, data: HostelCreate) -> Hostel:
        """Create a new hostel ensuring unique code constraint."""
        existing = await self.hostel_repo.get_by_code(data.code, include_deleted=True)
        if existing is not None:
            raise ConflictError("Hostel code already exists", code="HOSTEL_CODE_EXISTS")

        hostel = Hostel(
            name=data.name,
            code=data.code,
            gender_type=data.gender_type,
            address=data.address,
        )
        return await self.hostel_repo.create(hostel)

    async def get_hostel(self, hostel_id: UUID, include_deleted: bool = False) -> Hostel:
        """Retrieve a hostel by ID or raise NotFoundError."""
        hostel = await self.hostel_repo.get_by_id(hostel_id, include_deleted=include_deleted)
        if hostel is None:
            raise NotFoundError("Hostel not found", code="HOSTEL_NOT_FOUND")
        return hostel

    async def list_hostels(
        self,
        params: PaginationParams,
        gender_type: GenderType | None = None,
        search: str | None = None,
    ) -> Page[HostelRead]:
        """Return a paginated list of non-deleted hostels matching optional filters."""
        hostels, total = await self.hostel_repo.list(
            params=params,
            gender_type=gender_type,
            search=search,
        )
        items = [HostelRead.model_validate(h) for h in hostels]
        return Page.create(items=items, total=total, params=params)

    async def update_hostel(self, hostel_id: UUID, data: HostelUpdate) -> Hostel:
        """Update hostel details ensuring code uniqueness."""
        hostel = await self.get_hostel(hostel_id)
        if data.code is not None and data.code.strip().lower() != hostel.code.strip().lower():
            existing = await self.hostel_repo.get_by_code(data.code, include_deleted=True)
            if existing is not None and existing.id != hostel_id:
                raise ConflictError("Hostel code already exists", code="HOSTEL_CODE_EXISTS")

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(hostel, field, value)

        return await self.hostel_repo.update(hostel)

    async def delete_hostel(self, hostel_id: UUID) -> Hostel:
        """Soft delete a hostel after verifying deletion rules."""
        hostel = await self.get_hostel(hostel_id)
        await self._ensure_can_delete_hostel(hostel_id)
        return await self.hostel_repo.soft_delete(hostel)

    async def create_block(self, hostel_id: UUID, data: BlockCreate) -> Block:
        """Create a new block within a hostel ensuring unique block name per hostel."""
        await self.get_hostel(hostel_id)
        existing = await self.block_repo.get_by_name(hostel_id, data.name)
        if existing is not None:
            raise ConflictError(
                "Block with this name already exists in this hostel",
                code="BLOCK_NAME_EXISTS",
            )

        block = Block(
            hostel_id=hostel_id,
            name=data.name,
            floor_count=data.floor_count,
        )
        return await self.block_repo.create(block)

    async def get_block(self, block_id: UUID) -> Block:
        """Retrieve a block by ID or raise NotFoundError."""
        block = await self.block_repo.get_by_id(block_id)
        if block is None:
            raise NotFoundError("Block not found", code="BLOCK_NOT_FOUND")
        return block

    async def list_blocks(self, hostel_id: UUID) -> list[Block]:
        """List all blocks for a given hostel."""
        await self.get_hostel(hostel_id)
        return await self.block_repo.list_by_hostel(hostel_id)

    async def update_block(self, block_id: UUID, data: BlockUpdate) -> Block:
        """Update block details ensuring name uniqueness within the same hostel."""
        block = await self.get_block(block_id)
        if data.name is not None and data.name.strip().lower() != block.name.strip().lower():
            existing = await self.block_repo.get_by_name(block.hostel_id, data.name)
            if existing is not None and existing.id != block.id:
                raise ConflictError(
                    "Block with this name already exists in this hostel",
                    code="BLOCK_NAME_EXISTS",
                )

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(block, field, value)

        return await self.block_repo.update(block)

    async def delete_block(self, block_id: UUID) -> None:
        """Hard delete a block."""
        block = await self.get_block(block_id)
        await self.block_repo.delete(block)

    async def assign_warden(self, hostel_id: UUID, user_id: UUID) -> WardenAssignment:
        """Assign a warden user to a hostel."""
        await self.get_hostel(hostel_id)
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User not found", code="USER_NOT_FOUND")

        if user.role != UserRole.WARDEN:
            raise ValidationAppError(
                "Assigned user must have warden role",
                code="INVALID_WARDEN_ROLE",
                status_code=422,
            )

        existing = await self.warden_repo.get(hostel_id, user_id)
        if existing is not None:
            raise ConflictError(
                "Warden already assigned to this hostel",
                code="WARDEN_ALREADY_ASSIGNED",
            )

        assignment = WardenAssignment(hostel_id=hostel_id, user_id=user_id)
        created = await self.warden_repo.create(assignment)
        created.user = user
        return created

    async def remove_warden(self, hostel_id: UUID, user_id: UUID) -> None:
        """Remove a warden assignment from a hostel."""
        await self.get_hostel(hostel_id)
        assignment = await self.warden_repo.get(hostel_id, user_id)
        if assignment is None:
            raise NotFoundError(
                "Warden assignment not found",
                code="WARDEN_ASSIGNMENT_NOT_FOUND",
            )
        await self.warden_repo.delete(assignment)

    async def list_wardens(self, hostel_id: UUID) -> list[WardenAssignment]:
        """List all wardens assigned to a hostel."""
        await self.get_hostel(hostel_id)
        return await self.warden_repo.list_by_hostel(hostel_id)


async def ensure_hostel_access(session: AsyncSession, user: User, hostel_id: UUID) -> bool:
    """Standalone helper function to enforce hostel access control."""
    service = HostelService(session)
    return await service.ensure_hostel_access(user, hostel_id)
