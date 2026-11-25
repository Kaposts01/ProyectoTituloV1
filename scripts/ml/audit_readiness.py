"""Read-only QA readiness audit. Exports aggregates, never examples or training rows.

Supply ML_AUDIT_DATABASE_URL privately; no app startup, dotenv loading or migrations.
Run as a module: python -m scripts.ml.audit_readiness --help.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.services.payku_rejection_codes import payku_rejection_category
from app.services.toku_rejection_codes import (
    lookup_toku_code,
    normalize_processor_message,
)
from app.services.vp_rejection_codes import VP_REJECTION_LABELS

SOURCES = ("virtualpos1", "virtualpos2", "toku", "payku", "tch")
INVENTORY = ("source_records", "charges", "payments", "vp_charges", "vp_payments", "vp_report_payments",
             "tk_transactions", "tk_report_attempts", "p_transactions", "p_report_transactions", "tch_transacciones",
             "core_charges", "core_payments", "payment_rejection_details", "rejection_reason_catalog", "charge_recoveries", "status_change_events")
SOURCE = "CASE WHEN source IN ('virtualpos1','virtualpos2','toku','payku','tch','virtualpos') THEN source ELSE 'other' END"
PAID = "('pagado','pago','aceptado','aceptada','accepted','paid','success','aprobado','aprobada','cobrado','cobrada')"
REJECTED = "('rechazado','rejected','failed','failure','declined','error','rechazada')"

QUERIES = {
    "vp_charge_coverage": f"""SELECT CASE WHEN platform IN ('virtualpos1','virtualpos2') THEN platform ELSE 'other' END AS source,
        count(*) AS rows, count(*) FILTER (WHERE lower(status) IN {REJECTED}) AS rejected_rows,
        count(*) FILTER (WHERE lower(status) IN {PAID}) AS paid_rows,
        count(*) FILTER (WHERE charge_date IS NOT NULL) AS with_scheduled_date,
        count(*) FILTER (WHERE nullif(trim(raw_payload->'rejected_object'->>'code'),'') IS NOT NULL) AS with_top_rejection_code,
        min(charge_date) AS earliest_scheduled_date, max(charge_date) AS latest_scheduled_date
        FROM vp_charges GROUP BY 1 ORDER BY 1""",
    "vp_payment_coverage": f"""SELECT CASE WHEN platform IN ('virtualpos1','virtualpos2') THEN platform ELSE 'other' END AS source,
        count(*) AS rows, count(*) FILTER (WHERE lower(status) IN {REJECTED}) AS rejected_rows,
        count(*) FILTER (WHERE lower(status) IN {PAID}) AS paid_rows,
        count(*) FILTER (WHERE charge_external_id IS NOT NULL) AS linked_to_charge,
        count(*) FILTER (WHERE nullif(trim(raw_payload->'rejected_object'->>'code'),'') IS NOT NULL) AS with_top_rejection_code
        FROM vp_payments GROUP BY 1 ORDER BY 1""",
    "rejection_details": f"""SELECT {SOURCE} AS source, count(*) AS rows,
        count(*) FILTER (WHERE nullif(trim(code),'') IS NOT NULL) AS with_code,
        count(*) FILTER (WHERE nullif(trim(reason),'') IS NOT NULL) AS with_reason,
        count(*) FILTER (WHERE rejected_at IS NOT NULL) AS with_rejection_time,
        count(*) FILTER (WHERE charge_external_id IS NOT NULL) AS with_charge,
        count(*) FILTER (WHERE payment_external_id IS NOT NULL) AS with_payment,
        count(*) FILTER (WHERE rejected_at <= %(as_of)s - interval '30 days') AS nominally_mature,
        min(rejected_at) AS earliest_rejection, max(rejected_at) AS latest_rejection,
        max(captured_at) AS latest_capture FROM payment_rejection_details GROUP BY 1 ORDER BY 1""",
    "core_charges": f"""SELECT {SOURCE} AS source, count(*) AS rows,
        count(*) FILTER (WHERE latest_rejection_at IS NOT NULL) AS with_rejection_time,
        count(*) FILTER (WHERE nullif(trim(latest_rejection_reason),'') IS NOT NULL) AS with_reason,
        count(*) FILTER (WHERE latest_rejection_at <= %(as_of)s - interval '30 days') AS nominally_mature,
        min(latest_rejection_at) AS earliest_rejection, max(latest_rejection_at) AS latest_rejection,
        max(updated_at) AS latest_projection FROM core_charges GROUP BY 1 ORDER BY 1""",
    "core_payments": f"""SELECT {SOURCE} AS source, count(*) AS rows,
        count(*) FILTER (WHERE charge_id IS NOT NULL) AS linked_to_charge,
        count(*) FILTER (WHERE lower(source_status) IN {PAID}) AS paid_rows,
        count(*) FILTER (WHERE lower(source_status) IN {REJECTED}) AS rejected_rows,
        count(*) FILTER (WHERE occurred_at IS NULL) AS missing_event_time,
        count(*) FILTER (WHERE occurred_at > %(as_of)s) AS future_event_time,
        count(*) FILTER (WHERE nullif(trim(rejection_reason),'') IS NOT NULL) AS with_reason,
        min(occurred_at) AS earliest_event, max(occurred_at) FILTER (WHERE occurred_at <= %(as_of)s) AS latest_nonfuture_event,
        max(updated_at) AS latest_projection FROM core_payments GROUP BY 1 ORDER BY 1""",
    "linked_payment_candidates": f"""SELECT c.source, count(*) AS charges_with_rejection_time,
        count(*) FILTER (WHERE EXISTS (SELECT 1 FROM core_payments p WHERE p.charge_id=c.id AND p.source=c.source
          AND lower(p.source_status) IN {PAID} AND p.occurred_at>=c.latest_rejection_at
          AND p.occurred_at<=least(c.latest_rejection_at+interval '30 days',%(as_of)s))) AS paid_within_30d_candidates,
        count(*) FILTER (WHERE c.latest_rejection_at<=%(as_of)s-interval '30 days') AS nominally_mature
        FROM core_charges c WHERE c.source IN ('virtualpos1','virtualpos2','toku','payku','tch')
        AND c.latest_rejection_at IS NOT NULL GROUP BY c.source ORDER BY c.source""",
    "recoveries": f"""SELECT {SOURCE} AS source, count(*) AS rows,
        count(*) FILTER (WHERE status='cobrado') AS observed_paid,
        count(*) FILTER (WHERE status='no_cobrado') AS observed_unpaid,
        min(extract(epoch FROM closes_at-requested_at)/86400) AS min_horizon_days,
        max(extract(epoch FROM closes_at-requested_at)/86400) AS max_horizon_days,
        min(requested_at) AS earliest_request, max(observed_at) AS latest_observation
        FROM charge_recoveries GROUP BY 1 ORDER BY 1""",
    "status_history": f"""SELECT {SOURCE} AS source, count(*) AS rows,
        count(*) FILTER (WHERE NOT is_baseline) AS nonbaseline_rows,
        count(*) FILTER (WHERE NOT is_baseline AND provider_event_at IS NOT NULL) AS nonbaseline_with_provider_time,
        count(*) FILTER (WHERE NOT is_baseline AND entity_type IN ('charge','payment') AND field='status'
          AND lower(to_value) IN {PAID}) AS paid_status_changes,
        min(detected_at) FILTER (WHERE NOT is_baseline) AS earliest_nonbaseline_detection,
        max(detected_at) AS latest_detection FROM status_change_events GROUP BY 1 ORDER BY 1""",
    "sync_coverage": f"""SELECT {SOURCE} AS source, count(*) AS runs,
        count(*) FILTER (WHERE status IN ('success','completed')) AS successful_runs,
        max(finished_at) FILTER (WHERE status IN ('success','completed')) AS latest_success,
        max(finished_at) AS latest_finished FROM sync_runs GROUP BY 1 ORDER BY 1""",
    "toku_failed": """SELECT count(*) AS rows,
        count(*) FILTER (WHERE nullif(trim(raw_payload->'transaction'->>'response_code'),'') IS NOT NULL) AS with_code,
        count(*) FILTER (WHERE nullif(trim(raw_payload->'transaction'->>'original_response_message'),'') IS NOT NULL) AS with_message,
        count(DISTINCT raw_payload->'transaction'->>'original_response_message') AS distinct_raw_messages,
        count(*) FILTER (WHERE nullif(trim(raw_payload->'transaction'->>'transaction_date'),'') IS NOT NULL) AS with_reported_time
        FROM tk_transactions WHERE upper(status)='FAILED'""",
    "tch_quota_evidence": """SELECT count(*) AS rows,
        count(*) FILTER (WHERE upper(estado) LIKE 'RECHAZ%') AS rejected_rows,
        count(*) FILTER (WHERE upper(estado) LIKE 'ACEPT%') AS accepted_rows,
        count(*) FILTER (WHERE upper(estado) LIKE 'RECHAZ%' AND nullif(trim(razon_rechazo),'') IS NOT NULL) AS rejected_with_reason,
        count(*) FILTER (WHERE upper(estado) LIKE 'RECHAZ%' AND fecha_cargo ~ '^\\d{4}-\\d{2}-\\d{2}') AS rejected_with_iso_shaped_date,
        count(*) FILTER (WHERE upper(estado) LIKE 'RECHAZ%' AND nullif(trim(razon_rechazo),'') IS NOT NULL AND fecha_cargo ~ '^\\d{4}-\\d{2}-\\d{2}') AS rejected_with_reason_and_iso_shaped_date,
        count(*) FILTER (WHERE fecha_cargo ~ '^\\d{4}-\\d{2}-\\d{2}') AS iso_shaped_charge_date,
        min(fecha_cargo) FILTER (WHERE fecha_cargo ~ '^\\d{4}-\\d{2}-\\d{2}') AS earliest_iso_shaped_charge_date,
        max(fecha_cargo) FILTER (WHERE fecha_cargo ~ '^\\d{4}-\\d{2}-\\d{2}') AS latest_iso_shaped_charge_date,
        count(*) FILTER (WHERE origen='cargo') AS charge_origin,
        count(*) FILTER (WHERE origen='historial') AS history_origin,
        count(*) FILTER (WHERE nullif(trim(razon_rechazo),'') IS NOT NULL) AS with_reason,
        count(*) FILTER (WHERE rechazo_previo IS TRUE) AS previous_rejection,
        count(*) FILTER (WHERE rechazo_previo IS TRUE AND nullif(trim(rechazo_previo_en),'') IS NOT NULL) AS previous_rejection_dated,
        min(reporte_periodo) AS earliest_report_period, max(reporte_periodo) AS latest_report_period
        FROM tch_transacciones""",
    "tch_reason_aggregates": """SELECT count(*) AS grouped_rows, count(DISTINCT motivo) AS distinct_motives,
        min(reporte_periodo) AS earliest_report_period, max(reporte_periodo) AS latest_report_period FROM tch_rechazos_motivo""",
}


def parse_cutoff(value: str) -> datetime:
    cutoff = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if cutoff.tzinfo is None:
        raise ValueError("El corte requiere zona horaria.")
    if cutoff > datetime.now(UTC):
        raise ValueError("El corte no puede estar en el futuro.")
    return cutoff.astimezone(UTC)


def connection_args(raw_url: str, expected_database: str) -> dict:
    """An explicit local QA target is mandatory; URL query options cannot override safety settings."""
    try:
        url = make_url(raw_url)
    except (ArgumentError, ValueError):
        raise ValueError("URL QA invalida; no se muestra su contenido.") from None
    if not re.fullmatch(r"crm_qa_[a-z0-9_]+", expected_database):
        raise ValueError("Solo se permite una base QA identificada explicitamente.")
    if url.database != expected_database or url.host not in {"127.0.0.1", "localhost", "::1"} or url.port != 5433:
        raise ValueError("El destino no coincide con la copia QA local autorizada.")
    if url.get_backend_name() != "postgresql" or url.query:
        raise ValueError("URL PostgreSQL sin opciones adicionales requerida.")
    return {"host": url.host, "port": url.port, "dbname": url.database, "user": url.username, "password": url.password,
        "connect_timeout": 5, "application_name": "synkmetrix_ml_readiness_audit",
        "options": "-c default_transaction_read_only=on -c statement_timeout=60000 -c lock_timeout=3000 -c search_path=pg_catalog,public",
        "row_factory": dict_row}


def validate_session(metadata: dict, expected_database: str) -> None:
    if metadata["database"] != expected_database or metadata["read_only"] != "on" or metadata["isolation"] != "repeatable read":
        raise ValueError("La transaccion no cumple las guardas de auditoria.")


def summarize_texts(rows) -> list[dict]:
    """Inspect text only in memory. No text, code, IDs, hashes or individual examples leave this function."""
    totals = defaultdict(Counter)
    normalized = defaultdict(set)
    pii_pattern = re.compile(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}|\b\d{1,2}\.\d{3}\.\d{3}-[\dkK]\b", re.I)
    for row in rows:
        source, code, reason = row["source"], str(row["code"] or "").strip(), str(row["reason"] or "").strip()
        source = source if source in SOURCES else "other"
        count = int(row["n"])
        totals[source]["rows"] += count
        parsed = normalize_processor_message(reason)
        if parsed:
            normalized[source].add((code, parsed.processor_code, parsed.text.casefold()))
        known = code in VP_REJECTION_LABELS if source.startswith("virtualpos") else bool(lookup_toku_code(code)) if source == "toku" else bool(payku_rejection_category(reason)) if source == "payku" else False
        totals[source]["catalogue_recognized_rows"] += count if known else 0
        totals[source]["nonempty_text_rows"] += count if reason else 0
        totals[source]["suspected_pii_text_rows"] += count if pii_pattern.search(reason) else 0
    return [{"source": source, **totals[source], "normalized_code_text_pairs": len(normalized[source])} for source in sorted(totals)]


def run_audit(raw_url: str, expected_database: str, cutoff: datetime) -> dict:
    kwargs = connection_args(raw_url, expected_database)
    with psycopg.connect(**kwargs) as connection:
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        connection.read_only = True
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database() AS database, current_setting('transaction_read_only') AS read_only, current_setting('transaction_isolation') AS isolation, version_num AS revision FROM alembic_version")
            metadata = cursor.fetchone()
            validate_session(metadata, expected_database)
            sections = {}
            inventory = []
            for table in INVENTORY:
                cursor.execute(sql.SQL("SELECT count(*) AS rows FROM {}").format(sql.Identifier("public", table)))
                inventory.append({"table": table, "rows": cursor.fetchone()["rows"]})
            sections["exact_inventory"] = inventory
            for name, query in QUERIES.items():
                cursor.execute(query, {"as_of": cutoff} if "%(as_of)s" in query else None)
                sections[name] = cursor.fetchall()
            cursor.execute(f"SELECT {SOURCE} AS source, code, reason, count(*) AS n FROM payment_rejection_details GROUP BY 1,code,reason")
            sections["rejection_text_coverage"] = summarize_texts(cursor)
            cursor.execute("SELECT 'toku' AS source, raw_payload->'transaction'->>'response_code' AS code, raw_payload->'transaction'->>'original_response_message' AS reason, count(*) AS n FROM tk_transactions WHERE upper(status)='FAILED' GROUP BY 1,2,3")
            sections["toku_text_coverage"] = summarize_texts(cursor)
            cursor.execute("SELECT 'tch' AS source, codigo_respuesta AS code, razon_rechazo AS reason, count(*) AS n FROM tch_transacciones WHERE nullif(trim(razon_rechazo),'') IS NOT NULL GROUP BY 1,2,3")
            sections["tch_text_coverage"] = summarize_texts(cursor)
        connection.rollback()
    return {"audit_version": 1, "tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "generated_at": datetime.now(UTC).isoformat(), "as_of": cutoff.isoformat(),
        "session": metadata, "aggregates": sections,
        "limits": ["QA copy, not a fresh measurement of production", "Candidate joins are not validated recovery labels",
                   "Text PII heuristic is incomplete; no anonymization certification", "No training, benchmark or provider calls"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_audit(os.environ["ML_AUDIT_DATABASE_URL"], args.expected_database, parse_cutoff(args.as_of))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    except (psycopg.Error, ValueError, KeyError, OSError) as exc:
        # DB exceptions can contain SQL fragments or values: never echo them or credentials.
        print(f"Auditoria detenida ({type(exc).__name__}); sin informe completo nuevo.")
        return 1
    print("Auditoria QA completa: agregados guardados; transaccion de solo lectura revertida.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
