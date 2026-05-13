"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "rounds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("multiplier", sa.Numeric(12, 4), nullable=False),
        sa.Column("recorded_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("multiplier > 0", name="ck_rounds_multiplier_positive"),
    )
    op.create_index("idx_rounds_recorded_at", "rounds", ["recorded_at"])

    op.create_table(
        "analysis_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("prob_2x", sa.Numeric(6, 4)),
        sa.Column("prob_5x", sa.Numeric(6, 4)),
        sa.Column("prob_10x", sa.Numeric(6, 4)),
        sa.Column("moving_avg", sa.Numeric(12, 4)),
        sa.Column("window_size", sa.Integer()),
        sa.Column("snapshot_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("analysis_snapshots")
    op.drop_index("idx_rounds_recorded_at", table_name="rounds")
    op.drop_table("rounds")
    op.drop_table("users")
