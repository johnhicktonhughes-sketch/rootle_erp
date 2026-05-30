"""add inbound labels

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-05-30 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "inbound_labels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rootle_label_id", sa.String(length=128), nullable=False),
        sa.Column("lead_valuation_id", sa.Integer(), nullable=False),
        sa.Column("crm_person_record_id", sa.String(length=128), nullable=False),
        sa.Column("crm_valuation_request_id", sa.String(length=128), nullable=True),
        sa.Column("rootle_request_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("dispatch_method", sa.String(length=64), nullable=False),
        sa.Column("courier", sa.String(length=128), nullable=True),
        sa.Column("service_level", sa.String(length=128), nullable=True),
        sa.Column("tracking_number", sa.String(length=128), nullable=True),
        sa.Column("label_url", sa.String(length=1024), nullable=True),
        sa.Column("barcode_value", sa.String(length=256), nullable=False),
        sa.Column("qr_payload", sa.String(length=1024), nullable=False),
        sa.Column("destination_country", sa.String(length=128), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("mev_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("white_glove_required", sa.Boolean(), nullable=False),
        sa.Column("requested_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["lead_valuation_id"], ["lead_valuations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("barcode_value"),
        sa.UniqueConstraint("rootle_label_id"),
        sa.UniqueConstraint("tracking_number"),
    )
    op.create_index(
        "ix_inbound_labels_crm_person_record_id",
        "inbound_labels",
        ["crm_person_record_id"],
    )
    op.create_index(
        "ix_inbound_labels_crm_valuation_request_id",
        "inbound_labels",
        ["crm_valuation_request_id"],
    )
    op.create_index(
        "ix_inbound_labels_lead_valuation_id",
        "inbound_labels",
        ["lead_valuation_id"],
    )
    op.create_index(
        "ix_inbound_labels_rootle_request_id",
        "inbound_labels",
        ["rootle_request_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_inbound_labels_rootle_request_id", table_name="inbound_labels")
    op.drop_index("ix_inbound_labels_lead_valuation_id", table_name="inbound_labels")
    op.drop_index("ix_inbound_labels_crm_valuation_request_id", table_name="inbound_labels")
    op.drop_index("ix_inbound_labels_crm_person_record_id", table_name="inbound_labels")
    op.drop_table("inbound_labels")
