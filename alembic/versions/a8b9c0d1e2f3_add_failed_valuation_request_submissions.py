"""add failed valuation request submissions

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-06-11 09:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "failed_valuation_request_submissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rootle_request_id", sa.String(length=128), nullable=True),
        sa.Column("crm_person_record_id", sa.String(length=128), nullable=True),
        sa.Column("posthog_distinct_id", sa.String(length=256), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("normalised_payload", sa.JSON(), nullable=True),
        sa.Column("error_type", sa.String(length=128), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("last_retry_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("valuation_request_id", sa.Integer(), nullable=True),
        sa.Column("crm_valuation_request_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["valuation_request_id"], ["valuation_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_failed_valuation_request_submissions_crm_person_record_id",
        "failed_valuation_request_submissions",
        ["crm_person_record_id"],
    )
    op.create_index(
        "ix_failed_valuation_request_submissions_rootle_request_id",
        "failed_valuation_request_submissions",
        ["rootle_request_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_failed_valuation_request_submissions_rootle_request_id",
        table_name="failed_valuation_request_submissions",
    )
    op.drop_index(
        "ix_failed_valuation_request_submissions_crm_person_record_id",
        table_name="failed_valuation_request_submissions",
    )
    op.drop_table("failed_valuation_request_submissions")
