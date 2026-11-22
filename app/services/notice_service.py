"""Notice business logic service for announcement lifecycle and audience scoping."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleError, ForbiddenError, NotFoundError
from app.models.notice import Notice, NoticeAudience
from app.models.user import User, UserRole
from app.repositories.allocation_repository import AllocationRepository
from app.repositories.hostel_repository import WardenAssignmentRepository
from app.repositories.notice_repository import NoticeReadRepository, NoticeRepository
from app.repositories.student_repository import StudentRepository
from app.schemas.common import Page, PaginationParams
from app.schemas.notice import (
    NoticeCreate,
    NoticeRead,
    NoticeUnreadCount,
    NoticeUpdate,
)
from app.services.hostel_service import ensure_hostel_access

__all__ = ["NoticeService"]


class NoticeService:
    """Service managing notice announcements, lifecycle, permissions, and read tracking."""

    def __init__(
        self,
        session: AsyncSession,
        notice_repo: NoticeRepository | None = None,
        read_repo: NoticeReadRepository | None = None,
        warden_repo: WardenAssignmentRepository | None = None,
        student_repo: StudentRepository | None = None,
        allocation_repo: AllocationRepository | None = None,
    ) -> None:
        self.session = session
        self.notice_repo = notice_repo or NoticeRepository(session)
        self.read_repo = read_repo or NoticeReadRepository(session)
        self.warden_repo = warden_repo or WardenAssignmentRepository(session)
        self.student_repo = student_repo or StudentRepository(session)
        self.allocation_repo = allocation_repo or AllocationRepository(session)

    async def _get_student_hostel_id(self, user_id: UUID) -> UUID | None:
        """Fetch the active hostel ID for a student user if they have an active allocation."""
        profile = await self.student_repo.get_by_user_id(user_id)
        if profile is None:
            return None
        allocation = await self.allocation_repo.get_active_by_student_id(profile.id)
        if (
            allocation is None
            or allocation.bed is None
            or allocation.bed.room is None
            or allocation.bed.room.block is None
        ):
            return None
        return allocation.bed.room.block.hostel_id

    async def create_notice(self, current_user: User, payload: NoticeCreate) -> NoticeRead:
        """Create a notice enforcing global notice admin privileges and hostel scoping."""
        role_str = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if role_str not in (UserRole.ADMIN.value, UserRole.WARDEN.value):
            raise ForbiddenError(
                "Only administrators and wardens can create notices",
                code="FORBIDDEN",
            )

        if payload.hostel_id is None:
            if role_str != UserRole.ADMIN.value:
                raise ForbiddenError(
                    "Only administrators can create global notices",
                    code="FORBIDDEN",
                )
        else:
            await ensure_hostel_access(self.session, current_user, payload.hostel_id)

        published_at = payload.published_at or datetime.now(UTC)
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=UTC)

        expires_at = payload.expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)

        if expires_at is not None and expires_at <= published_at:
            raise BusinessRuleError(
                "expires_at must be strictly after published_at",
                code="INVALID_EXPIRY",
                status_code=400,
            )

        notice = Notice(
            hostel_id=payload.hostel_id,
            title=payload.title,
            body=payload.body,
            audience=payload.audience,
            is_pinned=payload.is_pinned,
            published_at=published_at,
            expires_at=payload.expires_at,
            created_by_id=current_user.id,
        )
        created = await self.notice_repo.create(notice)
        loaded = await self.notice_repo.get_by_id(created.id)
        return NoticeRead.model_validate(loaded or created)

    async def update_notice(
        self,
        current_user: User,
        notice_id: UUID,
        payload: NoticeUpdate,
    ) -> NoticeRead:
        """Update an existing notice enforcing scoping permissions."""
        notice = await self.notice_repo.get_by_id(notice_id)
        if notice is None:
            raise NotFoundError("Notice not found", code="NOTICE_NOT_FOUND")

        role_str = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if role_str not in (UserRole.ADMIN.value, UserRole.WARDEN.value):
            raise ForbiddenError(
                "Only administrators and wardens can modify notices",
                code="FORBIDDEN",
            )

        if notice.hostel_id is None:
            if role_str != UserRole.ADMIN.value:
                raise ForbiddenError(
                    "Only administrators can modify global notices",
                    code="FORBIDDEN",
                )
        else:
            await ensure_hostel_access(self.session, current_user, notice.hostel_id)

        new_published = (
            payload.published_at if payload.published_at is not None else notice.published_at
        )
        if new_published is not None and new_published.tzinfo is None:
            new_published = new_published.replace(tzinfo=UTC)

        new_expires = payload.expires_at if payload.expires_at is not None else notice.expires_at
        if new_expires is not None and new_expires.tzinfo is None:
            new_expires = new_expires.replace(tzinfo=UTC)

        if new_expires is not None and new_published is not None and new_expires <= new_published:
            raise BusinessRuleError(
                "expires_at must be strictly after published_at",
                code="INVALID_EXPIRY",
                status_code=400,
            )

        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(notice, key, value)

        updated = await self.notice_repo.update(notice)
        loaded = await self.notice_repo.get_by_id(updated.id)
        return NoticeRead.model_validate(loaded or updated)

    async def delete_notice(self, current_user: User, notice_id: UUID) -> None:
        """Delete an existing notice enforcing admin or assigned warden scoping."""
        notice = await self.notice_repo.get_by_id(notice_id)
        if notice is None:
            raise NotFoundError("Notice not found", code="NOTICE_NOT_FOUND")

        role_str = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if role_str not in (UserRole.ADMIN.value, UserRole.WARDEN.value):
            raise ForbiddenError(
                "Only administrators and wardens can delete notices",
                code="FORBIDDEN",
            )

        if notice.hostel_id is None:
            if role_str != UserRole.ADMIN.value:
                raise ForbiddenError(
                    "Only administrators can delete global notices",
                    code="FORBIDDEN",
                )
        else:
            await ensure_hostel_access(self.session, current_user, notice.hostel_id)

        await self.notice_repo.delete(notice)

    async def get_notice(self, current_user: User, notice_id: UUID) -> NoticeRead:
        """Fetch notice details verifying visibility constraints for current user."""
        notice = await self.notice_repo.get_by_id(notice_id)
        if notice is None:
            raise NotFoundError("Notice not found", code="NOTICE_NOT_FOUND")

        role_str = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        now = datetime.now(UTC)

        notice_published_at = (
            notice.published_at.replace(tzinfo=UTC)
            if notice.published_at.tzinfo is None
            else notice.published_at
        )
        notice_expires_at = (
            notice.expires_at.replace(tzinfo=UTC)
            if notice.expires_at is not None and notice.expires_at.tzinfo is None
            else notice.expires_at
        )

        if role_str == UserRole.ADMIN.value:
            pass
        elif role_str == UserRole.WARDEN.value:
            if notice.audience not in (NoticeAudience.ALL, NoticeAudience.WARDENS):
                raise ForbiddenError(
                    "You do not have permission to view this notice", code="FORBIDDEN"
                )
            warden_hostels = await self.warden_repo.list_hostel_ids_for_warden(current_user.id)
            if notice.hostel_id is not None and notice.hostel_id not in warden_hostels:
                raise ForbiddenError(
                    "You do not have permission to view this notice", code="FORBIDDEN"
                )
            if notice.created_by_id != current_user.id and (
                notice_published_at > now
                or (notice_expires_at is not None and notice_expires_at <= now)
            ):
                raise NotFoundError("Notice not found", code="NOTICE_NOT_FOUND")
        else:
            # Student
            if notice_published_at > now or (
                notice_expires_at is not None and notice_expires_at <= now
            ):
                raise NotFoundError("Notice not found", code="NOTICE_NOT_FOUND")
            if notice.audience not in (NoticeAudience.ALL, NoticeAudience.STUDENTS):
                raise ForbiddenError(
                    "You do not have permission to view this notice", code="FORBIDDEN"
                )
            student_hostel_id = await self._get_student_hostel_id(current_user.id)
            if notice.hostel_id is not None and notice.hostel_id != student_hostel_id:
                raise ForbiddenError(
                    "You do not have permission to view this notice", code="FORBIDDEN"
                )

        read_ids = await self.read_repo.get_read_notice_ids_for_user(current_user.id, [notice.id])
        read_model = NoticeRead.model_validate(notice)
        read_model.is_read = notice.id in read_ids
        return read_model

    async def list_notices(
        self,
        params: PaginationParams,
        current_user: User,
        include_drafts_expired: bool = False,
        hostel_id: UUID | None = None,
        audience: NoticeAudience | None = None,
    ) -> Page[NoticeRead]:
        """Fetch paginated notices visible to current user."""
        role_str = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )

        user_hostel_id: UUID | None = None
        warden_hostel_ids: list[UUID] | None = None

        if role_str == UserRole.ADMIN.value:
            pass
        elif role_str == UserRole.WARDEN.value:
            warden_hostel_ids = await self.warden_repo.list_hostel_ids_for_warden(current_user.id)
        else:
            user_hostel_id = await self._get_student_hostel_id(current_user.id)

        notices, total = await self.notice_repo.list_visible(
            params=params,
            user_role=current_user.role,
            user_id=current_user.id,
            user_hostel_id=user_hostel_id,
            warden_hostel_ids=warden_hostel_ids,
            include_drafts_expired=include_drafts_expired,
            hostel_id=hostel_id,
            audience=audience,
        )

        read_ids = await self.read_repo.get_read_notice_ids_for_user(
            current_user.id, [n.id for n in notices]
        )

        items: list[NoticeRead] = []
        for n in notices:
            item = NoticeRead.model_validate(n)
            item.is_read = n.id in read_ids
            items.append(item)

        return Page.create(items=items, total=total, params=params)

    async def mark_as_read(self, current_user: User, notice_id: UUID) -> NoticeRead:
        """Mark notice as read idempotently after checking access."""
        notice_read = await self.get_notice(current_user, notice_id)
        await self.read_repo.mark_read(notice_id, current_user.id)
        notice_read.is_read = True
        return notice_read

    async def get_unread_count(self, current_user: User) -> NoticeUnreadCount:
        """Calculate count of unread visible notices for the current user."""
        role_str = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )

        if role_str == UserRole.ADMIN.value:
            count = await self.read_repo.get_unread_count(
                user_role=UserRole.ADMIN,
                user_id=current_user.id,
            )
        elif role_str == UserRole.WARDEN.value:
            warden_hostels = await self.warden_repo.list_hostel_ids_for_warden(current_user.id)
            count = await self.read_repo.get_unread_count(
                user_role=UserRole.WARDEN,
                user_id=current_user.id,
                warden_hostel_ids=warden_hostels,
            )
        else:
            student_hostel = await self._get_student_hostel_id(current_user.id)
            count = await self.read_repo.get_unread_count(
                user_role=UserRole.STUDENT,
                user_id=current_user.id,
                user_hostel_id=student_hostel,
            )

        return NoticeUnreadCount(unread_count=count)
