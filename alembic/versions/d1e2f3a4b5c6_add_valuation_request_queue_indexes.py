"""add valuation request queue indexes

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-08-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, Sequence[str], None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_valuation_requests_created_at_id",
        "valuation_requests",
        ["created_at", "id"],
    )
    op.create_index(
        "ix_valuation_requests_pricing_status_created_at_id",
        "valuation_requests",
        ["pricing_status", "created_at", "id"],
    )
    op.create_index(
        "ix_valuation_requests_person_created_at_id",
        "valuation_requests",
        ["crm_person_record_id", "created_at", "id"],
    )
    op.create_index(
        "ix_valuation_requests_status_created_at_id",
        "valuation_requests",
        ["status", "created_at", "id"],
    )
    op.create_index(
        "ix_valuation_requests_current_stage_created_at_id",
        "valuation_requests",
        ["current_stage", "created_at", "id"],
    )
    op.create_index(
        "ix_valuation_requests_needs_mev_created_at_id",
        "valuation_requests",
        ["created_at", "id"],
        postgresql_where=sa.text("latest_mev_amount IS NULL"),
    )
    op.create_index(
        "ix_valuation_requests_needs_mev_person_created_id",
        "valuation_requests",
        ["crm_person_record_id", "created_at", "id"],
        postgresql_where=sa.text("latest_mev_amount IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_valuation_requests_needs_mev_person_created_id",
        table_name="valuation_requests",
    )
    op.drop_index(
        "ix_valuation_requests_needs_mev_created_at_id",
        table_name="valuation_requests",
    )
    op.drop_index(
        "ix_valuation_requests_current_stage_created_at_id",
        table_name="valuation_requests",
    )
    op.drop_index(
        "ix_valuation_requests_status_created_at_id",
        table_name="valuation_requests",
    )
    op.drop_index(
        "ix_valuation_requests_person_created_at_id",
        table_name="valuation_requests",
    )
    op.drop_index(
        "ix_valuation_requests_pricing_status_created_at_id",
        table_name="valuation_requests",
    )
    op.drop_index(
        "ix_valuation_requests_created_at_id",
        table_name="valuation_requests",
    )
