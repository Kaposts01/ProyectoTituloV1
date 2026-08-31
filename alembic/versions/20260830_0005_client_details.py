"""Add canonical client details and safe card summaries.

Revision ID: 20260830_0005
Revises: 20260830_0004
Create Date: 2026-08-30 04:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260830_0005"
down_revision = "20260830_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("social_id", sa.String(length=50), nullable=True))
    op.add_column("clients", sa.Column("gender_id", sa.String(length=50), nullable=True))
    op.add_column("clients", sa.Column("birth_date", sa.String(length=50), nullable=True))
    op.add_column("clients", sa.Column("provider_created_at", sa.String(length=50), nullable=True))
    op.add_column(
        "clients",
        sa.Column("cards", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.create_index("ix_clients_social_id", "clients", ["social_id"])


def downgrade() -> None:
    op.drop_index("ix_clients_social_id", table_name="clients")
    op.drop_column("clients", "cards")
    op.drop_column("clients", "provider_created_at")
    op.drop_column("clients", "birth_date")
    op.drop_column("clients", "gender_id")
    op.drop_column("clients", "social_id")
