"""API REST de solicitudes de baja de suscripcion multicanal (MGT-07/08/09/10; `/api/v1/cancellations`).

Rutas finas: la logica vive en `app/services/cancellation_requests.py` (ciclo de vida y aprobacion) y
`app/services/cancellation_apply.py` (ejecucion). El actor SIEMPRE sale del usuario autenticado (los cuerpos rechazan
campos extra). Toda escritura exige CSRF. Permisos (D12): `subscriptions.cancellation.request|approve|view`.
Los errores salen como `detail = {"code", "message", ...}`: mensajes fijos, sin eco de valores recibidos ni textos del
proveedor.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, time
from typing import Annotated, Any, Literal, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.api.v1.routes.billing_changes import _NoEchoRoute
from app.api.v1.routes.crm import get_db
from app.core.security import require_csrf, require_permissions
from app.models.auth import User
from app.models.cancellation import (
    SubscriptionCancellationRequest,
    SubscriptionCancellationRequestEvent,
)
from app.services import cancellation_apply as ca
from app.services import cancellation_requests as cr
from app.services.rbac import (
    CANCELLATION_APPROVE,
    CANCELLATION_REQUEST,
    CANCELLATION_VIEW,
)

log = logging.getLogger(__name__)

router = APIRouter(route_class=_NoEchoRoute)
TAGS = ["Cancellations"]

ChannelLiteral = Literal["virtualpos1", "virtualpos2", "toku", "payku", "tch"]
StatusLiteral = Literal[
    "pending", "approved", "applying", "pending_external", "completed", "failed", "requires_reconciliation",
    "rejected", "withdrawn", "expired", "not_executable",
]
ReasonLiteral = Literal[
    "member_request", "payment_failure", "duplicate_subscription", "deceased", "fraud_suspected",
    "organization_decision", "other",
]

# ----------------------------- esquemas -----------------------------


class CancellationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: ChannelLiteral
    subscription_external_id: str = Field(min_length=1, max_length=255)
    reason_code: ReasonLiteral
    reason_comment: str = Field(min_length=1, max_length=2000)
    toku_stop_mode: Literal["paused", "end_date"] | None = None
    toku_end_date: date | None = None
    confirm_irreversible: bool = False

    @field_validator("reason_comment")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("El comentario del motivo es obligatorio y no puede estar vacío.")
        return value

    def to_params(self) -> cr.CancellationParams:
        return cr.CancellationParams(**self.model_dump())


class CommentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: str | None = Field(default=None, max_length=2000)


class RequiredCommentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comment: str = Field(min_length=1, max_length=2000)

    @field_validator("comment")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("El comentario es obligatorio y no puede estar vacío.")
        return value


class ApplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = False


# ----------------------------- errores -----------------------------


def _detail(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **extra}


_BLOCKED_MESSAGES = {
    "INVOICE_IN_PROGRESS": "La suscripción tiene una factura en proceso de cobro: la baja no se realizó.",
    "INVOICE_LIST_FAILED": "No se pudo leer las facturas de la suscripción: la baja no se realizó.",
    "IRREVERSIBILITY_NOT_CONFIRMED": "La baja es irreversible y no fue confirmada de forma explícita.",
}


def _http(exc: BaseException) -> NoReturn:
    """Traduce errores tipados a HTTPException. Lo desconocido se re-lanza (500)."""
    if isinstance(exc, cr.RequestStateConflictError):
        raise HTTPException(409, _detail(exc.code, str(exc), current_status=exc.current_status, expected=list(exc.expected)))
    if isinstance(exc, cr.OpenRequestExistsError):
        raise HTTPException(409, _detail(exc.code, str(exc), open_request_id=str(exc.request_id) if exc.request_id else None,
                                         open_request_status=exc.status))
    if isinstance(exc, ca.InvalidRequestStateError):
        raise HTTPException(409, _detail(exc.code, str(exc), current_status=exc.status))
    if isinstance(exc, ca.SubscriptionBusyError):
        raise HTTPException(409, _detail("subscription_busy",
                                         "Otra operación está modificando esta suscripción; reintente en unos segundos."))
    if isinstance(exc, ca.BlockedError):
        raise HTTPException(409, _detail(exc.code, _BLOCKED_MESSAGES.get(exc.code, "La baja no se realizó."),
                                         request_status="approved"))
    if isinstance(exc, cr.RequestExpiredError | cr.DuplicateApproverError):
        raise HTTPException(409, _detail(exc.code, str(exc)))
    if isinstance(exc, ca.WritesDisabledError):
        raise HTTPException(403, _detail(exc.code, "Las escrituras al canal están deshabilitadas.", channel=exc.channel))
    if isinstance(exc, ca.ApplyFailedError):
        raise HTTPException(502, _detail(
            "apply_failed", "La baja falló en un paso sin efectos previos; un aprobador puede reabrir la solicitud.",
            request_status="failed", step=exc.step, step_code=exc.step_code))
    if isinstance(exc, ca.ReconciliationRequiredError):
        raise HTTPException(503, _detail(
            "reconciliation_required",
            "La baja quedó incompleta y requiere conciliación; un aprobador puede reabrirla para reanudar desde el paso fallido.",
            request_status="requires_reconciliation", step=exc.step, step_code=exc.step_code))
    if isinstance(exc, cr.RequestNotFoundError):
        raise HTTPException(404, _detail(exc.code, "Solicitud no encontrada."))
    if isinstance(exc, cr.SubscriptionUnknownError):
        raise HTTPException(404, _detail(exc.code, "Suscripción no encontrada."))
    if isinstance(exc, cr.SubscriptionNotActiveError):
        raise HTTPException(422, _detail(exc.code, str(exc), subscription_status=exc.status))
    if isinstance(exc, cr.InvalidFieldsError | cr.CommentRequiredError | cr.IrreversibleNotConfirmedError):
        raise HTTPException(422, _detail(exc.code, str(exc)))
    if isinstance(exc, cr.NotApproverError | cr.SelfApprovalNotAllowedError | cr.NotAllowedError):
        raise HTTPException(403, _detail(exc.code, str(exc)))
    raise exc


_HANDLED = (cr.CancellationError, ca.CancellationApplyError)

# ----------------------------- serializacion -----------------------------


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _safe_steps(steps: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Pasos con codigos fijos; el campo `error` (etiqueta de tipo) se conserva, nunca texto libre."""
    return [dict(s) for s in (steps or []) if isinstance(s, dict)]


