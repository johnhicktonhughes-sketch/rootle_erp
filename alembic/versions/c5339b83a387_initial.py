"""initial

Revision ID: c5339b83a387
Revises: 
Create Date: 2026-05-19 18:35:09.056375

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5339b83a387'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("first_name", sa.String(length=128), nullable=False),
        sa.Column("last_name", sa.String(length=128), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=256), nullable=True),
        sa.Column("address_line_1", sa.String(length=256), nullable=True),
        sa.Column("address_line_2", sa.String(length=256), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("postcode", sa.String(length=64), nullable=True),
        sa.Column("country", sa.String(length=128), nullable=True),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("preferred_contact_method", sa.String(length=64), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "lead_box_details",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("box_type", sa.String(length=128), nullable=True),
        sa.Column("condition", sa.String(length=128), nullable=True),
        sa.Column("item_description", sa.Text(), nullable=True),
        sa.Column("photo_urls", sa.JSON(), nullable=True),
        sa.Column("attachments", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "lead_box_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("box_detail_id", sa.Integer(), nullable=False),
        sa.Column("revision_type", sa.String(length=128), nullable=True),
        sa.Column("additional_description", sa.Text(), nullable=True),
        sa.Column("photo_urls", sa.JSON(), nullable=True),
        sa.Column("attachments", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["box_detail_id"], ["lead_box_details.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "lead_estimates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("box_detail_id", sa.Integer(), nullable=True),
        sa.Column("box_revision_id", sa.Integer(), nullable=True),
        sa.Column("estimated_value", sa.Float(), nullable=True),
        sa.Column("estimate_status", sa.String(length=64), nullable=False),
        sa.Column("pricing_metadata", sa.JSON(), nullable=True),
        sa.Column("accepted", sa.Boolean(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["box_detail_id"], ["lead_box_details.id"]),
        sa.ForeignKeyConstraint(["box_revision_id"], ["lead_box_revisions.id"]),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("lead_estimates")
    op.drop_table("lead_box_revisions")
    op.drop_table("lead_box_details")
    op.drop_table("leads")
