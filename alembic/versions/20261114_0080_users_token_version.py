"""CRM-16A: columna `users.token_version` para invalidar sesiones (logout, cambio y reseteo de clave).

Agrega un entero NOT NULL con default 0 en el servidor: las filas existentes quedan en 0 y los JWT emitidos antes
(sin claim `tv`) se tratan como version 0, asi que nadie pierde la sesion al aplicar la migracion. Sin backfill.
El downgrade quita la columna. Probada solo por pytest en la base `*_test`; la aplica el usuario.

Revision ID: 20261114_0080
Revises: 20261104_0071
Create Date: 2026-11-14 04:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "20261114_0080"
down_revision = "20261104_0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("users", "token_version")
