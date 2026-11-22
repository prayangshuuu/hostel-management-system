"""Database repositories for data access."""

from app.repositories.allocation_repository import AllocationRepository
from app.repositories.billing_repository import (
    FeeStructureRepository,
    InvoiceRepository,
    PaymentRepository,
)
from app.repositories.hostel_repository import (
    BlockRepository,
    HostelRepository,
    WardenAssignmentRepository,
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
    "FeeStructureRepository",
    "HostelRepository",
    "InvoiceRepository",
    "LeaveRepository",
    "PaymentRepository",
    "RoomRepository",
    "StudentRepository",
    "UserRepository",
    "VisitorRepository",
    "WardenAssignmentRepository",
]
