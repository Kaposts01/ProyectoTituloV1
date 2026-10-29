"""Aplicacion de solicitudes de baja de suscripcion multicanal aprobadas (MGT-08/09/10 y TCH).

Mismo esqueleto seguro que `billing_apply` (Opcion A):
1. Banderas de escritura y D30/irreversibilidad se comprueban ANTES de cambiar de estado (la solicitud sigue `approved`).
2. Lock por suscripcion (`billing_apply.subscription_lock`, advisory lock en conexion dedicada) y transicion atomica
   `approved -> applying` (UPDATE condicional).
3. Estado revalidado contra la suscripcion real (si ya esta dada de baja y aun no se detuvo desde aqui: `not_executable`).
4. Orden: DETENER la suscripcion -> CANCELAR cobros pendientes (por `charge_id` / anulando invoices) -> medio de pago
   (solo tarea manual registrada: VirtualPOS no tiene API, Toku queda pendiente de decision, Payku sin validar Q-09).
   Cada paso se verifica releyendo el proveedor (`refresh_subscription`). Parada en el PRIMER fallo.
5. Fallo sin efecto previo -> `failed` (reintentable tras `reopen`); fallo con pasos ya hechos (bajas irreversibles) ->
   `requires_reconciliation` con `requires_reconciliation = true` y la lista de pasos hechos. `reopen` conserva los pasos
   hechos: el reintento reanuda DESDE el paso fallido y es idempotente (no repite lo hecho).
6. Auditoria: eventos inmutables por paso, `write_runs` con el actor y el id de la solicitud (en `request_payload`).

Por canal: VirtualPOS reutiliza `cancel_subscription_with_outcome` (MGT-03/04); Toku usa PAUSED o `end_date` (D12, NUNCA
DELETE) y NIEGA la baja con invoices `in_progress` (D30); Payku usa DELETE (irreversible: exige `confirm_irreversible`) y
no elimina tarjetas (Q-09 sin validar); TCH no tiene API: la solicitud aprobada queda `pending_external` («en tramite») y
se cierra sola cuando el siguiente Excel trae la ficha eliminada (`close_tch_cancellations_from_report`).
Los errores usan codigos fijos: nunca texto libre del proveedor.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.toku.write_guard import TokuWriteBlockedError
from app.models.cancellation import SubscriptionCancellationRequest
from app.models.write_run import WriteRun
from app.services import billing_apply as ba
from app.services import cancellation_requests as cr
from app.services import write_payku as wp
from app.services import write_toku as wt
from app.services import write_virtualpos as wv
from app.services.subscription_refresh import RefreshError, refresh_subscription

log = logging.getLogger(__name__)

PROVIDER_STEPS = ("stop_subscription", "cancel_pending_charges", "payment_method")
TCH_STEPS = ("register_internal", "bank_mandate")
EFFECT_STEPS = frozenset({"stop_subscription", "cancel_pending_charges", "register_internal"})
STEP_EVENT = {"done": "step_completed", "failed": "step_failed", "manual": "step_manual"}
PAYMENT_METHOD_CODE = {
    "virtualpos1": "VP_NO_PAYMENT_METHOD_API", "virtualpos2": "VP_NO_PAYMENT_METHOD_API",
    "toku": "TOKU_PAYMENT_METHOD_DECISION_PENDING", "payku": "PAYKU_CARD_DELETE_Q09_UNVALIDATED",
}
STUCK_APPLYING_MINUTES = 30


# ----------------------------- errores tipados -----------------------------


class CancellationApplyError(Exception):
    """Base. `code` fijo, sin texto del proveedor."""

    code = "cancellation_apply_error"


class WritesDisabledError(CancellationApplyError):
    code = "writes_disabled"

    def __init__(self, channel: str) -> None:
        self.channel = channel
        super().__init__(f"Las escrituras al canal {channel} están deshabilitadas.")


class InvalidRequestStateError(CancellationApplyError):
    code = "invalid_request_state"

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"La solicitud no se puede aplicar en estado {status!r} (se exige 'approved').")


class BlockedError(CancellationApplyError):
    """La baja se NIEGA antes de tocar nada (D30 / confirmacion de irreversibilidad / listado fallido).
    La solicitud queda `approved`."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ApplyFailedError(CancellationApplyError):
    """Fallo sin efectos previos: la solicitud queda `failed`."""

    code = "apply_failed"

    def __init__(self, request_id: uuid.UUID, step: str, step_code: str) -> None:
        self.request_id, self.step, self.step_code = request_id, step, step_code
        super().__init__(f"{step}:{step_code}")


