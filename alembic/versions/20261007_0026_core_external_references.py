"""Add provider-neutral external references to Core financial facts.

Revision ID: 20261007_0026
Revises: 20261007_0025
"""

import sqlalchemy as sa

from alembic import op

revision = "20261007_0026"
down_revision = "20261007_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("core_subscriptions", "core_charges", "core_payments"):
        op.add_column(table, sa.Column("source", sa.String(50), nullable=False))
        op.add_column(table, sa.Column("external_id", sa.String(255), nullable=False))
        op.create_unique_constraint(f"uq_{table[:-1]}_source_external_id", table, ["source", "external_id"])


def downgrade() -> None:
    for table in ("core_payments", "core_charges", "core_subscriptions"):
        op.drop_constraint(f"uq_{table[:-1]}_source_external_id", table, type_="unique")
        op.drop_column(table, "external_id")
        op.drop_column(table, "source")
