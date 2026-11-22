"""Database repositories for data access."""

from app.repositories.allocation_repository import AllocationRepository
from app.repositories.billing_repository import (
    FeeStructureRepository,
    InvoiceRepository,
)
from app.repositories.hostel_repository import (
    BlockRepository,
    HostelRepository,
    WardenAssignmentRepository,
)
from app.repositories.room_repository import BedRepository, RoomRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.user_repository import UserRepository

__all__ = [
    "AllocationRepository",
    "BedRepository",
    "BlockRepository",
    "FeeStructureRepository",
    "HostelRepository",
    "InvoiceRepository",
    "RoomRepository",
    "StudentRepository",
    "UserRepository",
    "WardenAssignmentRepository",
]
