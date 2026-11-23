"""Coverage hardening unit tests for backend services layer."""

from datetime import UTC, date, datetime, time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.models.allocation import AllocationStatus
from app.models.billing import (
    FeePeriod,
    FeeStructure,
    Invoice,
    InvoiceStatus,
    Payment,
)
from app.models.complaint import ComplaintStatus
from app.models.hostel import Block, GenderType, Hostel
from app.models.mess import MealType
from app.models.notice import Notice, NoticeAudience
from app.models.operations import AttendanceLog, AttendanceType, LeaveRequest, LeaveStatus, Visitor
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.schemas.allocation import AllocationTransferRequest, AllocationVacateRequest
from app.schemas.billing import FeeStructureCreate
from app.schemas.common import PaginationParams
from app.schemas.complaint import (
    ComplaintAssignRequest,
    ComplaintCommentCreate,
    ComplaintStatusUpdateRequest,
)
from app.schemas.mess import MealOptOutCreate, MessMenuBulkUpdateRequest
from app.schemas.notice import NoticeCreate, NoticeUpdate
from app.schemas.operations import (
    AttendanceActionRequest,
    LeaveRequestCreate,
    VisitorCreate,
)
from app.schemas.student import StudentUpdate
from app.services.allocation_service import AllocationService
from app.services.billing_service import BillingService
from app.services.complaint_service import ComplaintService
from app.services.mess_service import MessService
from app.services.notice_service import NoticeService
from app.services.operations_service import OperationsService
from app.services.report_service import ReportService
from app.services.student_service import StudentService


def _mock_session_with_nested() -> AsyncMock:
    """Helper to mock AsyncSession with begin_nested sync factory."""
    session = AsyncMock()
    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=None)
    nested_cm.__aexit__ = AsyncMock(return_value=None)
    session.begin_nested = MagicMock(return_value=nested_cm)
    return session


# =============================================================================
# 1. StudentService Hardening Tests
# =============================================================================


@pytest.mark.asyncio
async def test_student_service_warden_access_forbidden() -> None:
    session = AsyncMock()
    service = StudentService(session)
    service.allocation_repo = AsyncMock()
    service.warden_repo = AsyncMock()

    warden = User(id=uuid4(), email="w@test.com", full_name="Warden", role=UserRole.WARDEN)
    profile = StudentProfile(id=uuid4(), user_id=uuid4(), student_no="S1", gender=GenderType.MALE)

    alloc = MagicMock()
    alloc.bed.room.block.hostel_id = uuid4()
    service.allocation_repo.get_active_by_student_id.return_value = alloc
    service.warden_repo.list_hostel_ids_for_warden.return_value = [uuid4()]

    with pytest.raises(ForbiddenError, match="outside your assigned hostels"):
        await service._ensure_warden_can_access_student(warden, profile)


@pytest.mark.asyncio
async def test_student_service_get_student_as_warden_with_allocation() -> None:
    session = AsyncMock()
    service = StudentService(session)
    service.student_repo = AsyncMock()
    service.allocation_repo = AsyncMock()
    service.warden_repo = AsyncMock()

    hostel_id = uuid4()
    warden = User(id=uuid4(), email="w@test.com", full_name="Warden", role=UserRole.WARDEN)
    profile = StudentProfile(id=uuid4(), user_id=uuid4(), student_no="S1", gender=GenderType.MALE)

    alloc = MagicMock()
    alloc.bed.room.block.hostel_id = hostel_id
    service.allocation_repo.get_active_by_student_id.return_value = alloc
    service.warden_repo.list_hostel_ids_for_warden.return_value = [hostel_id]
    service.student_repo.get_by_id.return_value = profile

    res = await service.get_student(profile.id, current_user=warden)
    assert res.id == profile.id
    assert res.current_allocation == alloc


@pytest.mark.asyncio
async def test_student_service_update_and_delete_as_warden() -> None:
    session = AsyncMock()
    service = StudentService(session)
    service.student_repo = AsyncMock()
    service.user_repo = AsyncMock()
    service.allocation_repo = AsyncMock()
    service.warden_repo = AsyncMock()

    hostel_id = uuid4()
    warden = User(id=uuid4(), email="w@test.com", full_name="Warden", role=UserRole.WARDEN)
    u = User(
        id=uuid4(), email="s@test.com", full_name="Student", role=UserRole.STUDENT, is_active=True
    )
    profile = StudentProfile(
        id=uuid4(), user_id=u.id, student_no="S1", gender=GenderType.MALE, user=u
    )

    alloc = MagicMock()
    alloc.bed.room.block.hostel_id = hostel_id
    service.allocation_repo.get_active_by_student_id.return_value = alloc
    service.warden_repo.list_hostel_ids_for_warden.return_value = [hostel_id]
    service.student_repo.get_by_id.return_value = profile

    # update_student
    await service.update_student(
        profile.id, StudentUpdate(full_name="New Name"), current_user=warden
    )
    service.student_repo.update.assert_awaited()

    # delete_student
    await service.delete_student(profile.id, current_user=warden)
    assert profile.is_deleted is True
    assert profile.user.is_active is False


@pytest.mark.asyncio
async def test_student_service_delete_student_rollback_on_error() -> None:
    session = AsyncMock()
    service = StudentService(session)
    service.student_repo = AsyncMock()
    service.user_repo = AsyncMock()

    admin = User(id=uuid4(), email="a@test.com", full_name="Admin", role=UserRole.ADMIN)
    u = User(id=uuid4(), email="s@test.com", full_name="Student", role=UserRole.STUDENT)
    profile = StudentProfile(
        id=uuid4(), user_id=u.id, student_no="S1", gender=GenderType.MALE, user=u
    )

    service.student_repo.get_by_id.return_value = profile
    service.student_repo.update.side_effect = RuntimeError("DB write failed")

    with pytest.raises(RuntimeError, match="DB write failed"):
        await service.delete_student(profile.id, current_user=admin)
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_student_service_list_students_populates_active_allocation() -> None:
    session = AsyncMock()
    service = StudentService(session)
    service.student_repo = AsyncMock()
    service.allocation_repo = AsyncMock()

    admin = User(id=uuid4(), email="a@test.com", full_name="Admin", role=UserRole.ADMIN)
    p_id = uuid4()
    p = MagicMock()
    p.id = p_id
    service.student_repo.list.return_value = ([p], 1)
    service.allocation_repo.get_active_by_student_ids.return_value = {p_id: MagicMock()}

    with patch("app.schemas.student.StudentProfileRead.model_validate") as mock_val:
        mock_val.return_value = MagicMock()
        page = await service.list_students(PaginationParams(page=1, size=10), current_user=admin)
        assert page.total == 1
        assert p.current_allocation is not None


# =============================================================================
# 2. NoticeService Hardening Tests
# =============================================================================


