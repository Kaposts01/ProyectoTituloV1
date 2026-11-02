"""Materializa los intentos FAILED de Toku como `core_payments` (RJ-15, decision D4 del usuario).

Hasta ahora `core_payments` de Toku eran solo los pagos exitosos de `tk_payments` (con `source_status` NULL) y
cada `tk_transactions` FAILED solo alimentaba `core_charges.latest_rejection_*` (RJ-01). Con esta funcion cada
intento FAILED es tambien una fila de `core_payments`:

- `source = 'toku'`, `external_id` = id de la transaccion (`tk_transactions.external_id`), `source_status = 'FAILED'`.
- `charge_id` / `subscription_id` por la factura del intento (`payment_intents[0].id_invoice` = `core_charges.external_id`);
  NULL si la factura no existe en core.
- `rejection_code` / `rejection_reason` / `rejection_reported_at` con la MISMA proyeccion de RJ-01
  (`toku_rejection_projection._rejection_values`): `response_code` o `ISO:NN`, glosa normalizada, fecha del intento.

Como no distorsionar los KPIs (revisado al disenar)
- Ningun dashboard, ni `charge_stats`, ni la recuperacion leen `core_payments`: las tarjetas leen `charges`/`payments`
  centralizados y `source_records`; la recuperacion lee `core_charges.latest_rejection_*`. Esta funcion no toca
  `core_charges`, ni `tk_*`, ni las tablas centralizadas (`tests/test_toku_failed_payments.py` lo comprueba con las cifras
  de Toku antes y despues y con un guardian que falla si aparece un lector nuevo de `core_payments`).
- Las filas FAILED se distinguen siempre por `source_status = 'FAILED'`; un lector futuro de `core_payments` debe
  excluirlas para contar solo pagos efectivos.
- `ON CONFLICT (source, external_id) DO UPDATE ... WHERE source_status = 'FAILED'`: solo se actualizan filas propias; si el id
  coincidiera con un pago exitoso existente, ese pago NO se toca (se cuenta en `skipped_foreign_conflict`).

Idempotente (una segunda corrida no escribe nada). No hace commit: lo hace el llamador. Sin datos personales.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.core import CoreCharge, CorePayment
from app.models.toku_channel import TokuTransaction
from app.services.toku_rejection_projection import _parse_ts, _rejection_values, load_report_attempt_codes

log = logging.getLogger(__name__)

SOURCE = "toku"
FAILED = "FAILED"
_BATCH = 500
_DEFAULT_CURRENCY = "CLP"
_COMPARED = ("subscription_id", "charge_id", "occurred_at", "currency", "rejection_code", "rejection_reason",
             "rejection_reported_at")


def _amount(*candidates: Any) -> Decimal | None:
    for value in candidates:
        if value is None or isinstance(value, bool) or str(value).strip() == "":
            continue
        try:
            return Decimal(str(value).replace(",", ".").strip()).quantize(Decimal("0.01"))
        except InvalidOperation:
            continue
    return None


def _same_amount(current: Any, new: Decimal | None) -> bool:
    if current is None or new is None:
        return current is None and new is None
    return Decimal(str(current)).quantize(Decimal("0.01")) == new


def materialize_failed_toku_payments(db: Session, *, apply: bool = True) -> dict[str, Any]:
    """Crea/actualiza un `core_payments` por cada transaccion FAILED de Toku. Con `apply=False` solo cuenta (dry-run)."""
    payload = TokuTransaction.raw_payload
    rows = db.execute(
        select(
            TokuTransaction.external_id,
            TokuTransaction.amount,
            TokuTransaction.currency,
            TokuTransaction.created_at_api,
            payload["transaction"]["response_code"].astext,
            payload["transaction"]["original_response_message"].astext,
            payload["transaction"]["transaction_date"].astext,
            payload["transaction"]["amount"].astext,
            payload["payment_intents"][0]["id_invoice"].astext,
            payload["transaction"]["id"].astext,
            payload["payment_intents"][0]["id"].astext,
        ).where(TokuTransaction.status == FAILED)
    ).all()

    stats: dict[str, Any] = {
        "failed_total": len(rows), "to_create": 0, "to_update": 0, "unchanged": 0, "skipped_foreign_conflict": 0,
        "without_charge": 0, "without_rejection_data": 0, "written": 0, "applied": apply,
    }
    if not rows:
        return stats

    charge_index = {
        r.external_id: (r.id, r.subscription_id)
        for r in db.execute(
            select(CoreCharge.external_id, CoreCharge.id, CoreCharge.subscription_id).where(CoreCharge.source == SOURCE)
        )
    }
    existing: dict[str, Any] = {}
    ids = [r[0] for r in rows]
    for i in range(0, len(ids), 5000):
        for r in db.execute(
            select(
                CorePayment.external_id, CorePayment.source_status, CorePayment.subscription_id, CorePayment.charge_id,
                CorePayment.occurred_at, CorePayment.amount, CorePayment.currency, CorePayment.rejection_code,
                CorePayment.rejection_reason, CorePayment.rejection_reported_at,
            ).where(CorePayment.source == SOURCE, CorePayment.external_id.in_(ids[i : i + 5000]))
        ):
            existing[r.external_id] = r

    to_write: list[dict[str, Any]] = []
    report = load_report_attempt_codes(db)  # RJ-11: codigo del reporte de Intentos para los FAILED sin codigo
    for ext_id, tx_amount, tx_currency, created_at_api, code, message, tx_date, payload_amount, invoice, tx_id, intent_id in rows:
        charge_id, subscription_id = charge_index.get(invoice, (None, None)) if invoice else (None, None)
        if charge_id is None:
            stats["without_charge"] += 1
        at = _parse_ts(tx_date) or _parse_ts(created_at_api)
        report_code = None if (code and str(code).strip()) else report.lookup((ext_id, tx_id, intent_id), invoice, at)[0]
        reject_code, reject_reason = _rejection_values(code, message, report_code)
        if reject_code is None and reject_reason is None:
            stats["without_rejection_data"] += 1
        values: dict[str, Any] = {
            "subscription_id": subscription_id,
            "charge_id": charge_id,
            "source_status": FAILED,
            "occurred_at": at,
            "amount": _amount(tx_amount, payload_amount),
            "currency": (tx_currency or _DEFAULT_CURRENCY)[:3].upper(),
            "rejection_code": reject_code,
            "rejection_reason": reject_reason,
            "rejection_reported_at": at,
        }
        current = existing.get(ext_id)
        if current is None:
            stats["to_create"] += 1
        elif current.source_status != FAILED:
            stats["skipped_foreign_conflict"] += 1
            continue
        elif all(getattr(current, k) == values[k] for k in _COMPARED) and _same_amount(current.amount, values["amount"]):
            stats["unchanged"] += 1
            continue
        else:
            stats["to_update"] += 1
        to_write.append({"id": uuid.uuid4(), "source": SOURCE, "external_id": ext_id, **values})

    if apply and to_write:
        now = datetime.now(UTC)
        for i in range(0, len(to_write), _BATCH):
            ins = insert(CorePayment).values(to_write[i : i + _BATCH])
            db.execute(ins.on_conflict_do_update(
                constraint="uq_core_payment_source_external_id",
                set_={
                    "subscription_id": ins.excluded.subscription_id,
                    "charge_id": ins.excluded.charge_id,
                    "occurred_at": ins.excluded.occurred_at,
                    "amount": ins.excluded.amount,
                    "currency": ins.excluded.currency,
                    "rejection_code": ins.excluded.rejection_code,
                    "rejection_reason": ins.excluded.rejection_reason,
                    "rejection_reported_at": ins.excluded.rejection_reported_at,
                    "updated_at": now,
                },
                where=CorePayment.source_status == FAILED,  # nunca pisa un pago exitoso
            ))
        stats["written"] = len(to_write)
    log.info("Toku FAILED -> core_payments: %s", stats)
    return stats
