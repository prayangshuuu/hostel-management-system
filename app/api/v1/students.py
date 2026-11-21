"""Student management and self-service API endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user, get_db, require_role
from app.models.hostel import GenderType
from app.models.user import User, UserRole
from app.schemas.common import Page, PaginationParams
from app.schemas.student import (
    StudentCreate,
    StudentCreatedResponse,
    StudentProfileRead,
    StudentUpdate,
)
from app.services.student_service import StudentService

router = APIRouter(prefix="/students", tags=["students"])


@router.post(
    "",
    response_model=StudentCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create student user and profile (admin or warden)",
)
async def create_student(
    body: StudentCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
) -> StudentCreatedResponse:
    """Create a new student user and linked student profile in a single transaction."""
    service = StudentService(session)
    return await service.create_student(data=body, current_user=current_user)


@router.get(
    "",
    response_model=Page[StudentProfileRead],
    summary="List student profiles (admin or warden)",
)
async def list_students(
    params: Annotated[PaginationParams, Depends()],
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
    department: Annotated[str | None, Query(description="Filter by department")] = None,
    year: Annotated[int | None, Query(ge=1, le=6, description="Filter by year")] = None,
    gender: Annotated[GenderType | None, Query(description="Filter by gender")] = None,
    has_allocation: Annotated[
        bool | None, Query(description="Filter by bed allocation status")
    ] = None,
    search: Annotated[str | None, Query(description="Search by name, student no, or email")] = None,
) -> Page[StudentProfileRead]:
    """List student profiles with optional filters, search, and warden scoping."""
    service = StudentService(session)
    return await service.list_students(
        params=params,
        current_user=current_user,
        department=department,
        year=year,
        gender=gender,
        has_allocation=has_allocation,
        search=search,
    )


@router.get(
    "/{id}",
    response_model=StudentProfileRead,
    summary="Get student profile by ID (admin, warden, or student self)",
)
async def get_student(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> StudentProfileRead:
    """Retrieve single student profile enforcing ownership and warden scoping."""
    service = StudentService(session)
    profile = await service.get_student(id=id, current_user=current_user)
    return StudentProfileRead.model_validate(profile)


@router.patch(
    "/{id}",
    response_model=StudentProfileRead,
    summary="Update student profile and user details (admin or warden)",
)
async def update_student(
    id: UUID,
    body: StudentUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
) -> StudentProfileRead:
    """Update academic, contact, and account details of a student."""
    service = StudentService(session)
    profile = await service.update_student(id=id, data=body, current_user=current_user)
    return StudentProfileRead.model_validate(profile)


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft delete student profile and deactivate user (admin or warden)",
)
async def delete_student(
    id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN, UserRole.WARDEN))],
) -> None:
    """Soft delete student profile and mark user account inactive."""
    service = StudentService(session)
    await service.delete_student(id=id, current_user=current_user)