@pytest.mark.asyncio
async def test_notice_service_get_student_hostel_id_branches() -> None:
    session = AsyncMock()
    service = NoticeService(session)
    service.student_repo = AsyncMock()
    service.allocation_repo = AsyncMock()

    u_id = uuid4()
    # 1. profile is None
    service.student_repo.get_by_user_id.return_value = None
    assert await service._get_student_hostel_id(u_id) is None

    # 2. profile exists, allocation is None
    prof = MagicMock(id=uuid4())
    service.student_repo.get_by_user_id.return_value = prof
    service.allocation_repo.get_active_by_student_id.return_value = None
    assert await service._get_student_hostel_id(u_id) is None

    # 3. bed is None
    alloc = MagicMock(bed=None)
    service.allocation_repo.get_active_by_student_id.return_value = alloc
    assert await service._get_student_hostel_id(u_id) is None

    # 4. room is None
    alloc.bed = MagicMock(room=None)
    assert await service._get_student_hostel_id(u_id) is None

    # 5. block is None
    alloc.bed.room = MagicMock(block=None)
    assert await service._get_student_hostel_id(u_id) is None

    # 6. valid block
    hostel_id = uuid4()
    alloc.bed.room.block = MagicMock(hostel_id=hostel_id)
    assert await service._get_student_hostel_id(u_id) == hostel_id


