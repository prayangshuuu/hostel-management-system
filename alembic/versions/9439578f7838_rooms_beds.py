"""rooms beds

Revision ID: 9439578f7838
Revises: 8c569132464c
Create Date: 2026-11-22 05:38:10.380443

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9439578f7838"
down_revision: str | Sequence[str] | None = "8c569132464c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "rooms",
        sa.Column("block_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=50), nullable=False),
        sa.Column("floor", sa.Integer(), nullable=False),
        sa.Column(
            "room_type",
            sa.Enum(
                "SINGLE",
                "DOUBLE",
                "TRIPLE",
                "DORM",
                name="roomtype",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("monthly_rent", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "AVAILABLE",
                "FULL",
                "MAINTENANCE",
                name="roomstatus",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["block_id"],
            ["blocks.id"],
            name=op.f("fk_rooms_block_id_blocks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rooms")),
        sa.UniqueConstraint("block_id", "number", name="uq_rooms_block_id_number"),
    )
    op.create_index(op.f("ix_rooms_block_id"), "rooms", ["block_id"], unique=False)
    op.create_index(op.f("ix_rooms_status"), "rooms", ["status"], unique=False)

    op.create_table(
        "beds",
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=20), nullable=False),
        sa.Column("is_occupied", sa.Boolean(), server_default="false", nullable=False),
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
            ["room_id"],
            ["rooms.id"],
            name=op.f("fk_beds_room_id_rooms"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_beds")),
        sa.UniqueConstraint("room_id", "label", name="uq_beds_room_id_label"),
    )
    op.create_index(op.f("ix_beds_is_occupied"), "beds", ["is_occupied"], unique=False)
    op.create_index(op.f("ix_beds_room_id"), "beds", ["room_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_beds_room_id"), table_name="beds")
    op.drop_index(op.f("ix_beds_is_occupied"), table_name="beds")
    op.drop_table("beds")
    op.drop_index(op.f("ix_rooms_status"), table_name="rooms")
    op.drop_index(op.f("ix_rooms_block_id"), table_name="rooms")
    op.drop_table("rooms")
