"""Unit tests for StudentService business rules, transactions, and scoping."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.hostel import GenderType
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.student import StudentCreate, StudentSelfUpdate, StudentUpdate
from app.services.student_service import StudentService


@pytest.mark.asyncio
async def test_create_student_transaction_rollback_on_profile_failure(
    db_session: AsyncSession,
) -> None:
    """Test that failure during profile step rolls back user creation, leaving no orphan user."""
    admin = User(
        id=uuid4(),
        email="admin_creator@example.com",
        full_name="Admin",
        hashed_password="pw",
        role=UserRole.ADMIN,
    )
    db_session.add(admin)
    await db_session.flush()

    service = StudentService(db_session)
    user_repo = UserRepository(db_session)

    payload = StudentCreate(
        email="atomic_student@example.com",
        full_name="Atomic Student",
        student_no="ATOMIC-01",
        gender=GenderType.MALE,
        department="Computer Science",
        year=1,
        guardian_name="Guardian Atomic",
        guardian_phone="+1234567890",
        emergency_contact="+1987654321",
    )

    # Simulate an error right after user addition when flushing the profile
    original_add = db_session.add

    def failing_add(instance: object) -> None:
        if isinstance(instance, StudentProfile):
            raise RuntimeError("Database error during profile insertion")
        original_add(instance)

    with (
        patch.object(db_session, "add", side_effect=failing_add),
        pytest.raises(RuntimeError, match="Database error during profile insertion"),
    ):
        await service.create_student(payload, current_user=admin)

    # Verify no orphan user exists in the database
    orphan = await user_repo.get_by_email("atomic_student@example.com")
    assert orphan is None


@pytest.mark.asyncio
async def test_create_student_duplicate_email_conflict(db_session: AsyncSession) -> None:
    """Test duplicate email raises ConflictError EMAIL_EXISTS."""
    admin = User(
        id=uuid4(),
        email="admin_dup@example.com",
        full_name="Admin",
        hashed_password="pw",
        role=UserRole.ADMIN,
    )
    existing_user = User(
        id=uuid4(),
        email="duplicate@example.com",
        full_name="Existing User",
        hashed_password="pw",
        role=UserRole.STUDENT,
    )
    db_session.add_all([admin, existing_user])
    await db_session.flush()

    service = StudentService(db_session)
    payload = StudentCreate(
        email="duplicate@example.com",
        full_name="New Student",
        student_no="UNIQUE-01",
        gender=GenderType.MALE,
        department="Physics",
        year=1,
        guardian_name="Guardian",
        guardian_phone="+1234567890",
        emergency_contact="+1987654321",
    )
    with pytest.raises(ConflictError) as exc_info:
        await service.create_student(payload, current_user=admin)
    assert exc_info.value.code == "EMAIL_EXISTS"


@pytest.mark.asyncio
async def test_create_student_duplicate_student_no_conflict(
    db_session: AsyncSession,
) -> None:
    """Test duplicate student_no raises ConflictError STUDENT_NO_EXISTS."""
    admin = User(
        id=uuid4(),
        email="admin_dup_no@example.com",
        full_name="Admin",
        hashed_password="pw",
        role=UserRole.ADMIN,
    )
    u = User(
        id=uuid4(),
        email="existing_stu@example.com",
        full_name="Existing Student",
        hashed_password="pw",
        role=UserRole.STUDENT,
    )
    db_session.add_all([admin, u])
    await db_session.flush()

    p = StudentProfile(
        id=uuid4(),
        user_id=u.id,
        student_no="EXISTING-NO-01",
        gender=GenderType.FEMALE,
        department="Chemistry",
        year=2,
        guardian_name="Guardian",
        guardian_phone="+1234567890",
        emergency_contact="+1987654321",
    )
    db_session.add(p)
    await db_session.flush()

    service = StudentService(db_session)
    payload = StudentCreate(
        email="brand_new@example.com",
        full_name="Brand New",
        student_no="EXISTING-NO-01",
        gender=GenderType.FEMALE,
        department="Math",
        year=2,
        guardian_name="Guardian",
        guardian_phone="+1234567890",
        emergency_contact="+1987654321",
    )
    with pytest.raises(ConflictError) as exc_info:
        await service.create_student(payload, current_user=admin)
    assert exc_info.value.code == "STUDENT_NO_EXISTS"


@pytest.mark.asyncio
async def test_create_student_generated_vs_provided_password(
    db_session: AsyncSession,
) -> None:
    """Test password generation when None vs custom password."""
    admin = User(
        id=uuid4(),
        email="admin_pw@example.com",
        full_name="Admin",
        hashed_password="pw",
        role=UserRole.ADMIN,
    )
    db_session.add(admin)
    await db_session.flush()

    service = StudentService(db_session)

    # Without password -> temporary_password returned
    p1 = StudentCreate(
        email="nopw@example.com",
        full_name="No PW",
        student_no="NOPW-01",
        gender=GenderType.MALE,
        department="CS",
        year=1,
        guardian_name="G",
        guardian_phone="+1234567890",
        emergency_contact="+1987654321",
    )
    res1 = await service.create_student(p1, current_user=admin)
    assert res1.temporary_password is not None
    assert len(res1.temporary_password) >= 8

    # With password -> temporary_password is None
    p2 = StudentCreate(
        email="withpw@example.com",
        full_name="With PW",
        student_no="WITHPW-02",
        gender=GenderType.FEMALE,
        department="CS",
        year=2,
        guardian_name="G",
        guardian_phone="+1234567890",
        emergency_contact="+1987654321",
        password="ValidPassword123",
    )
    res2 = await service.create_student(p2, current_user=admin)
    assert res2.temporary_password is None


@pytest.mark.asyncio
async def test_student_self_service_profile(db_session: AsyncSession) -> None:
    """Test get_my_profile and update_my_profile for student user."""
    student_user = User(
        id=uuid4(),
        email="stu_self@example.com",
        full_name="Self Student",
        phone="+1000000000",
        hashed_password="pw",
        role=UserRole.STUDENT,
    )
    db_session.add(student_user)
    await db_session.flush()

    profile = StudentProfile(
        id=uuid4(),
        user_id=student_user.id,
        student_no="SELF-01",
        gender=GenderType.MALE,
        department="Electrical",
        year=3,
        guardian_name="G Name",
        guardian_phone="+1111111111",
        emergency_contact="+1222222222",
    )
    db_session.add(profile)
    await db_session.flush()

    service = StudentService(db_session)

    # Get my profile
    my_prof = await service.get_my_profile(student_user)
    assert my_prof.id == profile.id

    # Update my profile (contact fields only)
    update_data = StudentSelfUpdate(
        phone="+1999999999",
        guardian_phone="+1888888888",
        emergency_contact="+1777777777",
    )
    updated = await service.update_my_profile(student_user, update_data)
    assert updated.guardian_phone == "+1888888888"
    assert updated.emergency_contact == "+1777777777"
    assert student_user.phone == "+1999999999"


@pytest.mark.asyncio
async def test_student_cannot_view_other_student_profile(
    db_session: AsyncSession,
) -> None:
    """Test that a student cannot view another student's profile."""
    u1 = User(
        id=uuid4(),
        email="s1@example.com",
        full_name="S1",
        hashed_password="pw",
        role=UserRole.STUDENT,
    )
    u2 = User(
        id=uuid4(),
        email="s2@example.com",
        full_name="S2",
        hashed_password="pw",
        role=UserRole.STUDENT,
    )
    db_session.add_all([u1, u2])
    await db_session.flush()

    p1 = StudentProfile(
        id=uuid4(),
        user_id=u1.id,
        student_no="S1-01",
        gender=GenderType.FEMALE,
        department="CS",
        year=1,
        guardian_name="G",
        guardian_phone="+1234567890",
        emergency_contact="+1987654321",
    )
    p2 = StudentProfile(
        id=uuid4(),
        user_id=u2.id,
        student_no="S2-02",
        gender=GenderType.MALE,
        department="CS",
        year=1,
        guardian_name="G",
        guardian_phone="+1234567890",
        emergency_contact="+1987654321",
    )
    db_session.add_all([p1, p2])
    await db_session.flush()

    service = StudentService(db_session)

    # S1 views S1 profile -> allowed
    view_own = await service.get_student(p1.id, current_user=u1)
    assert view_own.id == p1.id

    # S1 views S2 profile -> forbidden
    with pytest.raises(ForbiddenError) as exc_info:
        await service.get_student(p2.id, current_user=u1)
    assert exc_info.value.code == "FORBIDDEN"


