"""add prediction_evals table

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prediction_evals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("round_id", sa.Integer(), nullable=False),
        sa.Column("predicted_band", sa.String(10), nullable=False),
        sa.Column("actual_band", sa.String(10), nullable=False),
        sa.Column("actual_multiplier", sa.Numeric(12, 2), nullable=False),
        sa.Column("verdict", sa.String(4), nullable=False),   # "hit" | "miss"
        sa.Column("evaluated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_prediction_evals_round_id", "prediction_evals", ["round_id"])
    op.create_index("idx_prediction_evals_evaluated_at", "prediction_evals", ["evaluated_at"])


def downgrade() -> None:
    op.drop_table("prediction_evals")
