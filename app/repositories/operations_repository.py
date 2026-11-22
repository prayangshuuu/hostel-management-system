"""Operations repositories for attendance logs, leave requests, and visitors."""

import builtins
from datetime import UTC, date, datetime, time
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.base import ExecutableOption

from app.models.allocation import Allocation, AllocationStatus
from app.models.hostel import Block, Hostel
from app.models.operations import (
    AttendanceLog,
    AttendanceType,
    LeaveRequest,
    LeaveStatus,
    Visitor,
)
from app.models.room import Bed, Room
from app.models.student import StudentProfile
from app.models.user import User
from app.schemas.common import PaginationParams
from app.schemas.operations import PresentStudentRead


class AttendanceRepository:
    """Repository handling persistence and queries for AttendanceLog entities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _eager_load_options(self) -> builtins.list[ExecutableOption]:
        """Return eager loading options for student, user, allocation, and recorder."""
        return [
            selectinload(AttendanceLog.student).selectinload(StudentProfile.user),
            selectinload(AttendanceLog.student)
            .selectinload(StudentProfile.allocations)
            .selectinload(Allocation.bed)
            .selectinload(Bed.room)
            .selectinload(Room.block)
            .selectinload(Block.hostel),
            selectinload(AttendanceLog.recorder),
        ]

    async def get_latest_for_student(self, student_id: UUID) -> AttendanceLog | None:
        """Fetch the most recent attendance log for a student profile."""
        stmt = (
            select(AttendanceLog)
            .options(*self._eager_load_options())
            .where(AttendanceLog.student_id == student_id)
            .order_by(AttendanceLog.timestamp.desc(), AttendanceLog.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_id(self, id: UUID) -> AttendanceLog | None:
        """Fetch attendance log by primary key UUID with relationships loaded."""
        stmt = (
            select(AttendanceLog).options(*self._eager_load_options()).where(AttendanceLog.id == id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, attendance: AttendanceLog) -> AttendanceLog:
        """Add and flush a new attendance log record."""
        self.session.add(attendance)
        await self.session.flush()
        await self.session.refresh(attendance)
        return attendance

    async def list(
        self,
        params: PaginationParams,
        student_id: UUID | None = None,
        hostel_id: UUID | None = None,
        date_from: date | datetime | None = None,
        date_to: date | datetime | None = None,
        type: AttendanceType | None = None,
        warden_hostel_ids: builtins.list[UUID] | None = None,
    ) -> tuple[builtins.list[AttendanceLog], int]:
        """Fetch paginated attendance logs with optional scoping and filters."""
        if warden_hostel_ids is not None and len(warden_hostel_ids) == 0:
            return [], 0

        stmt = select(AttendanceLog).options(*self._eager_load_options())
        count_stmt = select(func.count(AttendanceLog.id))

        if student_id is not None:
            stmt = stmt.where(AttendanceLog.student_id == student_id)
            count_stmt = count_stmt.where(AttendanceLog.student_id == student_id)

        if type is not None:
            stmt = stmt.where(AttendanceLog.type == type)
            count_stmt = count_stmt.where(AttendanceLog.type == type)

        if date_from is not None:
            if isinstance(date_from, date) and not isinstance(date_from, datetime):
                dt_from = datetime.combine(date_from, time.min).replace(tzinfo=UTC)
            else:
                dt_from = date_from
            stmt = stmt.where(AttendanceLog.timestamp >= dt_from)
            count_stmt = count_stmt.where(AttendanceLog.timestamp >= dt_from)

        if date_to is not None:
            if isinstance(date_to, date) and not isinstance(date_to, datetime):
                dt_to = datetime.combine(date_to, time.max).replace(tzinfo=UTC)
            else:
                dt_to = date_to
            stmt = stmt.where(AttendanceLog.timestamp <= dt_to)
            count_stmt = count_stmt.where(AttendanceLog.timestamp <= dt_to)

        if hostel_id is not None or warden_hostel_ids is not None:
            alloc_subq = (
                select(Allocation.student_id)
                .join(Bed, Bed.id == Allocation.bed_id)
                .join(Room, Room.id == Bed.room_id)
                .join(Block, Block.id == Room.block_id)
                .where(Allocation.status == AllocationStatus.ACTIVE)
            )
            if hostel_id is not None:
                alloc_subq = alloc_subq.where(Block.hostel_id == hostel_id)
            if warden_hostel_ids is not None:
                alloc_subq = alloc_subq.where(Block.hostel_id.in_(warden_hostel_ids))

            stmt = stmt.where(AttendanceLog.student_id.in_(alloc_subq))
            count_stmt = count_stmt.where(AttendanceLog.student_id.in_(alloc_subq))

        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            stmt.order_by(
                AttendanceLog.timestamp.desc(),
                AttendanceLog.created_at.desc(),
            )
            .offset(params.offset)
            .limit(params.limit)
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def get_present_students(
        self,
        hostel_id: UUID | None = None,
        warden_hostel_ids: builtins.list[UUID] | None = None,
    ) -> builtins.list[PresentStudentRead]:
        """Fetch all students currently present inside the hostel based on latest check-in."""
        if warden_hostel_ids is not None and len(warden_hostel_ids) == 0:
            return []

        subq = select(
            AttendanceLog.student_id,
            AttendanceLog.type,
            AttendanceLog.timestamp.label("last_check_in"),
            func.row_number()
            .over(
                partition_by=AttendanceLog.student_id,
                order_by=(AttendanceLog.timestamp.desc(), AttendanceLog.created_at.desc()),
            )
            .label("rn"),
        ).subquery()

        stmt = (
            select(
                StudentProfile.id.label("student_id"),
                User.full_name.label("student_name"),
                StudentProfile.student_no.label("student_no"),
                Hostel.id.label("hostel_id"),
                Hostel.name.label("hostel_name"),
                Room.number.label("room_number"),
                Bed.label.label("bed_label"),
                subq.c.last_check_in,
            )
            .join(subq, (subq.c.student_id == StudentProfile.id) & (subq.c.rn == 1))
            .join(User, User.id == StudentProfile.user_id)
            .join(
                Allocation,
                (Allocation.student_id == StudentProfile.id)
                & (Allocation.status == AllocationStatus.ACTIVE),
            )
            .join(Bed, Bed.id == Allocation.bed_id)
            .join(Room, Room.id == Bed.room_id)
            .join(Block, Block.id == Room.block_id)
            .join(Hostel, Hostel.id == Block.hostel_id)
            .where(subq.c.type == AttendanceType.CHECK_IN)
            .where(StudentProfile.is_deleted.is_(False))
        )

        if hostel_id is not None:
            stmt = stmt.where(Hostel.id == hostel_id)
        if warden_hostel_ids is not None:
            stmt = stmt.where(Hostel.id.in_(warden_hostel_ids))

        stmt = stmt.order_by(Hostel.name.asc(), Room.number.asc(), Bed.label.asc())
        result = await self.session.execute(stmt)
        rows = result.mappings().all()

        return [
            PresentStudentRead(
                student_id=row["student_id"],
                student_name=row["student_name"],
                student_no=row["student_no"],
                hostel_id=row["hostel_id"],
                hostel_name=row["hostel_name"],
                room_number=row["room_number"],
                bed_label=row["bed_label"],
                last_check_in=row["last_check_in"],
            )
            for row in rows
        ]


class LeaveRepository:
    """Repository managing persistence and status transitions for LeaveRequest entities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _eager_load_options(self) -> builtins.list[ExecutableOption]:
        """Return eager loading options for student, user, allocation, and reviewer."""
        return [
            selectinload(LeaveRequest.student).selectinload(StudentProfile.user),
            selectinload(LeaveRequest.student)
            .selectinload(StudentProfile.allocations)
            .selectinload(Allocation.bed)
            .selectinload(Bed.room)
            .selectinload(Room.block)
            .selectinload(Block.hostel),
            selectinload(LeaveRequest.reviewer),
        ]

    async def get_by_id(self, id: UUID) -> LeaveRequest | None:
        """Fetch leave request by primary key UUID."""
        stmt = (
            select(LeaveRequest).options(*self._eager_load_options()).where(LeaveRequest.id == id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, leave: LeaveRequest) -> LeaveRequest:
        """Add and flush a new leave request record."""
        self.session.add(leave)
        await self.session.flush()
        await self.session.refresh(leave)
        return leave

    async def update(self, leave: LeaveRequest) -> LeaveRequest:
        """Flush changes to an existing leave request record."""
        await self.session.flush()
        await self.session.refresh(leave)
        return leave

    async def get_overlapping(
        self,
        student_id: UUID,
        from_date: date,
        to_date: date,
        exclude_id: UUID | None = None,
    ) -> builtins.list[LeaveRequest]:
        """Find pending or approved leave requests overlapping with the given date interval."""
        stmt = select(LeaveRequest).where(
            LeaveRequest.student_id == student_id,
            LeaveRequest.status.in_([LeaveStatus.PENDING, LeaveStatus.APPROVED]),
            LeaveRequest.from_date <= to_date,
            LeaveRequest.to_date >= from_date,
        )
        if exclude_id is not None:
            stmt = stmt.where(LeaveRequest.id != exclude_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list(
        self,
        params: PaginationParams,
        student_id: UUID | None = None,
        status: LeaveStatus | None = None,
        hostel_id: UUID | None = None,
        warden_hostel_ids: builtins.list[UUID] | None = None,
    ) -> tuple[builtins.list[LeaveRequest], int]:
        """Fetch paginated leave requests with optional scoping and status filters."""
        if warden_hostel_ids is not None and len(warden_hostel_ids) == 0:
            return [], 0

        stmt = select(LeaveRequest).options(*self._eager_load_options())
        count_stmt = select(func.count(LeaveRequest.id))

        if student_id is not None:
            stmt = stmt.where(LeaveRequest.student_id == student_id)
            count_stmt = count_stmt.where(LeaveRequest.student_id == student_id)

        if status is not None:
            stmt = stmt.where(LeaveRequest.status == status)
            count_stmt = count_stmt.where(LeaveRequest.status == status)

        if hostel_id is not None or warden_hostel_ids is not None:
            alloc_subq = (
                select(Allocation.student_id)
                .join(Bed, Bed.id == Allocation.bed_id)
                .join(Room, Room.id == Bed.room_id)
                .join(Block, Block.id == Room.block_id)
                .where(Allocation.status == AllocationStatus.ACTIVE)
            )
            if hostel_id is not None:
                alloc_subq = alloc_subq.where(Block.hostel_id == hostel_id)
            if warden_hostel_ids is not None:
                alloc_subq = alloc_subq.where(Block.hostel_id.in_(warden_hostel_ids))

            stmt = stmt.where(LeaveRequest.student_id.in_(alloc_subq))
            count_stmt = count_stmt.where(LeaveRequest.student_id.in_(alloc_subq))

        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            stmt.order_by(
                LeaveRequest.created_at.desc(),
            )
            .offset(params.offset)
            .limit(params.limit)
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total


class VisitorRepository:
    """Repository handling persistence, checkout updates, and queries for Visitor entities."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _eager_load_options(self) -> builtins.list[ExecutableOption]:
        """Return eager loading options for student and user."""
        return [
            selectinload(Visitor.student).selectinload(StudentProfile.user),
        ]

    async def get_by_id(self, id: UUID) -> Visitor | None:
        """Fetch visitor by primary key UUID."""
        stmt = select(Visitor).options(*self._eager_load_options()).where(Visitor.id == id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, visitor: Visitor) -> Visitor:
        """Add and flush a new visitor record."""
        self.session.add(visitor)
        await self.session.flush()
        await self.session.refresh(visitor)
        return visitor

    async def update(self, visitor: Visitor) -> Visitor:
        """Flush changes to an existing visitor record."""
        await self.session.flush()
        await self.session.refresh(visitor)
        return visitor

    async def get_active_by_student_and_visitor(
        self, student_id: UUID, name: str, phone: str
    ) -> Visitor | None:
        """Find an active visitor record for the given student, name, and phone."""
        stmt = select(Visitor).where(
            Visitor.student_id == student_id,
            func.lower(Visitor.name) == func.lower(name.strip()),
            Visitor.phone == phone.strip(),
            Visitor.check_out_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list(
        self,
        params: PaginationParams,
        student_id: UUID | None = None,
        active: bool | None = None,
        hostel_id: UUID | None = None,
        warden_hostel_ids: builtins.list[UUID] | None = None,
    ) -> tuple[builtins.list[Visitor], int]:
        """Fetch paginated visitor records with optional scoping and active filters."""
        if warden_hostel_ids is not None and len(warden_hostel_ids) == 0:
            return [], 0

        stmt = select(Visitor).options(*self._eager_load_options())
        count_stmt = select(func.count(Visitor.id))

        if student_id is not None:
            stmt = stmt.where(Visitor.student_id == student_id)
            count_stmt = count_stmt.where(Visitor.student_id == student_id)

        if active is True:
            stmt = stmt.where(Visitor.check_out_at.is_(None))
            count_stmt = count_stmt.where(Visitor.check_out_at.is_(None))
        elif active is False:
            stmt = stmt.where(Visitor.check_out_at.is_not(None))
            count_stmt = count_stmt.where(Visitor.check_out_at.is_not(None))

        if hostel_id is not None or warden_hostel_ids is not None:
            alloc_subq = (
                select(Allocation.student_id)
                .join(Bed, Bed.id == Allocation.bed_id)
                .join(Room, Room.id == Bed.room_id)
                .join(Block, Block.id == Room.block_id)
                .where(Allocation.status == AllocationStatus.ACTIVE)
            )
            if hostel_id is not None:
                alloc_subq = alloc_subq.where(Block.hostel_id == hostel_id)
            if warden_hostel_ids is not None:
                alloc_subq = alloc_subq.where(Block.hostel_id.in_(warden_hostel_ids))

            stmt = stmt.where(Visitor.student_id.in_(alloc_subq))
            count_stmt = count_stmt.where(Visitor.student_id.in_(alloc_subq))

        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar() or 0

        stmt = (
            stmt.order_by(
                Visitor.check_in_at.desc(),
                Visitor.created_at.desc(),
            )
            .offset(params.offset)
            .limit(params.limit)
        )

        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total
