"""Seed TCH permissions for existing installations.

Revision ID: 20260912_0015
Revises: 20260912_0014
Create Date: 2026-09-12 20:15:00
"""

import uuid

import sqlalchemy as sa

from alembic import op

revision = "20260912_0015"
down_revision = "20260912_0014"
branch_labels = None
depends_on = None

_PERMISSIONS = (
    ("tch.dashboard.view", "Ver dashboard TCH"),
    ("tch.suscripciones.view", "Ver suscripciones TCH"),
    ("tch.transacciones.view", "Ver transacciones TCH"),
)


def upgrade() -> None:
    bind = op.get_bind()
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("description", sa.String()),
    )
    bind.execute(
        sa.dialects.postgresql.insert(permissions)
        .values([{"id": uuid.uuid4(), "code": code, "description": description} for code, description in _PERMISSIONS])
        .on_conflict_do_nothing(index_elements=["code"])
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT roles.id, permissions.id
            FROM roles
            CROSS JOIN permissions
            WHERE roles.name = 'admin' AND permissions.code LIKE 'tch.%'
            ON CONFLICT DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM permissions
            WHERE code IN ('tch.dashboard.view', 'tch.suscripciones.view', 'tch.transacciones.view')
            """
        )
    )
