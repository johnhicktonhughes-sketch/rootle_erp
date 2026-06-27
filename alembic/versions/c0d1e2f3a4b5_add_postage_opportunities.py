"""add postage opportunities

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-06-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "postage_opportunities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_valuation_id", sa.Integer(), nullable=False),
        sa.Column("crm_person_record_id", sa.String(length=128), nullable=False),
        sa.Column("crm_valuation_request_id", sa.String(length=128), nullable=False),
        sa.Column("crm_postage_opportunity_id", sa.String(length=128), nullable=False),
        sa.Column("rootle_request_id", sa.String(length=128), nullable=False),
        sa.Column("rootle_postage_opportunity_id", sa.String(length=128), nullable=False),
        sa.Column("barcode_value", sa.String(length=256), nullable=False),
        sa.Column("qr_payload", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("triggered_by", sa.String(length=128), nullable=True),
        sa.Column("triggered_at", sa.DateTime(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["lead_valuation_id"], ["valuation_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "crm_postage_opportunity_id",
            name="uq_postage_opportunities_crm_postage_opportunity_id",
        ),
        sa.UniqueConstraint(
            "rootle_postage_opportunity_id",
            name="uq_postage_opportunities_rootle_postage_opportunity_id",
        ),
        sa.UniqueConstraint("barcode_value", name="uq_postage_opportunities_barcode_value"),
    )
    op.create_index(
        "ix_postage_opportunities_lead_valuation_id",
        "postage_opportunities",
        ["lead_valuation_id"],
    )
    op.create_index(
        "ix_postage_opportunities_crm_person_record_id",
        "postage_opportunities",
        ["crm_person_record_id"],
    )
    op.create_index(
        "ix_postage_opportunities_crm_valuation_request_id",
        "postage_opportunities",
        ["crm_valuation_request_id"],
    )
    op.create_index(
        "ix_postage_opportunities_rootle_request_id",
        "postage_opportunities",
        ["rootle_request_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_postage_opportunities_rootle_request_id", table_name="postage_opportunities")
    op.drop_index(
        "ix_postage_opportunities_crm_valuation_request_id",
        table_name="postage_opportunities",
    )
    op.drop_index(
        "ix_postage_opportunities_crm_person_record_id",
        table_name="postage_opportunities",
    )
    op.drop_index("ix_postage_opportunities_lead_valuation_id", table_name="postage_opportunities")
    op.drop_table("postage_opportunities")
