"""payment_rejection_columns: rechazo del intento en `payments` canonico (TK-PAR-03).

Solo AGREGA tres columnas nulas a `payments`: `rejection_code` (codigo del proveedor, p. ej. `TEPSP1008` de Toku, el
codigo de 4 digitos del reporte de Intentos o `ISO:NN`), `rejection_reason` (glosa normalizada, sin fecha ni hora) y
`rejected_at` (fecha del intento). Para Toku se llenan desde `transaction.response_code` /
`original_response_message` de `tk_transactions.raw_payload` en la consolidacion o con
`scripts/maintenance/project_toku_rejections.py --apply`. No reescribe datos existentes. Reversible: el downgrade
borra las columnas. La aplica el usuario (ningun agente corre Alembic).

Revision ID: 20261102_0056
Revises: 20261102_0052
Create Date: 2026-11-02 14:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "20261102_0056"
down_revision = "20261102_0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("rejection_code", sa.String(50), nullable=True))
    op.add_column("payments", sa.Column("rejection_reason", sa.String(500), nullable=True))
    op.add_column("payments", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_payments_rejection_code", "payments", ["rejection_code"])


def downgrade() -> None:
    op.drop_index("ix_payments_rejection_code", table_name="payments")
    op.drop_column("payments", "rejected_at")
    op.drop_column("payments", "rejection_reason")
    op.drop_column("payments", "rejection_code")
