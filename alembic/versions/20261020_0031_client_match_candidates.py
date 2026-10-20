"""Add client_match_candidates table for cross-canal deduplication review.

Revision ID: 20261020_0031
Revises: 20261020_0030
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261020_0031"
down_revision = "20261020_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_match_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("client_id_a", postgresql.UUID(as_uuid=True), sa.ForeignKey("core_clients.id"), nullable=False),
        sa.Column("client_id_b", postgresql.UUID(as_uuid=True), sa.ForeignKey("core_clients.id"), nullable=False),
        sa.Column("match_level", sa.String(1), nullable=False),
        sa.Column("match_signals", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("client_id_a", "client_id_b", name="uq_client_match_pair"),
    )
    op.create_index("ix_client_match_candidates_client_id_a", "client_match_candidates", ["client_id_a"])
    op.create_index("ix_client_match_candidates_client_id_b", "client_match_candidates", ["client_id_b"])
    op.create_index("ix_client_match_candidates_status", "client_match_candidates", ["status"])


def downgrade() -> None:
    op.drop_table("client_match_candidates")
