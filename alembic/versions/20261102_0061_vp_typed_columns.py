"""vp_typed_columns: montos y fechas de `vp_*` de texto a tipos numericos y de fecha (VP-PAR-13, GAP-VP-01).

`ALTER TABLE ... ALTER COLUMN ... TYPE ... USING` sobre:

* `amount` de `vp_plans`, `vp_subscriptions`, `vp_charges`, `vp_payments`: `varchar(50)` -> `numeric` (sin escala
  fija: CLP enteros y UF con decimales; nada se redondea).
* `vp_subscriptions.suscription_date`, `vp_subscriptions.canceled_at`, `vp_payments.payment_date`: -> `timestamp`
  SIN zona. Es la hora de pared que entrega VirtualPOS (`yyyy-mm-dd hh:mm:ss`); un sufijo de zona se ignora. Pasar a
  `timestamptz` exige decidir en que zona informa el proveedor (decision de negocio pendiente).
* `vp_charges.charge_date`: -> `date` (`yyyy-mm-dd`; la hora del respaldo `order.created_at` se descarta).

`vp_clients` queda en texto (`birth_date` es dato personal y `provider_created_at` no lo usa ningun KPI).

Datos sucios: ninguna fila se borra. Un valor que no se puede convertir (texto vacio, `"12a"`, `"2026-02-30"`,
`"pronto"`) queda NULL; antes del cambio se cuenta por columna en el log (`alembic.vp_l3`). El valor original sigue en
`raw_payload`. Misma regla que `app/services/vp_typed_fields.py`.

Duracion y bloqueo: cada `ALTER TYPE` reescribe la tabla completa y sus indices con bloqueo `ACCESS EXCLUSIVE` (no se
puede hacer por lotes). En `crm`, `vp_charges` (~230 mil filas, programacion hasta 2031) y `vp_payments` (~73 mil)
dominan: se espera del orden de 2 a 10 minutos en total, segun el disco. Durante ese tiempo las lecturas y la sync
VP quedan bloqueadas: aplicarla con la sync detenida, en una ventana sin uso, y SIEMPRE con un respaldo previo
(`pg_dump -Fc` de la base). La aplica el usuario (ningun agente corre Alembic contra `crm` ni `crm_sandbox`).

Reversible: el downgrade vuelve a `varchar(50)` con el texto canonico (`15000`, `2026-10-05`,
`2021-09-08 11:20:31`; la medianoche exacta vuelve como `yyyy-mm-dd`). Los valores que la subida dejo en NULL no se
recuperan con el downgrade (siguen en `raw_payload`).

Revision ID: 20261102_0061
Revises: 20261102_0060
Create Date: 2026-11-02 18:30:00
"""

import logging

import sqlalchemy as sa

from alembic import op

revision = "20261102_0061"
down_revision = "20261102_0060"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.vp_l3")

# Funciones temporales de la sesion (no quedan en el esquema); version SQL de app/services/vp_typed_fields.py.
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
"""

# (tabla, columna, tipo nuevo, funcion de conversion)
COLUMNS: tuple[tuple[str, str, str, str], ...] = (
    ("vp_plans", "amount", "numeric", "vp_l3_numeric"),
    ("vp_subscriptions", "amount", "numeric", "vp_l3_numeric"),
    ("vp_subscriptions", "suscription_date", "timestamp without time zone", "vp_l3_timestamp"),
    ("vp_subscriptions", "canceled_at", "timestamp without time zone", "vp_l3_timestamp"),
    ("vp_charges", "amount", "numeric", "vp_l3_numeric"),
    ("vp_charges", "charge_date", "date", "vp_l3_date"),
    ("vp_payments", "amount", "numeric", "vp_l3_numeric"),
    ("vp_payments", "payment_date", "timestamp without time zone", "vp_l3_timestamp"),
)


def _legacy_text(column: str, new_type: str) -> str:
    """Texto canonico al bajar (igual que `vp_typed_fields.as_legacy_text`)."""
    if new_type == "numeric":
        # trim_scale: 15000.00 -> 15000 (los montos que llegaron como texto no traian ceros de mas).
        return f"trim_scale({column})::text"
    if new_type == "date":
        return f"to_char({column}, 'YYYY-MM-DD')"
    return (f"CASE WHEN {column} = date_trunc('day', {column}) THEN to_char({column}, 'YYYY-MM-DD') "
            f"ELSE to_char({column}, 'YYYY-MM-DD HH24:MI:SS') || CASE WHEN date_trunc('second', {column}) <> {column} "
            f"THEN to_char({column}, '.US') ELSE '' END END")


def upgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql(_FUNCTIONS)
    total_lost = 0
    for table, column, _new_type, fn in COLUMNS:
        rows, informed, lost = conn.execute(sa.text(f"""
            SELECT count(*),
                   count(*) FILTER (WHERE btrim(coalesce({column}, '')) <> ''),
                   count(*) FILTER (WHERE btrim(coalesce({column}, '')) <> '' AND pg_temp.{fn}({column}) IS NULL)
            FROM {table}
        """)).one()
        total_lost += lost
        log.info("0061 %s.%s: %d filas, %d informadas, %d no convertibles (quedan NULL)", table, column, rows, informed, lost)
    for table, column, new_type, fn in COLUMNS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {new_type} USING pg_temp.{fn}({column})")
    log.info("0061 total de valores no convertibles que quedaron NULL: %d", total_lost)


def downgrade() -> None:
    conn = op.get_bind()
    for table, column, new_type, _fn in reversed(COLUMNS):
        conn.exec_driver_sql(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE varchar(50) USING {_legacy_text(column, new_type)}")
