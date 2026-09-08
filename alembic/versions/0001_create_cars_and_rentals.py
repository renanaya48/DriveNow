"""create cars and rentals

Revision ID: 0001
Revises:
Create Date: 2026-09-07

Initial schema: the ``cars`` fleet table and the ``rentals`` agreements table.
Hand-reviewed after autogenerate: portable server defaults (``now()``), explicit
constraint names, ordered create/drop.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cars",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "available",
                "in_use",
                "under_maintenance",
                name="car_status",
                native_enum=False,
                length=20,
            ),
            server_default="available",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "rentals",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("car_id", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(length=200), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["car_id"], ["cars.id"], name="fk_rentals_car_id"),
        sa.CheckConstraint(
            "end_at >= start_at", name="ck_rentals_end_after_start"
        ),
    )
    op.create_index("ix_rentals_car_id", "rentals", ["car_id"])
    op.create_index("ix_rentals_returned_at", "rentals", ["returned_at"])


def downgrade() -> None:
    op.drop_index("ix_rentals_returned_at", table_name="rentals")
    op.drop_index("ix_rentals_car_id", table_name="rentals")
    op.drop_table("rentals")
    op.drop_table("cars")
