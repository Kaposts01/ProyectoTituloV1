"""Cambio de monto de Toku por la bandeja de cambios de cobro (MGT-12, d106).

Reutiliza la bandeja de la Opcion A (`billing_change_requests`, estados en espanol, aprobadores de `billing_policy`):
la solicitud `change_amount` con `platform = 'toku'` se crea, aprueba, rechaza, retira y reabre igual que la de
VirtualPOS (`billing_requests`). Este modulo solo la EJECUTA, con el mismo esqueleto seguro que `billing_apply`:

1. Bandera `TOKU_WRITES_ENABLED` ANTES de cambiar de estado (la solicitud sigue `aprobada`, sin llamadas al proveedor).
2. Lock por suscripcion (`billing_apply.subscription_lock`) y transicion atomica `aprobada -> aplicando`.
3. Revalida que la suscripcion siga activa (si no: `no_ejecutable`).
4. `write_toku.apply_amount_change`: suscripcion -> cuotas impagas (sin las `in_progress`) -> verificacion releyendo.
5. Sin efectos o con compensacion limpia -> `fallida` (reintentable tras reabrir); con efectos sin revertir ->
   `requiere_conciliacion`. Exito -> `ejecutada`. Eventos inmutables y `write_runs` con el actor y `request_id`.

La escritura real queda detras de la bandera de Toku (apagada por defecto) y de sus guardas duras: fuera de produccion
solo ids `TEST-` o de la allowlist. Las pruebas usan clientes falsos (el host de Toku es compartido con produccion).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.toku.write_guard import TokuWriteBlockedError
from app.models.billing import (
    EVENT_APPLIED,
    EVENT_APPLYING,
    EVENT_FAILED,
    EVENT_NEEDS_RECONCILIATION,
    STATUS_APPROVED,
    STATUS_EXECUTED,
    STATUS_FAILED,
    STATUS_NEEDS_RECONCILIATION,
    BillingChangeRequest,
)
from app.models.write_run import WriteRun
from app.services import billing_apply as ba
from app.services import write_toku as wt
from app.services.write_virtualpos import ReconciliationRequiredError

log = logging.getLogger(__name__)

PLATFORM = "toku"


class TokuWritesDisabledError(ba.BillingApplyError):
    """`TOKU_WRITES_ENABLED` apagada: nada se escribio y la solicitud sigue `aprobada`."""


def _event(db: Session, req_id: uuid.UUID, event_type: str, actor: uuid.UUID | None,
           detail: dict[str, Any] | None = None) -> None:
    ba._event(db, req_id, event_type, actor, detail)


def _finish(db: Session, req: BillingChangeRequest, status: str, event: str, actor: uuid.UUID | None,
            code: str | None, detail: dict[str, Any]) -> None:
    req.status = status
    req.error_message = code
    run_id = db.scalar(select(WriteRun.id).where(WriteRun.request_id == req.id)
                       .order_by(WriteRun.started_at.desc()).limit(1))
    if run_id is not None:
        req.write_run_id = run_id
    if status == STATUS_EXECUTED:
        req.executed_at = datetime.now(UTC)
    _event(db, req.id, event, actor, {"code": code, **detail})
    db.commit()


async def apply_toku_amount_change(
    db: Session, request_id: uuid.UUID, *, actor_user_id: uuid.UUID | None, now: datetime | None = None
) -> ba.ApplyResult:
    """Ejecuta una solicitud Toku `change_amount` `aprobada` (ver docstring del modulo)."""
    req = db.get(BillingChangeRequest, request_id)
    if req is None:
        raise ba.RequestNotFoundError(str(request_id))
    if req.platform != PLATFORM or req.request_type != "change_amount":
        raise ba.InvalidRequestStateError(req.status)
    if req.status == STATUS_EXECUTED:
        return ba.ApplyResult(request_id=req.id, status=STATUS_EXECUTED, already_applied=True,
                              write_run_id=req.write_run_id)
    if req.status != STATUS_APPROVED:
        raise ba.InvalidRequestStateError(req.status)
    if not settings.toku_writes_enabled:
        raise TokuWritesDisabledError("Las escrituras a Toku están deshabilitadas.")
    sub = req.subscription_external_id

    with ba.subscription_lock(db, PLATFORM, sub):
        db.refresh(req)
        if req.status == STATUS_EXECUTED:
            return ba.ApplyResult(request_id=req.id, status=STATUS_EXECUTED, already_applied=True,
                                  write_run_id=req.write_run_id)
        if req.status != STATUS_APPROVED:
            raise ba.InvalidRequestStateError(req.status)
        state = ba._subscription_state(db, PLATFORM, sub)
        if state is None or not ba.is_active_status(state[0]):
            return ba._not_executable(db, req, actor_user_id, "subscription_not_active",
                                      {"status": state[0] if state else None})
        if not ba._claim_request(db, req.id):
            db.rollback()
            raise ba.InvalidRequestStateError("no aprobada (transición concurrente)")
        db.refresh(req)
        _event(db, req.id, EVENT_APPLYING, actor_user_id, {"channel": PLATFORM})
        db.commit()
        new_amount = int(req.new_amount)
        try:
            summary = await wt.apply_amount_change(
                db, sub, new_amount, requested_by_user_id=actor_user_id, billing_request_id=req.id)
        except wt.AmountChangeError as exc:
            db.rollback()
            req = db.get(BillingChangeRequest, request_id) or req
            if exc.effects and not exc.compensated:
                _finish(db, req, STATUS_NEEDS_RECONCILIATION, EVENT_NEEDS_RECONCILIATION, actor_user_id, exc.code,
                        {"updated_invoice_ids": exc.updated_invoice_ids})
                raise ReconciliationRequiredError(f"toku_amount:{exc.code}") from None
            _finish(db, req, STATUS_FAILED, EVENT_FAILED, actor_user_id, exc.code,
                    {"compensated": exc.compensated, "effects": exc.effects})
            raise ba.ApplyFailedError(req.id, None, exc.updated_invoice_ids if exc.compensated else []) from None
        except (TokuWriteBlockedError, wt.WriteDisabledError, wt.SubscriptionNotFoundError) as exc:
            db.rollback()
            req = db.get(BillingChangeRequest, request_id) or req
            code = getattr(exc, "code", None) or type(exc).__name__
            _finish(db, req, STATUS_FAILED, EVENT_FAILED, actor_user_id, f"toku_blocked:{code}"[:200], {})
            raise ba.ApplyFailedError(req.id, None, []) from None
        except wt.ReconciliationRequiredError:
            db.rollback()
            req = db.get(BillingChangeRequest, request_id) or req
            _finish(db, req, STATUS_NEEDS_RECONCILIATION, EVENT_NEEDS_RECONCILIATION, actor_user_id,
                    "LOCAL_WRITE_FAILED", {})
            raise ReconciliationRequiredError("toku_amount:LOCAL_WRITE_FAILED") from None
        except Exception as exc:
            db.rollback()
            req = db.get(BillingChangeRequest, request_id) or req
            _finish(db, req, STATUS_NEEDS_RECONCILIATION, EVENT_NEEDS_RECONCILIATION, actor_user_id,
                    ba.error_label(exc), {})
            raise ReconciliationRequiredError("toku_amount:UNEXPECTED_ERROR") from exc
        req.previous_amount = summary["previous_amount"] if summary["previous_amount"] is not None else req.previous_amount
        _finish(db, req, STATUS_EXECUTED, EVENT_APPLIED, actor_user_id, None, {
            "invoices_updated": len(summary["invoices_updated"]),
            "skipped_in_progress": len(summary["skipped_in_progress"])})
        req = db.get(BillingChangeRequest, request_id) or req
        result = ba.ApplyResult(request_id=req.id, status=STATUS_EXECUTED, write_run_id=req.write_run_id)
        result.toku = {"invoices_updated": summary["invoices_updated"],
                       "skipped_in_progress": summary["skipped_in_progress"],
                       "previous_amount": summary["previous_amount"], "new_amount": summary["new_amount"]}
        return result
