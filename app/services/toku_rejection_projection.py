"""Proyección de los rechazos de Toku (tk_transactions FAILED) a core_charges.latest_rejection_* (RJ-01)
y a `payments.rejection_*` canónico por intento (TK-PAR-03, `toku_transaction_rejection`).

Fuente: `tk_transactions.raw_payload` ya guarda el ítem completo de `GET /transactions`:
`transaction.response_code` (p. ej. `TEPSP1008`), `transaction.original_response_message` (glosa del
procesador) y `payment_intents[0].id_invoice` (la factura = `core_charges.external_id` de Toku).
No llama a ninguna API.

Reglas
- Por factura se toma el intento FAILED más reciente (por `transaction_date`) que traiga algún dato
  (código o glosa). Los FAILED sin ningún dato se cuentan y se ignoran.
- `latest_rejection_code` = `response_code` tal cual; si falta, el código de 4 dígitos del reporte «Intentos de pago»
  (`tk_report_attempts`, RJ-11 / backfill de TK-PAR-04, ver `ReportAttemptCodes`); si falta, el número ISO de la glosa como `ISO:NN`
  (así no se confunde con un código de Toku). `latest_rejection_reason` = glosa normalizada (sin fecha
  ni hora ni el ISO entre corchetes; ver `toku_rejection_codes`). `latest_rejection_at` = fecha del intento.
- Solo se actualizan cobros que ya existen en `core_charges`; no se crea ninguno. NO se materializan los
  intentos FAILED como `core_payments` (decisión por defecto; los pagos de Toku son los exitosos de
  `tk_payments`, así que ninguna fila existente corresponde a un intento fallido).
- UPDATE explícito por clave primaria, idempotente (solo filas cuyo valor cambia) y sin reemplazar un
  rechazo más reciente ya guardado por uno más antiguo.
- No hace commit: lo hace el llamador (el ETL de Core o el script de mantenimiento).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.core import CoreCharge
from app.models.crm import Payment
from app.models.toku_channel import TokuTransaction
from app.models.toku_report import TkReportAttempt
from app.services.rejected_month import CHILE_TZ
from app.services.toku_rejection_codes import normalize_processor_message

log = logging.getLogger(__name__)

_SOURCE = "toku"
_FAILED = "FAILED"
_REPORT_FAILED = "FALLIDO"


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _rejection_values(
    response_code: str | None, message: str | None, report_code: str | None = None
) -> tuple[str | None, str | None]:
    """(código, motivo) a guardar, o (None, None) si el intento no trae ningún dato.

    Prioridad del código: `response_code` de la API; si falta, el «Código de Respuesta Toku» del reporte de
    Intentos (`report_code`, 4 dígitos, RJ-11); si falta, el ISO de la glosa como `ISO:NN`.
    """
    code = str(response_code).strip().upper() if response_code and str(response_code).strip() else None
    if code is None and report_code and str(report_code).strip():
        code = str(report_code).strip()
    glosa = normalize_processor_message(message)
    if code is None and glosa is not None and glosa.processor_code:
        code = f"ISO:{glosa.processor_code}"
    return code, (glosa.text or None) if glosa is not None else None


@dataclass
class ReportAttemptCodes:
    """Códigos del reporte «Intentos de pago» (`tk_report_attempts`) para completar los FAILED sin código (RJ-11).

    El cruce con `tk_transactions` no está verificado con un encabezado real, así que se prueba en orden:
    1. exacto por id: el «ID» del intento contra el id de la transacción o el del payment intent;
    2. por deuda + día (hora de Chile): «Deuda» = factura del intento (`payment_intents[0].id_invoice`), solo si
       todos los intentos fallidos de esa deuda ese día tienen el MISMO código (si no, es ambiguo y no se usa).
    Solo intentos `FALLIDO` con código y no eliminados.
    """

    by_id: dict[str, str] = field(default_factory=dict)
    by_debt_day: dict[tuple[str, date], str] = field(default_factory=dict)

    def lookup(self, ids: tuple[str | None, ...], invoice: str | None, at: datetime | None) -> tuple[str | None, str | None]:
        """(código, cruce) con cruce `id` o `debt_day`; (None, None) sin coincidencia."""
        for candidate in ids:
            if candidate and candidate in self.by_id:
                return self.by_id[candidate], "id"
        if invoice and at is not None:
            code = self.by_debt_day.get((invoice, at.astimezone(CHILE_TZ).date()))
            if code:
                return code, "debt_day"
        return None, None


def load_report_attempt_codes(db: Session) -> ReportAttemptCodes:
    """Lee `tk_report_attempts`. Si la tabla no existe (migración sin aplicar) devuelve un índice vacío."""
    try:
        with db.begin_nested():
            rows = db.execute(
                select(TkReportAttempt.attempt_external_id, TkReportAttempt.debt_external_id,
                       TkReportAttempt.attempted_at, TkReportAttempt.response_code)
                .where(TkReportAttempt.status == _REPORT_FAILED, TkReportAttempt.response_code.is_not(None),
                       TkReportAttempt.deleted_at_source.is_(None))
            ).all()
    except SQLAlchemyError as exc:
        log.warning("Toku rechazos: tk_report_attempts no disponible (%s); se omite", type(exc).__name__)
        return ReportAttemptCodes()
    index = ReportAttemptCodes()
    per_day: dict[tuple[str, date], set[str]] = {}
    for attempt_id, debt, attempted_at, code in rows:
        index.by_id[str(attempt_id)] = code
        if debt and attempted_at is not None:
            per_day.setdefault((str(debt), attempted_at.astimezone(CHILE_TZ).date()), set()).add(code)
    index.by_debt_day = {key: next(iter(codes)) for key, codes in per_day.items() if len(codes) == 1}
    return index


def project_toku_rejections(db: Session, *, apply: bool = True) -> dict[str, Any]:
    """Calcula (y, con `apply=True`, escribe) el último rechazo por factura en core_charges de Toku.

    Retorna contadores; con `apply=False` no escribe nada (dry-run) y `charges_updated` indica cuántos
    cobros cambiarían.
    """
    payload = TokuTransaction.raw_payload
    rows = db.execute(
        select(
            TokuTransaction.external_id,
            TokuTransaction.created_at_api,
            payload["transaction"]["response_code"].astext,
            payload["transaction"]["original_response_message"].astext,
            payload["transaction"]["transaction_date"].astext,
            payload["payment_intents"][0]["id_invoice"].astext,
            payload["transaction"]["id"].astext,
            payload["payment_intents"][0]["id"].astext,
        ).where(TokuTransaction.status == _FAILED)
    )
    report = load_report_attempt_codes(db)

    stats: dict[str, Any] = {
        "failed_total": 0,
        "failed_without_invoice": 0,
        "failed_without_information": 0,
        "invoices_with_information": 0,
        "invoices_without_core_charge": 0,
        "charges_updated": 0,
        "charges_unchanged": 0,
        "charges_kept_newer": 0,
        "codes_from_report_by_id": 0,
        "codes_from_report_by_debt_day": 0,
        "applied": apply,
    }
    best: dict[str, tuple[tuple[datetime, str], str | None, str | None, datetime | None]] = {}
    floor = datetime.min.replace(tzinfo=UTC)
    for ext_id, created_at_api, response_code, message, tx_date, invoice, tx_id, intent_id in rows:
        stats["failed_total"] += 1
        if not invoice:
            stats["failed_without_invoice"] += 1
            continue
        at = _parse_ts(tx_date) or _parse_ts(created_at_api)
        report_code = None
        if not (response_code and str(response_code).strip()):
            report_code, match = report.lookup((ext_id, tx_id, intent_id), invoice, at)
            if match:
                stats[f"codes_from_report_by_{match}"] += 1
        code, reason = _rejection_values(response_code, message, report_code)
        if code is None and reason is None:
            stats["failed_without_information"] += 1
            continue
        order = (at or floor, str(ext_id))
        prev = best.get(invoice)
        if prev is None or order > prev[0]:
            best[invoice] = (order, code, reason, at)
    stats["invoices_with_information"] = len(best)
    if not best:
        return stats

    current = {
        row.external_id: row
        for row in db.execute(
            select(
                CoreCharge.id, CoreCharge.external_id, CoreCharge.latest_rejection_code,
                CoreCharge.latest_rejection_reason, CoreCharge.latest_rejection_at,
            ).where(CoreCharge.source == _SOURCE, CoreCharge.external_id.in_(list(best)))
        )
    }
    updates: list[dict[str, Any]] = []
    for invoice, (_order, code, reason, at) in best.items():
        row = current.get(invoice)
        if row is None:
            stats["invoices_without_core_charge"] += 1
            continue
        if row.latest_rejection_at is not None and (at is None or at < row.latest_rejection_at):
            stats["charges_kept_newer"] += 1
            continue
        if (row.latest_rejection_code, row.latest_rejection_reason, row.latest_rejection_at) == (code, reason, at):
            stats["charges_unchanged"] += 1
            continue
        updates.append({"id": row.id, "latest_rejection_code": code, "latest_rejection_reason": reason, "latest_rejection_at": at})
    stats["charges_updated"] = len(updates)
    if apply and updates:
        for i in range(0, len(updates), 1000):
            db.execute(update(CoreCharge), updates[i : i + 1000])
    log.info("Toku rechazos: %s", {k: v for k, v in stats.items()})
    return stats


# ── TK-PAR-03: rechazo por intento en `payments` canónico ─────────────────────────────────────────────────────────


def toku_transaction_rejection(
    payload: dict[str, Any] | None,
    status: str | None,
    report: ReportAttemptCodes | None = None,
    *,
    external_id: str | None = None,
    created_at_api: str | None = None,
) -> tuple[str | None, str | None, datetime | None]:
    """(código, motivo, fecha) del rechazo de UNA transacción de Toku, o (None, None, None).

    Solo para `status == FAILED` (un pago exitoso no tiene rechazo aunque traiga `response_code`). Mismas reglas que
    `core_charges.latest_rejection_*`: código de la API, si falta el del reporte de Intentos (`report`), si falta `ISO:NN`.
    Función pura: no consulta la base (el índice del reporte lo carga el llamador una sola vez).
    """
    if (status or "").upper() != _FAILED or not isinstance(payload, dict):
        return None, None, None
    tx = payload.get("transaction") if isinstance(payload.get("transaction"), dict) else {}
    intents = payload.get("payment_intents")
    intent = intents[0] if isinstance(intents, list) and intents and isinstance(intents[0], dict) else {}
    at = _parse_ts(tx.get("transaction_date")) or _parse_ts(created_at_api)
    response_code = tx.get("response_code")
    report_code = None
    if report is not None and not (response_code and str(response_code).strip()):
        report_code, _match = report.lookup((external_id, tx.get("id"), intent.get("id")), intent.get("id_invoice"), at)
    code, reason = _rejection_values(response_code, tx.get("original_response_message"), report_code)
    if code is None and reason is None:
        return None, None, None
    return code, (reason[:500] if reason else None), at


def project_toku_payment_rejections(db: Session, *, apply: bool = True) -> dict[str, Any]:
    """Escribe `payments.rejection_*` de Toku desde `tk_transactions` (backfill sin reconsolidar; TK-PAR-03).

    Idempotente: solo actualiza filas cuyo valor cambia; limpia el rechazo de un pago que ya no es FAILED. Con
    `apply=False` no escribe (dry-run). No hace commit. Si las columnas no existen (migración 0056 sin aplicar) no
    escribe nada y lo informa en `skipped`.
    """
    stats: dict[str, Any] = {
        "transactions_total": 0, "payments_without_row": 0, "payments_with_rejection": 0,
        "payments_updated": 0, "payments_unchanged": 0, "applied": apply, "skipped": None,
    }
    report = load_report_attempt_codes(db)
    try:
        with db.begin_nested():
            current = {
                row.external_id: row
                for row in db.execute(
                    select(Payment.id, Payment.external_id, Payment.rejection_code, Payment.rejection_reason,
                           Payment.rejected_at).where(Payment.source == _SOURCE)
                )
            }
    except SQLAlchemyError as exc:
        stats["skipped"] = f"payments.rejection_* no disponible ({type(exc).__name__})"
        log.warning("Toku rechazos en payments: %s; se omite", stats["skipped"])
        return stats
    updates: list[dict[str, Any]] = []
    for ext_id, status, created_at_api, payload in db.execute(
        select(TokuTransaction.external_id, TokuTransaction.status, TokuTransaction.created_at_api,
               TokuTransaction.raw_payload)
    ):
        stats["transactions_total"] += 1
        row = current.get(ext_id)
        if row is None:
            stats["payments_without_row"] += 1
            continue
        values = toku_transaction_rejection(payload, status, report, external_id=ext_id, created_at_api=created_at_api)
        if values[0] is not None or values[1] is not None:
            stats["payments_with_rejection"] += 1
        if (row.rejection_code, row.rejection_reason, row.rejected_at) == values:
            stats["payments_unchanged"] += 1
            continue
        updates.append({"id": row.id, "rejection_code": values[0], "rejection_reason": values[1], "rejected_at": values[2]})
    stats["payments_updated"] = len(updates)
    if apply and updates:
        for i in range(0, len(updates), 1000):
            db.execute(update(Payment), updates[i : i + 1000])
    log.info("Toku rechazos en payments: %s", stats)
    return stats