class ReconciliationRequiredError(CancellationApplyError):
    """Fallo con pasos ya hechos: la solicitud queda `requires_reconciliation`."""

    code = "reconciliation_required"

    def __init__(self, request_id: uuid.UUID, step: str, step_code: str) -> None:
        self.request_id, self.step, self.step_code = request_id, step, step_code
        super().__init__(f"{step}:{step_code}")


SubscriptionBusyError = ba.SubscriptionBusyError


# ----------------------------- contexto y resultado -----------------------------


@dataclass
class CancellationApplyResult:
    request_id: uuid.UUID
    status: str  # completed | pending_external | not_executable | dry_run
    already_applied: bool = False
    dry_run: bool = False
    reason: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    plan: dict[str, Any] | None = None
    write_run_id: uuid.UUID | None = None


@dataclass
class _Outcome:
    status: str  # done | manual | failed
    code: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Ctx:
    db: Session
    req: SubscriptionCancellationRequest
    channel: str
    sub: str
    actor: uuid.UUID | None
    run: WriteRun | None = None
    vp_outcome: Any = None  # CancelOutcome de la baja recien hecha (VirtualPOS)
    lock_conn: Any = None


# ----------------------------- utilidades -----------------------------


def writes_enabled(channel: str) -> bool:
    if channel in ("virtualpos1", "virtualpos2"):
        return bool(settings.virtualpos_writes_enabled)
    if channel == "toku":
        return bool(settings.toku_writes_enabled)
    if channel == "payku":
        return bool(settings.payku_writes_enabled)
    return True  # TCH: sin proveedor


def _event(db: Session, req_id: uuid.UUID, event_type: str, actor: uuid.UUID | None,
           detail: dict[str, Any] | None = None) -> None:
    cr._event(db, req_id, event_type, actor, detail)


def _step_map(req: SubscriptionCancellationRequest) -> dict[str, dict[str, Any]]:
    return {s["step"]: s for s in (req.steps or []) if isinstance(s, dict) and "step" in s}


def _record_step(ctx: _Ctx, name: str, out: _Outcome) -> None:
    steps = [s for s in (ctx.req.steps or []) if s.get("step") != name]
    entry = {"step": name, "status": out.status, "code": out.code, **out.data,
             "at": datetime.now(UTC).isoformat(timespec="seconds")}
    steps.append(entry)
    order = TCH_STEPS if ctx.channel == "tch" else PROVIDER_STEPS
    steps.sort(key=lambda s: order.index(s["step"]) if s["step"] in order else 99)
    ctx.req.steps = steps  # reasignar: JSONB no detecta mutaciones in situ
    _event(ctx.db, ctx.req.id, STEP_EVENT[out.status], ctx.actor, {"step": name, "code": out.code, **out.data})


def _label(exc: BaseException) -> str:
    return ba.error_label(exc)


def _chile_now(now: datetime | None) -> datetime:
    return ba._chile_now(now)


def _finish_run(ctx: _Ctx, status: str, message: str | None, payload: dict[str, Any]) -> None:
    if ctx.run is None:
        return
    ctx.run.status = status
    ctx.run.error_message = message[:2000] if message else None
    ctx.run.response_payload = payload
    ctx.run.finished_at = datetime.now(UTC)


def _summary(ctx: _Ctx) -> dict[str, Any]:
    return {"cancellation_request_id": str(ctx.req.id), "channel": ctx.channel,
            "steps": [{"step": s["step"], "status": s["status"], "code": s.get("code")} for s in ctx.req.steps or []]}


# ----------------------------- verificacion con el proveedor -----------------------------


