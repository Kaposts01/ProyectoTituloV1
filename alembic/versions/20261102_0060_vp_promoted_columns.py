"""vp_promoted_columns: columnas desde `raw_payload` en `vp_*` y motivo/ultimos 4 en `core_subscriptions`.

VP-PAR-07. Agrega columnas nulas y las llena desde `raw_payload`:

* `vp_subscriptions`: `card_type`, `card_brand`, `card_last4` (de `payment_method`; CHECK de 4 digitos, nunca PAN ni
  BIN), `terminal_pos` y `origin`. El `seller_id` NO se promueve (forma de RUT; decision de privacidad pendiente).
* `vp_payments`: `client_social_id` (`client.social_id`, lo usa el ETL Core), `authorized_at` (`order.authorized_at`,
  timestamp sin zona), y del primer tramo de `order.deposits`: `processing_fee`, `payout_amount`, `payout_date`.

VP-PAR-09. Agrega a `core_subscriptions` `rejection_reason` (Motivo de rechazo de `SuscriptoresPAT`, solo filas con
plataforma `resolved`), `card_last4` y `card_last4_source`: la tarjeta de la API manda (`api`) y el reporte completa
(`report`). Desde aqui el ETL Core (`core_vp_etl.persist_subscription_report_fields`) los mantiene.

Backfill dentro de la migracion, en lotes de 5.000 filas por clave primaria. Los valores que no se pueden convertir
(texto vacio, fecha imposible, monto no numerico) quedan NULL y se cuentan en el log (`alembic.vp_l3`); el original
sigue en `raw_payload`. Misma regla que `app/services/vp_typed_fields.py`.

Duracion esperada: las columnas nuevas son nulas (sin reescritura de tabla); el backfill reescribe una vez cada fila de
`vp_payments` (~73 mil), `vp_subscriptions` (~9 mil) y las `core_subscriptions` VP (~9 mil): del orden de 1 a 3
minutos en `crm`. Aplicarla con un respaldo previo (`pg_dump`). La aplica el usuario (ningun agente corre Alembic
contra `crm` ni `crm_sandbox`). Reversible: el downgrade borra las columnas (los datos siguen en `raw_payload`).

Revision ID: 20261102_0060
Revises: 20261102_0054
Create Date: 2026-11-02 18:00:00
"""

import logging

import sqlalchemy as sa

from alembic import op

revision = "20261102_0060"
down_revision = "20261102_0054"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.vp_l3")

BATCH = 5000

# Conversion segura (version SQL de app/services/vp_typed_fields.py). Funciones temporales de la sesion: no quedan
# en el esquema.
_FUNCTIONS = r"""
CREATE OR REPLACE FUNCTION pg_temp.vp_l3_numeric(v text) RETURNS numeric LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    IF v IS NULL OR v !~ '^\s*-?\d+(\.\d+)?\s*$' THEN RETURN NULL; END IF;
    RETURN btrim(v)::numeric;
EXCEPTION WHEN others THEN RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION pg_temp.vp_l3_timestamp(v text) RETURNS timestamp LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE m text[];
BEGIN
    m := regexp_match(v, '^\s*(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?))?');
    IF m IS NULL OR left(coalesce(m[2], ''), 2) = '24' THEN RETURN NULL; END IF;
    RETURN (m[1] || ' ' || coalesce(m[2], '00:00'))::timestamp;
EXCEPTION WHEN others THEN RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION pg_temp.vp_l3_date(v text) RETURNS date LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE m text[];
BEGIN
    m := regexp_match(v, '^\s*(\d{4}-\d{2}-\d{2})');
    IF m IS NULL THEN RETURN NULL; END IF;
    RETURN m[1]::date;
EXCEPTION WHEN others THEN RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION pg_temp.vp_l3_text(v jsonb, n integer) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN jsonb_typeof(v) IN ('string', 'number') THEN left(nullif(btrim(v #>> '{}'), ''), n) END
$$;

CREATE OR REPLACE FUNCTION pg_temp.vp_l3_last4(v jsonb) RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN jsonb_typeof(v) IN ('string', 'number') AND btrim(v #>> '{}') ~ '^[0-9]{4}$'
                THEN btrim(v #>> '{}') END
$$;
"""

