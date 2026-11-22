"""Operations service managing attendance, leave requests, and visitors."""

import builtins
from datetime import UTC, date, datetime, time
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationAppError,
)
from app.models.operations import (
    AttendanceLog,
    AttendanceType,
    LeaveRequest,
    LeaveStatus,
    Visitor,
)
from app.models.user import User, UserRole
from app.repositories.allocation_repository import AllocationRepository
from app.repositories.hostel_repository import WardenAssignmentRepository
from app.repositories.operations_repository import (
    AttendanceRepository,
    LeaveRepository,
    VisitorRepository,
)
from app.repositories.student_repository import StudentRepository
from app.schemas.common import PaginationParams
from app.schemas.operations import (
    AttendanceActionRequest,
    LeaveRequestCreate,
    LeaveReviewRequest,
    PresentStudentRead,
    VisitorCheckOutRequest,
    VisitorCreate,
)
from app.services.hostel_service import ensure_hostel_access


class OperationsService:
    """Business operations service for attendance, leave requests, and visitor management."""

    def __init__(
        self,
        session: AsyncSession,
        attendance_repo: AttendanceRepository | None = None,
        leave_repo: LeaveRepository | None = None,
        visitor_repo: VisitorRepository | None = None,
        student_repo: StudentRepository | None = None,
        allocation_repo: AllocationRepository | None = None,
        warden_repo: WardenAssignmentRepository | None = None,
    ) -> None:
        self.session = session
        self.attendance_repo = attendance_repo or AttendanceRepository(session)
        self.leave_repo = leave_repo or LeaveRepository(session)
        self.visitor_repo = visitor_repo or VisitorRepository(session)
        self.student_repo = student_repo or StudentRepository(session)
        self.allocation_repo = allocation_repo or AllocationRepository(session)
        self.warden_repo = warden_repo or WardenAssignmentRepository(session)

    # =========================================================================
    # Visiting Hours Validation Helper
    # =========================================================================

    def _check_visiting_hours(
        self,
        current_time: datetime | time | None = None,
        bypass: bool = False,
    ) -> None:
        """Validate whether the given time falls within configured hostel visiting hours."""
        if bypass:
            return

        if current_time is None:
            check_t = datetime.now(UTC).time()
        elif isinstance(current_time, datetime):
            check_t = current_time.time()
        else:
            check_t = current_time

        try:
            start_t = datetime.strptime(settings.VISIT_START, "%H:%M").time()
            end_t = datetime.strptime(settings.VISIT_END, "%H:%M").time()
        except ValueError:
            start_t = time(8, 0)
            end_t = time(20, 0)

        if start_t <= end_t:
            is_open = start_t <= check_t <= end_t
        else:
            is_open = check_t >= start_t or check_t <= end_t

        if not is_open:
            raise BusinessRuleError(
                f"Visiting hours are {settings.VISIT_START} to {settings.VISIT_END}",
                code="VISITING_HOURS_CLOSED",
                status_code=400,
            )

    # =========================================================================
    # Attendance Operations
    # =========================================================================

    async def check_in(
        self,
        data: AttendanceActionRequest,
        current_user: User,
    ) -> AttendanceLog:
        """Record student check-in enforcing active allocation, warden scoping, and sequence."""
        profile = await self.student_repo.get_by_id(data.student_id)
        if profile is None or profile.is_deleted:
            raise NotFoundError("Student profile not found", code="STUDENT_NOT_FOUND")

        allocation = await self.allocation_repo.get_active_by_student_id(data.student_id)
        if allocation is None:
            raise BusinessRuleError(
                "Student does not have an active hostel allocation",
                code="NO_ACTIVE_ALLOCATION",
                status_code=400,
            )

        hostel_id = allocation.bed.room.block.hostel_id
        await ensure_hostel_access(self.session, current_user, hostel_id)

        latest = await self.attendance_repo.get_latest_for_student(data.student_id)
        if latest is not None and latest.type == AttendanceType.CHECK_IN:
            raise ConflictError("Student is already checked in", code="ALREADY_CHECKED_IN")

        ts = data.timestamp or datetime.now(UTC)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        log = AttendanceLog(
            student_id=data.student_id,
            type=AttendanceType.CHECK_IN,
            timestamp=ts,
            recorded_by=current_user.id,
            remarks=data.remarks,
        )
        created = await self.attendance_repo.create(log)
        loaded = await self.attendance_repo.get_by_id(created.id)
        return loaded or created

    async def check_out(
        self,
        data: AttendanceActionRequest,
        current_user: User,
    ) -> AttendanceLog:
        """Record student check-out enforcing active allocation, warden scoping, and sequence."""
        profile = await self.student_repo.get_by_id(data.student_id)
        if profile is None or profile.is_deleted:
            raise NotFoundError("Student profile not found", code="STUDENT_NOT_FOUND")

        allocation = await self.allocation_repo.get_active_by_student_id(data.student_id)
        if allocation is None:
            raise BusinessRuleError(
                "Student does not have an active hostel allocation",
                code="NO_ACTIVE_ALLOCATION",
                status_code=400,
            )

        hostel_id = allocation.bed.room.block.hostel_id
        await ensure_hostel_access(self.session, current_user, hostel_id)

        latest = await self.attendance_repo.get_latest_for_student(data.student_id)
        if latest is None or latest.type == AttendanceType.CHECK_OUT:
            raise ConflictError("Student is already checked out", code="ALREADY_CHECKED_OUT")

        ts = data.timestamp or datetime.now(UTC)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        log = AttendanceLog(
            student_id=data.student_id,
            type=AttendanceType.CHECK_OUT,
            timestamp=ts,
            recorded_by=current_user.id,
            remarks=data.remarks,
        )
        created = await self.attendance_repo.create(log)
        loaded = await self.attendance_repo.get_by_id(created.id)
        return loaded or created

    async def get_present_students(
        self,
        current_user: User,
        hostel_id: UUID | None = None,
    ) -> builtins.list[PresentStudentRead]:
        """Fetch all students currently present inside the hostel enforcing warden assignment."""
        if current_user.role == UserRole.WARDEN:
            warden_hostel_ids = await self.warden_repo.list_hostel_ids_for_warden(current_user.id)
            if hostel_id is not None:
                if hostel_id not in warden_hostel_ids:
                    raise ForbiddenError("You are not assigned to this hostel", code="FORBIDDEN")
                return await self.attendance_repo.get_present_students(hostel_id=hostel_id)
            return await self.attendance_repo.get_present_students(
                warden_hostel_ids=warden_hostel_ids
            )

        return await self.attendance_repo.get_present_students(hostel_id=hostel_id)

    async def list_attendance(
        self,
        params: PaginationParams,
        current_user: User,
        student_id: UUID | None = None,
        hostel_id: UUID | None = None,
        date_from: date | datetime | None = None,
        date_to: date | datetime | None = None,
        type: AttendanceType | None = None,
    ) -> tuple[builtins.list[AttendanceLog], int]:
        """List paginated attendance logs enforcing warden scoping and optional filters."""
        warden_hostel_ids: builtins.list[UUID] | None = None
        if current_user.role == UserRole.WARDEN:
            warden_hostel_ids = await self.warden_repo.list_hostel_ids_for_warden(current_user.id)
            if hostel_id is not None:
                if hostel_id not in warden_hostel_ids:
                    raise ForbiddenError("You are not assigned to this hostel", code="FORBIDDEN")
                warden_hostel_ids = None

        return await self.attendance_repo.list(
            params=params,
            student_id=student_id,
            hostel_id=hostel_id,
            date_from=date_from,
            date_to=date_to,
            type=type,
            warden_hostel_ids=warden_hostel_ids,
        )

    async def get_my_attendance(
        self,
        current_user: User,
        params: PaginationParams,
        date_from: date | datetime | None = None,
        date_to: date | datetime | None = None,
        type: AttendanceType | None = None,
    ) -> tuple[builtins.list[AttendanceLog], int]:
        """Fetch paginated attendance logs for the authenticated student."""
        profile = await self.student_repo.get_by_user_id(current_user.id)
        if profile is None or profile.is_deleted:
            raise NotFoundError("Student profile not found", code="PROFILE_NOT_FOUND")

        return await self.attendance_repo.list(
            params=params,
            student_id=profile.id,
            date_from=date_from,
            date_to=date_to,
            type=type,
        )

    # =========================================================================
    # Leave Request Operations
    # =========================================================================

    async def create_leave_request(
        self,
        data: LeaveRequestCreate,
        current_user: User,
        current_date: date | None = None,
    ) -> LeaveRequest:
        """Submit a leave request enforcing active allocation, valid dates, and scoping."""
        if current_user.role == UserRole.STUDENT:
            profile = await self.student_repo.get_by_user_id(current_user.id)
            if profile is None or profile.is_deleted:
                raise NotFoundError("Student profile not found", code="PROFILE_NOT_FOUND")
            target_student_id = profile.id
        else:
            if data.student_id is None:
                raise ValidationAppError(
                    "student_id is required when creating leave on behalf of a student",
                    code="STUDENT_ID_REQUIRED",
                )
            profile = await self.student_repo.get_by_id(data.student_id)
            if profile is None or profile.is_deleted:
                raise NotFoundError("Student profile not found", code="STUDENT_NOT_FOUND")
            target_student_id = data.student_id

        allocation = await self.allocation_repo.get_active_by_student_id(target_student_id)
        if allocation is None:
            raise BusinessRuleError(
                "Student does not have an active hostel allocation",
                code="NO_ACTIVE_ALLOCATION",
                status_code=400,
            )

        if current_user.role == UserRole.WARDEN:
            await ensure_hostel_access(
                self.session, current_user, allocation.bed.room.block.hostel_id
            )

        today = current_date or date.today()
        if data.from_date < today:
            raise BusinessRuleError(
                "Leave from_date cannot be in the past",
                code="PAST_LEAVE_DATE",
                status_code=400,
            )
        if data.to_date < data.from_date:
            raise BusinessRuleError(
                "to_date must be greater than or equal to from_date",
                code="INVALID_DATE_RANGE",
                status_code=400,
            )

        overlapping = await self.leave_repo.get_overlapping(
            student_id=target_student_id,
            from_date=data.from_date,
            to_date=data.to_date,
        )
        if len(overlapping) > 0:
            raise ConflictError(
                "Student already has an overlapping leave request",
                code="OVERLAPPING_LEAVE_REQUEST",
            )

        leave = LeaveRequest(
            student_id=target_student_id,
            from_date=data.from_date,
            to_date=data.to_date,
            reason=data.reason,
            status=LeaveStatus.PENDING,
        )
        created = await self.leave_repo.create(leave)
        loaded = await self.leave_repo.get_by_id(created.id)
        return loaded or created

    async def approve_leave_request(
        self,
        leave_id: UUID,
        current_user: User,
        review: LeaveReviewRequest | None = None,
    ) -> LeaveRequest:
        """Approve a pending leave request enforcing warden assignment scoping."""
        leave = await self.leave_repo.get_by_id(leave_id)
        if leave is None:
            raise NotFoundError("Leave request not found", code="LEAVE_NOT_FOUND")

        if current_user.role == UserRole.WARDEN:
            allocation = await self.allocation_repo.get_active_by_student_id(leave.student_id)
            if allocation is None:
                raise ForbiddenError(
                    "Cannot review leave for unallocated student",
                    code="FORBIDDEN",
                )
            await ensure_hostel_access(
                self.session, current_user, allocation.bed.room.block.hostel_id
            )

        if leave.status != LeaveStatus.PENDING:
            raise ConflictError(
                f"Cannot approve leave request with status {leave.status.value}",
                code="LEAVE_ALREADY_PROCESSED",
            )

        leave.status = LeaveStatus.APPROVED
        leave.reviewed_by = current_user.id
        leave.reviewed_at = datetime.now(UTC)
        if review and review.review_notes is not None:
            leave.review_notes = review.review_notes

        return await self.leave_repo.update(leave)

    async def reject_leave_request(
        self,
        leave_id: UUID,
        current_user: User,
        review: LeaveReviewRequest | None = None,
    ) -> LeaveRequest:
        """Reject a pending leave request enforcing warden assignment scoping."""
        leave = await self.leave_repo.get_by_id(leave_id)
        if leave is None:
            raise NotFoundError("Leave request not found", code="LEAVE_NOT_FOUND")

        if current_user.role == UserRole.WARDEN:
            allocation = await self.allocation_repo.get_active_by_student_id(leave.student_id)
            if allocation is None:
                raise ForbiddenError(
                    "Cannot review leave for unallocated student",
                    code="FORBIDDEN",
                )
            await ensure_hostel_access(
                self.session, current_user, allocation.bed.room.block.hostel_id
            )

        if leave.status != LeaveStatus.PENDING:
            raise ConflictError(
                f"Cannot reject leave request with status {leave.status.value}",
                code="LEAVE_ALREADY_PROCESSED",
            )

        leave.status = LeaveStatus.REJECTED
        leave.reviewed_by = current_user.id
        leave.reviewed_at = datetime.now(UTC)
        if review and review.review_notes is not None:
            leave.review_notes = review.review_notes

        return await self.leave_repo.update(leave)

    async def cancel_leave_request(
        self,
        leave_id: UUID,
        current_user: User,
    ) -> LeaveRequest:
        """Cancel a pending leave request (student self or admin only)."""
        leave = await self.leave_repo.get_by_id(leave_id)
        if leave is None:
            raise NotFoundError("Leave request not found", code="LEAVE_NOT_FOUND")

        if current_user.role == UserRole.STUDENT:
            profile = await self.student_repo.get_by_user_id(current_user.id)
            if profile is None or profile.id != leave.student_id:
                raise ForbiddenError(
                    "You can only cancel your own leave requests", code="FORBIDDEN"
                )
        elif current_user.role != UserRole.ADMIN:
            raise ForbiddenError(
                "Only student self or admin can cancel leave request",
                code="FORBIDDEN",
            )

        if leave.status != LeaveStatus.PENDING:
            raise ConflictError(
                f"Cannot cancel leave request with status {leave.status.value}",
                code="LEAVE_ALREADY_PROCESSED",
            )

        leave.status = LeaveStatus.CANCELLED
        return await self.leave_repo.update(leave)

    async def get_leave_by_id(
        self,
        leave_id: UUID,
        current_user: User,
    ) -> LeaveRequest:
        """Fetch a single leave request by ID enforcing role authorization."""
        leave = await self.leave_repo.get_by_id(leave_id)
        if leave is None:
            raise NotFoundError("Leave request not found", code="LEAVE_NOT_FOUND")

        if current_user.role == UserRole.STUDENT:
            profile = await self.student_repo.get_by_user_id(current_user.id)
            if profile is None or profile.id != leave.student_id:
                raise ForbiddenError("Access forbidden to this leave request", code="FORBIDDEN")
        elif current_user.role == UserRole.WARDEN:
            allocation = await self.allocation_repo.get_active_by_student_id(leave.student_id)
            if allocation is not None:
                await ensure_hostel_access(
                    self.session, current_user, allocation.bed.room.block.hostel_id
                )

        return leave

    async def list_leaves(
        self,
        params: PaginationParams,
        current_user: User,
        student_id: UUID | None = None,
        status: LeaveStatus | None = None,
        hostel_id: UUID | None = None,
    ) -> tuple[builtins.list[LeaveRequest], int]:
        """Fetch paginated leave requests with optional filters and warden scoping."""
        warden_hostel_ids: builtins.list[UUID] | None = None
        if current_user.role == UserRole.WARDEN:
            warden_hostel_ids = await self.warden_repo.list_hostel_ids_for_warden(current_user.id)
            if hostel_id is not None:
                if hostel_id not in warden_hostel_ids:
                    raise ForbiddenError("You are not assigned to this hostel", code="FORBIDDEN")
                warden_hostel_ids = None

        return await self.leave_repo.list(
            params=params,
            student_id=student_id,
            status=status,
            hostel_id=hostel_id,
            warden_hostel_ids=warden_hostel_ids,
        )

    async def get_my_leaves(
        self,
        current_user: User,
        params: PaginationParams,
        status: LeaveStatus | None = None,
    ) -> tuple[builtins.list[LeaveRequest], int]:
        """Fetch paginated leave requests for the authenticated student."""
        profile = await self.student_repo.get_by_user_id(current_user.id)
        if profile is None or profile.is_deleted:
            raise NotFoundError("Student profile not found", code="PROFILE_NOT_FOUND")

        return await self.leave_repo.list(
            params=params,
            student_id=profile.id,
            status=status,
        )

    # =========================================================================
    # Visitor Operations
    # =========================================================================

    async def check_in_visitor(
        self,
        data: VisitorCreate,
        current_user: User,
        check_in_time: datetime | None = None,
        bypass_visiting_hours: bool = False,
    ) -> Visitor:
        """Register visitor entry enforcing visiting hours, active allocation, and uniqueness."""
        self._check_visiting_hours(current_time=check_in_time, bypass=bypass_visiting_hours)

        profile = await self.student_repo.get_by_id(data.student_id)
        if profile is None or profile.is_deleted:
            raise NotFoundError("Student profile not found", code="STUDENT_NOT_FOUND")

        allocation = await self.allocation_repo.get_active_by_student_id(data.student_id)
        if allocation is None:
            raise BusinessRuleError(
                "Student does not have an active hostel allocation",
                code="NO_ACTIVE_ALLOCATION",
                status_code=400,
            )

        hostel_id = allocation.bed.room.block.hostel_id
        await ensure_hostel_access(self.session, current_user, hostel_id)

        active_visitor = await self.visitor_repo.get_active_by_student_and_visitor(
            student_id=data.student_id,
            name=data.name,
            phone=data.phone,
        )
        if active_visitor is not None:
            raise ConflictError(
                "Visitor is already checked in and active inside",
                code="VISITOR_ALREADY_CHECKED_IN",
            )

        in_time = check_in_time or datetime.now(UTC)
        if in_time.tzinfo is None:
            in_time = in_time.replace(tzinfo=UTC)

        visitor = Visitor(
            student_id=data.student_id,
            name=data.name,
            phone=data.phone,
            relation=data.relation,
            check_in_at=in_time,
            id_proof_type=data.id_proof_type,
            id_proof_number=data.id_proof_number,
            remarks=data.remarks,
        )
        created = await self.visitor_repo.create(visitor)
        loaded = await self.visitor_repo.get_by_id(created.id)
        return loaded or created

    async def check_out_visitor(
        self,
        visitor_id: UUID,
        current_user: User,
        data: VisitorCheckOutRequest | None = None,
        check_out_time: datetime | None = None,
    ) -> Visitor:
        """Record visitor checkout enforcing active status and warden assignment."""
        visitor = await self.visitor_repo.get_by_id(visitor_id)
        if visitor is None:
            raise NotFoundError("Visitor record not found", code="VISITOR_NOT_FOUND")

        if visitor.check_out_at is not None:
            raise ConflictError(
                "Visitor has already checked out",
                code="VISITOR_ALREADY_CHECKED_OUT",
            )

        if current_user.role == UserRole.WARDEN:
            allocation = await self.allocation_repo.get_active_by_student_id(visitor.student_id)
            if allocation is None:
                raise ForbiddenError(
                    "Cannot manage visitor for unallocated student",
                    code="FORBIDDEN",
                )
            await ensure_hostel_access(
                self.session, current_user, allocation.bed.room.block.hostel_id
            )

        out_time = check_out_time or datetime.now(UTC)
        if out_time.tzinfo is None:
            out_time = out_time.replace(tzinfo=UTC)

        visitor.check_out_at = out_time
        if data and data.remarks:
            extra = data.remarks
            visitor.remarks = f"{visitor.remarks} | {extra}" if visitor.remarks else extra

        return await self.visitor_repo.update(visitor)

    async def get_visitor_by_id(
        self,
        visitor_id: UUID,
        current_user: User,
    ) -> Visitor:
        """Fetch a single visitor record by primary key UUID enforcing authorization."""
        visitor = await self.visitor_repo.get_by_id(visitor_id)
        if visitor is None:
            raise NotFoundError("Visitor record not found", code="VISITOR_NOT_FOUND")

        if current_user.role == UserRole.STUDENT:
            profile = await self.student_repo.get_by_user_id(current_user.id)
            if profile is None or profile.id != visitor.student_id:
                raise ForbiddenError("Access forbidden to this visitor record", code="FORBIDDEN")
        elif current_user.role == UserRole.WARDEN:
            allocation = await self.allocation_repo.get_active_by_student_id(visitor.student_id)
            if allocation is not None:
                await ensure_hostel_access(
                    self.session, current_user, allocation.bed.room.block.hostel_id
                )

        return visitor

    async def list_visitors(
        self,
        params: PaginationParams,
        current_user: User,
        student_id: UUID | None = None,
        active: bool | None = None,
        hostel_id: UUID | None = None,
    ) -> tuple[builtins.list[Visitor], int]:
        """Fetch paginated visitor records with optional active status filter and warden scoping."""
        warden_hostel_ids: builtins.list[UUID] | None = None
        if current_user.role == UserRole.WARDEN:
            warden_hostel_ids = await self.warden_repo.list_hostel_ids_for_warden(current_user.id)
            if hostel_id is not None:
                if hostel_id not in warden_hostel_ids:
                    raise ForbiddenError("You are not assigned to this hostel", code="FORBIDDEN")
                warden_hostel_ids = None

        return await self.visitor_repo.list(
            params=params,
            student_id=student_id,
            active=active,
            hostel_id=hostel_id,
            warden_hostel_ids=warden_hostel_ids,
        )

    async def get_my_visitors(
        self,
        current_user: User,
        params: PaginationParams,
        active: bool | None = None,
    ) -> tuple[builtins.list[Visitor], int]:
        """Fetch paginated visitor logs for the authenticated student."""
        profile = await self.student_repo.get_by_user_id(current_user.id)
        if profile is None or profile.is_deleted:
            raise NotFoundError("Student profile not found", code="PROFILE_NOT_FOUND")

        return await self.visitor_repo.list(
            params=params,
            student_id=profile.id,
            active=active,
        )