async def _verify_remote(ctx: _Ctx) -> tuple[_Outcome | None, Any]:
    """Relee la suscripcion (GET) y devuelve (fallo|None, RefreshResult|None). Codigos fijos."""
    try:
        res = await refresh_subscription(ctx.db, ctx.channel, ctx.sub, run_id=ctx.run.id if ctx.run else None)
    except RefreshError as exc:
        return _Outcome("failed", "REFRESH_FAILED", {"refresh_code": exc.code}), None
    if res.pending_charges:
        return _Outcome("failed", "PENDING_CHARGES_REMAIN", {"pending": res.pending_charges}), res
    if res.processing_charges:
        return _Outcome("failed", "PROCESSING_CHARGES", {"processing": res.processing_charges}), res
    return None, res


# ----------------------------- pasos: VirtualPOS -----------------------------


async def _vp_stop(ctx: _Ctx) -> _Outcome:
    try:
        _, outcome = await wv.cancel_subscription_with_outcome(
            ctx.db, ctx.sub, requested_by_user_id=ctx.actor, lock_held=True)
    except wv.ReconciliationRequiredError:
        # El proveedor SI dio de baja (remoto hecho); solo fallo la escritura local: el siguiente paso relee y repara.
        return _Outcome("done", "LOCAL_WRITE_FAILED", {"remote_cancelled": True})
    except wv.BillingFlowConflictError:
        return _Outcome("failed", "BILLING_FLOW_CONFLICT")
    except wv.SubscriptionNotFoundError:
        return _Outcome("failed", "SUBSCRIPTION_NOT_FOUND")
    except wv.WriteDisabledError:
        return _Outcome("failed", "WRITES_DISABLED")
    except Exception as exc:  # noqa: BLE001
        return _Outcome("failed", "PROVIDER_ERROR", {"error": _label(exc)})
    ctx.vp_outcome = outcome
    return _Outcome("done", None, {"closed_requests": len(outcome.closed_request_ids)})


async def _vp_pending(ctx: _Ctx) -> _Outcome:
    outcome = ctx.vp_outcome
    if outcome is None:  # reanudacion: la baja ya estaba hecha; limpiar local y verificar sin repetir el DELETE
        outcome = wv.CancelOutcome()
        try:
            outcome.closed_request_ids = wv._close_open_change_requests(
                ctx.db, ctx.channel, ctx.sub, ctx.actor, ctx.run.id if ctx.run else uuid.uuid4())
            wv._retire_calendar_mark(ctx.db, ctx.channel, ctx.sub)
            ctx.db.commit()
        except Exception:  # noqa: BLE001
            ctx.db.rollback()
            outcome.flag("local_cleanup_failed")
        await wv._verify_no_pending_charges(ctx.db, ctx.channel, ctx.sub, ctx.run.id if ctx.run else uuid.uuid4(),
                                            ctx.actor, outcome)
    if outcome.requires_reconciliation:
        return _Outcome("failed", str(outcome.reason or "RECONCILIATION").upper(),
                        {"pending": outcome.pending_charges, "processing": outcome.processing_charges})
    return _Outcome("done", None, {"pending": 0})


# ----------------------------- pasos: Toku -----------------------------


async def _toku_stop(ctx: _Ctx) -> _Outcome:
    options = ctx.req.options or {}
    try:
        if options.get("toku_stop_mode") == "end_date":
            await wt.set_subscription_end_date(ctx.db, ctx.sub, str(options["toku_end_date"]),
                                               requested_by_user_id=ctx.actor)
            return _Outcome("done", None, {"mode": "end_date", "end_date": options["toku_end_date"]})
        await wt.change_subscription_status(ctx.db, ctx.sub, "PAUSED", requested_by_user_id=ctx.actor)
        return _Outcome("done", None, {"mode": "paused"})
    except wt.ReconciliationRequiredError:
        return _Outcome("done", "LOCAL_WRITE_FAILED", {"remote_stopped": True})
    except TokuWriteBlockedError:
        return _Outcome("failed", "TOKU_WRITE_BLOCKED")
    except wt.WriteDisabledError:
        return _Outcome("failed", "WRITES_DISABLED")
    except wt.SubscriptionNotFoundError:
        return _Outcome("failed", "SUBSCRIPTION_NOT_FOUND")
    except Exception as exc:  # noqa: BLE001
        return _Outcome("failed", "PROVIDER_ERROR", {"error": _label(exc)})