@pytest.mark.asyncio
async def test_delete_student_soft_deletes_and_deactivates(
    db_session: AsyncSession,
) -> None:
    """Test delete_student soft-deletes profile and sets user.is_active = False."""
    admin = User(
        id=uuid4(),
        email="admin_del@example.com",
        full_name="Admin",
        hashed_password="pw",
        role=UserRole.ADMIN,
    )
    user = User(
        id=uuid4(),
        email="to_delete@example.com",
        full_name="To Delete",
        hashed_password="pw",
        role=UserRole.STUDENT,
        is_active=True,
    )
    db_session.add_all([admin, user])
    await db_session.flush()

    profile = StudentProfile(
        id=uuid4(),
        user_id=user.id,
        student_no="DEL-01",
        gender=GenderType.MALE,
        department="Civil",
        year=4,
        guardian_name="G",
        guardian_phone="+1234567890",
        emergency_contact="+1987654321",
    )
    db_session.add(profile)
    await db_session.flush()

    service = StudentService(db_session)
    await service.delete_student(profile.id, current_user=admin)

    assert profile.is_deleted is True
    assert user.is_active is False


@pytest.mark.asyncio
async def test_student_service_role_permissions_and_not_found(
    db_session: AsyncSession,
) -> None:
    """Test role permission rejections and not found errors across student service."""
    service = StudentService(db_session)

    student = User(
        id=uuid4(),
        email="role_stu@example.com",
        full_name="Role Student",
        hashed_password="pw",
        role=UserRole.STUDENT,
    )
    admin = User(
        id=uuid4(),
        email="role_admin@example.com",
        full_name="Role Admin",
        hashed_password="pw",
        role=UserRole.ADMIN,
    )
    warden = User(
        id=uuid4(),
        email="role_warden@example.com",
        full_name="Role Warden",
        hashed_password="pw",
        role=UserRole.WARDEN,
    )
    db_session.add_all([student, admin, warden])
    await db_session.flush()

    # 1. Student cannot create student
    with pytest.raises(ForbiddenError):
        await service.create_student(
            StudentCreate(
                email="test_forbidden@example.com",
                full_name="Test",
                student_no="FORBIDDEN-01",
                gender=GenderType.MALE,
                department="CS",
                year=1,
                guardian_name="G",
                guardian_phone="+1234567890",
                emergency_contact="+1987654321",
            ),
            current_user=student,
        )

    # 2. Student without profile accessing get_my_profile -> NotFoundError
    with pytest.raises(NotFoundError):
        await service.get_my_profile(student)

    # 3. Student without profile accessing update_my_profile -> NotFoundError
    with pytest.raises(NotFoundError):
        await service.update_my_profile(student, StudentSelfUpdate(phone="+1234567890"))

    # 4. Student without profile accessing get_student -> ForbiddenError
    random_id = uuid4()
    with pytest.raises(ForbiddenError):
        await service.get_student(random_id, current_user=student)

    # 5. Admin get_student not found -> NotFoundError
    with pytest.raises(NotFoundError):
        await service.get_student(random_id, current_user=admin)

    # 6. Student cannot update_student -> ForbiddenError
    with pytest.raises(ForbiddenError):
        await service.update_student(
            random_id,
            StudentUpdate(department="CS"),
            current_user=student,
        )

    # 7. Admin update_student not found -> NotFoundError
    with pytest.raises(NotFoundError):
        await service.update_student(
            random_id,
            StudentUpdate(department="CS"),
            current_user=admin,
        )

    # 8. Student cannot delete_student -> ForbiddenError
    with pytest.raises(ForbiddenError):
        await service.delete_student(random_id, current_user=student)

    # 9. Admin delete_student not found -> NotFoundError
    with pytest.raises(NotFoundError):
        await service.delete_student(random_id, current_user=admin)

    # 10. Student cannot list_students -> ForbiddenError
    from app.schemas.common import PaginationParams

    params = PaginationParams(page=1, size=10)
    with pytest.raises(ForbiddenError):
        await service.list_students(params=params, current_user=student)

    # 11. Warden can list students
    warden_list = await service.list_students(params=params, current_user=warden)
    assert warden_list.total >= 0


