"""Pydantic request and response schemas."""

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
from app.schemas.user import UserBase, UserCreate, UserRead, UserUpdate

__all__ = [
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
    "Page",
    "PaginationParams",
    "RefreshTokenRequest",
    "TokenResponse",
    "UserBase",
    "UserCreate",
    "UserRead",
    "UserUpdate",
    "WardenAssignRequest",
    "WardenAssignmentRead",
]
