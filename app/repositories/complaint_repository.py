"""Repositories for complaints and complaint comments."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.sql.base import ExecutableOption

from app.models.complaint import (
    Complaint,
    ComplaintCategory,
    ComplaintComment,
    ComplaintPriority,
    ComplaintStatus,
)
from app.models.hostel import Block
from app.models.room import Room
from app.models.student import StudentProfile
from app.schemas.common import PaginationParams

__all__ = [
    "ComplaintCommentRepository",
    "ComplaintRepository",
]


class ComplaintRepository:
    """Repository handling persistence and queries for Complaint entities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _eager_load_options(self, load_comments: bool = True) -> list[ExecutableOption]:
        """Return eager loading options for student, room, block, hostel, assignee, and comments."""
        options: list[ExecutableOption] = [
            joinedload(Complaint.student).joinedload(StudentProfile.user),
            joinedload(Complaint.room).joinedload(Room.block).joinedload(Block.hostel),
            joinedload(Complaint.assignee),
        ]
        if load_comments:
            options.append(selectinload(Complaint.comments).joinedload(ComplaintComment.author))
        return options

    async def get_by_id(self, id: UUID, load_comments: bool = True) -> Complaint | None:
        """Fetch a single complaint by UUID with relationships loaded."""
        stmt = (
            select(Complaint)
            .options(*self._eager_load_options(load_comments=load_comments))
            .where(Complaint.id == id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, complaint: Complaint) -> Complaint:
        """Add and flush a new complaint."""
        self.session.add(complaint)
        await self.session.flush()
        await self.session.refresh(complaint)
        return complaint

    async def update(self, complaint: Complaint) -> Complaint:
        """Flush changes to an existing complaint."""
        await self.session.flush()
        await self.session.refresh(complaint)
        return complaint

    async def list(
        self,
        params: PaginationParams,
        status: ComplaintStatus | None = None,
        priority: ComplaintPriority | None = None,
        category: ComplaintCategory | None = None,
        hostel_id: UUID | None = None,
        assigned_to: UUID | None = None,
        student_id: UUID | None = None,
        warden_hostel_ids: list[UUID] | None = None,
    ) -> tuple[list[Complaint], int]:
        """Fetch paginated complaints with optional scoping and filters."""
        if warden_hostel_ids is not None and len(warden_hostel_ids) == 0:
            return [], 0

        stmt = select(Complaint).options(*self._eager_load_options(load_comments=False))
        count_stmt = select(func.count(Complaint.id))

        if student_id is not None:
            stmt = stmt.where(Complaint.student_id == student_id)
            count_stmt = count_stmt.where(Complaint.student_id == student_id)

        if status is not None:
            stmt = stmt.where(Complaint.status == status)
            count_stmt = count_stmt.where(Complaint.status == status)

        if priority is not None:
            stmt = stmt.where(Complaint.priority == priority)
            count_stmt = count_stmt.where(Complaint.priority == priority)

        if category is not None:
            stmt = stmt.where(Complaint.category == category)
            count_stmt = count_stmt.where(Complaint.category == category)

        if assigned_to is not None:
            stmt = stmt.where(Complaint.assigned_to == assigned_to)
            count_stmt = count_stmt.where(Complaint.assigned_to == assigned_to)

        if hostel_id is not None or warden_hostel_ids is not None:
            subq = select(Room.id).join(Block, Block.id == Room.block_id)
            if hostel_id is not None:
                subq = subq.where(Block.hostel_id == hostel_id)
            if warden_hostel_ids is not None:
                subq = subq.where(Block.hostel_id.in_(warden_hostel_ids))
            stmt = stmt.where(Complaint.room_id.in_(subq))
            count_stmt = count_stmt.where(Complaint.room_id.in_(subq))

        total = await self.session.scalar(count_stmt) or 0
        stmt = stmt.order_by(Complaint.created_at.desc()).offset(params.offset).limit(params.limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total


class ComplaintCommentRepository:
    """Repository handling persistence and queries for ComplaintComment entities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, comment: ComplaintComment) -> ComplaintComment:
        """Add and flush a new complaint comment."""
        self.session.add(comment)
        await self.session.flush()
        await self.session.refresh(comment)
        return comment

    async def list_by_complaint(
        self, complaint_id: UUID, include_internal: bool = True
    ) -> list[ComplaintComment]:
        """Fetch comments for a complaint, optionally filtering internal comments."""
        stmt = (
            select(ComplaintComment)
            .options(selectinload(ComplaintComment.author))
            .where(ComplaintComment.complaint_id == complaint_id)
        )
        if not include_internal:
            stmt = stmt.where(ComplaintComment.is_internal.is_(False))
        stmt = stmt.order_by(ComplaintComment.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
