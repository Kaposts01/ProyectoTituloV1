"""AUTH-04: `users.google_email` para entrar con Google.

Columna nullable (los usuarios existentes quedan sin correo de Google, sin relleno) e indice unico parcial sobre
`lower(google_email)` donde no es nulo: un correo de Google identifica a un solo usuario. El administrador registra el
correo antes del primer ingreso; el login nunca crea usuarios.

`downgrade` elimina el indice y la columna (se pierden los correos registrados; no afecta a la contrasena ni a las sesiones).

Revision ID: 20261119_0084
Revises: 20261118_0083
Create Date: 2026-11-19 10:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "20261119_0084"
down_revision = "20261118_0083"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("google_email", sa.String(length=255), nullable=True))
    op.execute(
        "CREATE UNIQUE INDEX uq_users_google_email_lower ON users (lower(google_email)) WHERE google_email IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_users_google_email_lower")
    op.drop_column("users", "google_email")
