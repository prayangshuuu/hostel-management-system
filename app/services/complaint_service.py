"""Business logic service for complaint lifecycle, assignments, and comments."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleError, ForbiddenError, NotFoundError
from app.models.complaint import (
    Complaint,
    ComplaintCategory,
    ComplaintComment,
    ComplaintPriority,
    ComplaintStatus,
)
from app.models.room import RoomStatus
from app.models.user import User, UserRole
from app.repositories.allocation_repository import AllocationRepository
from app.repositories.complaint_repository import (
    ComplaintCommentRepository,
    ComplaintRepository,
)
from app.repositories.hostel_repository import WardenAssignmentRepository
from app.repositories.room_repository import RoomRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.user_repository import UserRepository
from app.schemas.common import PaginationParams
from app.schemas.complaint import (
    ComplaintAssignRequest,
    ComplaintCommentCreate,
    ComplaintCommentRead,
    ComplaintCreate,
    ComplaintDetailRead,
    ComplaintRead,
    ComplaintStatusUpdateRequest,
)
from app.services.audit_service import AuditService
from app.services.hostel_service import ensure_hostel_access

__all__ = ["ComplaintService"]


class ComplaintService:
    """Service managing complaint submission, assignment, status machine, and comments."""

    def __init__(
        self,
        session: AsyncSession,
        complaint_repo: ComplaintRepository | None = None,
        comment_repo: ComplaintCommentRepository | None = None,
        student_repo: StudentRepository | None = None,
        allocation_repo: AllocationRepository | None = None,
        room_repo: RoomRepository | None = None,
        user_repo: UserRepository | None = None,
        warden_repo: WardenAssignmentRepository | None = None,
    ) -> None:
        self.session = session
        self.complaint_repo = complaint_repo or ComplaintRepository(session)
        self.comment_repo = comment_repo or ComplaintCommentRepository(session)
        self.student_repo = student_repo or StudentRepository(session)
        self.allocation_repo = allocation_repo or AllocationRepository(session)
        self.room_repo = room_repo or RoomRepository(session)
        self.user_repo = user_repo or UserRepository(session)
        self.warden_repo = warden_repo or WardenAssignmentRepository(session)

    async def create_complaint(
        self,
        data: ComplaintCreate,
        current_user: User,
    ) -> Complaint:
        """Create a new complaint for the student's actively allocated room."""
        profile = await self.student_repo.get_by_user_id(current_user.id)
        if profile is None or profile.is_deleted:
            raise NotFoundError("Student profile not found", code="STUDENT_NOT_FOUND")

        allocation = await self.allocation_repo.get_active_by_student_id(profile.id)
        if allocation is None:
            raise BusinessRuleError(
                "Student does not have an active allocation",
                code="NO_ACTIVE_ALLOCATION",
                status_code=400,
            )

        complaint = Complaint(
            student_id=profile.id,
            room_id=allocation.bed.room_id,
            title=data.title,
            description=data.description,
            category=data.category,
            priority=data.priority,
            status=ComplaintStatus.OPEN,
        )
        created = await self.complaint_repo.create(complaint)
        loaded = await self.complaint_repo.get_by_id(created.id, load_comments=False)
        return loaded or created

    async def list_complaints(
        self,
        params: PaginationParams,
        current_user: User,
        status: ComplaintStatus | None = None,
        priority: ComplaintPriority | None = None,
        category: ComplaintCategory | None = None,
        hostel_id: UUID | None = None,
        assigned_to: UUID | None = None,
    ) -> tuple[list[Complaint], int]:
        """List paginated complaints with role-based scoping and filters."""
        if current_user.role == UserRole.STUDENT:
            profile = await self.student_repo.get_by_user_id(current_user.id)
            if profile is None:
                return [], 0
            student_id: UUID | None = profile.id
            warden_hostel_ids: list[UUID] | None = None
        elif current_user.role == UserRole.WARDEN:
            warden_hostel_ids = await self.warden_repo.list_hostel_ids_for_warden(current_user.id)
            if not warden_hostel_ids:
                return [], 0
            if hostel_id is not None and hostel_id not in warden_hostel_ids:
                raise ForbiddenError("You are not assigned to this hostel", code="FORBIDDEN")
            student_id = None
        else:
            warden_hostel_ids = None
            student_id = None

        return await self.complaint_repo.list(
            params=params,
            status=status,
            priority=priority,
            category=category,
            hostel_id=hostel_id,
            assigned_to=assigned_to,
            student_id=student_id,
            warden_hostel_ids=warden_hostel_ids,
        )

    async def get_complaint(
        self,
        id: UUID,
        current_user: User,
    ) -> ComplaintDetailRead:
        """Fetch complaint details (hiding internal comments from students)."""
        complaint = await self.complaint_repo.get_by_id(id, load_comments=True)
        if complaint is None:
            raise NotFoundError("Complaint not found", code="COMPLAINT_NOT_FOUND")

        if current_user.role == UserRole.STUDENT:
            profile = await self.student_repo.get_by_user_id(current_user.id)
            if profile is None or complaint.student_id != profile.id:
                raise ForbiddenError("You cannot view this complaint", code="FORBIDDEN")
        elif current_user.role == UserRole.WARDEN:
            hostel_id = complaint.room.block.hostel_id
            await ensure_hostel_access(self.session, current_user, hostel_id)

        if current_user.role == UserRole.STUDENT:
            comments = [c for c in complaint.comments if not c.is_internal]
        else:
            comments = list(complaint.comments)

        comment_reads = [ComplaintCommentRead.model_validate(c) for c in comments]
        base_read = ComplaintRead.model_validate(complaint)
        data = base_read.model_dump()
        data["comments"] = comment_reads
        return ComplaintDetailRead(**data)

    async def assign_complaint(
        self,
        id: UUID,
        data: ComplaintAssignRequest,
        current_user: User,
    ) -> Complaint:
        """Assign complaint to a user and transition OPEN to IN_PROGRESS."""
        complaint = await self.complaint_repo.get_by_id(id, load_comments=False)
        if complaint is None:
            raise NotFoundError("Complaint not found", code="COMPLAINT_NOT_FOUND")

        if current_user.role == UserRole.WARDEN:
            hostel_id = complaint.room.block.hostel_id
            await ensure_hostel_access(self.session, current_user, hostel_id)

        assignee = await self.user_repo.get_by_id(data.assigned_to)
        if assignee is None or not assignee.is_active:
            raise NotFoundError("Assigned user not found", code="USER_NOT_FOUND")

        complaint.assigned_to = data.assigned_to
        if complaint.status == ComplaintStatus.OPEN:
            complaint.status = ComplaintStatus.IN_PROGRESS

        await self.complaint_repo.update(complaint)
        loaded = await self.complaint_repo.get_by_id(complaint.id, load_comments=False)
        return loaded or complaint

    async def update_status(
        self,
        id: UUID,
        data: ComplaintStatusUpdateRequest,
        current_user: User,
    ) -> Complaint:
        """Transition complaint status enforcing state machine and permission scoping."""
        complaint = await self.complaint_repo.get_by_id(id, load_comments=True)
        if complaint is None:
            raise NotFoundError("Complaint not found", code="COMPLAINT_NOT_FOUND")

        if current_user.role == UserRole.STUDENT:
            profile = await self.student_repo.get_by_user_id(current_user.id)
            if profile is None or complaint.student_id != profile.id:
                raise ForbiddenError("You cannot update this complaint", code="FORBIDDEN")
            if data.status not in (ComplaintStatus.OPEN, ComplaintStatus.CLOSED):
                raise ForbiddenError(
                    "Students can only reopen or close complaints",
                    code="FORBIDDEN",
                )
            if data.mark_room_maintenance:
                raise ForbiddenError(
                    "Students cannot modify room maintenance status",
                    code="FORBIDDEN",
                )
        elif current_user.role == UserRole.WARDEN:
            hostel_id = complaint.room.block.hostel_id
            await ensure_hostel_access(self.session, current_user, hostel_id)

        allowed_transitions: dict[ComplaintStatus, set[ComplaintStatus]] = {
            ComplaintStatus.OPEN: {ComplaintStatus.IN_PROGRESS, ComplaintStatus.CLOSED},
            ComplaintStatus.IN_PROGRESS: {ComplaintStatus.RESOLVED, ComplaintStatus.CLOSED},
            ComplaintStatus.RESOLVED: {ComplaintStatus.CLOSED, ComplaintStatus.OPEN},
            ComplaintStatus.CLOSED: set(),
        }

        if data.status not in allowed_transitions.get(complaint.status, set()):
            raise BusinessRuleError(
                f"Invalid complaint status transition from '{complaint.status}' to '{data.status}'",
                code="INVALID_STATUS_TRANSITION",
                status_code=400,
            )

        if complaint.status == ComplaintStatus.RESOLVED and data.status == ComplaintStatus.OPEN:
            now = datetime.now(UTC)
            resolved_at = complaint.resolved_at
            if resolved_at is not None:
                if resolved_at.tzinfo is None:
                    resolved_at = resolved_at.replace(tzinfo=UTC)
                if now > resolved_at + timedelta(days=7):
                    raise BusinessRuleError(
                        "Reopen window expired (max 7 days)",
                        code="REOPEN_WINDOW_EXPIRED",
                        status_code=400,
                    )
            complaint.resolved_at = None
        elif data.status == ComplaintStatus.RESOLVED:
            complaint.resolved_at = datetime.now(UTC)

        old_status = str(
            complaint.status.value if hasattr(complaint.status, "value") else complaint.status
        )
        complaint.status = data.status

        if data.resolution_notes:
            comment = ComplaintComment(
                complaint_id=complaint.id,
                author_id=current_user.id,
                body=data.resolution_notes,
                is_internal=False,
            )
            await self.comment_repo.create(comment)

        if data.mark_room_maintenance:
            room = await self.room_repo.get_by_id(complaint.room_id)
            if room is not None:
                room.status = RoomStatus.MAINTENANCE
                await self.room_repo.update(room)

        await self.complaint_repo.update(complaint)

        new_status = str(
            complaint.status.value if hasattr(complaint.status, "value") else complaint.status
        )
        await AuditService.record(
            self.session,
            current_user.id,
            "complaint.status_change",
            "Complaint",
            complaint.id,
            {"old_status": old_status, "new_status": new_status},
        )

        loaded = await self.complaint_repo.get_by_id(complaint.id, load_comments=False)
        return loaded or complaint

    async def add_comment(
        self,
        id: UUID,
        data: ComplaintCommentCreate,
        current_user: User,
    ) -> ComplaintComment:
        """Post a comment to a complaint thread."""
        complaint = await self.complaint_repo.get_by_id(id, load_comments=False)
        if complaint is None:
            raise NotFoundError("Complaint not found", code="COMPLAINT_NOT_FOUND")

        if current_user.role == UserRole.STUDENT:
            profile = await self.student_repo.get_by_user_id(current_user.id)
            if profile is None or complaint.student_id != profile.id:
                raise ForbiddenError("You cannot comment on this complaint", code="FORBIDDEN")
            is_internal = False
        elif current_user.role == UserRole.WARDEN:
            hostel_id = complaint.room.block.hostel_id
            await ensure_hostel_access(self.session, current_user, hostel_id)
            is_internal = data.is_internal
        else:
            is_internal = data.is_internal

        comment = ComplaintComment(
            complaint_id=complaint.id,
            author_id=current_user.id,
            body=data.body,
            is_internal=is_internal,
        )
        created = await self.comment_repo.create(comment)
        created.author = current_user
        return created
