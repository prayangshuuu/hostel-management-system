"""Database repositories for data access."""

from app.repositories.allocation_repository import AllocationRepository
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
    "HostelRepository",
    "RoomRepository",
    "StudentRepository",
    "UserRepository",
    "WardenAssignmentRepository",
]
