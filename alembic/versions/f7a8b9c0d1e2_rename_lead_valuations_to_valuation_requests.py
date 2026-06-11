"""rename lead valuations to valuation requests

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-06-11 09:15:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.rename_table("lead_valuations", "valuation_requests")
    op.execute(
        "ALTER INDEX ix_lead_valuations_crm_person_record_id "
        "RENAME TO ix_valuation_requests_crm_person_record_id"
    )
    op.execute(
        "ALTER TABLE valuation_requests "
        "RENAME CONSTRAINT uq_lead_valuations_crm_valuation_request_id "
        "TO uq_valuation_requests_crm_valuation_request_id"
    )
    op.execute(
        "ALTER TABLE valuation_requests "
        "RENAME CONSTRAINT uq_lead_valuations_rootle_request_id "
        "TO uq_valuation_requests_rootle_request_id"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "ALTER TABLE valuation_requests "
        "RENAME CONSTRAINT uq_valuation_requests_rootle_request_id "
        "TO uq_lead_valuations_rootle_request_id"
    )
    op.execute(
        "ALTER TABLE valuation_requests "
        "RENAME CONSTRAINT uq_valuation_requests_crm_valuation_request_id "
        "TO uq_lead_valuations_crm_valuation_request_id"
    )
    op.execute(
        "ALTER INDEX ix_valuation_requests_crm_person_record_id "
        "RENAME TO ix_lead_valuations_crm_person_record_id"
    )
    op.rename_table("valuation_requests", "lead_valuations")
