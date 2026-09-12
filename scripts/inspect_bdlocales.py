"""Inspecciona las 3 BDlocales y reporta tablas, conteos y columnas.

Uso: python scripts/inspect_bdlocales.py
Requiere que los 3 contenedores Docker estén corriendo.
"""

import sys

import psycopg
import psycopg.rows

from app.core.config import settings

DATABASES = {
    "VirtualPOS": settings.virtualpos_db_url,
    "Payku": settings.payku_db_url,
    "Toku": settings.toku_db_url,
}

SAMPLE_QUERY = """
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = %s
ORDER BY ordinal_position
"""

TABLE_LIST_QUERY = """
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
ORDER BY table_name
"""


def inspect(label: str, dsn: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'═' * 60}")

    if not dsn:
        print("  Sin URL configurada en .env")
        return
    try:
        dsn = dsn.replace("postgresql+psycopg://", "postgresql://")
        with psycopg.connect(dsn, row_factory=psycopg.rows.dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(TABLE_LIST_QUERY)
                tables = [r["table_name"] for r in cur.fetchall()]

            if not tables:
                print("  (sin tablas)")
                return

            for table in tables:
                if table.endswith("_ordenado"):
                    continue  # saltar vistas ordenadas

                with conn.cursor() as cur:
                    cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
                    count = cur.fetchone()["n"]

                with conn.cursor() as cur:
                    cur.execute(SAMPLE_QUERY, (table,))
                    cols = [f"{r['column_name']} ({r['data_type']})" for r in cur.fetchall()]

                print(f"\n  Tabla: {table}  [{count} filas]")
                print(f"  Columnas: {', '.join(cols)}")

                if count > 0:
                    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                        cur.execute(f"SELECT raw_payload FROM {table} LIMIT 1")
                        sample = cur.fetchone()
                    if sample and sample.get("raw_payload"):
                        keys = list(sample["raw_payload"].keys())[:10]
                        print(f"  raw_payload keys: {keys}")

    except psycopg.OperationalError as exc:
        print(f"  ERROR de conexión: {exc}", file=sys.stderr)


def main() -> None:
    for label, dsn in DATABASES.items():
        inspect(label, dsn)
    print("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    main()
