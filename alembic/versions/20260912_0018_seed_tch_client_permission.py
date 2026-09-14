"""Seed the TCH client read permission.

Revision ID: 20260912_0018
Revises: 20260912_0017
Create Date: 2026-09-12 22:30:00
"""

import uuid

import sqlalchemy as sa

from alembic import op

revision = "20260912_0018"
down_revision = "20260912_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO permissions (id, code, description)
            VALUES (:id, 'tch.clientes.view', 'Ver clientes TCH')
            ON CONFLICT (code) DO NOTHING
            """
        ),
        {"id": uuid.uuid4()},
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT roles.id, permissions.id
            FROM roles CROSS JOIN permissions
            WHERE roles.name = 'admin' AND permissions.code = 'tch.clientes.view'
            ON CONFLICT DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM permissions WHERE code = 'tch.clientes.view'"))
