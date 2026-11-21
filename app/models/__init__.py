"""SQLAlchemy domain models."""

from app.models.hostel import Block, GenderType, Hostel, WardenAssignment
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.user import User, UserRole

__all__ = [
    "Bed",
    "Block",
    "GenderType",
    "Hostel",
    "Room",
    "RoomStatus",
    "RoomType",
    "User",
    "UserRole",
    "WardenAssignment",
]
