"""Business logic services."""

from app.services.auth_service import AuthService
from app.services.hostel_service import HostelService, ensure_hostel_access
from app.services.room_service import RoomService, generate_bed_labels
from app.services.user_service import UserService

__all__ = [
    "AuthService",
    "HostelService",
    "RoomService",
    "UserService",
    "ensure_hostel_access",
    "generate_bed_labels",
]
