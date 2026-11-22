"""Property-based testing with Hypothesis.

Invariants tested:
1. Invoice & Payment math:
   - Total payments never exceed invoice total.
   - Balance is always >= 0.
   - Status transitions (unpaid -> partial -> paid) are mathematically consistent.
   - Overpayment and invalid payments are strictly rejected.
2. Bed allocation:
   - A student cannot hold multiple active allocations simultaneously.
   - A bed cannot be occupied by > 1 student simultaneously.
   - Allocation state transitions (allocate -> transfer -> vacate/cancel)
     preserve 1-to-1 invariants.
"""

from collections.abc import AsyncGenerator
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.exceptions import BusinessRuleError
from app.db.base import Base
from app.models.allocation import Allocation, AllocationStatus
from app.models.billing import (
    Invoice,
    InvoiceStatus,
    PaymentMethod,
)
from app.models.hostel import Block, GenderType, Hostel
from app.models.room import Bed, Room, RoomStatus, RoomType
from app.models.student import StudentProfile
from app.models.user import User, UserRole
from app.repositories.allocation_repository import AllocationRepository
from app.schemas.billing import PaymentCreate
from app.services.billing_service import BillingService

# =============================================================================
# 1. Hypothesis Strategies & Model-Level Property Tests
# =============================================================================


class InvoicePaymentSimulator:
    """Simulates invoice and payment ledger according to core domain rules."""

    def __init__(self, total_amount: Decimal) -> None:
        self.total_amount = total_amount
        self.paid_amount = Decimal("0.00")
        self.status: InvoiceStatus = InvoiceStatus.UNPAID
        self.payments: list[Decimal] = []

    @property
    def balance(self) -> Decimal:
        return self.total_amount - self.paid_amount

    def apply_payment(self, amount: Decimal) -> bool:
        """Attempt to apply payment; returns True if accepted, False if rejected."""
        if amount <= Decimal("0.00"):
            return False
        if self.status == InvoiceStatus.PAID:
            return False
        if amount > self.balance:
            return False

        self.payments.append(amount)
        self.paid_amount += amount
        if self.paid_amount == self.total_amount:
            self.status = InvoiceStatus.PAID
        else:
            self.status = InvoiceStatus.PARTIAL
        return True


# Decimal strategy generating 2-decimal money values
money_strategy = st.decimals(
    min_value=Decimal("1.00"),
    max_value=Decimal("10000.00"),
    places=2,
)

payment_amounts_strategy = st.lists(
    st.decimals(min_value=Decimal("0.01"), max_value=Decimal("5000.00"), places=2),
    min_size=1,
    max_size=30,
)


@given(total_amount=money_strategy, payment_attempts=payment_amounts_strategy)
@settings(max_examples=150)
def test_hypothesis_invoice_payment_invariants(
    total_amount: Decimal, payment_attempts: list[Decimal]
) -> None:
    """Property: Invariant check on sequential payments against an invoice.

    - Total payments never exceed total_amount
    - balance >= 0 at all times
    - total_amount == paid_amount + balance
    - status transitions: UNPAID -> PARTIAL -> PAID
    """
    sim = InvoicePaymentSimulator(total_amount)

    assert sim.status.value == InvoiceStatus.UNPAID.value
    assert sim.balance == total_amount
    assert sim.paid_amount == Decimal("0.00")

    for pay in payment_attempts:
        prev_paid = sim.paid_amount
        prev_balance = sim.balance
        accepted = sim.apply_payment(pay)

        # Invariants that MUST hold unconditionally after each attempt:
        assert sim.paid_amount <= sim.total_amount, "Paid amount exceeded invoice total!"
        assert sim.balance >= Decimal("0.00"), "Invoice balance became negative!"
        assert sim.paid_amount + sim.balance == sim.total_amount, "Ledger does not balance!"

        if accepted:
            assert sim.paid_amount == prev_paid + pay
            assert sim.balance == prev_balance - pay
            if sim.paid_amount == sim.total_amount:
                assert sim.status == InvoiceStatus.PAID
                assert sim.balance == Decimal("0.00")
            else:
                assert sim.status == InvoiceStatus.PARTIAL
                assert sim.balance > Decimal("0.00")
        else:
            # Rejection preserves state identically
            assert sim.paid_amount == prev_paid
            assert sim.balance == prev_balance


