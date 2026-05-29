"""add mev calculation audit

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a7
Create Date: 2026-05-29 10:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "lead_valuations",
        sa.Column("latest_mev_amount", sa.Numeric(precision=12, scale=2), nullable=True),
    )
    op.add_column(
        "lead_valuations",
        sa.Column("latest_mev_currency", sa.String(length=3), nullable=True),
    )
    op.add_column(
        "lead_valuations",
        sa.Column("latest_mev_margin", sa.Numeric(precision=7, scale=4), nullable=True),
    )
    op.add_column(
        "lead_valuations",
        sa.Column("latest_mev_calculated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "lead_valuation_mev_calculations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_valuation_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("margin", sa.Numeric(precision=7, scale=4), nullable=False),
        sa.Column("calculation_method", sa.String(length=128), nullable=True),
        sa.Column("calculated_by", sa.String(length=128), nullable=True),
        sa.Column("calculated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["lead_valuation_id"], ["lead_valuations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lead_valuation_mev_calculations_lead_valuation_id",
        "lead_valuation_mev_calculations",
        ["lead_valuation_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_lead_valuation_mev_calculations_lead_valuation_id",
        table_name="lead_valuation_mev_calculations",
    )
    op.drop_table("lead_valuation_mev_calculations")
    op.drop_column("lead_valuations", "latest_mev_calculated_at")
    op.drop_column("lead_valuations", "latest_mev_margin")
    op.drop_column("lead_valuations", "latest_mev_currency")
    op.drop_column("lead_valuations", "latest_mev_amount")