async def _toku_pending(ctx: _Ctx) -> _Outcome:
    try:
        res = await wt.void_unpaid_invoices(ctx.db, ctx.sub, requested_by_user_id=ctx.actor)
    except wt.DeleteAbortedError as exc:
        return _Outcome("failed", exc.code, {"voided": len(exc.voided_invoice_ids)})
    except TokuWriteBlockedError:
        return _Outcome("failed", "TOKU_WRITE_BLOCKED")
    except Exception as exc:  # noqa: BLE001
        return _Outcome("failed", "PROVIDER_ERROR", {"error": _label(exc)})
    failure, _ = await _verify_remote(ctx)
    if failure is not None:
        return _Outcome("failed", failure.code, {**failure.data, "voided": len(res["voided"])})
    return _Outcome("done", None, {"voided": len(res["voided"])})


# ----------------------------- pasos: Payku -----------------------------


async def _payku_stop(ctx: _Ctx) -> _Outcome:
    if (ctx.req.options or {}).get("confirm_irreversible") is not True:  # defensa: el CHECK de BD ya lo exige
        return _Outcome("failed", "IRREVERSIBILITY_NOT_CONFIRMED")
    try:
        await wp.delete_subscription(ctx.db, ctx.sub, requested_by_user_id=ctx.actor)
    except wp.ReconciliationRequiredError:
        return _Outcome("done", "LOCAL_WRITE_FAILED", {"remote_deleted": True})
    except wp.WriteDisabledError:
        return _Outcome("failed", "WRITES_DISABLED")
    except wp.SubscriptionNotFoundError:
        return _Outcome("failed", "SUBSCRIPTION_NOT_FOUND")
    except Exception as exc:  # noqa: BLE001
        return _Outcome("failed", "PROVIDER_ERROR", {"error": _label(exc)})
    return _Outcome("done", None, {"irreversible": True})


async def _payku_pending(ctx: _Ctx) -> _Outcome:
    failure, _ = await _verify_remote(ctx)  # Payku no tiene API para cancelar cuotas: solo se verifica
    if failure is not None:
        return _Outcome("failed", failure.code, failure.data)
    return _Outcome("done", None, {"pending": 0})


_RUNNERS = {
    "virtualpos1": {"stop_subscription": _vp_stop, "cancel_pending_charges": _vp_pending},
    "virtualpos2": {"stop_subscription": _vp_stop, "cancel_pending_charges": _vp_pending},
    "toku": {"stop_subscription": _toku_stop, "cancel_pending_charges": _toku_pending},
    "payku": {"stop_subscription": _payku_stop, "cancel_pending_charges": _payku_pending},
}


# ----------------------------- plan / dry-run -----------------------------


async def _toku_precheck(sub: str) -> dict[str, list[str]]:
    try:
        return await wt.precheck_unpaid_invoices(sub)
    except wt.DeleteAbortedError as exc:
        raise BlockedError(exc.code) from None


def build_plan(db: Session, req: SubscriptionCancellationRequest, *, toku_precheck: dict | None = None) -> dict[str, Any]:
    """Plan de ejecucion de solo lectura (dry-run): vista previa recalculada, pasos hechos y pendientes, bloqueos."""
    preview = cr.build_cascade_preview(db, req.channel, req.subscription_external_id, req.options or {})
    done = {n for n, s in _step_map(req).items() if s.get("status") in ("done", "manual")}
    order = TCH_STEPS if req.channel == "tch" else PROVIDER_STEPS
    blockers = list(preview["blockers"])
    if toku_precheck is not None and toku_precheck["in_progress"] and "INVOICE_IN_PROGRESS" not in blockers:
        blockers.append("INVOICE_IN_PROGRESS")
    if not writes_enabled(req.channel):
        blockers.append("WRITES_DISABLED")
    return {
        "channel": req.channel, "request_status": req.status, "preview": preview,
        "steps_done": sorted(done), "steps_to_run": [n for n in order if n not in done], "blockers": blockers,
        "invoices_to_void": len(toku_precheck["to_void"]) if toku_precheck else None,
        "irreversible": preview["irreversible"],
    }


# ----------------------------- API publica -----------------------------