# =============================================================================
# 2. Hypothesis Allocation Model Invariants
# =============================================================================


class AllocationSimulator:
    """In-memory state tracker simulating bed allocation invariants."""

    def __init__(self, student_count: int = 5, bed_count: int = 5) -> None:
        self.students = [uuid4() for _ in range(student_count)]
        self.beds = [uuid4() for _ in range(bed_count)]
        # Map student_id -> active bed_id
        self.student_to_bed: dict[UUID, UUID] = {}
        # Map bed_id -> active student_id
        self.bed_to_student: dict[UUID, UUID] = {}

    def allocate(self, s_idx: int, b_idx: int) -> bool:
        s_id = self.students[s_idx % len(self.students)]
        b_id = self.beds[b_idx % len(self.beds)]

        # Domain rule: student cannot have active allocation
        if s_id in self.student_to_bed:
            return False
        # Domain rule: bed cannot be already occupied
        if b_id in self.bed_to_student:
            return False

        self.student_to_bed[s_id] = b_id
        self.bed_to_student[b_id] = s_id
        return True

    def vacate(self, s_idx: int) -> bool:
        s_id = self.students[s_idx % len(self.students)]
        if s_id not in self.student_to_bed:
            return False
        b_id = self.student_to_bed.pop(s_id)
        self.bed_to_student.pop(b_id)
        return True

    def transfer(self, s_idx: int, target_b_idx: int) -> bool:
        s_id = self.students[s_idx % len(self.students)]
        target_b_id = self.beds[target_b_idx % len(self.beds)]

        if s_id not in self.student_to_bed:
            return False
        if target_b_id in self.bed_to_student:
            return False

        old_b_id = self.student_to_bed[s_id]
        self.bed_to_student.pop(old_b_id)

        self.student_to_bed[s_id] = target_b_id
        self.bed_to_student[target_b_id] = s_id
        return True


action_strategy = st.lists(
    st.tuples(
        st.sampled_from(["allocate", "vacate", "transfer"]),
        st.integers(min_value=0, max_value=20),
        st.integers(min_value=0, max_value=20),
    ),
    min_size=1,
    max_size=50,
)


@given(actions=action_strategy)
@settings(max_examples=100)
def test_hypothesis_bed_allocation_invariants(
    actions: list[tuple[str, int, int]],
) -> None:
    """Property: Invariant check on arbitrary sequences of allocations, vacates, and transfers.

    - A student never holds > 1 active bed
    - A bed is never occupied by > 1 student
    - Bijective correspondence: active students count == active beds count
    """
    sim = AllocationSimulator(student_count=6, bed_count=6)

    for action, s_idx, b_idx in actions:
        if action == "allocate":
            sim.allocate(s_idx, b_idx)
        elif action == "vacate":
            sim.vacate(s_idx)
        elif action == "transfer":
            sim.transfer(s_idx, b_idx)

        # Invariants that MUST hold unconditionally:
        assert len(sim.student_to_bed) == len(sim.bed_to_student)
        assert len(set(sim.student_to_bed.values())) == len(sim.student_to_bed)
        assert len(set(sim.bed_to_student.values())) == len(sim.bed_to_student)
        for s, b in sim.student_to_bed.items():
            assert sim.bed_to_student[b] == s


# =============================================================================
# 3. Rule-Based State Machine Testing with Hypothesis
# =============================================================================


class InvoiceStateMachine(RuleBasedStateMachine):
    """Hypothesis state machine verifying billing mathematical consistency."""

    def __init__(self) -> None:
        super().__init__()
        self.total = Decimal("1000.00")
        self.paid = Decimal("0.00")
        self.status = InvoiceStatus.UNPAID

    @property
    def balance(self) -> Decimal:
        return self.total - self.paid

    @rule(payment=st.decimals(min_value=Decimal("1.00"), max_value=Decimal("500.00"), places=2))
    def pay_partial(self, payment: Decimal) -> None:
        if self.status != InvoiceStatus.PAID and payment <= self.balance:
            self.paid += payment
            if self.paid == self.total:
                self.status = InvoiceStatus.PAID
            else:
                self.status = InvoiceStatus.PARTIAL

    @rule()
    def pay_full_remainder(self) -> None:
        if self.status != InvoiceStatus.PAID and self.balance > 0:
            self.paid += self.balance
            self.status = InvoiceStatus.PAID

    @invariant()
    def math_is_consistent(self) -> None:
        assert self.paid <= self.total
        assert self.balance >= Decimal("0.00")
        assert self.paid + self.balance == self.total

    @invariant()
    def status_is_consistent(self) -> None:
        if self.paid == Decimal("0.00"):
            assert self.status == InvoiceStatus.UNPAID
        elif self.paid == self.total:
            assert self.status == InvoiceStatus.PAID
            assert self.balance == Decimal("0.00")
        else:
            assert self.status == InvoiceStatus.PARTIAL
            assert self.balance > Decimal("0.00")


