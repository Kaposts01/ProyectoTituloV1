"""Solicitudes de baja de suscripcion multicanal (MGT-07): ciclo de vida, aprobacion y vista previa de la cascada.

Logica detras de `app/api/v1/routes/cancellations.py`. Modelo: `app/models/cancellation.py` (tabla nueva; estados en
INGLES; la Opcion A y sus estados en espanol no se tocan, D38). La EJECUCION vive en `cancellation_apply.py`.

Reglas
- D12: JEFATURA solicita; ADMIN o JEFATURA aprueban; EJECUTIVO solo lee. Quien aprueba es quien tiene el permiso
  `subscriptions.cancellation.approve` (admin y jefatura por la migracion 0050); NO se duplica la lista de roles aprobadores
  de `billing_policy` (esa es de la Opcion A y por defecto solo incluye `admin`). De la politica compartida se reutilizan
  autoaprobacion (auditada), doble aprobacion (apagada por defecto) y los dias de expiracion.
- Una sola solicitud abierta por (canal, suscripcion): chequeo previo + indice unico parcial.
- Motivo obligatorio: `reason_code` fijo + `reason_comment` no vacio. La baja de Payku exige confirmacion explicita
  (`confirm_irreversible`) porque el DELETE es irreversible. En Toku la baja es PAUSED o `end_date` (D12; nunca DELETE).
- Cada transicion: SELECT ... FOR UPDATE + UPDATE condicional y un evento inmutable con el actor (autor SIEMPRE del token).
- Este modulo NO escribe en ningun proveedor. Los errores llevan un `code` estable y nunca texto del proveedor.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.auth import User
from app.models.cancellation import (
    CHANNELS,
    OPEN_STATUSES,
    REASON_CODES,
    SubscriptionCancellationRequest,
    SubscriptionCancellationRequestEvent,
)
from app.models.payku_channel import PaykuTransaction
from app.models.tch import TchSuscripcion
from app.models.toku_channel import TokuInvoice
from app.models.vp import VpCharge
from app.services import billing_requests as br
from app.services.billing_plan import PENDING_STATES, norm_state
from app.services.rbac import CANCELLATION_APPROVE, permission_codes
from app.services.subscription_refresh import _current_status

log = logging.getLogger(__name__)

REOPENABLE_STATUSES = ("failed", "requires_reconciliation")
TOKU_STOP_MODES = ("paused", "end_date")
TERMINAL_SUBSCRIPTION_STATES = frozenset({
    "cancelada", "cancelado", "cancelled", "canceled", "deleted", "delete", "eliminada", "eliminado", "terminated",
    "finalizada", "finalizado", "expired", "expirada",
})
PROCESSING_STATES = frozenset({"procesando", "processing"})
TOKU_UNPAID_STATES = frozenset({"unpaid", "partially_paid"})
PAYKU_PENDING_STATES = frozenset({"pending", "retry"})
PREVIEW_ID_LIMIT = 50
ADMIN_ROLE = "admin"


# ----------------------------- errores tipados -----------------------------


class CancellationError(Exception):
    """Base de los errores de este modulo. `code` es estable y lo expone la API."""

    code = "cancellation_error"


class InvalidFieldsError(CancellationError):
    code = "invalid_fields"


class CommentRequiredError(CancellationError):
    code = "comment_required"


class IrreversibleNotConfirmedError(CancellationError):
    code = "irreversibility_confirmation_required"

    def __init__(self) -> None:
        super().__init__("La baja en Payku es irreversible: debe confirmarse de forma explícita (confirm_irreversible).")


class SubscriptionUnknownError(CancellationError):
    code = "subscription_not_found"


class SubscriptionNotActiveError(CancellationError):
    code = "subscription_not_active"

    def __init__(self, status: str | None) -> None:
        self.status = status
        super().__init__("La suscripción ya está dada de baja; no admite otra solicitud de baja.")


class OpenRequestExistsError(CancellationError):
    code = "open_request_exists"

    def __init__(self, request_id: uuid.UUID | None, status: str | None) -> None:
        self.request_id = request_id
        self.status = status
        super().__init__("Ya existe una solicitud de baja abierta para esta suscripción.")


class RequestNotFoundError(CancellationError):
    code = "request_not_found"


class RequestStateConflictError(CancellationError):
    code = "invalid_request_state"

    def __init__(self, current: str, expected: Sequence[str]) -> None:
        self.current_status = current
        self.expected = tuple(expected)
        super().__init__(f"La solicitud está en estado {current!r}; se requiere {' o '.join(expected)}.")


class RequestExpiredError(CancellationError):
    code = "request_expired"

    def __init__(self) -> None:
        super().__init__("La solicitud expiró y ya no se puede aprobar.")


class NotApproverError(CancellationError):
    code = "not_approver"

    def __init__(self) -> None:
        super().__init__("No tienes permiso para aprobar solicitudes de baja.")


class SelfApprovalNotAllowedError(CancellationError):
    code = "self_approval_not_allowed"

    def __init__(self) -> None:
        super().__init__("Autoaprobación no permitida por la política vigente.")


class DuplicateApproverError(CancellationError):
    code = "duplicate_approver"

    def __init__(self) -> None:
        super().__init__("Ya aprobaste esta solicitud; se necesita otro aprobador distinto.")


class NotAllowedError(CancellationError):
    code = "forbidden"


# ----------------------------- consulta de estado y vista previa -----------------------------


def normalize_channel(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if raw in ("virtualpos", "vp", "vp1"):
        raw = "virtualpos1"
    elif raw == "vp2":
        raw = "virtualpos2"
    if raw not in CHANNELS:
        raise InvalidFieldsError(f"channel debe ser uno de: {', '.join(CHANNELS)}.")
    return raw


def subscription_status(db: Session, channel: str, external_id: str) -> str | None:
    """Estado local de la suscripcion (None = no existe). TCH: `estado` de la ficha, o ELIMINADA si trae fecha de baja."""
    if channel == "tch":
        if not external_id.isdigit():
            return None
        row = db.execute(select(TchSuscripcion.estado, TchSuscripcion.fecha_eliminacion).where(
            TchSuscripcion.numero_ficha == int(external_id)).limit(1)).first()
        if row is None:
            return None
        return "ELIMINADA" if (row[1] or "").strip() else (row[0] or "VIGENTE")
    return _current_status(db, channel, external_id)


def is_terminal_status(status: str | None) -> bool:
    return norm_state(status) in TERMINAL_SUBSCRIPTION_STATES


def _charge_rows(db: Session, channel: str, sub: str) -> tuple[list[str], list[str], list[str]]:
    """(pendientes, procesando, en_curso_toku) de la ultima sincronizacion local. TCH no tiene cobros que cancelar."""
    pending: list[str] = []
    processing: list[str] = []
    in_progress: list[str] = []
    if channel in ("virtualpos1", "virtualpos2"):
        for ext, status in db.execute(select(VpCharge.external_id, VpCharge.status).where(
                VpCharge.platform == channel, VpCharge.subscription_external_id == sub)):
            state = norm_state(status)
            if state in PENDING_STATES:
                pending.append(ext)
            elif state in PROCESSING_STATES:
                processing.append(ext)
    elif channel == "toku":
        for ext, status, raw in db.execute(select(TokuInvoice.external_id, TokuInvoice.status, TokuInvoice.raw_payload)
                                           .where(TokuInvoice.subscription_id == sub)):
            general = norm_state((raw or {}).get("general_status") or status)
            if general not in TOKU_UNPAID_STATES:
                continue
            (in_progress if (raw or {}).get("in_progress") else pending).append(ext)
    elif channel == "payku":
        for ext, status in db.execute(select(PaykuTransaction.external_id, PaykuTransaction.status).where(
                PaykuTransaction.subscription_id == sub)):
            if norm_state(status) in PAYKU_PENDING_STATES:
                pending.append(ext)
    return pending, processing, in_progress


def stop_step_action(channel: str, options: dict[str, Any]) -> tuple[str, bool]:
    """(accion, reversible) del paso de detener la suscripcion."""
    if channel in ("virtualpos1", "virtualpos2"):
        return "cancel_subscription", False
    if channel == "toku":
        return ("set_end_date", True) if options.get("toku_stop_mode") == "end_date" else ("pause_subscription", True)
    if channel == "payku":
        return "delete_subscription", False
    return "register_internal", True


def build_cascade_preview(db: Session, channel: str, sub: str, options: dict[str, Any]) -> dict[str, Any]:
    """Que se cancelara, segun la ultima sincronizacion LOCAL (el ejecutor relee el proveedor antes de actuar).

    Solo ids internos de cobros y conteos: nada de datos personales. `blockers` lista motivos que negarian la baja."""
    status = subscription_status(db, channel, sub)
    pending, processing, in_progress = _charge_rows(db, channel, sub)
    action, reversible = stop_step_action(channel, options)
    blockers: list[str] = []
    if channel == "toku" and in_progress:
        blockers.append("INVOICE_IN_PROGRESS")  # D30
    if channel == "payku" and options.get("confirm_irreversible") is not True:
        blockers.append("IRREVERSIBILITY_NOT_CONFIRMED")
    charges_action = {
        "virtualpos1": "cancel_by_charge_id", "virtualpos2": "cancel_by_charge_id", "toku": "void_invoices",
        "payku": "verify_only_no_api", "tch": "not_applicable",
    }[channel]
    payment_reason = {
        "virtualpos1": "no_api", "virtualpos2": "no_api", "toku": "decision_pending",
        "payku": "q09_unvalidated", "tch": "bank_mandate_outside_crm",
    }[channel]
    return {
        "channel": channel,
        "subscription_status": status,
        "irreversible": not reversible,
        "pending_charges": len(pending),
        "pending_charge_ids": sorted(pending)[:PREVIEW_ID_LIMIT],
        "processing_charges": len(processing),
        "in_progress_invoices": len(in_progress),
        "blockers": blockers,
        "steps": [
            {"step": "stop_subscription", "action": action, "reversible": reversible},
            {"step": "cancel_pending_charges", "action": charges_action, "count": len(pending)},
            {"step": "payment_method", "action": "manual_task", "reason": payment_reason},
        ] if channel != "tch" else [
            {"step": "register_internal", "action": action, "reversible": True},
            {"step": "bank_mandate", "action": "manual_task", "reason": payment_reason},
        ],
        "source": "local_last_sync",
    }


# ----------------------------- creacion -----------------------------


@dataclass
class CancellationParams:
    channel: str
    subscription_external_id: str
    reason_code: str
    reason_comment: str
    toku_stop_mode: str | None = None
    toku_end_date: date | None = None
    confirm_irreversible: bool = False


@dataclass
class PreparedCancellation:
    request: SubscriptionCancellationRequest  # transitorio (no agregado a la sesion)
    preview: dict[str, Any]
    policy: Any
    approvals_required: int
    warnings: list[str] = field(default_factory=list)


def _chile_today(now: datetime | None) -> date:
    return br.ba._chile_now(now).date()


def _utc(now: datetime | None) -> datetime:
    return br._utc(now)


def _normalize_options(p: CancellationParams, today: date) -> dict[str, Any]:
    options: dict[str, Any] = {}
    if p.channel == "toku":
        mode = p.toku_stop_mode or "paused"
        if mode not in TOKU_STOP_MODES:
            raise InvalidFieldsError(f"toku_stop_mode debe ser uno de: {', '.join(TOKU_STOP_MODES)}.")
        options["toku_stop_mode"] = mode
        if mode == "end_date":
            if p.toku_end_date is None:
                raise InvalidFieldsError("toku_stop_mode=end_date requiere toku_end_date.")
            if not today <= p.toku_end_date <= today + timedelta(days=366 * 5):
                raise InvalidFieldsError("toku_end_date debe estar entre hoy y 5 años desde hoy (hora de Chile).")
            options["toku_end_date"] = p.toku_end_date.isoformat()
        elif p.toku_end_date is not None:
            raise InvalidFieldsError("toku_end_date solo aplica con toku_stop_mode=end_date.")
    else:
        if p.toku_stop_mode is not None or p.toku_end_date is not None:
            raise InvalidFieldsError("toku_stop_mode y toku_end_date solo aplican al canal toku.")
    if p.channel == "payku":
        if p.confirm_irreversible is not True:
            raise IrreversibleNotConfirmedError
        options["confirm_irreversible"] = True
    elif p.confirm_irreversible:
        raise InvalidFieldsError("confirm_irreversible solo aplica al canal payku.")
    return options


def prepare_request(db: Session, params: CancellationParams, *, now: datetime | None = None) -> PreparedCancellation:
    """Valida, fija la vista previa de la cascada (lectura local) y arma la solicitud sin guardarla."""
    p = params
    p.channel = normalize_channel(p.channel)
    p.subscription_external_id = (p.subscription_external_id or "").strip()
    if not p.subscription_external_id:
        raise InvalidFieldsError("subscription_external_id es obligatorio.")
    if p.reason_code not in REASON_CODES:
        raise InvalidFieldsError(f"reason_code debe ser uno de: {', '.join(REASON_CODES)}.")
    comment = (p.reason_comment or "").strip()
    if not comment:
        raise CommentRequiredError("El comentario del motivo es obligatorio y no puede estar vacío.")
    options = _normalize_options(p, _chile_today(now))
    status = subscription_status(db, p.channel, p.subscription_external_id)
    if status is None:
        raise SubscriptionUnknownError("Suscripción no encontrada.")
    if is_terminal_status(status):
        raise SubscriptionNotActiveError(status)
    policy = br.get_policy(db)
    preview = build_cascade_preview(db, p.channel, p.subscription_external_id, options)
    required = br.required_approvals(policy, subscriptions=1, variation_pct=None)
    req = SubscriptionCancellationRequest(
        id=uuid.uuid4(), channel=p.channel, subscription_external_id=p.subscription_external_id, status="pending",
        reason_code=p.reason_code, reason_comment=comment, options=options, cascade_preview=preview, steps=[],
        rules_snapshot={"self_approval_enabled": bool(policy.self_approval_enabled),
                        "dual_approval_enabled": bool(policy.dual_approval_enabled),
                        "request_expiry_days": int(policy.request_expiry_days)},
        approvals_required=required, approvals_count=0, self_approved=False, requires_reconciliation=False,
    )
    return PreparedCancellation(request=req, preview=preview, policy=policy, approvals_required=required)


def find_open_request(db: Session, channel: str, sub: str) -> SubscriptionCancellationRequest | None:
    return db.scalar(select(SubscriptionCancellationRequest).where(
        SubscriptionCancellationRequest.channel == channel,
        SubscriptionCancellationRequest.subscription_external_id == sub,
        SubscriptionCancellationRequest.status.in_(OPEN_STATUSES)).limit(1))


def _event(db: Session, req_id: uuid.UUID, event_type: str, actor_id: uuid.UUID | None,
           detail: dict[str, Any] | None = None) -> None:
    db.add(SubscriptionCancellationRequestEvent(
        request_id=req_id, event_type=event_type, actor_user_id=actor_id, detail=detail or {},
        created_at=datetime.now(UTC)))  # reloj real: orden estable dentro de una transaccion


def is_approver(user: User) -> bool:
    """Aprobador = usuario activo con el permiso `subscriptions.cancellation.approve` (admin y jefatura, D12)."""
    return bool(getattr(user, "is_active", True)) and CANCELLATION_APPROVE in permission_codes(user)


def create_request(
    db: Session, actor: User, params: CancellationParams, *, now: datetime | None = None
) -> SubscriptionCancellationRequest:
    """Crea la solicitud (`pending`, o `approved` si se autoaprueba, con evento `self_approved`). No escribe en proveedores."""
    channel = normalize_channel(params.channel)
    existing = find_open_request(db, channel, (params.subscription_external_id or "").strip())
    if existing is not None:
        raise OpenRequestExistsError(existing.id, existing.status)
    prepared = prepare_request(db, params, now=now)
    req, policy = prepared.request, prepared.policy
    created = _utc(now)
    req.requested_by_user_id = actor.id
    req.expires_at = created + timedelta(days=int(policy.request_expiry_days))
    db.add(req)
    db.flush()
    _event(db, req.id, "created", actor.id, {
        "channel": req.channel, "reason_code": req.reason_code, "approvals_required": req.approvals_required,
        "pending_charges": prepared.preview.get("pending_charges"), "blockers": prepared.preview.get("blockers")})
    if policy.self_approval_enabled and is_approver(actor):
        req.approvals_count = 1
        req.self_approved = True
        final = req.approvals_count >= req.approvals_required
        if final:
            req.status = "approved"
            req.approved_by_user_id = actor.id
            req.decided_at = created
        _event(db, req.id, "self_approved", actor.id, {
            "self_approved": True, "approvals_count": req.approvals_count,
            "approvals_required": req.approvals_required, "final": final})
    try:
        db.commit()
    except IntegrityError:  # carrera con otra creacion: indice unico parcial
        db.rollback()
        other = find_open_request(db, req.channel, req.subscription_external_id)
        raise OpenRequestExistsError(other.id if other else None, other.status if other else None) from None
    db.refresh(req)
    return req


# ----------------------------- transiciones -----------------------------


def _lock_request(db: Session, request_id: uuid.UUID) -> SubscriptionCancellationRequest:
    req = db.scalar(select(SubscriptionCancellationRequest).where(SubscriptionCancellationRequest.id == request_id)
                    .with_for_update().execution_options(populate_existing=True))
    if req is None:
        raise RequestNotFoundError("Solicitud no encontrada.")
    return req


def _current_status_of(db: Session, request_id: uuid.UUID) -> str:
    return str(db.scalar(select(SubscriptionCancellationRequest.status).where(
        SubscriptionCancellationRequest.id == request_id)) or "unknown")


def _clean_comment(comment: str | None, *, required: bool) -> str | None:
    text = (comment or "").strip()
    if required and not text:
        raise CommentRequiredError("El comentario es obligatorio y no puede estar vacío.")
    return text or None


def _require_approver(actor: User, request_id: uuid.UUID, action: str) -> None:
    if not is_approver(actor):
        log.warning("cancelacion intento denegado: accion=%s solicitud=%s usuario=%s", action, request_id, actor.id)
        raise NotApproverError


def _approver_ids(db: Session, request_id: uuid.UUID) -> set[uuid.UUID]:
    last_reopen = db.scalar(select(func.max(SubscriptionCancellationRequestEvent.created_at)).where(
        SubscriptionCancellationRequestEvent.request_id == request_id,
        SubscriptionCancellationRequestEvent.event_type == "reopened"))
    q = select(SubscriptionCancellationRequestEvent.actor_user_id).where(
        SubscriptionCancellationRequestEvent.request_id == request_id,
        SubscriptionCancellationRequestEvent.event_type.in_(("approved", "self_approved")))
    if last_reopen is not None:
        q = q.where(SubscriptionCancellationRequestEvent.created_at > last_reopen)
    return {a for a in db.scalars(q) if a is not None}


def _expire_one(db: Session, req: SubscriptionCancellationRequest, when: datetime) -> None:
    db.execute(update(SubscriptionCancellationRequest)
               .where(SubscriptionCancellationRequest.id == req.id, SubscriptionCancellationRequest.status == "pending")
               .values(status="expired", decided_at=when, updated_at=func.now())
               .execution_options(synchronize_session=False))
    _event(db, req.id, "expired", None, {"expires_at": req.expires_at.isoformat() if req.expires_at else None})


def approve(db: Session, request_id: uuid.UUID, actor: User, comment: str | None = None, *,
            now: datetime | None = None) -> SubscriptionCancellationRequest:
    """Aprueba (o autoaprueba) una solicitud `pending`. Con doble aprobacion hacen falta aprobadores DISTINTOS."""
    text = _clean_comment(comment, required=False)
    when = _utc(now)
    req = _lock_request(db, request_id)
    if req.status != "pending":
        db.rollback()
        raise RequestStateConflictError(req.status, ("pending",))
    if req.expires_at is not None and req.expires_at <= when:
        _expire_one(db, req, when)
        db.commit()
        raise RequestExpiredError
    _require_approver(actor, req.id, "approve")
    policy = br.get_policy(db)
    is_self = actor.id == req.requested_by_user_id
    if is_self and not policy.self_approval_enabled:
        log.warning("cancelacion autoaprobacion denegada: solicitud=%s usuario=%s", req.id, actor.id)
        db.rollback()
        raise SelfApprovalNotAllowedError
    if actor.id in _approver_ids(db, req.id):
        db.rollback()
        raise DuplicateApproverError
    new_count = int(req.approvals_count) + 1
    final = new_count >= int(req.approvals_required)
    values: dict[str, Any] = {
        "approvals_count": new_count, "self_approved": bool(req.self_approved) or is_self, "updated_at": func.now()}
    if final:
        values.update(status="approved", approved_by_user_id=actor.id, decided_at=when)
    updated = db.execute(
        update(SubscriptionCancellationRequest)
        .where(SubscriptionCancellationRequest.id == req.id, SubscriptionCancellationRequest.status == "pending",
               SubscriptionCancellationRequest.approvals_count == req.approvals_count)
        .values(**values).execution_options(synchronize_session=False)
    ).rowcount
    if updated != 1:
        db.rollback()
        raise RequestStateConflictError(_current_status_of(db, request_id), ("pending",))
    _event(db, req.id, "self_approved" if is_self else "approved", actor.id, {
        "approvals_count": new_count, "approvals_required": int(req.approvals_required), "final": final,
        "self_approved": is_self, "comment": text})
    db.commit()
    db.refresh(req)
    return req


def reject(db: Session, request_id: uuid.UUID, actor: User, comment: str | None, *,
           now: datetime | None = None) -> SubscriptionCancellationRequest:
    """Rechaza una solicitud `pending`. Comentario obligatorio (el CHECK de BD tambien lo exige)."""
    text = _clean_comment(comment, required=True)
    req = _lock_request(db, request_id)
    if req.status != "pending":
        db.rollback()
        raise RequestStateConflictError(req.status, ("pending",))
    _require_approver(actor, req.id, "reject")
    updated = db.execute(
        update(SubscriptionCancellationRequest)
        .where(SubscriptionCancellationRequest.id == req.id, SubscriptionCancellationRequest.status == "pending")
        .values(status="rejected", decision_comment=text, decided_at=_utc(now), updated_at=func.now())
        .execution_options(synchronize_session=False)
    ).rowcount
    if updated != 1:
        db.rollback()
        raise RequestStateConflictError(_current_status_of(db, request_id), ("pending",))
    _event(db, req.id, "rejected", actor.id, {"comment": text})
    db.commit()
    db.refresh(req)
    return req


def withdraw(db: Session, request_id: uuid.UUID, actor: User, comment: str | None = None, *,
             now: datetime | None = None) -> SubscriptionCancellationRequest:
    """Retira una solicitud `pending`: solo su solicitante o un admin (propiedad antes que estado: 403 antes que 409)."""
    text = _clean_comment(comment, required=False)
    req = _lock_request(db, request_id)
    if actor.id != req.requested_by_user_id and not any(r.name == ADMIN_ROLE for r in actor.roles):
        db.rollback()
        raise NotAllowedError("Solo el solicitante o un administrador puede retirar la solicitud.")
    if req.status != "pending":
        db.rollback()
        raise RequestStateConflictError(req.status, ("pending",))
    updated = db.execute(
        update(SubscriptionCancellationRequest)
        .where(SubscriptionCancellationRequest.id == req.id, SubscriptionCancellationRequest.status == "pending")
        .values(status="withdrawn", decided_at=_utc(now), updated_at=func.now())
        .execution_options(synchronize_session=False)
    ).rowcount
    if updated != 1:
        db.rollback()
        raise RequestStateConflictError(_current_status_of(db, request_id), ("pending",))
    _event(db, req.id, "withdrawn", actor.id, {"comment": text})
    db.commit()
    db.refresh(req)
    return req


def reopen(db: Session, request_id: uuid.UUID, actor: User, comment: str | None, *,
           now: datetime | None = None) -> SubscriptionCancellationRequest:
    """`failed` / `requires_reconciliation` -> `approved` (o `pending` si la politica exige dos aprobaciones).

    Comentario obligatorio; solo un aprobador. Los PASOS ya hechos se conservan: el siguiente `apply` reanuda desde el
    paso fallido (no repite lo hecho). Sin reintento automatico."""
    text = _clean_comment(comment, required=True)
    req = _lock_request(db, request_id)
    if req.status not in REOPENABLE_STATUSES:
        db.rollback()
        raise RequestStateConflictError(req.status, REOPENABLE_STATUSES)
    _require_approver(actor, req.id, "reopen")
    policy = br.get_policy(db)
    required = br.required_approvals(policy, subscriptions=1, variation_pct=None)
    previous_status, previous_error = req.status, req.error_message
    previous_count, previous_required = int(req.approvals_count), int(req.approvals_required)
    when = _utc(now)
    new_status = "approved" if required == 1 else "pending"
    values: dict[str, Any] = {
        "status": new_status, "error_message": None, "requires_reconciliation": False, "approvals_count": 0,
        "approvals_required": required, "decided_at": when if new_status == "approved" else None,
        "updated_at": func.now()}
    if new_status == "pending":
        values["expires_at"] = when + timedelta(days=int(policy.request_expiry_days))
    else:
        values["approved_by_user_id"] = actor.id
    try:
        with db.begin_nested():
            updated = db.execute(
                update(SubscriptionCancellationRequest)
                .where(SubscriptionCancellationRequest.id == req.id,
                       SubscriptionCancellationRequest.status == previous_status)
                .values(**values).execution_options(synchronize_session=False)
            ).rowcount
    except IntegrityError:
        db.rollback()
        raise OpenRequestExistsError(None, None) from None
    if updated != 1:
        db.rollback()
        raise RequestStateConflictError(_current_status_of(db, request_id), REOPENABLE_STATUSES)
    _event(db, req.id, "reopened", actor.id, {
        "from_status": previous_status, "to_status": new_status, "comment": text, "previous_error": previous_error,
        "previous_approvals_count": previous_count, "previous_approvals_required": previous_required,
        "new_approvals_required": required, "steps_kept": [s.get("step") for s in (req.steps or [])
                                                            if s.get("status") == "done"]})
    db.commit()
    db.refresh(req)
    return req


def expire_pending_cancellation_requests(db: Session, now: datetime | None = None) -> list[uuid.UUID]:
    """Pasa a `expired` las `pending` con `expires_at <= now` (limite INCLUSIVO). Idempotente; evento con actor NULL."""
    when = _utc(now)
    rows = db.execute(
        update(SubscriptionCancellationRequest)
        .where(SubscriptionCancellationRequest.status == "pending",
               SubscriptionCancellationRequest.expires_at.is_not(None),
               SubscriptionCancellationRequest.expires_at <= when)
        .values(status="expired", decided_at=when, updated_at=func.now())
        .returning(SubscriptionCancellationRequest.id, SubscriptionCancellationRequest.expires_at)
        .execution_options(synchronize_session=False)
    ).all()
    for rid, expires_at in rows:
        _event(db, rid, "expired", None, {"expires_at": expires_at.isoformat() if expires_at else None})
    db.commit()
    return [r[0] for r in rows]


# ----------------------------- consulta -----------------------------


@dataclass
class RequestFilters:
    statuses: list[str] | None = None
    channel: str | None = None
    subscription_external_id: str | None = None
    requested_by_user_id: uuid.UUID | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    limit: int = 50
    offset: int = 0


def list_requests(db: Session, f: RequestFilters) -> tuple[list[SubscriptionCancellationRequest], int]:
    model = SubscriptionCancellationRequest
    q = select(model)
    if f.statuses:
        q = q.where(model.status.in_(f.statuses))
    if f.channel:
        q = q.where(model.channel == normalize_channel(f.channel))
    if f.subscription_external_id:
        q = q.where(model.subscription_external_id == f.subscription_external_id)
    if f.requested_by_user_id:
        q = q.where(model.requested_by_user_id == f.requested_by_user_id)
    if f.created_from:
        q = q.where(model.created_at >= f.created_from)
    if f.created_to:
        q = q.where(model.created_at <= f.created_to)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(model.created_at.desc(), model.id).limit(f.limit).offset(f.offset)).all()
    return list(rows), total


def get_request(db: Session, request_id: uuid.UUID) -> SubscriptionCancellationRequest:
    req = db.get(SubscriptionCancellationRequest, request_id)
    if req is None:
        raise RequestNotFoundError("Solicitud no encontrada.")
    return req


def get_events(db: Session, request_id: uuid.UUID) -> list[SubscriptionCancellationRequestEvent]:
    model = SubscriptionCancellationRequestEvent
    return list(db.scalars(select(model).where(model.request_id == request_id).order_by(model.created_at, model.id)))


usernames = br.usernames