@pytest.mark.asyncio
async def test_notice_service_create_naive_timestamps_and_expiry() -> None:
    session = AsyncMock()
    service = NoticeService(session)
    service.notice_repo = AsyncMock()

    admin = User(id=uuid4(), email="a@test.com", full_name="Admin", role=UserRole.ADMIN)

    # expires_at <= published_at raises BusinessRuleError
    payload_invalid = NoticeCreate.model_construct(
        title="Notice 1",
        body="Body",
        audience=NoticeAudience.ALL,
        hostel_id=None,
        published_at=datetime(2026, 1, 2, 10, 0),
        expires_at=datetime(2026, 1, 1, 10, 0),
        is_pinned=False,
    )
    with pytest.raises(BusinessRuleError, match="strictly after"):
        await service.create_notice(admin, payload_invalid)

    # valid naive timestamps get converted to UTC tzinfo
    payload_valid = NoticeCreate(
        title="Notice 2",
        body="Body",
        audience=NoticeAudience.ALL,
        published_at=datetime(2026, 1, 1, 10, 0),
        expires_at=datetime(2026, 1, 2, 10, 0),
    )
    created_notice = Notice(
        id=uuid4(),
        title="Notice 2",
        body="Body",
        audience=NoticeAudience.ALL,
        published_at=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
        expires_at=datetime(2026, 1, 2, 10, 0, tzinfo=UTC),
        created_by_id=admin.id,
        is_pinned=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    service.notice_repo.create.return_value = created_notice
    service.notice_repo.get_by_id.return_value = created_notice

    res = await service.create_notice(admin, payload_valid)
    assert res.title == "Notice 2"


@pytest.mark.asyncio
async def test_notice_service_update_and_delete_edge_cases() -> None:
    session = AsyncMock()
    service = NoticeService(session)
    service.notice_repo = AsyncMock()

    admin = User(id=uuid4(), email="a@test.com", full_name="Admin", role=UserRole.ADMIN)
    student = User(id=uuid4(), email="s@test.com", full_name="Student", role=UserRole.STUDENT)
    notice_id = uuid4()

    # update notice not found
    service.notice_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.update_notice(admin, notice_id, NoticeUpdate(title="T"))

    # update notice forbidden for student
    notice = Notice(
        id=notice_id,
        title="Old",
        body="B",
        audience=NoticeAudience.ALL,
        published_at=datetime.now(UTC),
        created_by_id=admin.id,
        is_pinned=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    service.notice_repo.get_by_id.return_value = notice
    with pytest.raises(ForbiddenError):
        await service.update_notice(student, notice_id, NoticeUpdate(title="T"))

    # update notice naive expires_at conversion
    update_naive = NoticeUpdate(expires_at=datetime(2026, 12, 31, 23, 59))
    service.notice_repo.update.return_value = notice
    await service.update_notice(admin, notice_id, update_naive)

    # delete notice not found
    service.notice_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.delete_notice(admin, notice_id)

    # delete notice forbidden for student
    service.notice_repo.get_by_id.return_value = notice
    with pytest.raises(ForbiddenError):
        await service.delete_notice(student, notice_id)


@pytest.mark.asyncio
async def test_notice_service_get_notice_role_scenarios() -> None:
    session = AsyncMock()
    service = NoticeService(session)
    service.notice_repo = AsyncMock()
    service.warden_repo = AsyncMock()
    service.read_repo = AsyncMock()
    service.read_repo.get_read_notice_ids_for_user.return_value = set()

    h1 = uuid4()
    h2 = uuid4()
    admin = User(id=uuid4(), email="a@test.com", full_name="Admin", role=UserRole.ADMIN)
    warden = User(id=uuid4(), email="w@test.com", full_name="Warden", role=UserRole.WARDEN)
    student = User(id=uuid4(), email="s@test.com", full_name="Student", role=UserRole.STUDENT)

    # 1. Admin views notice -> passes
    notice = Notice(
        id=uuid4(),
        title="Notice",
        body="Body",
        audience=NoticeAudience.STUDENTS,
        published_at=datetime.now(UTC),
        created_by_id=admin.id,
        is_pinned=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    service.notice_repo.get_by_id.return_value = notice
    read = await service.get_notice(admin, notice.id)
    assert read.id == notice.id

    # 2. Warden views notice with STUDENTS audience -> ForbiddenError
    service.warden_repo.list_hostel_ids_for_warden.return_value = [h1]
    with pytest.raises(ForbiddenError):
        await service.get_notice(warden, notice.id)

    # 3. Warden views notice outside assigned hostels -> ForbiddenError
    notice.audience = NoticeAudience.WARDENS
    notice.hostel_id = h2
    with pytest.raises(ForbiddenError):
        await service.get_notice(warden, notice.id)

    # 4. Warden views draft/expired notice created by someone else -> NotFoundError
    notice.hostel_id = h1
    notice.created_by_id = admin.id
    notice.expires_at = datetime(2020, 1, 1, tzinfo=UTC)
    with pytest.raises(NotFoundError):
        await service.get_notice(warden, notice.id)

    # 5. Student views expired notice -> NotFoundError
    with pytest.raises(NotFoundError):
        await service.get_notice(student, notice.id)

    # 6. Student views future draft notice -> NotFoundError
    notice.expires_at = None
    notice.published_at = datetime(2099, 1, 1, tzinfo=UTC)
    with pytest.raises(NotFoundError):
        await service.get_notice(student, notice.id)

    # 7. Student views notice with WARDENS audience -> ForbiddenError
    notice.published_at = datetime(2020, 1, 1, tzinfo=UTC)
    with pytest.raises(ForbiddenError):
        await service.get_notice(student, notice.id)

    # 8. Student views notice with different hostel -> ForbiddenError
    notice.audience = NoticeAudience.STUDENTS
    service._get_student_hostel_id = AsyncMock(return_value=h2)
    with pytest.raises(ForbiddenError):
        await service.get_notice(student, notice.id)


@pytest.mark.asyncio
async def test_notice_service_list_and_unread_count_warden() -> None:
    session = AsyncMock()
    service = NoticeService(session)
    service.warden_repo = AsyncMock()
    service.notice_repo = AsyncMock()
    service.read_repo = AsyncMock()

    h_id = uuid4()
    warden = User(id=uuid4(), email="w@test.com", full_name="Warden", role=UserRole.WARDEN)
    service.warden_repo.list_hostel_ids_for_warden.return_value = [h_id]
    service.notice_repo.list_visible.return_value = ([], 0)
    service.read_repo.get_read_notice_ids_for_user.return_value = set()
    service.read_repo.get_unread_count.return_value = 5

    page = await service.list_notices(PaginationParams(page=1, size=10), current_user=warden)
    assert page.total == 0

    count = await service.get_unread_count(current_user=warden)
    assert count.unread_count == 5


# =============================================================================
# 3. MessService Hardening Tests
# =============================================================================


@pytest.mark.asyncio
async def test_mess_service_update_hostel_menu_not_found() -> None:
    session = AsyncMock()
    service = MessService(session)
    service.hostel_repo = AsyncMock()
    service.hostel_repo.get_by_id.return_value = None

    admin = User(id=uuid4(), email="a@test.com", full_name="Admin", role=UserRole.ADMIN)
    with pytest.raises(NotFoundError, match="Hostel not found"):
        await service.update_hostel_menu(uuid4(), MessMenuBulkUpdateRequest(entries=[]), admin)


@pytest.mark.asyncio
async def test_mess_service_get_hostel_menu_roles_and_branches() -> None:
    session = AsyncMock()
    service = MessService(session)
    service.hostel_repo = AsyncMock()
    service.mess_menu_repo = AsyncMock()
    service.hostel_service = AsyncMock()
    service.student_repo = AsyncMock()
    service.allocation_repo = AsyncMock()

    h_id = uuid4()
    hostel = Hostel(id=h_id, name="H", code="H", gender_type=GenderType.MIXED)
    service.hostel_repo.get_by_id.return_value = hostel
    service.mess_menu_repo.get_by_hostel.return_value = []

    # Admin pass
    admin = User(id=uuid4(), email="a@test.com", full_name="Admin", role=UserRole.ADMIN)
    menu = await service.get_hostel_menu(h_id, admin)
    assert menu.hostel_id == h_id

    # Warden ensure_hostel_access
    warden = User(id=uuid4(), email="w@test.com", full_name="Warden", role=UserRole.WARDEN)
    menu_w = await service.get_hostel_menu(h_id, warden)
    assert menu_w.hostel_id == h_id
    service.hostel_service.ensure_hostel_access.assert_awaited_with(warden, h_id)

    # Student without profile -> ForbiddenError
    student = User(id=uuid4(), email="s@test.com", full_name="Student", role=UserRole.STUDENT)
    service.student_repo.get_by_user_id.return_value = None
    with pytest.raises(ForbiddenError):
        await service.get_hostel_menu(h_id, student)

    # Student without active allocation -> ForbiddenError
    prof = StudentProfile(id=uuid4(), user_id=student.id, student_no="S1", gender=GenderType.MALE)
    service.student_repo.get_by_user_id.return_value = prof
    service.allocation_repo.get_active_by_student_id.return_value = None
    with pytest.raises(ForbiddenError):
        await service.get_hostel_menu(h_id, student)

    # Unknown role -> ForbiddenError
    other_user = User(id=uuid4(), email="o@test.com", full_name="Other", role="OTHER")
    with pytest.raises(ForbiddenError):
        await service.get_hostel_menu(h_id, other_user)


@pytest.mark.asyncio
async def test_mess_service_student_menu_and_opt_out_missing_records() -> None:
    session = AsyncMock()
    service = MessService(session)
    service.student_repo = AsyncMock()
    service.allocation_repo = AsyncMock()
    service.meal_opt_out_repo = AsyncMock()
    service.hostel_repo = AsyncMock()

    student = User(id=uuid4(), email="s@test.com", full_name="Student", role=UserRole.STUDENT)

    # get_student_today_menu profile None -> NotFoundError
    service.student_repo.get_by_user_id.return_value = None
    with pytest.raises(NotFoundError, match="Student profile not found"):
        await service.get_student_today_menu(student)

    # get_student_today_menu allocation None -> BusinessRuleError
    prof = StudentProfile(id=uuid4(), user_id=student.id, student_no="S1", gender=GenderType.MALE)
    service.student_repo.get_by_user_id.return_value = prof
    service.allocation_repo.get_active_by_student_id.return_value = None
    with pytest.raises(BusinessRuleError, match="active allocation"):
        await service.get_student_today_menu(student)

    # opt_out_meal profile None -> NotFoundError
    service.student_repo.get_by_user_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.opt_out_meal(
            MealOptOutCreate(date=date.today(), meal_type=MealType.BREAKFAST), student
        )

    # opt_out_meal allocation None -> BusinessRuleError
    service.student_repo.get_by_user_id.return_value = prof
    with pytest.raises(BusinessRuleError, match="active allocation"):
        await service.opt_out_meal(
            MealOptOutCreate(date=date.today(), meal_type=MealType.BREAKFAST), student
        )

    # cancel_opt_out profile None -> NotFoundError
    service.student_repo.get_by_user_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.cancel_opt_out(uuid4(), student)

    # cancel_opt_out opt_out None -> NotFoundError
    service.student_repo.get_by_user_id.return_value = prof
    service.meal_opt_out_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="Meal opt-out not found"):
        await service.cancel_opt_out(uuid4(), student)

    # list_student_opt_outs profile None -> NotFoundError
    service.student_repo.get_by_user_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.list_student_opt_outs(PaginationParams(page=1, size=10), student)

    # get_headcount hostel not found -> NotFoundError
    service.hostel_repo.get_by_id.return_value = None
    admin = User(id=uuid4(), email="a@test.com", full_name="Admin", role=UserRole.ADMIN)
    with pytest.raises(NotFoundError, match="Hostel not found"):
        await service.get_headcount(uuid4(), date.today(), admin)


# =============================================================================
# 4. BillingService Hardening Tests
# =============================================================================


@pytest.mark.asyncio
async def test_billing_service_fee_structure_and_invoice_generate_errors() -> None:
    session = AsyncMock()
    service = BillingService(session)
    service.hostel_repo = AsyncMock()
    service.fee_repo = AsyncMock()
    service.allocation_repo = AsyncMock()
    service.invoice_repo = AsyncMock()

    # create_fee_structure hostel not found
    service.hostel_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="Hostel not found"):
        await service.create_fee_structure(
            FeeStructureCreate(
                hostel_id=uuid4(),
                room_type=RoomType.DOUBLE,
                amount=Decimal("100"),
                period=FeePeriod.MONTHLY,
            )
        )

    # generate_invoices hostel not found
    admin = User(id=uuid4(), email="a@test.com", full_name="Admin", role=UserRole.ADMIN)
    with pytest.raises(NotFoundError, match="Hostel not found"):
        await service.generate_invoices(
            uuid4(), date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 5), admin
        )

    # generate_invoices missing fee structure raises BusinessRuleError
    hostel = Hostel(id=uuid4(), name="H", code="H", gender_type=GenderType.MIXED)
    service.hostel_repo.get_by_id.return_value = hostel
    service.fee_repo.list_by_hostel.return_value = []  # no fee structure

    alloc = MagicMock()
    alloc.id = uuid4()
    alloc.start_date = date(2026, 1, 1)
    alloc.end_date = None
    alloc.bed.room.room_type = RoomType.SINGLE
    alloc.bed.room.monthly_rent = None  # no monthly rent either
    service.allocation_repo.get_overlapping_for_hostel.return_value = [alloc]
    service.invoice_repo.get_existing_for_allocation_period.return_value = None

    with pytest.raises(BusinessRuleError, match="No active fee structure found"):
        await service.generate_invoices(
            hostel.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 5), admin
        )


