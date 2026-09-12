"""Add local private notes for CRM clients.

Revision ID: 20260912_0013
Revises: 20260912_0012
Create Date: 2026-09-12 14:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "20260912_0013"
down_revision = "20260912_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("private_note", sa.String(length=2000), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "private_note")