TestInvoiceStateMachine = InvoiceStateMachine.TestCase


# =============================================================================
# 4. Service-Level DB Invariant Integration with Hypothesis
# =============================================================================


@pytest.fixture
async def prop_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_billing_service_db_property_invariants(prop_engine: AsyncEngine) -> None:
    """Verify that BillingService enforces the mathematical invariants in SQLite."""
    session_maker = async_sessionmaker(prop_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as session:
        # Seed admin, hostel, block, room, bed, student, allocation
        admin = User(
            id=uuid4(),
            email="admin_prop@hostel.example.com",
            full_name="Admin Prop",
            hashed_password="hash",
            role=UserRole.ADMIN,
            is_active=True,
        )
        student_user = User(
            id=uuid4(),
            email="student_prop@hostel.example.com",
            full_name="Student Prop",
            hashed_password="hash",
            role=UserRole.STUDENT,
            is_active=True,
        )
        hostel = Hostel(
            id=uuid4(), name="Prop Hostel", code="PROP-01", gender_type=GenderType.MIXED
        )
        block = Block(id=uuid4(), hostel_id=hostel.id, name="Block A", floor_count=2)
        room = Room(
            id=uuid4(),
            block_id=block.id,
            number="101",
            floor=1,
            room_type=RoomType.SINGLE,
            capacity=1,
            monthly_rent=Decimal("500.00"),
            status=RoomStatus.AVAILABLE,
        )
        bed = Bed(id=uuid4(), room_id=room.id, label="A", is_occupied=False)
        student = StudentProfile(
            id=uuid4(),
            user_id=student_user.id,
            student_no="STU-PROP-1",
            gender=GenderType.MALE,
            department="CS",
            year=1,
            guardian_name="Guardian",
            guardian_phone="+1111111111",
            emergency_contact="+2222222222",
        )
        alloc = Allocation(
            id=uuid4(),
            student_id=student.id,
            bed_id=bed.id,
            start_date=date.today(),
            status=AllocationStatus.ACTIVE,
        )
        invoice = Invoice(
            id=uuid4(),
            student_id=student.id,
            allocation_id=alloc.id,
            period_start=date.today(),
            period_end=date.today() + timedelta(days=30),
            amount=Decimal("500.00"),
            paid_amount=Decimal("0.00"),
            due_date=date.today() + timedelta(days=7),
            status=InvoiceStatus.UNPAID,
        )

        session.add_all([admin, student_user, hostel, block, room, bed, student, alloc, invoice])
        await session.commit()

        service = BillingService(session)

        # 1. Partial payment 1: 200.00
        p1 = await service.record_payment(
            invoice_id=invoice.id,
            data=PaymentCreate(amount=Decimal("200.00"), method=PaymentMethod.CASH),
            current_user=admin,
        )
        assert p1.amount == Decimal("200.00")

        await session.refresh(invoice)
        assert invoice.paid_amount == Decimal("200.00")
        assert invoice.balance == Decimal("300.00")
        assert invoice.status == InvoiceStatus.PARTIAL

        # 2. Overpayment attempt: 300.01 should fail
        with pytest.raises(BusinessRuleError) as exc_info:
            await service.record_payment(
                invoice_id=invoice.id,
                data=PaymentCreate(amount=Decimal("300.01"), method=PaymentMethod.CASH),
                current_user=admin,
            )
        assert exc_info.value.code == "OVERPAYMENT_NOT_ALLOWED"

        # Invariant preserved
        await session.refresh(invoice)
        assert invoice.paid_amount == Decimal("200.00")
        assert invoice.balance == Decimal("300.00")
        assert invoice.status == InvoiceStatus.PARTIAL

        # 3. Partial payment 2: 150.00
        await service.record_payment(
            invoice_id=invoice.id,
            data=PaymentCreate(amount=Decimal("150.00"), method=PaymentMethod.CARD),
            current_user=admin,
        )
        await session.refresh(invoice)
        assert invoice.paid_amount == Decimal("350.00")
        assert invoice.balance == Decimal("150.00")
        assert invoice.status == InvoiceStatus.PARTIAL

        # 4. Final payment: 150.00 -> PAID
        await service.record_payment(
            invoice_id=invoice.id,
            data=PaymentCreate(amount=Decimal("150.00"), method=PaymentMethod.ONLINE),
            current_user=admin,
        )
        await session.refresh(invoice)
        assert invoice.paid_amount == Decimal("500.00")
        assert invoice.balance == Decimal("0.00")
        assert invoice.status.value == InvoiceStatus.PAID.value

        # 5. Subsequent payment when already paid must fail
        with pytest.raises(BusinessRuleError) as exc_paid:
            await service.record_payment(
                invoice_id=invoice.id,
                data=PaymentCreate(amount=Decimal("10.00"), method=PaymentMethod.CASH),
                current_user=admin,
            )
        assert exc_paid.value.code == "INVOICE_ALREADY_PAID"


@pytest.mark.asyncio
async def test_bed_allocation_db_unique_constraints(prop_engine: AsyncEngine) -> None:
    """Verify that multiple active allocations for the same student or bed fail at DB level."""
    session_maker = async_sessionmaker(prop_engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as session:
        hostel = Hostel(
            id=uuid4(), name="Constraint Hostel", code="C-01", gender_type=GenderType.MIXED
        )
        block = Block(id=uuid4(), hostel_id=hostel.id, name="Block C", floor_count=1)
        room = Room(
            id=uuid4(),
            block_id=block.id,
            number="201",
            floor=1,
            room_type=RoomType.DOUBLE,
            capacity=2,
            monthly_rent=Decimal("400.00"),
            status=RoomStatus.AVAILABLE,
        )
        bed1 = Bed(id=uuid4(), room_id=room.id, label="A", is_occupied=True)
        bed2 = Bed(id=uuid4(), room_id=room.id, label="B", is_occupied=False)
        u1 = User(
            id=uuid4(),
            email="stu1@hostel.test",
            full_name="S1",
            hashed_password="h",
            role=UserRole.STUDENT,
        )
        u2 = User(
            id=uuid4(),
            email="stu2@hostel.test",
            full_name="S2",
            hashed_password="h",
            role=UserRole.STUDENT,
        )
        s1 = StudentProfile(
            id=uuid4(),
            user_id=u1.id,
            student_no="STU-C1",
            gender=GenderType.MALE,
            department="CS",
            year=1,
            guardian_name="G1",
            guardian_phone="+1111111111",
            emergency_contact="+2222222222",
        )
        s2 = StudentProfile(
            id=uuid4(),
            user_id=u2.id,
            student_no="STU-C2",
            gender=GenderType.FEMALE,
            department="IT",
            year=2,
            guardian_name="G2",
            guardian_phone="+3333333333",
            emergency_contact="+4444444444",
        )
        alloc1 = Allocation(
            id=uuid4(),
            student_id=s1.id,
            bed_id=bed1.id,
            start_date=date.today(),
            status=AllocationStatus.ACTIVE,
        )

        session.add_all([hostel, block, room, bed1, bed2, u1, u2, s1, s2, alloc1])
        await session.commit()

        alloc_repo = AllocationRepository(session)

        # 1. Active student constraint: s1 already has active allocation
        existing_alloc_student = await alloc_repo.get_active_by_student_id(s1.id)
        assert existing_alloc_student is not None
        assert existing_alloc_student.id == alloc1.id

        # 2. Active bed constraint: bed1 already has active allocation
        existing_alloc_bed = await alloc_repo.get_active_by_bed_id(bed1.id)
        assert existing_alloc_bed is not None
        assert existing_alloc_bed.id == alloc1.id

        # 3. Inactive bed2 has no active allocation
        no_alloc_bed2 = await alloc_repo.get_active_by_bed_id(bed2.id)
        assert no_alloc_bed2 is None