@pytest.mark.asyncio
async def test_billing_service_generate_invoices_d_days_le_zero_skip() -> None:
    session = AsyncMock()
    service = BillingService(session)
    service.hostel_repo = AsyncMock()
    service.fee_repo = AsyncMock()
    service.allocation_repo = AsyncMock()
    service.invoice_repo = AsyncMock()

    hostel = Hostel(id=uuid4(), name="H", code="H", gender_type=GenderType.MIXED)
    service.hostel_repo.get_by_id.return_value = hostel
    fs = FeeStructure(
        id=uuid4(),
        hostel_id=hostel.id,
        room_type=RoomType.SINGLE,
        amount=Decimal("100"),
        period=FeePeriod.MONTHLY,
    )
    service.fee_repo.list_by_hostel.return_value = [fs]

    alloc = MagicMock()
    alloc.id = uuid4()
    # End date before period_start produces d_days <= 0
    alloc.start_date = date(2026, 1, 15)
    alloc.end_date = date(2026, 1, 10)
    alloc.bed.room.room_type = RoomType.SINGLE
    service.allocation_repo.get_overlapping_for_hostel.return_value = [alloc]
    service.invoice_repo.get_existing_for_allocation_period.return_value = None

    admin = User(id=uuid4(), email="a@test.com", full_name="Admin", role=UserRole.ADMIN)
    res = await service.generate_invoices(
        hostel.id, date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 5), admin
    )
    assert res.skipped_count == 1
    assert res.generated_count == 0


@pytest.mark.asyncio
async def test_billing_service_get_list_invoices_forbidden_and_not_found() -> None:
    session = AsyncMock()
    service = BillingService(session)
    service.invoice_repo = AsyncMock()
    service.warden_repo = AsyncMock()

    other = User(id=uuid4(), email="o@test.com", full_name="Other", role="ANONYMOUS")
    student = User(id=uuid4(), email="s@test.com", full_name="Student", role=UserRole.STUDENT)

    # get_invoice not found
    service.invoice_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="Invoice not found"):
        await service.get_invoice(uuid4(), student)

    # get_invoice unknown role -> ForbiddenError
    inv = MagicMock()
    service.invoice_repo.get_by_id.return_value = inv
    with pytest.raises(ForbiddenError):
        await service.get_invoice(uuid4(), other)

    # list_invoices student role -> ForbiddenError
    with pytest.raises(ForbiddenError):
        await service.list_invoices(PaginationParams(page=1, size=10), student)

    # list_invoices returns items
    admin = User(id=uuid4(), email="a@test.com", full_name="Admin", role=UserRole.ADMIN)
    inv_obj = Invoice(
        id=uuid4(),
        allocation_id=uuid4(),
        student_id=uuid4(),
        amount=Decimal("100"),
        paid_amount=Decimal("0"),
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        due_date=date(2026, 2, 5),
        status=InvoiceStatus.UNPAID,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    service.invoice_repo.list.return_value = ([inv_obj], 1)
    page = await service.list_invoices(PaginationParams(page=1, size=10), admin)
    assert page.total == 1
    assert len(page.items) == 1


@pytest.mark.asyncio
async def test_billing_service_record_payment_not_found_and_forbidden() -> None:
    session = AsyncMock()
    service = BillingService(session)
    service.invoice_repo = AsyncMock()

    service.invoice_repo.get_by_id_for_update.return_value = None
    student = User(id=uuid4(), email="s@test.com", full_name="Student", role=UserRole.STUDENT)
    with pytest.raises(NotFoundError, match="Invoice not found"):
        await service.record_payment(uuid4(), MagicMock(), student)

    inv = MagicMock()
    service.invoice_repo.get_by_id_for_update.return_value = inv
    other = User(id=uuid4(), email="o@test.com", full_name="Other", role="GUEST")
    with pytest.raises(ForbiddenError):
        await service.record_payment(uuid4(), MagicMock(), other)


@pytest.mark.asyncio
async def test_billing_service_student_balance_scoped_and_my_queries() -> None:
    session = AsyncMock()
    service = BillingService(session)
    service.student_repo = AsyncMock()

    student_user = User(id=uuid4(), email="s@test.com", full_name="Student", role=UserRole.STUDENT)

    # get_student_balance_scoped forbidden for student
    with pytest.raises(ForbiddenError):
        await service.get_student_balance_scoped(uuid4(), student_user)

    # get_student_balance_scoped student not found
    admin = User(id=uuid4(), email="a@test.com", full_name="Admin", role=UserRole.ADMIN)
    service.student_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="Student not found"):
        await service.get_student_balance_scoped(uuid4(), admin)

    # get_my_invoices profile not found
    service.student_repo.get_by_user_id.return_value = None
    with pytest.raises(NotFoundError, match="Student profile not found"):
        await service.get_my_invoices(student_user)

    # get_my_balance profile not found
    with pytest.raises(NotFoundError, match="Student profile not found"):
        await service.get_my_balance(student_user)


@pytest.mark.asyncio
async def test_billing_service_delete_and_void_invoice_branches() -> None:
    session = AsyncMock()
    service = BillingService(session)
    service.invoice_repo = AsyncMock()

    # delete_invoice not found
    service.invoice_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="Invoice not found"):
        await service.delete_invoice(uuid4())

    # delete_invoice success
    inv = MagicMock(payments=[], paid_amount=Decimal("0.00"))
    service.invoice_repo.get_by_id.return_value = inv
    await service.delete_invoice(uuid4())
    service.invoice_repo.delete.assert_awaited_with(inv)

    # void_invoice not found
    service.invoice_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="Invoice not found"):
        await service.void_invoice(uuid4())


