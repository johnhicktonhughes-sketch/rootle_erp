"""add valuation item categories

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-28 19:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


valuation_item_categories = sa.table(
    "valuation_item_categories",
    sa.column("name", sa.String),
    sa.column("label", sa.String),
    sa.column("active", sa.Boolean),
    sa.column("sort_order", sa.Integer),
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "valuation_item_categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_valuation_item_categories_name"),
    )
    op.bulk_insert(
        valuation_item_categories,
        [
            {"name": "gold", "label": "Gold", "active": True, "sort_order": 0},
            {"name": "silver", "label": "Silver", "active": True, "sort_order": 1},
            {"name": "coins", "label": "Coins", "active": True, "sort_order": 2},
        ],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("valuation_item_categories")
