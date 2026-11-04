"""core_subscription_signals: calculated per-subscription signals (Toku report ETL).

Revision ID: 20261028_0040
Revises: 20261028_0039
Create Date: 2026-10-28 14:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20261028_0040"
down_revision = "20261028_0039"
branch_labels = None
depends_on = None

SEVERITIES = "('SU', 'TE', 'PE', 'UE', 'UNKNOWN')"


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "core_subscription_signals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "subscription_id",
            UUID(as_uuid=True),
            sa.ForeignKey("core_subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(50), nullable=False, server_default="toku"),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("lifecycle_status", sa.String(20), nullable=False),
        sa.Column("payment_method_status", sa.String(100)),
        sa.Column("is_chargeable", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_effectively_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("consecutive_failed_debts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_response_code", sa.String(10)),
        sa.Column("last_response_severity", sa.String(10)),
        sa.Column("recoverable_reason", sa.String(20)),
        sa.Column("is_recoverable", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("report_generated_at", sa.DateTime(timezone=True)),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("subscription_id", name="uq_core_subscription_signals_subscription"),
        sa.UniqueConstraint("source", "external_id", name="uq_core_subscription_signals_source_external"),
        sa.CheckConstraint(
            "lifecycle_status IN ('active', 'deleted', 'unknown')", name="ck_tkr_signals_lifecycle"
        ),
        sa.CheckConstraint(
            f"last_response_severity IS NULL OR last_response_severity IN {SEVERITIES}",
            name="ck_tkr_signals_severity",
        ),
        sa.CheckConstraint(
            "recoverable_reason IS NULL OR recoverable_reason IN ('streak', 'blocked_card', 'expired_card')",
            name="ck_tkr_signals_reason",
        ),
        sa.CheckConstraint(
            "consecutive_failed_debts >= 0 AND consecutive_failed_attempts >= 0", name="ck_tkr_signals_counters"
        ),
    )
    op.create_index("ix_core_subscription_signals_is_recoverable", "core_subscription_signals", ["is_recoverable"])
    op.create_index(
        "ix_core_subscription_signals_recoverable_reason", "core_subscription_signals", ["recoverable_reason"]
    )


def downgrade() -> None:
    op.drop_table("core_subscription_signals")
