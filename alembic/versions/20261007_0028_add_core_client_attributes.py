"""Create core_client_attributes table for per-source PII evidence.

Revision ID: 20261007_0028
Revises: 20261007_0027
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261007_0028"
down_revision = "20261007_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "core_client_attributes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("core_clients.id"), nullable=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("attribute_type", sa.String(30), nullable=False),
        sa.Column("attribute_value", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("source", "attribute_type", "attribute_value", name="uq_core_client_attribute"),
    )
    op.create_index("ix_core_client_attributes_client_id", "core_client_attributes", ["client_id"])
    op.create_index("ix_core_client_attributes_source", "core_client_attributes", ["source"])
    op.create_index("ix_core_client_attributes_attribute_type", "core_client_attributes", ["attribute_type"])


def downgrade() -> None:
    op.drop_table("core_client_attributes")