def _request_json(r: SubscriptionCancellationRequest, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "id": str(r.id), "channel": r.channel, "subscription_external_id": r.subscription_external_id,
        "status": r.status, "reason_code": r.reason_code, "reason_comment": r.reason_comment,
        "requested_by_user_id": str(r.requested_by_user_id), "requested_by": names.get(r.requested_by_user_id),
        "approved_by_user_id": str(r.approved_by_user_id) if r.approved_by_user_id else None,
        "approved_by": names.get(r.approved_by_user_id) if r.approved_by_user_id else None,
        "self_approved": r.self_approved, "approvals_required": r.approvals_required,
        "approvals_count": r.approvals_count, "decided_at": _iso(r.decided_at), "decision_comment": r.decision_comment,
        "options": r.options or {}, "requires_reconciliation": r.requires_reconciliation,
        "write_run_id": str(r.write_run_id) if r.write_run_id else None, "expires_at": _iso(r.expires_at),
        "executed_at": _iso(r.executed_at), "error_message": r.error_message,
        "created_at": _iso(r.created_at), "updated_at": _iso(r.updated_at),
    }


def _event_json(e: SubscriptionCancellationRequestEvent, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "id": str(e.id), "event_type": e.event_type,
        "actor_user_id": str(e.actor_user_id) if e.actor_user_id else None,
        "actor": names.get(e.actor_user_id) if e.actor_user_id else "sistema",
        "detail": e.detail or {}, "created_at": _iso(e.created_at),
    }


def _detail_json(db: Session, r: SubscriptionCancellationRequest) -> dict[str, Any]:
    events = cr.get_events(db, r.id)
    names = cr.usernames(db, {r.requested_by_user_id, r.approved_by_user_id, *(e.actor_user_id for e in events)})
    return {**_request_json(r, names), "cascade_preview": r.cascade_preview or {}, "steps": _safe_steps(r.steps),
            "rules_snapshot": r.rules_snapshot or {}, "events": [_event_json(e, names) for e in events]}


def _apply_json(result: ca.CancellationApplyResult, request: SubscriptionCancellationRequest) -> dict[str, Any]:
    return {
        "request_id": str(result.request_id), "status": result.status, "request_status": request.status,
        "already_applied": result.already_applied, "dry_run": result.dry_run, "reason": result.reason,
        "steps": _safe_steps(result.steps), "plan": result.plan,
        "write_run_id": str(result.write_run_id) if result.write_run_id else None,
    }


# ----------------------------- rutas -----------------------------

Db = Annotated[Session, Depends(get_db)]
Requester = Annotated[User, Depends(require_permissions(CANCELLATION_REQUEST))]
Approver = Annotated[User, Depends(require_permissions(CANCELLATION_APPROVE))]
Viewer = Annotated[User, Depends(require_permissions(CANCELLATION_VIEW))]
_CSRF = [Depends(require_csrf)]


@router.post("/preview", dependencies=_CSRF, tags=TAGS)
def preview_cancellation(body: CancellationBody, current_user: Requester, db: Db) -> dict:
    """Vista previa de la cascada (solo lectura local, no guarda nada): que se cancelara y que quedara manual."""
    try:
        prepared = cr.prepare_request(db, body.to_params())
    except _HANDLED as exc:
        raise _http(exc) from None
    req = prepared.request
    open_req = cr.find_open_request(db, req.channel, req.subscription_external_id)
    return {
        "cascade_preview": prepared.preview, "options": req.options, "approvals_required": prepared.approvals_required,
        "would_self_approve": bool(prepared.policy.self_approval_enabled and cr.is_approver(current_user)),
        "expires_in_days": int(prepared.policy.request_expiry_days),
        "open_request": {"id": str(open_req.id), "status": open_req.status} if open_req else None,
    }


