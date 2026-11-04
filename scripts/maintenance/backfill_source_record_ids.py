"""Vincula filas centralizadas existentes con su ``source_records`` (SYNC-GAP-03).

Por defecto es --dry-run: solo cuenta las filas que se vincularian. Solo
``--apply`` escribe. Nunca sobrescribe un vinculo existente ni viola la
restriccion UNIQUE de ``source_record_id``. No imprime datos personales.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.db.session import SessionLocal

# (tabla centralizada, source, resource_type en source_records)
_TARGETS: list[tuple[str, str, str]] = [
    *[("clients", s, "client") for s in ("virtualpos1", "virtualpos2", "payku", "tch")],
    ("clients", "toku", "customer"),
    *[("plans", s, "plan") for s in ("virtualpos1", "virtualpos2", "payku")],
    *[("subscriptions", s, "subscription") for s in ("virtualpos1", "virtualpos2", "toku", "payku", "tch")],
    *[("charges", s, "charge") for s in ("virtualpos1", "virtualpos2")],
    ("charges", "toku", "invoice"),
    ("charges", "tch", "transaction"),
    *[("payments", s, "payment") for s in ("virtualpos1", "virtualpos2")],
    *[("payments", s, "transaction") for s in ("toku", "payku")],
    ("payment_methods", "toku", "payment_method"),
]

_COND = """
t.source_record_id IS NULL
  AND t.source = :source
  AND sr.source = t.source
  AND sr.resource_type = :resource_type
  AND sr.external_id = t.external_id
  AND NOT EXISTS (SELECT 1 FROM {table} o WHERE o.source_record_id = sr.id)
"""


def run(apply: bool) -> None:
    db = SessionLocal()
    try:
        total = 0
        for table, source, resource_type in _TARGETS:
            params = {"source": source, "resource_type": resource_type}
            cond = _COND.format(table=table)
            if apply:
                sql = f"UPDATE {table} t SET source_record_id = sr.id FROM source_records sr WHERE {cond}"
                count = db.execute(text(sql), params).rowcount
            else:
                sql = f"SELECT count(*) FROM {table} t, source_records sr WHERE {cond}"
                count = db.execute(text(sql), params).scalar_one()
            total += count
            print(f"{table}/{source}/{resource_type}: {count}")
        if apply:
            db.commit()
        else:
            db.rollback()
        mode = "aplicado" if apply else "dry-run (sin escrituras)"
        print(f"Total vinculable: {total} [{mode}]")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="Modo por defecto: no escribe.")
    group.add_argument("--apply", action="store_true", help="Escribe los vinculos.")
    args = parser.parse_args()
    run(apply=args.apply)


if __name__ == "__main__":
    main()