def _claim(db: Session, request_id: uuid.UUID) -> bool:
    return db.execute(
        update(SubscriptionCancellationRequest)
        .where(SubscriptionCancellationRequest.id == request_id, SubscriptionCancellationRequest.status == "approved")
        .values(status="applying", updated_at=func.now())
        .execution_options(synchronize_session=False)
    ).rowcount == 1


def _not_executable(db: Session, req: SubscriptionCancellationRequest, actor: uuid.UUID | None, reason: str,
                    detail: dict[str, Any] | None = None) -> CancellationApplyResult:
    updated = db.execute(
        update(SubscriptionCancellationRequest)
        .where(SubscriptionCancellationRequest.id == req.id, SubscriptionCancellationRequest.status == "approved")
        .values(status="not_executable", error_message=reason[:200], updated_at=func.now())
        .execution_options(synchronize_session=False)
    ).rowcount
    if updated == 1:
        _event(db, req.id, "not_executable", actor, {"reason": reason, **(detail or {})})
    db.commit()
    return CancellationApplyResult(request_id=req.id, status="not_executable", reason=reason)


async def apply_cancellation_request(
    db: Session,
    request_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None,
    now: datetime | None = None,
    dry_run: bool = False,
) -> CancellationApplyResult:
    """Aplica una solicitud `approved` (ver docstring del modulo).

    Errores (antes de cambiar de estado: la solicitud sigue `approved`): `WritesDisabledError`, `BlockedError`
    (D30 `INVOICE_IN_PROGRESS`, `INVOICE_LIST_FAILED`, `IRREVERSIBILITY_NOT_CONFIRMED`), `SubscriptionBusyError`.
    Tras reclamar la solicitud: `ApplyFailedError` (-> `failed`) o `ReconciliationRequiredError`
    (-> `requires_reconciliation`). `not_executable` (suscripcion ya dada de baja) se devuelve sin escribir.
    Reaplicar una `completed` o `pending_external` es un no-op (`already_applied`).
    """
    req = db.get(SubscriptionCancellationRequest, request_id)
    if req is None:
        raise cr.RequestNotFoundError("Solicitud no encontrada.")
    if req.status in ("completed", "pending_external"):
        return CancellationApplyResult(request_id=req.id, status=req.status, already_applied=True,
                                       steps=list(req.steps or []), write_run_id=req.write_run_id)
    if req.status != "approved":
        raise InvalidRequestStateError(req.status)
    channel, sub = req.channel, req.subscription_external_id
    steps_done = {n for n, s in _step_map(req).items() if s.get("status") in ("done", "manual")}

    toku_pre: dict[str, list[str]] | None = None
    if channel == "toku" and "stop_subscription" not in steps_done:
        toku_pre = await _toku_precheck(sub)  # D30: leer y negar ANTES de tocar nada
    if dry_run:
        return CancellationApplyResult(request_id=req.id, status="dry_run", dry_run=True,
                                       steps=list(req.steps or []), plan=build_plan(db, req, toku_precheck=toku_pre))
    if not writes_enabled(channel):
        raise WritesDisabledError(channel)
    if toku_pre is not None and toku_pre["in_progress"]:
        raise BlockedError("INVOICE_IN_PROGRESS")
    if channel == "payku" and (req.options or {}).get("confirm_irreversible") is not True:
        raise BlockedError("IRREVERSIBILITY_NOT_CONFIRMED")

    with ba.subscription_lock(db, channel, sub) as lock_conn:
        db.refresh(req)
        if req.status in ("completed", "pending_external"):
            return CancellationApplyResult(request_id=req.id, status=req.status, already_applied=True,
                                           steps=list(req.steps or []), write_run_id=req.write_run_id)
        if req.status != "approved":
            raise InvalidRequestStateError(req.status)
        steps_done = {n for n, s in _step_map(req).items() if s.get("status") in ("done", "manual")}
        status_now = cr.subscription_status(db, channel, sub)
        if "stop_subscription" not in steps_done and "register_internal" not in steps_done and (
                status_now is None or cr.is_terminal_status(status_now)):
            return _not_executable(db, req, actor_user_id, "subscription_not_active", {"status": status_now})
        if not _claim(db, req.id):
            db.rollback()
            raise InvalidRequestStateError("not_approved (concurrent transition)")
        db.refresh(req)
        ctx = _Ctx(db=db, req=req, channel=channel, sub=sub, actor=actor_user_id, lock_conn=lock_conn)
        if channel != "tch":
            ctx.run = WriteRun(
                source=channel, resource_type="subscription", external_id=sub, operation="apply_cancellation_request",
                status="pending", requested_by_user_id=actor_user_id,
                request_payload={"cancellation_request_id": str(req.id), "channel": channel,
                                 "resumed_steps": sorted(steps_done)})
            db.add(ctx.run)
            db.flush()
            req.write_run_id = ctx.run.id
        _event(db, req.id, "applying", actor_user_id, {
            "write_run_id": str(ctx.run.id) if ctx.run else None, "resumed_steps": sorted(steps_done)})
        db.commit()
        try:
            return await _execute(ctx, now)
        except (ApplyFailedError, ReconciliationRequiredError):
            raise
        except Exception as exc:
            db.rollback()
            ctx.req = db.get(SubscriptionCancellationRequest, req.id) or req
            ctx.run = db.get(WriteRun, ctx.run.id) if ctx.run else None
            _finalize_failure(ctx, "unexpected", _Outcome("failed", "UNEXPECTED_ERROR", {"error": _label(exc)}))
            raise ReconciliationRequiredError(req.id, "unexpected", "UNEXPECTED_ERROR") from exc
        except BaseException:
            try:
                db.rollback()
                ctx.req = db.get(SubscriptionCancellationRequest, req.id) or req
                ctx.run = db.get(WriteRun, ctx.run.id) if ctx.run else None
                _finalize_failure(ctx, "interrupted", _Outcome("failed", "INTERRUPTED"), force_reconcile=True)
            except Exception as rec_exc:  # noqa: BLE001
                log.error("no se pudo registrar la interrupcion de %s: %s", req.id, type(rec_exc).__name__)
            raise