@pytest.mark.asyncio
async def test_billing_service_list_payments_forbidden_and_success() -> None:
    session = AsyncMock()
    service = BillingService(session)
    service.payment_repo = AsyncMock()

    student = User(id=uuid4(), email="s@test.com", full_name="Student", role=UserRole.STUDENT)
    with pytest.raises(ForbiddenError):
        await service.list_payments(PaginationParams(page=1, size=10), student)

    admin = User(id=uuid4(), email="a@test.com", full_name="Admin", role=UserRole.ADMIN)
    p_obj = Payment(
        id=uuid4(),
        invoice_id=uuid4(),
        amount=Decimal("50.00"),
        method="cash",
        reference="REF1",
        paid_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    service.payment_repo.list.return_value = ([p_obj], 1)
    page = await service.list_payments(PaginationParams(page=1, size=10), admin)
    assert page.total == 1
    assert len(page.items) == 1


# =============================================================================
# 5. OperationsService Hardening Tests
# =============================================================================


def test_operations_service_visiting_hours_branches() -> None:
    session = AsyncMock()
    service = OperationsService(session)

    # 1. bypass = True
    service._check_visiting_hours(bypass=True)

    # 2. current_time as time object
    service._check_visiting_hours(current_time=time(12, 0))

    # 3. ValueError in strptime fallback
    with patch("app.services.operations_service.settings") as mock_settings:
        mock_settings.VISIT_START = "invalid"
        mock_settings.VISIT_END = "invalid"
        # 12:00 should fall within fallback 8:00 - 20:00
        service._check_visiting_hours(current_time=time(12, 0))

    # 4. overnight visiting hours (start_t > end_t)
    with patch("app.services.operations_service.settings") as mock_settings:
        mock_settings.VISIT_START = "20:00"
        mock_settings.VISIT_END = "06:00"
        # 22:00 is within overnight window
        service._check_visiting_hours(current_time=time(22, 0))


@pytest.mark.asyncio
async def test_operations_service_check_in_out_naive_and_no_alloc() -> None:
    session = AsyncMock()
    service = OperationsService(session)
    service.student_repo = AsyncMock()
    service.allocation_repo = AsyncMock()
    service.attendance_repo = AsyncMock()

    admin = User(id=uuid4(), email="a@test.com", full_name="Admin", role=UserRole.ADMIN)
    s_id = uuid4()
    prof = StudentProfile(id=s_id, user_id=uuid4(), student_no="S1", gender=GenderType.MALE)
    service.student_repo.get_by_id.return_value = prof

    alloc = MagicMock()
    alloc.bed.room.block.hostel_id = uuid4()
    service.allocation_repo.get_active_by_student_id.return_value = alloc
    service.attendance_repo.get_latest_for_student.return_value = None
    service.attendance_repo.create.return_value = AttendanceLog(
        id=uuid4(),
        student_id=s_id,
        type=AttendanceType.CHECK_IN,
        timestamp=datetime.now(UTC),
        recorded_by=admin.id,
    )
    service.attendance_repo.get_by_id.return_value = None

    # check_in with naive timestamp
    req_naive = AttendanceActionRequest(student_id=s_id, timestamp=datetime(2026, 1, 1, 10, 0))
    await service.check_in(req_naive, admin)

    # check_out with no active allocation
    service.allocation_repo.get_active_by_student_id.return_value = None
    with pytest.raises(BusinessRuleError, match="active hostel allocation"):
        await service.check_out(req_naive, admin)

    # check_out with naive timestamp
    service.allocation_repo.get_active_by_student_id.return_value = alloc
    latest_checkin = AttendanceLog(
        id=uuid4(),
        student_id=s_id,
        type=AttendanceType.CHECK_IN,
        timestamp=datetime.now(UTC),
        recorded_by=admin.id,
    )
    service.attendance_repo.get_latest_for_student.return_value = latest_checkin
    service.attendance_repo.create.return_value = AttendanceLog(
        id=uuid4(),
        student_id=s_id,
        type=AttendanceType.CHECK_OUT,
        timestamp=datetime.now(UTC),
        recorded_by=admin.id,
    )
    await service.check_out(req_naive, admin)


@pytest.mark.asyncio
async def test_operations_service_get_present_students_warden_specific() -> None:
    session = AsyncMock()
    service = OperationsService(session)
    service.warden_repo = AsyncMock()
    service.attendance_repo = AsyncMock()

    h_id = uuid4()
    warden = User(id=uuid4(), email="w@test.com", full_name="Warden", role=UserRole.WARDEN)
    service.warden_repo.list_hostel_ids_for_warden.return_value = [h_id]
    service.attendance_repo.get_present_students.return_value = []

    res = await service.get_present_students(warden, hostel_id=h_id)
    assert res == []


@pytest.mark.asyncio
async def test_operations_service_create_leave_branches() -> None:
    session = AsyncMock()
    service = OperationsService(session)
    service.student_repo = AsyncMock()
    service.allocation_repo = AsyncMock()

    student = User(id=uuid4(), email="s@test.com", full_name="Student", role=UserRole.STUDENT)

    # profile None -> NotFoundError
    service.student_repo.get_by_user_id.return_value = None
    with pytest.raises(NotFoundError, match="Student profile not found"):
        await service.create_leave_request(
            LeaveRequestCreate(from_date=date.today(), to_date=date.today(), reason="R"), student
        )

    # to_date < from_date -> BusinessRuleError
    prof = StudentProfile(id=uuid4(), user_id=student.id, student_no="S1", gender=GenderType.MALE)
    service.student_repo.get_by_user_id.return_value = prof
    alloc = MagicMock()
    service.allocation_repo.get_active_by_student_id.return_value = alloc
    with pytest.raises(BusinessRuleError, match="greater than or equal to from_date"):
        await service.create_leave_request(
            LeaveRequestCreate.model_construct(
                from_date=date(2026, 5, 10), to_date=date(2026, 5, 5), reason="R", student_id=None
            ),
            student,
            current_date=date(2026, 5, 1),
        )


@pytest.mark.asyncio
async def test_operations_service_approve_reject_cancel_leave_scoping() -> None:
    session = AsyncMock()
    service = OperationsService(session)
    service.leave_repo = AsyncMock()
    service.allocation_repo = AsyncMock()

    warden = User(id=uuid4(), email="w@test.com", full_name="Warden", role=UserRole.WARDEN)
    leave = LeaveRequest(
        id=uuid4(),
        student_id=uuid4(),
        from_date=date.today(),
        to_date=date.today(),
        reason="R",
        status=LeaveStatus.PENDING,
    )
    service.leave_repo.get_by_id.return_value = leave

    # Warden approving/rejecting leave for student without allocation -> ForbiddenError
    service.allocation_repo.get_active_by_student_id.return_value = None
    with pytest.raises(ForbiddenError, match="Cannot review leave for unallocated student"):
        await service.approve_leave_request(leave.id, warden)

    with pytest.raises(ForbiddenError, match="Cannot review leave for unallocated student"):
        await service.reject_leave_request(leave.id, warden)

    # Warden canceling leave -> ForbiddenError (only student self or admin)
    with pytest.raises(ForbiddenError, match="Only student self or admin can cancel"):
        await service.cancel_leave_request(leave.id, warden)


@pytest.mark.asyncio
async def test_operations_service_my_leaves_and_visitor_branches() -> None:
    session = AsyncMock()
    service = OperationsService(session)
    service.student_repo = AsyncMock()
    service.leave_repo = AsyncMock()
    service.visitor_repo = AsyncMock()
    service.allocation_repo = AsyncMock()

    student = User(id=uuid4(), email="s@test.com", full_name="Student", role=UserRole.STUDENT)
    prof = StudentProfile(id=uuid4(), user_id=student.id, student_no="S1", gender=GenderType.MALE)
    service.student_repo.get_by_user_id.return_value = prof
    service.leave_repo.list.return_value = ([], 0)

    # get_my_leaves
    _res, total = await service.get_my_leaves(student, PaginationParams(page=1, size=10))
    assert total == 0

    # check_in_visitor naive in_time
    admin = User(id=uuid4(), email="a@test.com", full_name="Admin", role=UserRole.ADMIN)
    service.student_repo.get_by_id.return_value = prof
    alloc = MagicMock()
    alloc.bed.room.block.hostel_id = uuid4()
    service.allocation_repo.get_active_by_student_id.return_value = alloc
    service.visitor_repo.get_active_by_student_and_visitor.return_value = None
    vis = Visitor(
        id=uuid4(),
        student_id=prof.id,
        name="V",
        phone="123",
        relation="P",
        check_in_at=datetime.now(UTC),
    )
    service.visitor_repo.create.return_value = vis
    service.visitor_repo.get_by_id.return_value = vis

    v_create = VisitorCreate(student_id=prof.id, name="V", phone="123", relation="P")
    await service.check_in_visitor(
        v_create, admin, check_in_time=datetime(2026, 1, 1, 10, 0), bypass_visiting_hours=True
    )

    # check_out_visitor warden unallocated student -> ForbiddenError
    warden = User(id=uuid4(), email="w@test.com", full_name="Warden", role=UserRole.WARDEN)
    vis_active = Visitor(
        id=uuid4(),
        student_id=prof.id,
        name="V",
        phone="123",
        relation="P",
        check_in_at=datetime.now(UTC),
        check_out_at=None,
    )
    service.visitor_repo.get_by_id.return_value = vis_active
    service.allocation_repo.get_active_by_student_id.return_value = None
    with pytest.raises(ForbiddenError, match="Cannot manage visitor for unallocated student"):
        await service.check_out_visitor(vis_active.id, warden)

    # check_out_visitor naive check_out_time
    service.visitor_repo.update.return_value = vis_active
    await service.check_out_visitor(
        vis_active.id, admin, check_out_time=datetime(2026, 1, 1, 11, 0)
    )

    # get_visitor_by_id warden with active allocation
    service.allocation_repo.get_active_by_student_id.return_value = alloc
    with patch("app.services.operations_service.ensure_hostel_access") as mock_ensure:
        await service.get_visitor_by_id(vis_active.id, warden)
        mock_ensure.assert_awaited()

    # get_my_visitors
    service.visitor_repo.list.return_value = ([], 0)
    _v_res, v_tot = await service.get_my_visitors(student, PaginationParams(page=1, size=10))
    assert v_tot == 0


# =============================================================================
# 6. AllocationService Hardening Tests
# =============================================================================


@pytest.mark.asyncio
async def test_allocation_service_allocate_validation_branches() -> None:
    session = AsyncMock()
    service = AllocationService(session)
    service.room_repo = AsyncMock()
    service.bed_repo = AsyncMock()
    service.allocation_repo = AsyncMock()
    service.block_repo = AsyncMock()
    service.hostel_repo = AsyncMock()
    service.student_repo = AsyncMock()

    admin = User(id=uuid4(), email="a@test.com", full_name="Admin", role=UserRole.ADMIN)
    u_mock = User(
        id=uuid4(), email="s@test.com", full_name="Student", role=UserRole.STUDENT, is_active=True
    )
    student = StudentProfile(
        id=uuid4(), user_id=u_mock.id, student_no="S1", gender=GenderType.MALE, user=u_mock
    )
    service.student_repo.get_by_id.return_value = student
    service.allocation_repo.get_active_by_student_id.return_value = None

    # 1. room_id provided, room_check is None -> NotFoundError
    data_room_only = MagicMock(room_id=uuid4(), bed_id=None, start_date=date.today())
    service.room_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="Room not found"):
        await service.allocate(data_room_only, admin)

    # 2. room_id provided, free_bed found but get_by_id_for_update is None -> NotFoundError
    service.room_repo.get_by_id.return_value = MagicMock()
    free_bed = MagicMock(id=uuid4(), is_occupied=False)
    service.bed_repo.list_by_room.return_value = [free_bed]
    service.bed_repo.get_by_id_for_update.return_value = None
    with pytest.raises(NotFoundError, match="Bed not found"):
        await service.allocate(data_room_only, admin)

    # 3. neither bed_id nor room_id -> BusinessRuleError
    data_none = MagicMock(room_id=None, bed_id=None, start_date=date.today())
    with pytest.raises(BusinessRuleError, match="Either bed_id or room_id must be provided"):
        await service.allocate(data_none, admin)

    # 4. active_bed_alloc is not None -> BusinessRuleError
    data_bed = MagicMock(room_id=None, bed_id=uuid4(), start_date=date.today())
    bed = Bed(id=data_bed.bed_id, room_id=uuid4(), label="B1", is_occupied=False)
    service.bed_repo.get_by_id_for_update.return_value = bed
    service.allocation_repo.get_active_by_bed_id.return_value = MagicMock()
    with pytest.raises(BusinessRuleError, match="Bed is already occupied"):
        await service.allocate(data_bed, admin)

    # 5. room is None / is_deleted -> NotFoundError
    service.allocation_repo.get_active_by_bed_id.return_value = None
    service.room_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="Room not found"):
        await service.allocate(data_bed, admin)

    # 6. block is None -> NotFoundError
    room = Room(
        id=bed.room_id,
        block_id=uuid4(),
        number="101",
        floor=1,
        room_type=RoomType.SINGLE,
        capacity=1,
        status=RoomStatus.AVAILABLE,
    )
    service.room_repo.get_by_id.return_value = room
    service.block_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="Block not found"):
        await service.allocate(data_bed, admin)

    # 7. hostel is None / is_deleted -> NotFoundError
    block = Block(id=room.block_id, hostel_id=uuid4(), name="Block A")
    service.block_repo.get_by_id.return_value = block
    service.hostel_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="Hostel not found"):
        await service.allocate(data_bed, admin)


