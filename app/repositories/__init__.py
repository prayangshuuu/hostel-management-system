"""Database repositories for data access."""

from app.repositories.allocation_repository import AllocationRepository
from app.repositories.billing_repository import (
    FeeStructureRepository,
    InvoiceRepository,
    PaymentRepository,
)
from app.repositories.complaint_repository import (
    ComplaintCommentRepository,
    ComplaintRepository,
)
from app.repositories.hostel_repository import (
    BlockRepository,
    HostelRepository,
    WardenAssignmentRepository,
)
from app.repositories.mess_repository import (
    MealOptOutRepository,
    MessMenuRepository,
)
from app.repositories.notice_repository import (
    NoticeReadRepository,
    NoticeRepository,
)
from app.repositories.operations_repository import (
    AttendanceRepository,
    LeaveRepository,
    VisitorRepository,
)
from app.repositories.room_repository import BedRepository, RoomRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.user_repository import UserRepository

__all__ = [
    "AllocationRepository",
    "AttendanceRepository",
    "BedRepository",
    "BlockRepository",
    "ComplaintCommentRepository",
    "ComplaintRepository",
    "FeeStructureRepository",
    "HostelRepository",
    "InvoiceRepository",
    "LeaveRepository",
    "MealOptOutRepository",
    "MessMenuRepository",
    "NoticeReadRepository",
    "NoticeRepository",
    "PaymentRepository",
    "RoomRepository",
    "StudentRepository",
    "UserRepository",
    "VisitorRepository",
    "WardenAssignmentRepository",
]
