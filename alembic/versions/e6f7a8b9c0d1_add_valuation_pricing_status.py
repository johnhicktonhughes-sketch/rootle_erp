"""add valuation pricing status

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-06-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "lead_valuations",
        sa.Column(
            "pricing_status",
            sa.String(length=64),
            server_default="pricing_pending",
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE lead_valuations
        SET pricing_status = 'mev_calculated'
        WHERE latest_mev_amount IS NOT NULL
        """
    )
    op.alter_column("lead_valuations", "pricing_status", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("lead_valuations", "pricing_status")