@pytest.mark.asyncio
async def test_allocation_service_vacate_and_cancel_errors() -> None:
    session = AsyncMock()
    service = AllocationService(session)
    service.allocation_repo = AsyncMock()

    student = User(id=uuid4(), email="s@test.com", full_name="Student", role=UserRole.STUDENT)
    admin = User(id=uuid4(), email="a@test.com", full_name="Admin", role=UserRole.ADMIN)

    # vacate forbidden for student
    with pytest.raises(ForbiddenError):
        await service.vacate(uuid4(), AllocationVacateRequest(), student)

    # vacate not found
    service.allocation_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="Allocation not found"):
        await service.vacate(uuid4(), AllocationVacateRequest(), admin)

    # cancel forbidden for student
    with pytest.raises(ForbiddenError):
        await service.cancel(uuid4(), student)

    # cancel not found
    with pytest.raises(NotFoundError, match="Allocation not found"):
        await service.cancel(uuid4(), admin)


@pytest.mark.asyncio
async def test_allocation_service_transfer_errors() -> None:
    session = _mock_session_with_nested()
    service = AllocationService(session)
    service.allocation_repo = AsyncMock()
    service.student_repo = AsyncMock()
    service.bed_repo = AsyncMock()
    service.room_repo = AsyncMock()
    service.block_repo = AsyncMock()
    service.hostel_repo = AsyncMock()

    student = User(id=uuid4(), email="s@test.com", full_name="Student", role=UserRole.STUDENT)
    admin = User(id=uuid4(), email="a@test.com", full_name="Admin", role=UserRole.ADMIN)

    # transfer forbidden for student
    with pytest.raises(ForbiddenError):
        await service.transfer(uuid4(), AllocationTransferRequest(new_bed_id=uuid4()), student)

    # transfer allocation not found
    service.allocation_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="Allocation not found"):
        await service.transfer(uuid4(), AllocationTransferRequest(new_bed_id=uuid4()), admin)

    # allocation status not active
    alloc = MagicMock()
    alloc.status = AllocationStatus.ENDED
    service.allocation_repo.get_by_id.return_value = alloc
    with pytest.raises(BusinessRuleError, match="Only active allocations can be transferred"):
        await service.transfer(uuid4(), AllocationTransferRequest(new_bed_id=uuid4()), admin)

    def _reset_alloc() -> None:
        alloc.status = AllocationStatus.ACTIVE
        alloc.bed.room.block.hostel_id = uuid4()
        alloc.bed.id = uuid4()

    # new_bed not found
    _reset_alloc()
    service.bed_repo.get_by_id_for_update.return_value = None
    with pytest.raises(NotFoundError, match="New bed not found"):
        await service.transfer(uuid4(), AllocationTransferRequest(new_bed_id=uuid4()), admin)

    # new_bed does not belong to specified new room
    _reset_alloc()
    new_bed = Bed(id=uuid4(), room_id=uuid4(), label="B2", is_occupied=False)
    service.bed_repo.get_by_id_for_update.return_value = new_bed
    with pytest.raises(BusinessRuleError, match="New bed does not belong to specified new room"):
        await service.transfer(
            uuid4(), AllocationTransferRequest(new_bed_id=new_bed.id, new_room_id=uuid4()), admin
        )

    # transfer using room_id: new room not found
    _reset_alloc()
    service.room_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="New room not found"):
        await service.transfer(uuid4(), AllocationTransferRequest(new_room_id=uuid4()), admin)

    # transfer using room_id: free_bed found but get_by_id_for_update is None
    _reset_alloc()
    service.room_repo.get_by_id.return_value = MagicMock()
    free_bed = MagicMock(id=uuid4(), is_occupied=False)
    service.bed_repo.list_by_room.return_value = [free_bed]
    service.bed_repo.get_by_id_for_update.return_value = None
    with pytest.raises(NotFoundError, match="New bed not found"):
        await service.transfer(uuid4(), AllocationTransferRequest(new_room_id=uuid4()), admin)

    # transfer: neither new_bed_id nor new_room_id provided
    _reset_alloc()
    with pytest.raises(
        BusinessRuleError, match="Either new_bed_id or new_room_id must be provided"
    ):
        await service.transfer(uuid4(), AllocationTransferRequest.model_construct(), admin)

    # transfer: new_bed is occupied
    _reset_alloc()
    new_bed.is_occupied = True
    service.bed_repo.get_by_id_for_update.return_value = new_bed
    with pytest.raises(BusinessRuleError, match="New bed is already occupied"):
        await service.transfer(uuid4(), AllocationTransferRequest(new_bed_id=new_bed.id), admin)

    # transfer: active_bed_alloc is not None
    _reset_alloc()
    new_bed.is_occupied = False
    service.allocation_repo.get_active_by_bed_id.return_value = MagicMock()
    with pytest.raises(BusinessRuleError, match="New bed is already occupied"):
        await service.transfer(uuid4(), AllocationTransferRequest(new_bed_id=new_bed.id), admin)

    # transfer: new_room is None or is_deleted
    _reset_alloc()
    service.allocation_repo.get_active_by_bed_id.return_value = None
    service.room_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="New room not found"):
        await service.transfer(uuid4(), AllocationTransferRequest(new_bed_id=new_bed.id), admin)

    # transfer: new_block is None
    _reset_alloc()
    new_room = Room(
        id=new_bed.room_id,
        block_id=uuid4(),
        number="102",
        floor=1,
        room_type=RoomType.SINGLE,
        capacity=1,
        status=RoomStatus.AVAILABLE,
    )
    service.room_repo.get_by_id.return_value = new_room
    service.block_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="Block not found"):
        await service.transfer(uuid4(), AllocationTransferRequest(new_bed_id=new_bed.id), admin)

    # transfer: new_hostel is None
    _reset_alloc()
    new_block = Block(id=new_room.block_id, hostel_id=uuid4(), name="Block B")
    service.block_repo.get_by_id.return_value = new_block
    service.hostel_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="Hostel not found"):
        await service.transfer(uuid4(), AllocationTransferRequest(new_bed_id=new_bed.id), admin)

    # transfer: IntegrityError caught and converted to ConflictError
    _reset_alloc()
    new_hostel = Hostel(id=new_block.hostel_id, name="HB", code="HB", gender_type=GenderType.MIXED)
    service.hostel_repo.get_by_id.return_value = new_hostel
    student_obj = StudentProfile(
        id=alloc.student_id, user_id=uuid4(), student_no="S1", gender=GenderType.MALE
    )
    service.student_repo.get_by_id.return_value = student_obj
    service.allocation_repo.create.side_effect = IntegrityError(
        "statement", "params", Exception("unique")
    )

    with pytest.raises(ConflictError, match="Allocation conflict detected"):
        await service.transfer(uuid4(), AllocationTransferRequest(new_bed_id=new_bed.id), admin)


