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


def _rename_constraint_if_exists(table_name: str, old_name: str, new_name: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = '{table_name}'::regclass
                AND conname = '{old_name}'
            )
            AND NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = '{table_name}'::regclass
                AND conname = '{new_name}'
            ) THEN
                ALTER TABLE {table_name}
                RENAME CONSTRAINT {old_name} TO {new_name};
            END IF;
        END $$;
        """
    )


def _rename_index_if_exists(old_name: str, new_name: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_class
                WHERE relkind = 'i'
                AND relname = '{old_name}'
            )
            AND NOT EXISTS (
                SELECT 1
                FROM pg_class
                WHERE relkind = 'i'
                AND relname = '{new_name}'
            ) THEN
                ALTER INDEX {old_name} RENAME TO {new_name};
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.rename_table("lead_valuations", "valuation_requests")
    _rename_index_if_exists(
        "ix_lead_valuations_crm_person_record_id",
        "ix_valuation_requests_crm_person_record_id",
    )
    _rename_constraint_if_exists(
        "valuation_requests",
        "uq_lead_valuations_crm_valuation_request_id",
        "uq_valuation_requests_crm_valuation_request_id",
    )
    _rename_constraint_if_exists(
        "valuation_requests",
        "lead_valuations_crm_valuation_request_id_key",
        "uq_valuation_requests_crm_valuation_request_id",
    )
    _rename_constraint_if_exists(
        "valuation_requests",
        "uq_lead_valuations_rootle_request_id",
        "uq_valuation_requests_rootle_request_id",
    )
    _rename_constraint_if_exists(
        "valuation_requests",
        "lead_valuations_rootle_request_id_key",
        "uq_valuation_requests_rootle_request_id",
    )
    _rename_constraint_if_exists(
        "valuation_requests",
        "lead_valuations_pkey",
        "valuation_requests_pkey",
    )


def downgrade() -> None:
    """Downgrade schema."""
    _rename_constraint_if_exists(
        "valuation_requests",
        "valuation_requests_pkey",
        "lead_valuations_pkey",
    )
    _rename_constraint_if_exists(
        "valuation_requests",
        "uq_valuation_requests_rootle_request_id",
        "uq_lead_valuations_rootle_request_id",
    )
    _rename_constraint_if_exists(
        "valuation_requests",
        "uq_valuation_requests_crm_valuation_request_id",
        "uq_lead_valuations_crm_valuation_request_id",
    )
    _rename_index_if_exists(
        "ix_valuation_requests_crm_person_record_id",
        "ix_lead_valuations_crm_person_record_id",
    )
    op.rename_table("valuation_requests", "lead_valuations")
