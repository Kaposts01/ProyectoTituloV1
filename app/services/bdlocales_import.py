"""Read-only import from the legacy local databases into central channel tables."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import psycopg
import psycopg.rows
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.channel_store import (
    store_payku_resources,
    store_toku_resources,
    store_vp_resources,
)
from app.services.payload_sanitization import sanitize_payload


@dataclass
class ImportSummary:
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))


_TABLES: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "virtualpos": (settings.virtualpos_db_url, (("cliente", "client"), ("plan", "plan"), ("subscripcion", "subscription"), ("cargos", "charge"), ("transacciones", "payment"))),
    "toku": (settings.toku_db_url, (("customer", "customer"), ("subscription", "subscription"), ("invoices", "invoice"), ("payment", "transaction"), ("payment_method", "payment_method"))),
    "payku": (settings.payku_db_url, (("cliente", "client"), ("plan", "plan"), ("subscripcion", "subscription"), ("transaccion", "transaction"))),
}


def _read_rows(dsn: str, table: str, batch_size: int):
    query = f"SELECT platform, remote_id, raw_payload FROM {table} ORDER BY platform NULLS FIRST, remote_id" if table in {"cliente", "plan", "subscripcion", "cargos", "transacciones"} and dsn == settings.virtualpos_db_url else f"SELECT remote_id, raw_payload FROM {table} ORDER BY remote_id"
    with (
        psycopg.connect(dsn.replace("postgresql+psycopg://", "postgresql://"), row_factory=psycopg.rows.dict_row) as conn,
        conn.cursor() as cursor,
    ):
        cursor.execute(query)
        while rows := cursor.fetchmany(batch_size):
            yield rows


def import_bdlocales(db: Session, sources: Sequence[str] | None = None, batch_size: int = 1000) -> ImportSummary:
    """Import all selected legacy tables without changing the source databases."""
    summary = ImportSummary()
    for source in sources or tuple(_TABLES):
        dsn, tables = _TABLES[source]
        if not dsn:
            raise RuntimeError(f"Missing local database URL for {source}.")
        for table, resource_type in tables:
            for rows in _read_rows(dsn, table, batch_size):
                if source == "virtualpos":
                    by_platform: dict[str, list[dict]] = defaultdict(list)
                    for row in rows:
                        platform = str(row["platform"] or "").lower()
                        if platform not in {"virtualpos1", "virtualpos2"}:
                            raise RuntimeError(f"Invalid VirtualPOS platform in {table}.")
                        payload = sanitize_payload(row["raw_payload"])
                        payload["__external_id"] = str(row["remote_id"]) if row["remote_id"] else hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
                        by_platform[platform].append(payload)
                    for platform, payloads in by_platform.items():
                        summary.counts[f"{source}.{table}.{platform}"] += store_vp_resources(db, resource_type, payloads, platform=platform)
                else:
                    payloads = []
                    for row in rows:
                        payload = sanitize_payload(row["raw_payload"])
                        payload["__external_id"] = str(row["remote_id"]) if row["remote_id"] else hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
                        payloads.append(payload)
                    store: Callable[[Session, str, list[dict]], int] = store_toku_resources if source == "toku" else store_payku_resources
                    summary.counts[f"{source}.{table}"] += store(db, resource_type, payloads)
    return summary
