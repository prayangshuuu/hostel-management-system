"""hostels blocks wardens

Revision ID: 8c569132464c
Revises: 2933c76ad37b
Create Date: 2026-11-22 05:18:06.129034

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8c569132464c"
down_revision: str | Sequence[str] | None = "2933c76ad37b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "hostels",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column(
            "gender_type",
            sa.Enum("MALE", "FEMALE", "MIXED", name="gendertype", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hostels")),
    )
    op.create_index(op.f("ix_hostels_code"), "hostels", ["code"], unique=True)

    op.create_table(
        "blocks",
        sa.Column("hostel_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("floor_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["hostel_id"],
            ["hostels.id"],
            name=op.f("fk_blocks_hostel_id_hostels"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blocks")),
        sa.UniqueConstraint("hostel_id", "name", name="uq_blocks_hostel_id_name"),
    )
    op.create_index(op.f("ix_blocks_hostel_id"), "blocks", ["hostel_id"], unique=False)

    op.create_table(
        "warden_assignments",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("hostel_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["hostel_id"],
            ["hostels.id"],
            name=op.f("fk_warden_assignments_hostel_id_hostels"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_warden_assignments_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_warden_assignments")),
        sa.UniqueConstraint("user_id", "hostel_id", name="uq_warden_assignments_user_id_hostel_id"),
    )
    op.create_index(
        op.f("ix_warden_assignments_hostel_id"),
        "warden_assignments",
        ["hostel_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_warden_assignments_user_id"),
        "warden_assignments",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_warden_assignments_user_id"), table_name="warden_assignments")
    op.drop_index(op.f("ix_warden_assignments_hostel_id"), table_name="warden_assignments")
    op.drop_table("warden_assignments")
    op.drop_index(op.f("ix_blocks_hostel_id"), table_name="blocks")
    op.drop_table("blocks")
    op.drop_index(op.f("ix_hostels_code"), table_name="hostels")
    op.drop_table("hostels")
