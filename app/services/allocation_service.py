"""Room bed allocation service managing lifecycle, business rules, and transactions."""

from datetime import date
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.models.allocation import Allocation, AllocationStatus
from app.models.hostel import GenderType
from app.models.room import Bed, RoomStatus
from app.models.user import User, UserRole
from app.repositories.allocation_repository import AllocationRepository
from app.repositories.hostel_repository import (
    BlockRepository,
    HostelRepository,
    WardenAssignmentRepository,
)
from app.repositories.room_repository import BedRepository, RoomRepository
from app.repositories.student_repository import StudentRepository
from app.schemas.allocation import (
    AllocationCreate,
    AllocationRead,
    AllocationTransferRequest,
    AllocationVacateRequest,
    OccupantRead,
)
from app.schemas.common import Page, PaginationParams
from app.services.hostel_service import ensure_hostel_access
from app.services.room_service import RoomService


class AllocationService:
    """Service handling bed allocation, transfer, vacate, cancel, and scoping invariants."""

    def __init__(
        self,
        session: AsyncSession,
        allocation_repo: AllocationRepository | None = None,
        bed_repo: BedRepository | None = None,
        room_repo: RoomRepository | None = None,
        block_repo: BlockRepository | None = None,
        hostel_repo: HostelRepository | None = None,
        student_repo: StudentRepository | None = None,
        warden_repo: WardenAssignmentRepository | None = None,
    ) -> None:
        self.session = session
        self.allocation_repo = allocation_repo or AllocationRepository(session)
        self.bed_repo = bed_repo or BedRepository(session)
        self.room_repo = room_repo or RoomRepository(session)
        self.block_repo = block_repo or BlockRepository(session)
        self.hostel_repo = hostel_repo or HostelRepository(session)
        self.student_repo = student_repo or StudentRepository(session)
        self.warden_repo = warden_repo or WardenAssignmentRepository(session)

    async def allocate(self, data: AllocationCreate, current_user: User) -> Allocation:
        """Assign an active student to an available bed with domain and scoping validation."""
        user_role = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if user_role not in (UserRole.ADMIN.value, UserRole.WARDEN.value):
            raise ForbiddenError("Only admin and warden can allocate beds", code="FORBIDDEN")

        student = await self.student_repo.get_by_id(data.student_id)
        if student is None or student.is_deleted:
            raise NotFoundError("Student not found", code="STUDENT_NOT_FOUND")

        if student.user is None or not student.user.is_active:
            raise BusinessRuleError(
                "Student user account is inactive",
                code="USER_INACTIVE",
                status_code=400,
            )

        active_student_alloc = await self.allocation_repo.get_active_by_student_id(student.id)
        if active_student_alloc is not None:
            raise BusinessRuleError(
                "Student already has an active allocation",
                code="STUDENT_ALREADY_ALLOCATED",
                status_code=400,
            )

        bed: Bed | None = None
        if data.bed_id is not None:
            bed = await self.bed_repo.get_by_id_for_update(data.bed_id)
            if bed is None:
                raise NotFoundError("Bed not found", code="BED_NOT_FOUND")
            if data.room_id is not None and bed.room_id != data.room_id:
                raise BusinessRuleError(
                    "Bed does not belong to specified room",
                    code="BED_NOT_IN_ROOM",
                    status_code=400,
                )
        elif data.room_id is not None:
            room_check = await self.room_repo.get_by_id(data.room_id, include_deleted=False)
            if room_check is None:
                raise NotFoundError("Room not found", code="ROOM_NOT_FOUND")

            room_beds = await self.bed_repo.list_by_room(data.room_id)
            free_bed = next((b for b in room_beds if not b.is_occupied), None)
            if free_bed is None:
                raise BusinessRuleError("Room is full", code="ROOM_FULL", status_code=400)

            bed = await self.bed_repo.get_by_id_for_update(free_bed.id)
            if bed is None:
                raise NotFoundError("Bed not found", code="BED_NOT_FOUND")
        else:
            raise BusinessRuleError(
                "Either bed_id or room_id must be provided",
                code="BED_OR_ROOM_REQUIRED",
                status_code=400,
            )

        if bed.is_occupied:
            raise BusinessRuleError(
                "Bed is already occupied",
                code="BED_ALREADY_OCCUPIED",
                status_code=400,
            )

        active_bed_alloc = await self.allocation_repo.get_active_by_bed_id(bed.id)
        if active_bed_alloc is not None:
            raise BusinessRuleError(
                "Bed is already occupied",
                code="BED_ALREADY_OCCUPIED",
                status_code=400,
            )

        room = await self.room_repo.get_by_id(bed.room_id, include_deleted=False, load_beds=True)
        if room is None or room.is_deleted:
            raise NotFoundError("Room not found", code="ROOM_NOT_FOUND")

        if room.status == RoomStatus.MAINTENANCE:
            raise BusinessRuleError(
                "Room is under maintenance",
                code="ROOM_UNDER_MAINTENANCE",
                status_code=400,
            )

        block = await self.block_repo.get_by_id(room.block_id)
        if block is None:
            raise NotFoundError("Block not found", code="BLOCK_NOT_FOUND")

        hostel = await self.hostel_repo.get_by_id(block.hostel_id)
        if hostel is None or hostel.is_deleted:
            raise NotFoundError("Hostel not found", code="HOSTEL_NOT_FOUND")

        await ensure_hostel_access(self.session, current_user, hostel.id)

        if (
            hostel.gender_type != GenderType.MIXED
            and student.gender.value != hostel.gender_type.value
        ):
            raise BusinessRuleError(
                "Student gender does not match hostel gender type",
                code="GENDER_MISMATCH",
                status_code=400,
            )

        bed.is_occupied = True
        await self.bed_repo.update(bed)

        RoomService.recalculate_status(room)
        await self.room_repo.update(room)

        allocation = Allocation(
            student_id=student.id,
            bed_id=bed.id,
            start_date=data.start_date,
            status=AllocationStatus.ACTIVE,
        )

        try:
            await self.allocation_repo.create(allocation)
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("Allocation conflict detected", code="ALLOCATION_CONFLICT") from exc

        loaded = await self.allocation_repo.get_by_id(allocation.id)
        return loaded or allocation

    async def vacate(
        self, allocation_id: UUID, data: AllocationVacateRequest, current_user: User
    ) -> Allocation:
        """End an active room bed allocation, freeing the bed and updating room status."""
        user_role = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if user_role not in (UserRole.ADMIN.value, UserRole.WARDEN.value):
            raise ForbiddenError("Only admin and warden can vacate allocations", code="FORBIDDEN")

        allocation = await self.allocation_repo.get_by_id(allocation_id)
        if allocation is None:
            raise NotFoundError("Allocation not found", code="ALLOCATION_NOT_FOUND")

        hostel_id = allocation.bed.room.block.hostel_id
        await ensure_hostel_access(self.session, current_user, hostel_id)

        if allocation.status != AllocationStatus.ACTIVE:
            raise BusinessRuleError(
                "Only active allocations can be vacated",
                code="ALLOCATION_NOT_ACTIVE",
                status_code=400,
            )

        allocation.status = AllocationStatus.ENDED
        allocation.end_date = data.end_date or date.today()
        if data.reason is not None:
            allocation.reason = data.reason

        bed = allocation.bed
        bed.is_occupied = False
        await self.bed_repo.update(bed)

        room = await self.room_repo.get_by_id(bed.room_id, include_deleted=False, load_beds=True)
        if room is not None:
            RoomService.recalculate_status(room)
            await self.room_repo.update(room)

        await self.allocation_repo.update(allocation)
        loaded = await self.allocation_repo.get_by_id(allocation.id)
        return loaded or allocation

    async def transfer(
        self, allocation_id: UUID, data: AllocationTransferRequest, current_user: User
    ) -> Allocation:
        """Atomically vacate existing allocation and assign a new bed in a single transaction."""
        user_role = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if user_role not in (UserRole.ADMIN.value, UserRole.WARDEN.value):
            raise ForbiddenError("Only admin and warden can transfer allocations", code="FORBIDDEN")

        allocation = await self.allocation_repo.get_by_id(allocation_id)
        if allocation is None:
            raise NotFoundError("Allocation not found", code="ALLOCATION_NOT_FOUND")

        if allocation.status != AllocationStatus.ACTIVE:
            raise BusinessRuleError(
                "Only active allocations can be transferred",
                code="ALLOCATION_NOT_ACTIVE",
                status_code=400,
            )

        old_hostel_id = allocation.bed.room.block.hostel_id
        await ensure_hostel_access(self.session, current_user, old_hostel_id)

        student_id = allocation.student_id
        student = allocation.student

        async with self.session.begin_nested():
            allocation.status = AllocationStatus.ENDED
            allocation.end_date = date.today()
            allocation.reason = data.reason or "Transferred to new bed/room"

            old_bed = allocation.bed
            old_bed.is_occupied = False
            await self.bed_repo.update(old_bed)

            old_room = await self.room_repo.get_by_id(
                old_bed.room_id, include_deleted=False, load_beds=True
            )
            if old_room is not None:
                RoomService.recalculate_status(old_room)
                await self.room_repo.update(old_room)

            await self.allocation_repo.update(allocation)

            new_bed: Bed | None = None
            if data.new_bed_id is not None:
                if data.new_bed_id == old_bed.id:
                    raise BusinessRuleError(
                        "Cannot transfer to the same bed currently occupied",
                        code="CANNOT_TRANSFER_TO_SAME_BED",
                        status_code=400,
                    )
                new_bed = await self.bed_repo.get_by_id_for_update(data.new_bed_id)
                if new_bed is None:
                    raise NotFoundError("New bed not found", code="BED_NOT_FOUND")
                if data.new_room_id is not None and new_bed.room_id != data.new_room_id:
                    raise BusinessRuleError(
                        "New bed does not belong to specified new room",
                        code="BED_NOT_IN_ROOM",
                        status_code=400,
                    )
            elif data.new_room_id is not None:
                room_check = await self.room_repo.get_by_id(data.new_room_id, include_deleted=False)
                if room_check is None:
                    raise NotFoundError("New room not found", code="ROOM_NOT_FOUND")

                room_beds = await self.bed_repo.list_by_room(data.new_room_id)
                free_bed = next((b for b in room_beds if not b.is_occupied), None)
                if free_bed is None:
                    raise BusinessRuleError("Room is full", code="ROOM_FULL", status_code=400)

                new_bed = await self.bed_repo.get_by_id_for_update(free_bed.id)
                if new_bed is None:
                    raise NotFoundError("New bed not found", code="BED_NOT_FOUND")
            else:
                raise BusinessRuleError(
                    "Either new_bed_id or new_room_id must be provided",
                    code="BED_OR_ROOM_REQUIRED",
                    status_code=400,
                )

            if new_bed.is_occupied:
                raise BusinessRuleError(
                    "New bed is already occupied",
                    code="BED_ALREADY_OCCUPIED",
                    status_code=400,
                )

            active_bed_alloc = await self.allocation_repo.get_active_by_bed_id(new_bed.id)
            if active_bed_alloc is not None:
                raise BusinessRuleError(
                    "New bed is already occupied",
                    code="BED_ALREADY_OCCUPIED",
                    status_code=400,
                )

            new_room = await self.room_repo.get_by_id(
                new_bed.room_id, include_deleted=False, load_beds=True
            )
            if new_room is None or new_room.is_deleted:
                raise NotFoundError("New room not found", code="ROOM_NOT_FOUND")

            if new_room.status == RoomStatus.MAINTENANCE:
                raise BusinessRuleError(
                    "New room is under maintenance",
                    code="ROOM_UNDER_MAINTENANCE",
                    status_code=400,
                )

            new_block = await self.block_repo.get_by_id(new_room.block_id)
            if new_block is None:
                raise NotFoundError("Block not found", code="BLOCK_NOT_FOUND")

            new_hostel = await self.hostel_repo.get_by_id(new_block.hostel_id)
            if new_hostel is None or new_hostel.is_deleted:
                raise NotFoundError("Hostel not found", code="HOSTEL_NOT_FOUND")

            await ensure_hostel_access(self.session, current_user, new_hostel.id)

            if (
                new_hostel.gender_type != GenderType.MIXED
                and student.gender.value != new_hostel.gender_type.value
            ):
                raise BusinessRuleError(
                    "Student gender does not match hostel gender type",
                    code="GENDER_MISMATCH",
                    status_code=400,
                )

            new_bed.is_occupied = True
            await self.bed_repo.update(new_bed)

            RoomService.recalculate_status(new_room)
            await self.room_repo.update(new_room)

            new_allocation = Allocation(
                student_id=student_id,
                bed_id=new_bed.id,
                start_date=date.today(),
                status=AllocationStatus.ACTIVE,
            )

            try:
                await self.allocation_repo.create(new_allocation)
            except IntegrityError as exc:
                raise ConflictError(
                    "Allocation conflict detected", code="ALLOCATION_CONFLICT"
                ) from exc

        loaded = await self.allocation_repo.get_by_id(new_allocation.id)
        return loaded or new_allocation

    async def cancel(self, allocation_id: UUID, current_user: User) -> Allocation:
        """Cancel an allocation scheduled to start in the future, freeing reserved resources."""
        user_role = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if user_role not in (UserRole.ADMIN.value, UserRole.WARDEN.value):
            raise ForbiddenError("Only admin and warden can cancel allocations", code="FORBIDDEN")

        allocation = await self.allocation_repo.get_by_id(allocation_id)
        if allocation is None:
            raise NotFoundError("Allocation not found", code="ALLOCATION_NOT_FOUND")

        hostel_id = allocation.bed.room.block.hostel_id
        await ensure_hostel_access(self.session, current_user, hostel_id)

        if allocation.status != AllocationStatus.ACTIVE:
            raise BusinessRuleError(
                "Only active allocations can be cancelled",
                code="ALLOCATION_NOT_ACTIVE",
                status_code=400,
            )

        if allocation.start_date <= date.today():
            raise BusinessRuleError(
                "Can only cancel allocations starting in the future",
                code="CANNOT_CANCEL_ACTIVE_ALLOCATION",
                status_code=400,
            )

        allocation.status = AllocationStatus.CANCELLED
        bed = allocation.bed
        bed.is_occupied = False
        await self.bed_repo.update(bed)

        room = await self.room_repo.get_by_id(bed.room_id, include_deleted=False, load_beds=True)
        if room is not None:
            RoomService.recalculate_status(room)
            await self.room_repo.update(room)

        await self.allocation_repo.update(allocation)
        loaded = await self.allocation_repo.get_by_id(allocation.id)
        return loaded or allocation

    async def get_allocation(self, id: UUID, current_user: User) -> Allocation:
        """Retrieve allocation by ID with role-based scoping."""
        allocation = await self.allocation_repo.get_by_id(id)
        if allocation is None:
            raise NotFoundError("Allocation not found", code="ALLOCATION_NOT_FOUND")

        user_role = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if user_role == UserRole.STUDENT.value:
            if allocation.student.user_id != current_user.id:
                raise ForbiddenError("You cannot view this allocation", code="FORBIDDEN")
        elif user_role == UserRole.WARDEN.value:
            hostel_id = allocation.bed.room.block.hostel_id
            await ensure_hostel_access(self.session, current_user, hostel_id)
        elif user_role != UserRole.ADMIN.value:
            raise ForbiddenError("Access forbidden", code="FORBIDDEN")

        return allocation

    async def get_student_active_allocation(
        self, student_id: UUID, current_user: User
    ) -> Allocation:
        """Retrieve the active allocation for a given student."""
        user_role = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        student = await self.student_repo.get_by_id(student_id)
        if student is None or student.is_deleted:
            raise NotFoundError("Student not found", code="STUDENT_NOT_FOUND")

        if user_role == UserRole.STUDENT.value:
            if student.user_id != current_user.id:
                raise ForbiddenError("You cannot view this allocation", code="FORBIDDEN")
        elif user_role == UserRole.WARDEN.value:
            # Warden access scoping
            warden_hostels = await self.warden_repo.list_hostel_ids_for_warden(current_user.id)
            active_alloc = await self.allocation_repo.get_active_by_student_id(student.id)
            if active_alloc is not None:
                hostel_id = active_alloc.bed.room.block.hostel_id
                if hostel_id not in warden_hostels:
                    raise ForbiddenError(
                        "You cannot access allocations outside your assigned hostels",
                        code="FORBIDDEN",
                    )
                return active_alloc
            raise NotFoundError(
                "No active allocation found for this student",
                code="ALLOCATION_NOT_FOUND",
            )
        elif user_role != UserRole.ADMIN.value:
            raise ForbiddenError("Access forbidden", code="FORBIDDEN")

        active_alloc = await self.allocation_repo.get_active_by_student_id(student.id)
        if active_alloc is None:
            raise NotFoundError(
                "No active allocation found for this student",
                code="ALLOCATION_NOT_FOUND",
            )
        return active_alloc

    async def get_my_active_allocation(self, current_user: User) -> Allocation:
        """Retrieve active allocation for the currently authenticated student."""
        profile = await self.student_repo.get_by_user_id(current_user.id)
        if profile is None or profile.is_deleted:
            raise NotFoundError("Student profile not found", code="PROFILE_NOT_FOUND")

        active_alloc = await self.allocation_repo.get_active_by_student_id(profile.id)
        if active_alloc is None:
            raise NotFoundError(
                "No active allocation found for this student",
                code="ALLOCATION_NOT_FOUND",
            )
        return active_alloc

    async def get_room_occupants(self, room_id: UUID, current_user: User) -> list[OccupantRead]:
        """Fetch list of occupants for a room with warden scoping."""
        user_role = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if user_role not in (UserRole.ADMIN.value, UserRole.WARDEN.value):
            raise ForbiddenError("Only admin and warden can view room occupants", code="FORBIDDEN")

        room = await self.room_repo.get_by_id(room_id, include_deleted=False)
        if room is None:
            raise NotFoundError("Room not found", code="ROOM_NOT_FOUND")

        block = await self.block_repo.get_by_id(room.block_id)
        if block is None:
            raise NotFoundError("Block not found", code="BLOCK_NOT_FOUND")

        await ensure_hostel_access(self.session, current_user, block.hostel_id)
        return await self.allocation_repo.get_room_occupants(room_id)

    async def list_allocations(
        self,
        params: PaginationParams,
        current_user: User,
        hostel_id: UUID | None = None,
        room_id: UUID | None = None,
        student_id: UUID | None = None,
        status: AllocationStatus | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> Page[AllocationRead]:
        """Fetch paginated allocations with filters and warden scoping."""
        user_role = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if user_role not in (UserRole.ADMIN.value, UserRole.WARDEN.value):
            raise ForbiddenError("Only admin and warden can list allocations", code="FORBIDDEN")

        warden_hostel_ids: list[UUID] | None = None
        if user_role == UserRole.WARDEN.value:
            warden_hostel_ids = await self.warden_repo.list_hostel_ids_for_warden(current_user.id)
            if hostel_id is not None and hostel_id not in warden_hostel_ids:
                raise ForbiddenError("You are not assigned to this hostel", code="FORBIDDEN")

        allocations, total = await self.allocation_repo.list(
            params=params,
            hostel_id=hostel_id,
            room_id=room_id,
            student_id=student_id,
            status=status,
            start_date=start_date,
            end_date=end_date,
            warden_hostel_ids=warden_hostel_ids,
        )

        items = [AllocationRead.model_validate(a) for a in allocations]
        return Page.create(items=items, total=total, params=params)


__all__ = ["AllocationService"]