@pytest.mark.asyncio
async def test_allocation_service_scoping_and_occupants_queries() -> None:
    session = AsyncMock()
    service = AllocationService(session)
    service.student_repo = AsyncMock()
    service.warden_repo = AsyncMock()
    service.allocation_repo = AsyncMock()
    service.room_repo = AsyncMock()
    service.block_repo = AsyncMock()

    other = User(id=uuid4(), email="o@test.com", full_name="Other", role="OTHER")
    student = User(id=uuid4(), email="s@test.com", full_name="Student", role=UserRole.STUDENT)
    warden = User(id=uuid4(), email="w@test.com", full_name="Warden", role=UserRole.WARDEN)

    # get_allocation unknown role -> ForbiddenError
    alloc = MagicMock()
    with pytest.raises(ForbiddenError):
        await service.get_allocation(alloc, other)

    # get_student_active_allocation student not found
    service.student_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="Student not found"):
        await service.get_student_active_allocation(uuid4(), warden)

    # get_student_active_allocation warden outside assigned hostels -> ForbiddenError
    s_obj = StudentProfile(id=uuid4(), user_id=uuid4(), student_no="S1", gender=GenderType.MALE)
    service.student_repo.get_by_id.return_value = s_obj
    h_assigned = uuid4()
    h_unassigned = uuid4()
    service.warden_repo.list_hostel_ids_for_warden.return_value = [h_assigned]

    active_alloc = MagicMock()
    active_alloc.bed.room.block.hostel_id = h_unassigned
    service.allocation_repo.get_active_by_student_id.return_value = active_alloc
    with pytest.raises(ForbiddenError, match="outside your assigned hostels"):
        await service.get_student_active_allocation(s_obj.id, warden)

    # get_student_active_allocation warden inside assigned hostels -> returns active_alloc
    active_alloc.bed.room.block.hostel_id = h_assigned
    res_alloc = await service.get_student_active_allocation(s_obj.id, warden)
    assert res_alloc == active_alloc

    # get_student_active_allocation unknown role -> ForbiddenError
    with pytest.raises(ForbiddenError):
        await service.get_student_active_allocation(s_obj.id, other)

    # get_my_active_allocation profile None -> NotFoundError
    service.student_repo.get_by_user_id.return_value = None
    with pytest.raises(NotFoundError, match="Student profile not found"):
        await service.get_my_active_allocation(student)

    # get_room_occupants student role -> ForbiddenError
    with pytest.raises(ForbiddenError):
        await service.get_room_occupants(uuid4(), student)

    # get_room_occupants room None -> NotFoundError
    admin = User(id=uuid4(), email="a@test.com", full_name="Admin", role=UserRole.ADMIN)
    service.room_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="Room not found"):
        await service.get_room_occupants(uuid4(), admin)

    # get_room_occupants block None -> NotFoundError
    r_mock = MagicMock(block_id=uuid4())
    service.room_repo.get_by_id.return_value = r_mock
    service.block_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="Block not found"):
        await service.get_room_occupants(uuid4(), admin)

    # list_allocations student role -> ForbiddenError
    with pytest.raises(ForbiddenError):
        await service.list_allocations(PaginationParams(page=1, size=10), student)

    # list_allocations warden with unassigned hostel -> ForbiddenError
    with pytest.raises(ForbiddenError, match="You are not assigned to this hostel"):
        await service.list_allocations(
            PaginationParams(page=1, size=10), warden, hostel_id=h_unassigned
        )