def _finalize_failure(ctx: _Ctx, step: str, out: _Outcome, *, force_reconcile: bool = False) -> bool:
    """Cierra la solicitud como `failed` (sin efectos previos) o `requires_reconciliation`. Devuelve True si reconcilia."""
    req = ctx.req
    effect = force_reconcile or any(
        s.get("status") == "done" and s["step"] in EFFECT_STEPS for s in (req.steps or []) if s.get("step") != step)
    status = "requires_reconciliation" if effect else "failed"
    req.status = status
    req.requires_reconciliation = effect
    req.error_message = f"{step}:{out.code}"[:200]
    _event(ctx.db, req.id, "requires_reconciliation" if effect else "failed", ctx.actor, {
        "step": step, "code": out.code, "steps_done": [s["step"] for s in req.steps or [] if s.get("status") == "done"]})
    _finish_run(ctx, "reconciliation_required" if effect else "failed", req.error_message, _summary(ctx))
    ctx.db.commit()
    return effect


async def _execute(ctx: _Ctx, now: datetime | None) -> CancellationApplyResult:
    channel = ctx.channel
    if channel == "tch":
        return _execute_tch(ctx)
    runners = _RUNNERS[channel]
    for name in PROVIDER_STEPS:
        current = _step_map(ctx.req).get(name)
        if current is not None and current.get("status") in ("done", "manual"):
            continue  # idempotencia: lo hecho no se repite
        if name == "payment_method":
            out = _Outcome("manual", PAYMENT_METHOD_CODE[channel], {"task": "remove_payment_method_manually"})
        else:
            out = await runners[name](ctx)
        _record_step(ctx, name, out)
        ctx.db.commit()
        if out.status == "failed":
            reconcile = _finalize_failure(ctx, name, out)
            err_cls = ReconciliationRequiredError if reconcile else ApplyFailedError
            raise err_cls(ctx.req.id, name, str(out.code))
    req = ctx.req
    req.status = "completed"
    req.requires_reconciliation = False
    req.error_message = None
    req.executed_at = datetime.now(UTC)
    _event(ctx.db, req.id, "completed", ctx.actor, {
        "steps": [{"step": s["step"], "status": s["status"], "code": s.get("code")} for s in req.steps or []]})
    _finish_run(ctx, "completed", None, _summary(ctx))
    ctx.db.commit()
    return CancellationApplyResult(request_id=req.id, status="completed", steps=list(req.steps or []),
                                   write_run_id=ctx.run.id if ctx.run else None)