# `order` del pago: arriba en `GET /payments`, dentro de `payment` en el detalle.
_ORDER = "(CASE WHEN jsonb_typeof(t.raw_payload->'order') = 'object' THEN t.raw_payload->'order' " \
         "ELSE t.raw_payload->'payment'->'order' END)"
_DEPOSIT = f"(CASE WHEN jsonb_typeof({_ORDER}->'deposits') = 'array' THEN {_ORDER}->'deposits'->0 END)"

_SUBSCRIPTION_SET = """
    card_type = pg_temp.vp_l3_text(t.raw_payload->'payment_method'->'card_type', 20),
    card_brand = pg_temp.vp_l3_text(t.raw_payload->'payment_method'->'brand', 50),
    card_last4 = pg_temp.vp_l3_last4(t.raw_payload->'payment_method'->'last4CardDigit'),
    terminal_pos = pg_temp.vp_l3_text(t.raw_payload->'terminal_pos', 255),
    origin = pg_temp.vp_l3_text(t.raw_payload->'origin', 100)
"""

_PAYMENT_SET = f"""
    client_social_id = pg_temp.vp_l3_text(t.raw_payload->'client'->'social_id', 50),
    authorized_at = pg_temp.vp_l3_timestamp({_ORDER}->>'authorized_at'),
    processing_fee = pg_temp.vp_l3_numeric({_DEPOSIT}->>'processing_fee'),
    payout_amount = pg_temp.vp_l3_numeric({_DEPOSIT}->>'payout_amount'),
    payout_date = pg_temp.vp_l3_date({_DEPOSIT}->>'payout_date')
"""

_CORE_SUBSCRIPTION_UPDATE = """
    UPDATE core_subscriptions cs SET
        card_last4 = coalesce(vs.card_last4, rs.card_last4),
        card_last4_source = CASE WHEN vs.card_last4 IS NOT NULL THEN 'api'
                                 WHEN rs.card_last4 IS NOT NULL THEN 'report' END,
        rejection_reason = nullif(btrim(rs.rejection_reason), '')
    FROM vp_subscriptions vs
    LEFT JOIN vp_report_subscriptions rs
           ON rs.platform_status = 'resolved' AND rs.platform = vs.platform
          AND rs.subscription_external_id = vs.external_id
    WHERE cs.source = vs.platform AND cs.external_id = vs.external_id AND cs.id = ANY(:ids)
"""


def _batched_ids(conn, table: str, where: str):
    last = None
    while True:
        params = {"n": BATCH}
        keyset = ""
        if last is not None:
            keyset = "AND id > :last"
            params["last"] = last
        ids = conn.execute(sa.text(f"SELECT id FROM {table} WHERE {where} {keyset} ORDER BY id LIMIT :n"), params).scalars().all()
        if not ids:
            return
        yield ids
        last = ids[-1]


def _backfill(conn, table: str, set_sql: str, where: str = "raw_payload IS NOT NULL") -> int:
    total = 0
    for ids in _batched_ids(conn, table, where):
        total += conn.execute(sa.text(f"UPDATE {table} t SET {set_sql} WHERE t.id = ANY(:ids)"), {"ids": ids}).rowcount or 0
    return total


def _log_counts(conn, table: str, columns: tuple[str, ...]) -> None:
    filled = ", ".join(f"count({c})" for c in columns)
    row = conn.execute(sa.text(f"SELECT count(*), {filled} FROM {table}")).one()
    detail = ", ".join(f"{c}={v}" for c, v in zip(columns, row[1:], strict=True))
    log.info("0060 %s: %d filas; con valor: %s", table, row[0], detail)


def _log_unconvertible_payments(conn) -> None:
    """Pagos cuyo texto venia informado pero no se pudo convertir (quedan NULL)."""
    row = conn.execute(sa.text(f"""
        SELECT
          count(*) FILTER (WHERE coalesce(btrim({_ORDER}->>'authorized_at'), '') <> '' AND authorized_at IS NULL),
          count(*) FILTER (WHERE coalesce(btrim({_DEPOSIT}->>'processing_fee'), '') <> '' AND processing_fee IS NULL),
          count(*) FILTER (WHERE coalesce(btrim({_DEPOSIT}->>'payout_amount'), '') <> '' AND payout_amount IS NULL),
          count(*) FILTER (WHERE coalesce(btrim({_DEPOSIT}->>'payout_date'), '') <> '' AND payout_date IS NULL)
        FROM vp_payments t
    """)).one()
    log.info("0060 vp_payments no convertibles (quedan NULL): authorized_at=%d, processing_fee=%d, payout_amount=%d, "
             "payout_date=%d", *row)


