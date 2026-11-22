"""SQLAlchemy domain models."""

from app.models.allocation import Allocation, AllocationStatus
from app.models.audit import AuditLog
from app.models.billing import (
    FeePeriod,
    FeeStructure,
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentMethod,
)
from app.models.complaint import (
    Complaint,
    ComplaintCategory,
    ComplaintComment,
    ComplaintPriority,
    ComplaintStatus,
)
from app.models.hostel import Block, GenderType, Hostel, WardenAssignment
from app.models.mess import MealOptOut, MealType, MessMenu
from app.models.notice import Notice, NoticeAudience, NoticeRead
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
    "AuditLog",
    "Bed",
    "Block",
    "Complaint",
    "ComplaintCategory",
    "ComplaintComment",
    "ComplaintPriority",
    "ComplaintStatus",
    "FeePeriod",
    "FeeStructure",
    "GenderType",
    "Hostel",
    "Invoice",
    "InvoiceStatus",
    "LeaveRequest",
    "LeaveStatus",
    "MealOptOut",
    "MealType",
    "MessMenu",
    "Notice",
    "NoticeAudience",
    "NoticeRead",
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
