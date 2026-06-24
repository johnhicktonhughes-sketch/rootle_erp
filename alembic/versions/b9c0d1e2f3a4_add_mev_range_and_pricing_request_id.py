"""add mev range and pricing request id

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-06-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("valuation_requests", sa.Column("mev_low", sa.Numeric(12, 2), nullable=True))
    op.add_column("valuation_requests", sa.Column("mev_high", sa.Numeric(12, 2), nullable=True))
    op.add_column(
        "valuation_requests",
        sa.Column("pricing_request_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "lead_valuation_mev_calculations",
        sa.Column("mev_low", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "lead_valuation_mev_calculations",
        sa.Column("mev_high", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "lead_valuation_mev_calculations",
        sa.Column("pricing_request_id", sa.String(length=128), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("lead_valuation_mev_calculations", "pricing_request_id")
    op.drop_column("lead_valuation_mev_calculations", "mev_high")
    op.drop_column("lead_valuation_mev_calculations", "mev_low")
    op.drop_column("valuation_requests", "pricing_request_id")
    op.drop_column("valuation_requests", "mev_high")
    op.drop_column("valuation_requests", "mev_low")