def _execute_tch(ctx: _Ctx) -> CancellationApplyResult:
    """TCH no tiene API de escritura: la solicitud aprobada queda «en tramite» (`pending_external`) y el mandato lo
    tramita una persona en el banco (tarea manual). Se cierra con `close_tch_cancellations_from_report`."""
    _record_step(ctx, "register_internal", _Outcome("done", None, {"channel": "tch"}))
    _record_step(ctx, "bank_mandate", _Outcome("manual", "TCH_BANK_MANDATE_OUTSIDE_CRM",
                                               {"task": "revoke_bank_mandate_manually"}))
    ctx.req.status = "pending_external"
    ctx.req.requires_reconciliation = False
    ctx.req.error_message = None
    _event(ctx.db, ctx.req.id, "pending_external", ctx.actor, {"awaiting": "next_tch_report_with_fecha_eliminacion"})
    ctx.db.commit()
    return CancellationApplyResult(request_id=ctx.req.id, status="pending_external", steps=list(ctx.req.steps or []))


# ----------------------------- cierre de TCH por Excel -----------------------------


def close_tch_cancellations_from_report(db: Session, *, now: datetime | None = None) -> list[uuid.UUID]:
    """Cierra (`completed`) las bajas TCH `pending_external` cuya ficha ya trae `fecha_eliminacion` en la tabla local
    (cargada por el ETL del Excel). Idempotente; evento `closed_by_report` con actor sistema. Devuelve los ids cerrados.

    Pendiente (anotado en docs/designs/baja-cascada.md): invocarla al final del ETL/importacion del Excel TCH y la
    exportacion para tesoreria/banco; hoy solo estan el modelo y el cierre."""
    closed: list[uuid.UUID] = []
    rows = db.scalars(select(SubscriptionCancellationRequest).where(
        SubscriptionCancellationRequest.channel == "tch",
        SubscriptionCancellationRequest.status == "pending_external").with_for_update()).all()
    for req in rows:
        status = cr.subscription_status(db, "tch", req.subscription_external_id)
        if status is None or not cr.is_terminal_status(status):
            continue
        req.status = "completed"
        req.executed_at = datetime.now(UTC)
        req.error_message = None
        _event(db, req.id, "closed_by_report", None, {"source": "tch_report", "subscription_status": status})
        closed.append(req.id)
    db.commit()
    return closed


# ----------------------------- barredor -----------------------------


def sweep_stuck_applying(
    db: Session, *, older_than_minutes: int = STUCK_APPLYING_MINUTES, now: datetime | None = None
) -> list[uuid.UUID]:
    """Solicitudes de baja en `applying` sin actividad hace mas de N minutos (proceso caido) pasan a
    `requires_reconciliation` (evento con actor sistema). Si el lock esta tomado (aplicacion viva) se omite."""
    cutoff = (now or datetime.now(UTC)) - timedelta(minutes=older_than_minutes)
    model = SubscriptionCancellationRequest
    stuck = list(db.execute(select(model.id, model.channel, model.subscription_external_id).where(
        model.status == "applying", model.updated_at < cutoff)))
    swept: list[uuid.UUID] = []
    for req_id, channel, sub in stuck:
        try:
            with ba.subscription_lock(db, channel, sub):
                changed = db.execute(
                    update(model).where(model.id == req_id, model.status == "applying", model.updated_at < cutoff)
                    .values(status="requires_reconciliation", requires_reconciliation=True,
                            error_message="StuckApplying", updated_at=func.now())
                    .execution_options(synchronize_session=False)).rowcount
                if changed != 1:
                    db.rollback()
                    continue
                db.execute(update(WriteRun).where(
                    WriteRun.request_payload["cancellation_request_id"].astext == str(req_id),
                    WriteRun.status == "pending").values(
                    status="reconciliation_required", error_message="StuckApplying", finished_at=datetime.now(UTC)))
                _event(db, req_id, "requires_reconciliation", None,
                       {"reason": "stuck_applying", "older_than_minutes": older_than_minutes})
                db.commit()
                swept.append(req_id)
        except SubscriptionBusyError:
            db.rollback()
    return swept