# =============================================================================
# 7. ComplaintService & ReportService Hardening Tests
# =============================================================================


@pytest.mark.asyncio
async def test_complaint_service_and_report_service_hardening() -> None:
    session = AsyncMock()
    comp_service = ComplaintService(session)
    comp_service.student_repo = AsyncMock()
    comp_service.complaint_repo = AsyncMock()
    comp_service.user_repo = AsyncMock()
    comp_service.comment_repo = AsyncMock()

    student = User(id=uuid4(), email="s@test.com", full_name="Student", role=UserRole.STUDENT)
    admin = User(id=uuid4(), email="a@test.com", full_name="Admin", role=UserRole.ADMIN)

    # list_complaints: student without profile -> [], 0
    comp_service.student_repo.get_by_user_id.return_value = None
    items, total = await comp_service.list_complaints(PaginationParams(page=1, size=10), student)
    assert items == []
    assert total == 0

    # assign_complaint: complaint None -> NotFoundError
    comp_service.complaint_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="Complaint not found"):
        await comp_service.assign_complaint(
            uuid4(), ComplaintAssignRequest(assigned_to=uuid4()), admin
        )

    # update_status: complaint None -> NotFoundError
    with pytest.raises(NotFoundError, match="Complaint not found"):
        await comp_service.update_status(
            uuid4(), ComplaintStatusUpdateRequest(status=ComplaintStatus.CLOSED), admin
        )

    # update_status: student not owning complaint -> ForbiddenError
    comp_service.complaint_repo.get_by_id.return_value = MagicMock(student_id=uuid4())
    comp_service.student_repo.get_by_user_id.return_value = StudentProfile(
        id=uuid4(), user_id=student.id, student_no="S1", gender=GenderType.MALE
    )
    with pytest.raises(ForbiddenError):
        await comp_service.update_status(
            uuid4(), ComplaintStatusUpdateRequest(status=ComplaintStatus.CLOSED), student
        )

    # add_comment: complaint None -> NotFoundError
    comp_service.complaint_repo.get_by_id.return_value = None
    with pytest.raises(NotFoundError, match="Complaint not found"):
        await comp_service.add_comment(uuid4(), ComplaintCommentCreate(body="Hello"), admin)

    # add_comment: student not owning complaint -> ForbiddenError
    comp_service.complaint_repo.get_by_id.return_value = MagicMock(student_id=uuid4())
    with pytest.raises(ForbiddenError):
        await comp_service.add_comment(uuid4(), ComplaintCommentCreate(body="Hello"), student)

    # add_comment: admin role sets is_internal
    c_obj = MagicMock(id=uuid4(), student_id=uuid4())
    comp_service.complaint_repo.get_by_id.return_value = c_obj
    comp_service.comment_repo.create.return_value = MagicMock(author=None)
    await comp_service.add_comment(
        uuid4(), ComplaintCommentCreate(body="Internal note", is_internal=True), admin
    )
    created_comment = comp_service.comment_repo.create.call_args[0][0]
    assert created_comment.is_internal is True

    # ReportService: get_student_dashboard with no profile
    report_service = ReportService(session)
    report_service.student_repo = AsyncMock()
    report_service.student_repo.get_by_user_id.return_value = None
    dash = await report_service.get_student_dashboard(student)
    assert dash.balance == Decimal("0.00")
    assert dash.open_complaints_count == 0


def test_coverage_edge_cases():
    """Verify edge case schema methods and utility functions for coverage completeness."""
    from starlette.requests import Request

    from app.core.csrf import verify_csrf
    from app.core.exceptions import RateLimitExceededError
    from app.schemas.hostel import BlockBase, BlockUpdate, HostelBase, HostelUpdate
    from app.schemas.notice import NoticeRead
    from app.schemas.report import DashboardSummaryRead
    from app.schemas.student import StudentCreate
    from app.services.audit_service import AuditService

    # 1. Audit payload sanitizer UUID and datetime
    u = uuid4()
    now = datetime.now(UTC)
    assert AuditService.sanitize_payload(u) == str(u)
    assert AuditService.sanitize_payload(now) == now.isoformat()

    # 2. Rate limit exception
    err = RateLimitExceededError()
    assert err.status_code == 429

    # 3. CSRF GET bypass
    req = Request({"type": "http", "method": "GET", "path": "/"})
    verify_csrf(req)

    # 4. Student password strength branches
    with pytest.raises(ValueError, match="at least one letter"):
        StudentCreate.check_password_policy("12345678")
    with pytest.raises(ValueError, match="at least one number"):
        StudentCreate.check_password_policy("abcdefgh")

    # 5. Hostel whitespace strip non-string fallback
    assert HostelBase.strip_whitespace(123) == 123
    assert HostelUpdate.strip_whitespace(123) == 123
    assert BlockBase.strip_whitespace(456) == 456
    assert BlockUpdate.strip_whitespace(456) == 456

    # 6. NoticeRead dict before validator
    nid = uuid4()
    nr = NoticeRead.model_validate(
        {
            "id": nid,
            "title": "Test",
            "body": "Notice body",
            "audience": "all",
            "is_pinned": False,
            "created_at": now,
            "published_at": now,
            "updated_at": now,
            "author_id": uuid4(),
        }
    )
    assert nr.id == nid

    # 7. DashboardSummaryRead open_complaints_count property
    dash = DashboardSummaryRead(
        total_hostels=2,
        total_rooms=10,
        total_beds=50,
        active_students=45,
        total_capacity=100,
        occupied_beds=50,
        available_beds=50,
        occupancy_rate=50.0,
        pending_leaves=0,
        open_complaints=5,
        active_notices=2,
        present_now=40,
        invoices_due_this_month=Decimal("0.00"),
        collected_this_month=Decimal("0.00"),
        outstanding_total=Decimal("0.00"),
    )
    assert dash.open_complaints_count == 5
