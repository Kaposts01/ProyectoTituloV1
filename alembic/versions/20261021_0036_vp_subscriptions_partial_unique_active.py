"""Add partial unique index on vp_subscriptions for active/subscribing plan+client.

Guards against the race condition in create_subscription where two concurrent
requests could both pass the application-level antiduplicado SELECT before
either writes to the DB.

Revision ID: 20261021_0036
Revises: 20261021_0035
Create Date: 2026-10-21
"""

from alembic import op

revision = "20261021_0036"
down_revision = "20261021_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX uq_vp_sub_active_plan_client
        ON vp_subscriptions (platform, plan_external_id, client_social_id)
        WHERE status IN ('ACTIVA', 'SUSCRIBIENDO')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_vp_sub_active_plan_client")
