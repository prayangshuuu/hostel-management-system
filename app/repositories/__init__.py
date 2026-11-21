"""Database repositories for data access."""

from app.repositories.hostel_repository import (
    BlockRepository,
    HostelRepository,
    WardenAssignmentRepository,
)
from app.repositories.user_repository import UserRepository

__all__ = [
    "BlockRepository",
    "HostelRepository",
    "UserRepository",
    "WardenAssignmentRepository",
]
