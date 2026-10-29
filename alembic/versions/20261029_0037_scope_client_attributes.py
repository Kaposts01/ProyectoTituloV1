"""Scope observed attribute uniqueness to the client, preserving shared values.

Revision ID: 20261029_0037
Revises: 20261021_0036
"""

import sqlalchemy as sa

from alembic import op

revision = "20261029_0037"
down_revision = "20261021_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL 15+ keeps unlinked observations idempotent as well.
    op.drop_constraint("uq_core_client_attribute", "core_client_attributes", type_="unique")
    op.create_unique_constraint(
        "uq_core_client_attribute", "core_client_attributes",
        ["client_id", "source", "attribute_type", "attribute_value"],
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    # Restoring the previous constraint must never discard shared observations.
    shared = op.get_bind().scalar(sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM core_client_attributes
            GROUP BY source, attribute_type, attribute_value
            HAVING count(*) > 1
        )
    """))
    if shared:
        raise RuntimeError("Downgrade blocked: shared client attributes require review; no rows were removed.")
    op.drop_constraint("uq_core_client_attribute", "core_client_attributes", type_="unique")
    op.create_unique_constraint(
        "uq_core_client_attribute", "core_client_attributes",
        ["source", "attribute_type", "attribute_value"],
    )