@router.post("", status_code=201, dependencies=_CSRF, tags=TAGS)
def create_cancellation(body: CancellationBody, current_user: Requester, db: Db) -> dict:
    """Crea la solicitud con motivo obligatorio. Si la política lo permite y el solicitante aprueba, queda autoaprobada (auditada)."""
    try:
        req = cr.create_request(db, current_user, body.to_params())
    except _HANDLED as exc:
        raise _http(exc) from None
    return _detail_json(db, req)


@router.get("", tags=TAGS)
def list_cancellations(
    _user: Viewer,
    db: Db,
    status: Annotated[list[StatusLiteral] | None, Query()] = None,
    channel: ChannelLiteral | None = None,
    subscription_id: Annotated[str | None, Query(max_length=255)] = None,
    requested_by: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    filters = cr.RequestFilters(
        statuses=list(status) if status else None, channel=channel, subscription_external_id=subscription_id,
        requested_by_user_id=requested_by,
        created_from=datetime.combine(date_from, time.min, tzinfo=UTC) if date_from else None,
        created_to=datetime.combine(date_to, time.max, tzinfo=UTC) if date_to else None,
        limit=limit, offset=offset)
    rows, total = cr.list_requests(db, filters)
    names = cr.usernames(db, {i for r in rows for i in (r.requested_by_user_id, r.approved_by_user_id)})
    return {"items": [_request_json(r, names) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/{request_id}", tags=TAGS)
def get_cancellation(request_id: uuid.UUID, _user: Viewer, db: Db) -> dict:
    try:
        return _detail_json(db, cr.get_request(db, request_id))
    except _HANDLED as exc:
        raise _http(exc) from None


@router.get("/{request_id}/events", tags=TAGS)
def get_cancellation_events(request_id: uuid.UUID, _user: Viewer, db: Db) -> dict:
    try:
        cr.get_request(db, request_id)
    except _HANDLED as exc:
        raise _http(exc) from None
    events = cr.get_events(db, request_id)
    names = cr.usernames(db, {e.actor_user_id for e in events})
    return {"items": [_event_json(e, names) for e in events], "total": len(events)}


@router.post("/{request_id}/approve", dependencies=_CSRF, tags=TAGS)
def approve_cancellation(request_id: uuid.UUID, current_user: Approver, db: Db, body: CommentBody | None = None) -> dict:
    try:
        req = cr.approve(db, request_id, current_user, body.comment if body else None)
    except _HANDLED as exc:
        raise _http(exc) from None
    return _detail_json(db, req)


@router.post("/{request_id}/reject", dependencies=_CSRF, tags=TAGS)
def reject_cancellation(request_id: uuid.UUID, body: RequiredCommentBody, current_user: Approver, db: Db) -> dict:
    try:
        req = cr.reject(db, request_id, current_user, body.comment)
    except _HANDLED as exc:
        raise _http(exc) from None
    return _detail_json(db, req)


@router.post("/{request_id}/withdraw", dependencies=_CSRF, tags=TAGS)
def withdraw_cancellation(request_id: uuid.UUID, current_user: Requester, db: Db, body: CommentBody | None = None) -> dict:
    """Retira una solicitud pendiente (solo su solicitante o un admin)."""
    try:
        req = cr.withdraw(db, request_id, current_user, body.comment if body else None)
    except _HANDLED as exc:
        raise _http(exc) from None
    return _detail_json(db, req)


@router.post("/{request_id}/reopen", dependencies=_CSRF, tags=TAGS)
def reopen_cancellation(request_id: uuid.UUID, body: RequiredCommentBody, current_user: Approver, db: Db) -> dict:
    """Reabre una solicitud `failed` / `requires_reconciliation` (comentario obligatorio): el siguiente apply reanuda
    desde el paso fallido sin repetir lo hecho."""
    try:
        req = cr.reopen(db, request_id, current_user, body.comment)
    except _HANDLED as exc:
        raise _http(exc) from None
    return _detail_json(db, req)


@router.post("/{request_id}/apply", dependencies=_CSRF, tags=TAGS)
async def apply_cancellation(request_id: uuid.UUID, current_user: Approver, db: Db, body: ApplyBody | None = None) -> dict:
    """Ejecuta una solicitud aprobada (o `dry_run=true` para ver el plan sin escribir). Solo aprobadores."""
    try:
        result = await ca.apply_cancellation_request(
            db, request_id, actor_user_id=current_user.id, dry_run=bool(body and body.dry_run))
    except _HANDLED as exc:
        raise _http(exc) from None
    return _apply_json(result, cr.get_request(db, request_id))
