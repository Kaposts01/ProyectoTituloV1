"""payku_cycles_status_recovery: modelo de cargos Payku, estado normalizado y permiso de la pestaña Payku.

* PK-06: tabla `p_cycles` (ciclos de cobro de `paid[]` de `GET /api/sususcriptionv3`) y `p_transactions` ampliada con
  `status_normalized`, `order_ref` y `description` (no se guardan `verification_key` ni `authorization_code`).
* PK-PAR-07: `p_subscriptions.status_normalized` (taxonomia comun) sin reemplazar el `status` crudo. El upgrade la
  llena para las filas existentes con el mismo mapeo que `app/services/payku_status.py` (un UPDATE por columna nula).
* REC-05: permiso `general.recovery.payku.view`, otorgado por datos a los roles que ya tienen
  `virtualpos.recovery.view` y `payku.subscriptions.view` (misma regla que la 0052; nadie gana acceso nuevo a datos).

Solo agrega: no borra ni reescribe datos crudos. Reversible: el downgrade quita el permiso y sus asignaciones, las
columnas nuevas y la tabla `p_cycles`. La aplica el usuario (ningun agente corre Alembic).

Revision ID: 20261102_0055
Revises: 20261102_0057
Create Date: 2026-11-02 12:00:00
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261102_0055"
down_revision = "20261102_0057"
branch_labels = None
depends_on = None

PERMISSIONS = {
    "general.recovery.payku.view": "Ver la pestaña Payku del Recuperador general (solo lectura)",
}
# Copia de rbac.PAYKU_RECOVERY_GRANT_RULES.
GRANT_RULES = {
    "general.recovery.payku.view": ("virtualpos.recovery.view", "payku.subscriptions.view"),
}

# Copia de payku_status.PAYKU_COMMON_STATUS / PAYKU_CHARGE_STATUS (las pruebas verifican que coincidan).
SUBSCRIPTION_STATUS = {
    "register": "pending_enrollment",
    "active": "active",
    "suspended_awaits_change_plan": "active",
    "suspended": "suspended",
    "cancel": "cancelled",
    "delete": "cancelled",
    "finish": "cancelled",
}
CHARGE_STATUS = {
    "success": "paid",
    "pending": "pending",
    "retry": "retrying",
    "rejected": "rejected",
    "first payment rejected": "rejected",
    "maximum attempt limit": "rejected",
    "payment consumes failed": "rejected",
    "refunded": "refunded",
    "refunded partial": "refunded",
    "canceled by customer": "cancelled",
    "canceled by paymaster": "cancelled",
    "canceled by payku": "cancelled",
}


def _case(mapping: dict[str, str], expr: str) -> str:
    whens = " ".join(f"WHEN '{raw}' THEN '{common}'" for raw, common in mapping.items())
    return f"CASE {expr} {whens} ELSE 'unknown' END"


def grant(bind) -> None:
    for code, description in PERMISSIONS.items():
        bind.execute(
            sa.text(
                "INSERT INTO permissions (id, code, description) VALUES (:id, :code, :description) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"id": uuid.uuid4(), "code": code, "description": description},
        )
    for code, required in GRANT_RULES.items():
        bind.execute(
            sa.text(
                """
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT rp.role_id, target.id
                FROM role_permissions rp
                JOIN permissions p ON p.id = rp.permission_id
                CROSS JOIN permissions target
                WHERE target.code = :code AND p.code = ANY(:required)
                GROUP BY rp.role_id, target.id
                HAVING COUNT(DISTINCT p.code) = :n
                ON CONFLICT DO NOTHING
                """
            ),
            {"code": code, "required": list(required), "n": len(required)},
        )


def revoke(bind) -> None:
    codes = list(PERMISSIONS)
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code = ANY(:codes))"
        ),
        {"codes": codes},
    )
    bind.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:codes)"), {"codes": codes})


def backfill_status(bind) -> None:
    """Llena `status_normalized` donde falta (idempotente). El ETL Core la mantiene al dia despues."""
    sub_expr = _case(SUBSCRIPTION_STATUS, "lower(btrim(coalesce(status, '')))")
    bind.execute(sa.text(f"UPDATE p_subscriptions SET status_normalized = {sub_expr} WHERE status_normalized IS NULL"))
    tx_expr = _case(
        CHARGE_STATUS,
        "regexp_replace(replace(lower(btrim(coalesce(status, ''))), 'á', 'a'), '\\s+', ' ', 'g')",
    )
    bind.execute(sa.text(f"UPDATE p_transactions SET status_normalized = {tx_expr} WHERE status_normalized IS NULL"))


def upgrade() -> None:
    op.create_table(
        "p_cycles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("subscription_id", sa.String(255), nullable=False),
        sa.Column("cycle_day", sa.String(50), nullable=True),
        sa.Column("payment_day", sa.String(50), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("status_normalized", sa.String(30), nullable=True),
        sa.Column("amount_paid", sa.String(50), nullable=True),
        sa.Column("try_number", sa.Integer(), nullable=True),
        sa.Column("paid_number", sa.Integer(), nullable=True),
        sa.Column("transaction_ids", postgresql.JSONB(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("external_id", name="uq_p_cycle_external_id"),
    )
    for column in ("external_id", "subscription_id", "cycle_day", "status", "status_normalized"):
        op.create_index(f"ix_p_cycles_{column}", "p_cycles", [column])

    op.add_column("p_subscriptions", sa.Column("status_normalized", sa.String(30), nullable=True))
    op.create_index("ix_p_subscriptions_status_normalized", "p_subscriptions", ["status_normalized"])
    op.add_column("p_transactions", sa.Column("status_normalized", sa.String(30), nullable=True))
    op.add_column("p_transactions", sa.Column("order_ref", sa.String(100), nullable=True))
    op.add_column("p_transactions", sa.Column("description", sa.Text(), nullable=True))
    op.create_index("ix_p_transactions_status_normalized", "p_transactions", ["status_normalized"])
    op.create_index("ix_p_transactions_order_ref", "p_transactions", ["order_ref"])

    bind = op.get_bind()
    backfill_status(bind)
    grant(bind)


def downgrade() -> None:
    revoke(op.get_bind())
    op.drop_index("ix_p_transactions_order_ref", table_name="p_transactions")
    op.drop_index("ix_p_transactions_status_normalized", table_name="p_transactions")
    op.drop_column("p_transactions", "description")
    op.drop_column("p_transactions", "order_ref")
    op.drop_column("p_transactions", "status_normalized")
    op.drop_index("ix_p_subscriptions_status_normalized", table_name="p_subscriptions")
    op.drop_column("p_subscriptions", "status_normalized")
    for column in ("status_normalized", "status", "cycle_day", "subscription_id", "external_id"):
        op.drop_index(f"ix_p_cycles_{column}", table_name="p_cycles")
    op.drop_table("p_cycles")
