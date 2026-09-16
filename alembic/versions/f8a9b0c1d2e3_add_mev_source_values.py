"""Store the original value range and median alongside MEV calculations."""
from alembic import op
import sqlalchemy as sa

revision = "f8a9b0c1d2e3"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade():
    # Historical source values cannot reliably be inferred from old MEVs.
    for table in ("valuation_requests", "lead_valuation_mev_calculations"):
        for column in ("value_low", "value_high", "value_median"):
            op.add_column(table, sa.Column(column, sa.Numeric(12, 2), nullable=True))


def downgrade():
    for table in ("lead_valuation_mev_calculations", "valuation_requests"):
        for column in ("value_median", "value_high", "value_low"):
            op.drop_column(table, column)
