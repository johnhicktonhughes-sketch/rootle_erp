"""add lead valuations

Revision ID: a1b2c3d4e5f6
Revises: 9c7d5e2f1a04
Create Date: 2026-05-27 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "9c7d5e2f1a04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "lead_valuations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("crm_system", sa.String(length=64), nullable=False),
        sa.Column("crm_person_record_id", sa.String(length=128), nullable=False),
        sa.Column("crm_valuation_request_id", sa.String(length=128), nullable=True),
        sa.Column("rootle_request_id", sa.String(length=128), nullable=False),
        sa.Column("posthog_distinct_id", sa.String(length=256), nullable=True),
        sa.Column("item_categories", sa.JSON(), nullable=False),
        sa.Column("item_photo_url", sa.String(length=1024), nullable=False),
        sa.Column("valuation_guide_id", sa.String(length=128), nullable=True),
        sa.Column("valuation_guide_url", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("current_stage", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("customer_email", sa.String(length=256), nullable=True),
        sa.Column("address_line_1", sa.String(length=256), nullable=True),
        sa.Column("address_line_2", sa.String(length=256), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("postcode", sa.String(length=64), nullable=True),
        sa.Column("country", sa.String(length=128), nullable=True),
        sa.Column("item_submitted_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("contact_details_received_at", sa.DateTime(), nullable=True),
        sa.Column("stage_3_completed_at", sa.DateTime(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "crm_valuation_request_id",
            name="uq_lead_valuations_crm_valuation_request_id",
        ),
        sa.UniqueConstraint(
            "rootle_request_id",
            name="uq_lead_valuations_rootle_request_id",
        ),
    )
    op.create_index(
        "ix_lead_valuations_crm_person_record_id",
        "lead_valuations",
        ["crm_person_record_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_lead_valuations_crm_person_record_id",
        table_name="lead_valuations",
    )
    op.drop_table("lead_valuations")