@pytest.mark.asyncio
async def test_update_student_user_and_profile_fields(db_session: AsyncSession) -> None:
    """Test update_student updating both User fields and profile fields."""
    admin = User(
        id=uuid4(),
        email="admin_full_up@example.com",
        full_name="Admin",
        hashed_password="pw",
        role=UserRole.ADMIN,
    )
    user = User(
        id=uuid4(),
        email="update_target@example.com",
        full_name="Original Name",
        phone="+1000000000",
        hashed_password="pw",
        role=UserRole.STUDENT,
        is_active=True,
    )
    db_session.add_all([admin, user])
    await db_session.flush()

    profile = StudentProfile(
        id=uuid4(),
        user_id=user.id,
        student_no="FULL-UP-01",
        gender=GenderType.FEMALE,
        department="BioTech",
        year=1,
        guardian_name="Original Guardian",
        guardian_phone="+1111111111",
        emergency_contact="+1222222222",
    )
    db_session.add(profile)
    await db_session.flush()

    service = StudentService(db_session)
    update_payload = StudentUpdate(
        full_name="New Name",
        phone="+1999999999",
        is_active=False,
        department="Biomedical",
        year=2,
        guardian_name="New Guardian",
    )
    updated = await service.update_student(profile.id, update_payload, current_user=admin)

    assert updated.department == "Biomedical"
    assert updated.year == 2
    assert updated.guardian_name == "New Guardian"
    assert updated.user.full_name == "New Name"
    assert updated.user.phone == "+1999999999"
    assert updated.user.is_active is False
