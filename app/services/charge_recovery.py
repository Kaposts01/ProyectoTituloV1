from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.charge_recovery import ChargeRecovery
from app.models.crm import Charge

PAID_STATUSES = {"pagado", "pago", "aceptado", "aceptada", "accepted", "paid", "success", "aprobado", "aprobada", "cobrado", "cobrada"}
FINAL_UNPAID_STATUSES = {"rechazado", "rejected", "failed", "failure", "declined", "error", "cancelado", "cancelled", "expirado", "expired"}
CARD_REASON_TERMS = ("tarjeta", "card", "cuenta bloqueada", "account blocked", "bloquead", "vencid", "expired")


def is_paid(status: str | None) -> bool:
    return str(status or "").strip().lower() in PAID_STATUSES


def needs_card_change(*values: str | None) -> bool:
    reason = " ".join(str(value or "").lower() for value in values)
    return any(term in reason for term in CARD_REASON_TERMS)


def reconcile_charge_recoveries(db: Session, source: str) -> None:
    """Finalize mature retry cycles from the charge state observed by a successful sync."""
    now = datetime.now(UTC)
    recoveries = db.scalars(
        select(ChargeRecovery).where(
            ChargeRecovery.source == source,
            ChargeRecovery.status.in_(("en_seguimiento", "pendiente_de_conciliacion")),
        )
    ).all()
    for recovery in recoveries:
        charge = db.scalar(
            select(Charge).where(
                Charge.source == source,
                Charge.external_id == recovery.charge_external_id,
            )
        )
        if charge is None:
            if now >= recovery.closes_at:
                recovery.status = "pendiente_de_conciliacion"
            continue
        recovery.observed_charge_status = charge.status
        recovery.observed_at = now
        if now < recovery.closes_at:
            continue
        if is_paid(charge.status):
            recovery.status = "cobrado"
            recovery.closed_at = now
        elif str(charge.status or "").strip().lower() in FINAL_UNPAID_STATUSES:
            recovery.status = "no_cobrado"
            recovery.closed_at = now
        else:
            recovery.status = "pendiente_de_conciliacion"
