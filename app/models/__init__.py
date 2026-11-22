"""SQLAlchemy domain models."""

from app.models.allocation import Allocation, AllocationStatus
from app.models.billing import (
    FeePeriod,
    FeeStructure,
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentMethod,
)
from app.models.hostel import Block, GenderType, Hostel, WardenAssignment
from app.models.operations import (
    AttendanceLog,
    AttendanceType,
    LeaveRequest,
    LeaveStatus,
    Visitor,
)
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole

__all__ = [
    "Allocation",
    "AllocationStatus",
    "AttendanceLog",
    "AttendanceType",
    "Bed",
    "Block",
    "FeePeriod",
    "FeeStructure",
    "GenderType",
    "Hostel",
    "Invoice",
    "InvoiceStatus",
    "LeaveRequest",
    "LeaveStatus",
    "Payment",
    "PaymentMethod",
    "Room",
    "RoomStatus",
    "RoomType",
    "StudentProfile",
    "User",
    "UserRole",
    "Visitor",
    "WardenAssignment",
]
