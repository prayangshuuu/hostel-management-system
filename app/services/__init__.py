"""Business logic services."""

from app.services.allocation_service import AllocationService
from app.services.auth_service import AuthService
from app.services.billing_service import BillingService
from app.services.complaint_service import ComplaintService
from app.services.hostel_service import HostelService, ensure_hostel_access
from app.services.operations_service import OperationsService
from app.services.room_service import RoomService, generate_bed_labels
from app.services.student_service import StudentService, generate_temporary_password
from app.services.user_service import UserService

__all__ = [
    "AllocationService",
    "AuthService",
    "BillingService",
    "ComplaintService",
    "HostelService",
    "OperationsService",
    "RoomService",
    "StudentService",
    "UserService",
    "ensure_hostel_access",
    "generate_bed_labels",
    "generate_temporary_password",
]
