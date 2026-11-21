"""Student service managing profile lifecycle, transactions, and access rules."""

import secrets
import string
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.security import hash_password, validate_password_policy
from app.models.hostel import GenderType
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.repositories.allocation_repository import AllocationRepository
from app.repositories.hostel_repository import WardenAssignmentRepository
from app.repositories.student_repository import StudentRepository
from app.repositories.user_repository import UserRepository
from app.schemas.common import Page, PaginationParams
from app.schemas.student import (
    StudentCreate,
    StudentCreatedResponse,
    StudentProfileRead,
    StudentSelfUpdate,
    StudentUpdate,
)


def generate_temporary_password(length: int = 12) -> str:
    """Generate a cryptographically secure random password meeting strength policy."""
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.isalpha() for c in pw) and any(c.isdigit() for c in pw):
            return pw


class StudentService:
    """Service handling business rules, transactions, and scoping for students."""

    def __init__(
        self,
        session: AsyncSession,
        student_repo: StudentRepository | None = None,
        user_repo: UserRepository | None = None,
        warden_repo: WardenAssignmentRepository | None = None,
        allocation_repo: AllocationRepository | None = None,
    ) -> None:
        self.session = session
        self.student_repo = student_repo or StudentRepository(session)
        self.user_repo = user_repo or UserRepository(session)
        self.warden_repo = warden_repo or WardenAssignmentRepository(session)
        self.allocation_repo = allocation_repo or AllocationRepository(session)

    async def _ensure_warden_can_access_student(
        self, warden: User, profile: StudentProfile
    ) -> None:
        """Scoping hook: Warden sees students allocated in assigned hostels or unallocated."""
        active_alloc = await self.allocation_repo.get_active_by_student_id(profile.id)
        if active_alloc is not None:
            hostel_id = active_alloc.bed.room.block.hostel_id
            warden_hostels = await self.warden_repo.list_hostel_ids_for_warden(warden.id)
            if hostel_id not in warden_hostels:
                raise ForbiddenError(
                    "You cannot access students allocated outside your assigned hostels",
                    code="FORBIDDEN",
                )

    async def create_student(
        self, data: StudentCreate, current_user: User
    ) -> StudentCreatedResponse:
        """Create User and StudentProfile atomically in a single transaction."""
        user_role = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if user_role not in (UserRole.ADMIN.value, UserRole.WARDEN.value):
            raise ForbiddenError(
                "Only admin and warden can create student profiles",
                code="FORBIDDEN",
            )

        existing_user = await self.user_repo.get_by_email(data.email)
        if existing_user is not None:
            raise ConflictError("User with this email already exists", code="EMAIL_EXISTS")

        existing_student = await self.student_repo.get_by_student_no(
            data.student_no, include_deleted=True
        )
        if existing_student is not None:
            raise ConflictError("Student number already exists", code="STUDENT_NO_EXISTS")

        if data.password:
            validate_password_policy(data.password)
            plain_password = data.password
            temporary_password: str | None = None
        else:
            plain_password = generate_temporary_password()
            temporary_password = plain_password

        hashed = hash_password(plain_password)

        try:
            user = User(
                email=data.email.strip().lower(),
                full_name=data.full_name.strip(),
                phone=data.phone.strip() if data.phone else None,
                hashed_password=hashed,
                role=UserRole.STUDENT,
                is_active=True,
            )
            self.session.add(user)
            await self.session.flush()

            profile = StudentProfile(
                user_id=user.id,
                student_no=data.student_no.strip(),
                gender=data.gender,
                department=data.department.strip(),
                year=data.year,
                guardian_name=data.guardian_name.strip(),
                guardian_phone=data.guardian_phone.strip(),
                emergency_contact=data.emergency_contact.strip(),
            )
            self.session.add(profile)
            await self.session.flush()
            await self.session.refresh(profile)
            profile.user = user

            return StudentCreatedResponse(
                id=profile.id,
                user_id=profile.user_id,
                student_no=profile.student_no,
                gender=profile.gender,
                department=profile.department,
                year=profile.year,
                guardian_name=profile.guardian_name,
                guardian_phone=profile.guardian_phone,
                emergency_contact=profile.emergency_contact,
                is_deleted=profile.is_deleted,
                created_at=profile.created_at,
                updated_at=profile.updated_at,
                full_name=user.full_name,
                email=user.email,
                phone=user.phone,
                is_active=user.is_active,
                current_allocation=None,
                temporary_password=temporary_password,
            )
        except Exception:
            await self.session.rollback()
            raise

    async def get_my_profile(self, current_user: User) -> StudentProfile:
        """Fetch profile for current student user."""
        profile = await self.student_repo.get_by_user_id(current_user.id)
        if profile is None:
            raise NotFoundError("Student profile not found", code="PROFILE_NOT_FOUND")
        profile.current_allocation = await self.allocation_repo.get_active_by_student_id(profile.id)
        return profile

    async def update_my_profile(
        self, current_user: User, data: StudentSelfUpdate
    ) -> StudentProfile:
        """Update contact fields only for the current student user."""
        profile = await self.student_repo.get_by_user_id(current_user.id)
        if profile is None:
            raise NotFoundError("Student profile not found", code="PROFILE_NOT_FOUND")

        update_data = data.model_dump(exclude_unset=True)
        if "phone" in update_data:
            current_user.phone = update_data["phone"]
            await self.user_repo.update(current_user)

        if "emergency_contact" in update_data:
            profile.emergency_contact = update_data["emergency_contact"]
        if "guardian_phone" in update_data:
            profile.guardian_phone = update_data["guardian_phone"]

        updated_profile = await self.student_repo.update(profile)
        updated_profile.user = current_user
        return updated_profile

    async def get_student(self, id: UUID, current_user: User) -> StudentProfile:
        """Fetch student profile enforcing role and ownership rules."""
        user_role = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )

        if user_role == UserRole.STUDENT.value:
            my_profile = await self.student_repo.get_by_user_id(current_user.id)
            if my_profile is None or my_profile.id != id:
                raise ForbiddenError(
                    "You cannot view other student profiles",
                    code="FORBIDDEN",
                )
            my_profile.current_allocation = await self.allocation_repo.get_active_by_student_id(
                my_profile.id
            )
            return my_profile

        profile = await self.student_repo.get_by_id(id)
        if profile is None:
            raise NotFoundError("Student not found", code="STUDENT_NOT_FOUND")

        if user_role == UserRole.WARDEN.value:
            await self._ensure_warden_can_access_student(current_user, profile)

        profile.current_allocation = await self.allocation_repo.get_active_by_student_id(profile.id)
        return profile

    async def update_student(
        self, id: UUID, data: StudentUpdate, current_user: User
    ) -> StudentProfile:
        """Update student profile and user account by admin or warden."""
        user_role = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if user_role not in (UserRole.ADMIN.value, UserRole.WARDEN.value):
            raise ForbiddenError(
                "Only admin and warden can update student profiles",
                code="FORBIDDEN",
            )

        profile = await self.student_repo.get_by_id(id)
        if profile is None:
            raise NotFoundError("Student not found", code="STUDENT_NOT_FOUND")

        if user_role == UserRole.WARDEN.value:
            await self._ensure_warden_can_access_student(current_user, profile)

        update_dict = data.model_dump(exclude_unset=True)
        user_fields = {"full_name", "phone", "is_active"}
        user_updated = False
        for field in user_fields:
            if field in update_dict:
                setattr(profile.user, field, update_dict[field])
                user_updated = True
        if user_updated:
            await self.user_repo.update(profile.user)

        profile_fields = {
            "department",
            "year",
            "guardian_name",
            "guardian_phone",
            "emergency_contact",
        }
        for field in profile_fields:
            if field in update_dict:
                setattr(profile, field, update_dict[field])

        return await self.student_repo.update(profile)

    async def delete_student(self, id: UUID, current_user: User) -> None:
        """Soft delete StudentProfile and deactivate User in same transaction."""
        user_role = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if user_role not in (UserRole.ADMIN.value, UserRole.WARDEN.value):
            raise ForbiddenError(
                "Only admin and warden can delete students",
                code="FORBIDDEN",
            )

        profile = await self.student_repo.get_by_id(id)
        if profile is None:
            raise NotFoundError("Student not found", code="STUDENT_NOT_FOUND")

        if user_role == UserRole.WARDEN.value:
            await self._ensure_warden_can_access_student(current_user, profile)

        try:
            profile.is_deleted = True
            await self.student_repo.update(profile)

            profile.user.is_active = False
            await self.user_repo.update(profile.user)
        except Exception:
            await self.session.rollback()
            raise

    async def list_students(
        self,
        params: PaginationParams,
        current_user: User,
        department: str | None = None,
        year: int | None = None,
        gender: GenderType | None = None,
        has_allocation: bool | None = None,
        search: str | None = None,
    ) -> Page[StudentProfileRead]:
        """Fetch paginated list of student profiles with filters and warden scoping."""
        user_role = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if user_role not in (UserRole.ADMIN.value, UserRole.WARDEN.value):
            raise ForbiddenError(
                "Only admin and warden can list students",
                code="FORBIDDEN",
            )

        warden_hostel_ids: list[UUID] | None = None
        if user_role == UserRole.WARDEN.value:
            warden_hostel_ids = await self.warden_repo.list_hostel_ids_for_warden(current_user.id)

        profiles, total = await self.student_repo.list(
            params=params,
            department=department,
            year=year,
            gender=gender,
            has_allocation=has_allocation,
            search=search,
            warden_hostel_ids=warden_hostel_ids,
        )

        for p in profiles:
            p.current_allocation = await self.allocation_repo.get_active_by_student_id(p.id)

        items = [StudentProfileRead.model_validate(p) for p in profiles]
        return Page.create(items=items, total=total, params=params)
