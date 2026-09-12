"""ETL BDlocales: raw_payload en canónicas, source_record_id nullable, tabla etl_runs.

Revision ID: 20260911_0007
Revises: 20260831_0006
Create Date: 2026-09-11 12:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from alembic import op

revision = "20260911_0007"
down_revision = "20260831_0006"
branch_labels = None
depends_on = None

_CANONICAL_TABLES = ("clients", "plans", "subscriptions", "charges", "payments")


def upgrade() -> None:
    for table in _CANONICAL_TABLES:
        op.add_column(table, sa.Column("raw_payload", JSONB, nullable=True))
        op.alter_column(table, "source_record_id", nullable=True)

    op.create_table(
        "etl_runs",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("channels_processed", ARRAY(sa.String), nullable=True),
        sa.Column("records_upserted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
    )
    op.create_index("ix_etl_runs_status", "etl_runs", ["status"])
    op.create_index("ix_etl_runs_started_at", "etl_runs", [sa.text("started_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_etl_runs_started_at", "etl_runs")
    op.drop_index("ix_etl_runs_status", "etl_runs")
    op.drop_table("etl_runs")

    for table in _CANONICAL_TABLES:
        op.alter_column(table, "source_record_id", nullable=False)
        op.drop_column(table, "raw_payload")
