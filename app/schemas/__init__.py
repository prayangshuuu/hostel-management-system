"""Pydantic request and response schemas."""

from app.schemas.allocation import (
    AllocationCreate,
    AllocationRead,
    AllocationStatus,
    AllocationTransferRequest,
    AllocationVacateRequest,
    OccupantRead,
)
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshTokenRequest,
    TokenResponse,
)
from app.schemas.common import Page, PaginationParams
from app.schemas.health import HealthResponse
from app.schemas.hostel import (
    BlockBase,
    BlockCreate,
    BlockRead,
    BlockUpdate,
    HostelBase,
    HostelCreate,
    HostelRead,
    HostelUpdate,
    WardenAssignmentRead,
    WardenAssignRequest,
)
from app.schemas.room import (
    BedRead,
    RoomBase,
    RoomCreate,
    RoomRead,
    RoomStatus,
    RoomType,
    RoomUpdate,
    RoomWithBedsRead,
)
from app.schemas.student import (
    StudentCreate,
    StudentCreatedResponse,
    StudentProfileRead,
    StudentSelfUpdate,
    StudentUpdate,
)
from app.schemas.user import UserBase, UserCreate, UserRead, UserUpdate

__all__ = [
    "AllocationCreate",
    "AllocationRead",
    "AllocationStatus",
    "AllocationTransferRequest",
    "AllocationVacateRequest",
    "BedRead",
    "BlockBase",
    "BlockCreate",
    "BlockRead",
    "BlockUpdate",
    "ChangePasswordRequest",
    "HealthResponse",
    "HostelBase",
    "HostelCreate",
    "HostelRead",
    "HostelUpdate",
    "LoginRequest",
    "OccupantRead",
    "Page",
    "PaginationParams",
    "RefreshTokenRequest",
    "RoomBase",
    "RoomCreate",
    "RoomRead",
    "RoomStatus",
    "RoomType",
    "RoomUpdate",
    "RoomWithBedsRead",
    "StudentCreate",
    "StudentCreatedResponse",
    "StudentProfileRead",
    "StudentSelfUpdate",
    "StudentUpdate",
    "TokenResponse",
    "UserBase",
    "UserCreate",
    "UserRead",
    "UserUpdate",
    "WardenAssignRequest",
    "WardenAssignmentRead",
]
