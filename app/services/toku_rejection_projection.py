"""Proyección de los rechazos de Toku (tk_transactions FAILED) a core_charges.latest_rejection_* (RJ-01).

Fuente: `tk_transactions.raw_payload` ya guarda el ítem completo de `GET /transactions`:
`transaction.response_code` (p. ej. `TEPSP1008`), `transaction.original_response_message` (glosa del
procesador) y `payment_intents[0].id_invoice` (la factura = `core_charges.external_id` de Toku).
No llama a ninguna API.

Reglas
- Por factura se toma el intento FAILED más reciente (por `transaction_date`) que traiga algún dato
  (código o glosa). Los FAILED sin ningún dato se cuentan y se ignoran.
- `latest_rejection_code` = `response_code` tal cual; si falta, el número ISO de la glosa como `ISO:NN`
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
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.core import CoreCharge
from app.models.toku_channel import TokuTransaction
from app.services.toku_rejection_codes import normalize_processor_message

log = logging.getLogger(__name__)

_SOURCE = "toku"
_FAILED = "FAILED"


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _rejection_values(response_code: str | None, message: str | None) -> tuple[str | None, str | None]:
    """(código, motivo) a guardar, o (None, None) si el intento no trae ningún dato."""
    code = str(response_code).strip().upper() if response_code and str(response_code).strip() else None
    glosa = normalize_processor_message(message)
    if code is None and glosa is not None and glosa.processor_code:
        code = f"ISO:{glosa.processor_code}"
    return code, (glosa.text or None) if glosa is not None else None


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
        ).where(TokuTransaction.status == _FAILED)
    )

    stats: dict[str, Any] = {
        "failed_total": 0,
        "failed_without_invoice": 0,
        "failed_without_information": 0,
        "invoices_with_information": 0,
        "invoices_without_core_charge": 0,
        "charges_updated": 0,
        "charges_unchanged": 0,
        "charges_kept_newer": 0,
        "applied": apply,
    }
    best: dict[str, tuple[tuple[datetime, str], str | None, str | None, datetime | None]] = {}
    floor = datetime.min.replace(tzinfo=UTC)
    for ext_id, created_at_api, response_code, message, tx_date, invoice in rows:
        stats["failed_total"] += 1
        if not invoice:
            stats["failed_without_invoice"] += 1
            continue
        code, reason = _rejection_values(response_code, message)
        if code is None and reason is None:
            stats["failed_without_information"] += 1
            continue
        at = _parse_ts(tx_date) or _parse_ts(created_at_api)
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
