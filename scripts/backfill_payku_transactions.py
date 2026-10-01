"""Materializa transacciones Payku históricas ya preservadas en staging.

No consulta al proveedor: reconstruye ``p_transactions`` a partir de
``source_records`` y permite ejecutar luego el ETL normal de Payku.
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.models.source_record import SourceRecord
from app.services.channel_store import store_payku_resources

_BATCH_SIZE = 500


def main() -> None:
    db = SessionLocal()
    try:
        records = db.scalars(
            select(SourceRecord)
            .where(SourceRecord.source == "payku", SourceRecord.resource_type == "transaction")
            .order_by(SourceRecord.id)
        ).yield_per(_BATCH_SIZE)
        batch: list[dict] = []
        materialized = 0
        for record in records:
            batch.append(record.payload)
            if len(batch) == _BATCH_SIZE:
                materialized += store_payku_resources(db, "transaction", batch)
                batch.clear()
        if batch:
            materialized += store_payku_resources(db, "transaction", batch)
        db.commit()
        print(f"Payku: {materialized} transacciones materializadas en p_transactions.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
