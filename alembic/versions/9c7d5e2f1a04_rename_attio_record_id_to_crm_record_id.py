"""rename attio record id to crm record id

Revision ID: 9c7d5e2f1a04
Revises: 486219e0ada9
Create Date: 2026-05-26 18:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9c7d5e2f1a04"
down_revision: Union[str, Sequence[str], None] = "486219e0ada9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("uq_leads_attio_record_id", "leads", type_="unique")

    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.alter_column(
            "attio_record_id",
            new_column_name="crm_record_id",
            existing_type=sa.String(length=128),
            existing_nullable=True,
        )
        batch_op.add_column(
            sa.Column(
                "crm_system",
                sa.String(length=64),
                server_default="attio",
                nullable=False,
            )
        )

    op.create_unique_constraint("uq_leads_crm_record_id", "leads", ["crm_record_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_leads_crm_record_id", "leads", type_="unique")

    with op.batch_alter_table("leads", schema=None) as batch_op:
        batch_op.drop_column("crm_system")
        batch_op.alter_column(
            "crm_record_id",
            new_column_name="attio_record_id",
            existing_type=sa.String(length=128),
            existing_nullable=True,
        )

    op.create_unique_constraint(
        "uq_leads_attio_record_id",
        "leads",
        ["attio_record_id"],
    )
