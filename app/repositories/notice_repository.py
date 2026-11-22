"""Notice and NoticeRead repository layer."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.notice import Notice, NoticeAudience, NoticeRead
from app.models.user import UserRole
from app.schemas.common import PaginationParams

__all__ = [
    "NoticeReadRepository",
    "NoticeRepository",
]


class NoticeRepository:
    """Repository handling database operations for the Notice entity."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, id: UUID) -> Notice | None:
        """Fetch a single notice by primary key UUID with relationships loaded."""
        stmt = (
            select(Notice)
            .options(
                selectinload(Notice.hostel),
                selectinload(Notice.created_by),
            )
            .where(Notice.id == id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, notice: Notice) -> Notice:
        """Add and flush a new notice record."""
        self.session.add(notice)
        await self.session.flush()
        await self.session.refresh(notice)
        return notice

    async def update(self, notice: Notice) -> Notice:
        """Flush changes to an existing notice record."""
        await self.session.flush()
        await self.session.refresh(notice)
        return notice

    async def delete(self, notice: Notice) -> None:
        """Delete an existing notice record."""
        await self.session.delete(notice)
        await self.session.flush()

    async def list_visible(
        self,
        params: PaginationParams,
        user_role: UserRole | str,
        user_id: UUID,
        user_hostel_id: UUID | None = None,
        warden_hostel_ids: list[UUID] | None = None,
        include_drafts_expired: bool = False,
        hostel_id: UUID | None = None,
        audience: NoticeAudience | None = None,
    ) -> tuple[list[Notice], int]:
        """Fetch paginated notices visible to user based on role, audience, and hostel scoping."""
        stmt = select(Notice).options(
            selectinload(Notice.hostel),
            selectinload(Notice.created_by),
        )
        count_stmt = select(func.count(Notice.id))

        role_str = user_role.value if isinstance(user_role, UserRole) else str(user_role)
        now = datetime.now(UTC)

        # 1. Published and expiration filtering
        if role_str == UserRole.ADMIN.value:
            # Admin sees all unless specific time constraints or draft filter
            pass
        elif role_str == UserRole.WARDEN.value:
            if not include_drafts_expired:
                time_filter = (
                    Notice.published_at <= now,
                    or_(Notice.expires_at.is_(None), Notice.expires_at > now),
                )
                stmt = stmt.where(*time_filter)
                count_stmt = count_stmt.where(*time_filter)
        else:
            # Student always only sees published and non-expired notices
            time_filter = (
                Notice.published_at <= now,
                or_(Notice.expires_at.is_(None), Notice.expires_at > now),
            )
            stmt = stmt.where(*time_filter)
            count_stmt = count_stmt.where(*time_filter)

        # 2. Audience and hostel scoping based on role
        if role_str == UserRole.ADMIN.value:
            if hostel_id is not None:
                stmt = stmt.where(Notice.hostel_id == hostel_id)
                count_stmt = count_stmt.where(Notice.hostel_id == hostel_id)
            if audience is not None:
                stmt = stmt.where(Notice.audience == audience)
                count_stmt = count_stmt.where(Notice.audience == audience)

        elif role_str == UserRole.WARDEN.value:
            # Wardens see audience in (ALL, WARDENS)
            allowed_audiences = [NoticeAudience.ALL, NoticeAudience.WARDENS]
            if audience is not None:
                if audience in allowed_audiences:
                    stmt = stmt.where(Notice.audience == audience)
                    count_stmt = count_stmt.where(Notice.audience == audience)
                else:
                    stmt = stmt.where(false())
                    count_stmt = count_stmt.where(false())
            else:
                stmt = stmt.where(Notice.audience.in_(allowed_audiences))
                count_stmt = count_stmt.where(Notice.audience.in_(allowed_audiences))

            # Hostel scoping: hostel_id IS NULL or in assigned hostels
            assigned = warden_hostel_ids or []
            if hostel_id is not None:
                if hostel_id in assigned:
                    stmt = stmt.where(Notice.hostel_id == hostel_id)
                    count_stmt = count_stmt.where(Notice.hostel_id == hostel_id)
                else:
                    stmt = stmt.where(false())
                    count_stmt = count_stmt.where(false())
            else:
                if assigned:
                    hostel_filter = or_(Notice.hostel_id.is_(None), Notice.hostel_id.in_(assigned))
                else:
                    hostel_filter = Notice.hostel_id.is_(None)
                stmt = stmt.where(hostel_filter)
                count_stmt = count_stmt.where(hostel_filter)

        else:
            # Students see audience in (ALL, STUDENTS)
            allowed_audiences = [NoticeAudience.ALL, NoticeAudience.STUDENTS]
            if audience is not None:
                if audience in allowed_audiences:
                    stmt = stmt.where(Notice.audience == audience)
                    count_stmt = count_stmt.where(Notice.audience == audience)
                else:
                    stmt = stmt.where(false())
                    count_stmt = count_stmt.where(false())
            else:
                stmt = stmt.where(Notice.audience.in_(allowed_audiences))
                count_stmt = count_stmt.where(Notice.audience.in_(allowed_audiences))

            # Hostel scoping: hostel_id IS NULL or matching active hostel
            if hostel_id is not None:
                if user_hostel_id is not None and hostel_id == user_hostel_id:
                    stmt = stmt.where(Notice.hostel_id == hostel_id)
                    count_stmt = count_stmt.where(Notice.hostel_id == hostel_id)
                else:
                    stmt = stmt.where(false())
                    count_stmt = count_stmt.where(false())
            else:
                if user_hostel_id is not None:
                    hostel_filter = or_(
                        Notice.hostel_id.is_(None), Notice.hostel_id == user_hostel_id
                    )
                else:
                    hostel_filter = Notice.hostel_id.is_(None)
                stmt = stmt.where(hostel_filter)
                count_stmt = count_stmt.where(hostel_filter)

        # 3. Ordering: pinned first, then newest published_at, then created_at
        stmt = stmt.order_by(
            Notice.is_pinned.desc(),
            Notice.published_at.desc(),
            Notice.created_at.desc(),
        )

        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        paginated_stmt = stmt.offset(params.offset).limit(params.limit)
        items_result = await self.session.execute(paginated_stmt)
        items = list(items_result.scalars().all())

        return items, total


class NoticeReadRepository:
    """Repository handling read status tracking for notices."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def mark_read(self, notice_id: UUID, user_id: UUID) -> NoticeRead:
        """Mark notice as read idempotently for a user."""
        stmt = select(NoticeRead).where(
            NoticeRead.notice_id == notice_id,
            NoticeRead.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing

        notice_read = NoticeRead(
            notice_id=notice_id,
            user_id=user_id,
            read_at=datetime.now(UTC),
        )
        self.session.add(notice_read)
        await self.session.flush()
        await self.session.refresh(notice_read)
        return notice_read

    async def get_read_notice_ids_for_user(
        self,
        user_id: UUID,
        notice_ids: list[UUID],
    ) -> set[UUID]:
        """Fetch set of notice UUIDs that have been marked as read by user."""
        if not notice_ids:
            return set()

        stmt = select(NoticeRead.notice_id).where(
            NoticeRead.user_id == user_id,
            NoticeRead.notice_id.in_(notice_ids),
        )
        result = await self.session.execute(stmt)
        return set(result.scalars().all())

    async def get_unread_count(
        self,
        user_role: UserRole | str,
        user_id: UUID,
        user_hostel_id: UUID | None = None,
        warden_hostel_ids: list[UUID] | None = None,
    ) -> int:
        """Calculate count of visible active notices not yet read by user."""
        now = datetime.now(UTC)
        read_subq = (
            select(NoticeRead.notice_id).where(NoticeRead.user_id == user_id).scalar_subquery()
        )

        stmt = select(func.count(Notice.id)).where(Notice.id.not_in(read_subq))

        # Always filter active notices for unread count
        stmt = stmt.where(
            Notice.published_at <= now,
            or_(Notice.expires_at.is_(None), Notice.expires_at > now),
        )

        role_str = user_role.value if isinstance(user_role, UserRole) else str(user_role)
        if role_str == UserRole.STUDENT.value:
            stmt = stmt.where(Notice.audience.in_([NoticeAudience.ALL, NoticeAudience.STUDENTS]))
            if user_hostel_id is not None:
                stmt = stmt.where(
                    or_(Notice.hostel_id.is_(None), Notice.hostel_id == user_hostel_id)
                )
            else:
                stmt = stmt.where(Notice.hostel_id.is_(None))
        elif role_str == UserRole.WARDEN.value:
            stmt = stmt.where(Notice.audience.in_([NoticeAudience.ALL, NoticeAudience.WARDENS]))
            assigned = warden_hostel_ids or []
            if assigned:
                stmt = stmt.where(or_(Notice.hostel_id.is_(None), Notice.hostel_id.in_(assigned)))
            else:
                stmt = stmt.where(Notice.hostel_id.is_(None))

        result = await self.session.execute(stmt)
        return result.scalar() or 0