def upgrade() -> None:
    op.add_column("vp_subscriptions", sa.Column("card_type", sa.String(20), nullable=True))
    op.add_column("vp_subscriptions", sa.Column("card_brand", sa.String(50), nullable=True))
    op.add_column("vp_subscriptions", sa.Column("card_last4", sa.String(4), nullable=True))
    op.add_column("vp_subscriptions", sa.Column("terminal_pos", sa.String(255), nullable=True))
    op.add_column("vp_subscriptions", sa.Column("origin", sa.String(100), nullable=True))
    op.create_check_constraint("ck_vp_subscriptions_card_last4", "vp_subscriptions",
                               "card_last4 IS NULL OR card_last4 ~ '^[0-9]{4}$'")

    op.add_column("vp_payments", sa.Column("client_social_id", sa.String(50), nullable=True))
    op.add_column("vp_payments", sa.Column("authorized_at", sa.DateTime(), nullable=True))
    op.add_column("vp_payments", sa.Column("processing_fee", sa.Numeric(), nullable=True))
    op.add_column("vp_payments", sa.Column("payout_amount", sa.Numeric(), nullable=True))
    op.add_column("vp_payments", sa.Column("payout_date", sa.Date(), nullable=True))
    op.create_index("ix_vp_payments_client_social_id", "vp_payments", ["client_social_id"])

    op.add_column("core_subscriptions", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.add_column("core_subscriptions", sa.Column("card_last4", sa.String(4), nullable=True))
    op.add_column("core_subscriptions", sa.Column("card_last4_source", sa.String(10), nullable=True))
    op.create_check_constraint("ck_core_subscriptions_card_last4", "core_subscriptions",
                               "card_last4 IS NULL OR card_last4 ~ '^[0-9]{4}$'")
    op.create_check_constraint("ck_core_subscriptions_card_last4_source", "core_subscriptions",
                               "card_last4_source IS NULL OR card_last4_source IN ('api', 'report')")

    conn = op.get_bind()
    conn.exec_driver_sql(_FUNCTIONS)
    subs = _backfill(conn, "vp_subscriptions", _SUBSCRIPTION_SET)
    pays = _backfill(conn, "vp_payments", _PAYMENT_SET)
    core = 0
    for ids in _batched_ids(conn, "core_subscriptions", "source IN ('virtualpos1', 'virtualpos2')"):
        core += conn.execute(sa.text(_CORE_SUBSCRIPTION_UPDATE), {"ids": ids}).rowcount or 0
    log.info("0060 backfill: vp_subscriptions=%d, vp_payments=%d, core_subscriptions=%d filas revisadas", subs, pays, core)
    _log_counts(conn, "vp_subscriptions", ("card_type", "card_brand", "card_last4", "terminal_pos", "origin"))
    _log_counts(conn, "vp_payments", ("client_social_id", "authorized_at", "processing_fee", "payout_amount", "payout_date"))
    _log_counts(conn, "core_subscriptions", ("rejection_reason", "card_last4", "card_last4_source"))
    _log_unconvertible_payments(conn)


def downgrade() -> None:
    op.drop_constraint("ck_core_subscriptions_card_last4_source", "core_subscriptions", type_="check")
    op.drop_constraint("ck_core_subscriptions_card_last4", "core_subscriptions", type_="check")
    op.drop_column("core_subscriptions", "card_last4_source")
    op.drop_column("core_subscriptions", "card_last4")
    op.drop_column("core_subscriptions", "rejection_reason")

    op.drop_index("ix_vp_payments_client_social_id", table_name="vp_payments")
    for column in ("payout_date", "payout_amount", "processing_fee", "authorized_at", "client_social_id"):
        op.drop_column("vp_payments", column)

    op.drop_constraint("ck_vp_subscriptions_card_last4", "vp_subscriptions", type_="check")
    for column in ("origin", "terminal_pos", "card_last4", "card_brand", "card_type"):
        op.drop_column("vp_subscriptions", column)
