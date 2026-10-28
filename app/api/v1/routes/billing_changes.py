"""API REST de solicitudes de cambio de cobro VirtualPOS y politica de aprobadores (opcion A, paso 4).

Rutas finas: toda la logica vive en `app/services/billing_requests.py`. El actor SIEMPRE sale del usuario
autenticado (los cuerpos rechazan campos extra, p. ej. un `requested_by_user_id`). Ninguna ruta llama al DELETE plural
del proveedor: la ejecucion pasa por `billing_apply`, que cancela cobro por cobro.
Los errores salen como `detail = {"code", "message", ...}`; nunca incluyen payloads del proveedor, PII ni credenciales.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Annotated, Any, Literal, NoReturn

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from httpx import HTTPStatusError
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db
from app.core.security import require_any_permission, require_csrf, require_permissions
from app.integrations.virtualpos.client import VirtualPOSAPIError
from app.models.auth import User
from app.models.billing import (
    BillingChangeRequest,
    BillingChangeRequestEvent,
    BillingPolicy,
    BillingPolicyAudit,
)
from app.services import billing_requests as svc
from app.services.billing_apply import (
    ApplyFailedError,
    ApplyResult,
    InvalidRequestStateError,
    PlanDriftError,
    RequestNotFoundError,
    SubscriptionBlockedError,
    SubscriptionBusyError,
)
from app.services.billing_plan import plan_to_preview_json
from app.services.write_virtualpos import (
    FixedPlanChargeBlockedError,
    ReconciliationRequiredError,
    WriteDisabledError,
)

log = logging.getLogger(__name__)

router = APIRouter()
TAGS = ["Billing changes"]

RequestType = Literal["change_amount", "change_date", "renew_calendar", "one_off_charge"]
StatusLiteral = Literal[
    "pendiente", "aprobada", "aplicando", "ejecutada", "rechazada", "expirada", "retirada", "fallida",
    "requiere_conciliacion", "no_ejecutable",
]

_PROVIDER_ERRORS = (HTTPStatusError, VirtualPOSAPIError, httpx.TransportError)

# ----------------------------- esquemas -----------------------------


class ChangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_type: RequestType
    platform: str = Field(default="virtualpos1", max_length=20)
    subscription_external_id: str = Field(min_length=1, max_length=255)
    new_amount: int | None = Field(default=None, ge=1, le=10**10)
    new_charge_day: int | None = Field(default=None, ge=1, le=31)
    new_charge_date: date | None = None
    horizon_months: int | None = Field(default=None, ge=1, le=60)
    horizon_start_month: str | None = Field(default=None, pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    requester_comment: str | None = Field(default=None, max_length=2000)
    task_ref: str | None = Field(default=None, min_length=1, max_length=100)

    def to_params(self) -> svc.RequestParams:
        return svc.RequestParams(**self.model_dump())


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

    accept_drift: bool = False


class PolicyUpdateBody(BaseModel):
    """Parche parcial: solo los campos enviados cambian. `reason` queda en la auditoria."""

    model_config = ConfigDict(extra="forbid")

    approver_roles: list[str] | None = Field(default=None, max_length=50)
    approver_user_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)
    self_approval_enabled: bool | None = None
    dual_approval_enabled: bool | None = None
    dual_threshold_subscriptions: int | None = Field(default=None, ge=1, le=100_000)
    dual_threshold_variation_pct: Decimal | None = Field(default=None, ge=0, le=Decimal("9999.99"), decimal_places=2)
    renewal_threshold_days: int | None = Field(default=None, ge=1, le=3650)
    request_expiry_days: int | None = Field(default=None, ge=1, le=365)
    horizon_months: int | None = Field(default=None, ge=1, le=60)
    window_days: int | None = Field(default=None, ge=1, le=365)
    reason: str | None = Field(default=None, max_length=1000)

    def to_patch(self) -> dict[str, Any]:
        patch = self.model_dump(exclude_unset=True, exclude={"reason"})
        if patch.get("approver_user_ids") is not None:
            patch["approver_user_ids"] = [str(x) for x in patch["approver_user_ids"]]
        if patch.get("dual_threshold_variation_pct") is not None:
            patch["dual_threshold_variation_pct"] = float(patch["dual_threshold_variation_pct"])
        null_fields = [k for k, v in patch.items() if v is None]
        if null_fields:
            raise HTTPException(422, _detail("policy_invalid", f"Campos sin valor: {', '.join(sorted(null_fields))}."))
        return patch


# ----------------------------- errores -----------------------------


def _detail(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **extra}


def _http(exc: BaseException) -> NoReturn:
    """Traduce errores tipados a HTTPException. Lo desconocido se re-lanza (500)."""
    if isinstance(exc, PlanDriftError):
        raise HTTPException(409, _detail(
            "plan_drift", "El estado en VirtualPOS cambió desde la aprobación; el plan recalculado difiere del aprobado. "
                          "Revise la diferencia y, si la acepta, reintente con accept_drift=true.",
            diff=exc.diff, new_preview=exc.new_preview, retry_with={"accept_drift": True}))
    if isinstance(exc, InvalidRequestStateError):
        raise HTTPException(409, _detail("invalid_request_state", str(exc), current_status=exc.status))
    if isinstance(exc, svc.RequestStateConflictError):
        raise HTTPException(409, _detail(exc.code, str(exc), current_status=exc.current_status, expected=list(exc.expected)))
    if isinstance(exc, svc.OpenRequestExistsError):
        raise HTTPException(409, _detail(exc.code, str(exc),
                                         open_request_id=str(exc.request_id) if exc.request_id else None,
                                         open_request_status=exc.status))
    if isinstance(exc, SubscriptionBusyError):
        raise HTTPException(409, _detail("subscription_busy", "Otra operación está modificando esta suscripción; reintente en unos segundos."))
    if isinstance(exc, SubscriptionBlockedError):
        raise HTTPException(409, _detail("subscription_blocked", "La suscripción tiene cobros pendientes de conciliación."))
    if isinstance(exc, svc.RequestExpiredError | svc.DuplicateApproverError):
        raise HTTPException(409, _detail(exc.code, str(exc)))
    if isinstance(exc, ApplyFailedError):
        raise HTTPException(502, _detail(
            "apply_failed", "No se pudo aplicar el cambio en VirtualPOS. Se compensaron los cobros creados y el calendario "
                            "original quedó intacto. La solicitud quedó 'fallida'; un aprobador puede reabrirla.",
            request_status="fallida", compensated=len(exc.compensated)))
    if isinstance(exc, ReconciliationRequiredError):
        raise HTTPException(503, _detail(
            "reconciliation_required", "La aplicación quedó incompleta y requiere conciliación manual. "
                                       "La solicitud pasó a 'requiere_conciliacion'.", request_status="requiere_conciliacion"))
    if isinstance(exc, WriteDisabledError):
        raise HTTPException(403, _detail("writes_disabled", "Las escrituras a VirtualPOS están deshabilitadas."))
    if isinstance(exc, FixedPlanChargeBlockedError):
        raise HTTPException(422, _detail("fixed_plan_charge_blocked", str(exc)))
    if isinstance(exc, RequestNotFoundError):
        raise HTTPException(404, _detail("request_not_found", "Solicitud no encontrada."))
    if isinstance(exc, svc.SubscriptionUnknownError):
        raise HTTPException(404, _detail(exc.code, "Suscripción no encontrada."))
    if isinstance(exc, svc.SubscriptionNotActiveError):
        raise HTTPException(422, _detail(exc.code, str(exc), subscription_status=exc.status))
    if isinstance(exc, svc.PlanInvalidError):
        raise HTTPException(422, _detail(exc.code, str(exc), errors=exc.errors))
    if isinstance(exc, svc.NoChangesError):
        raise HTTPException(422, _detail(exc.code, str(exc)))
    if isinstance(exc, svc.PolicyValidationError):
        raise HTTPException(422, _detail(exc.code, str(exc), policy_code=exc.policy_code))
    if isinstance(exc, svc.InvalidRequestFieldsError | svc.CommentRequiredError):
        raise HTTPException(422, _detail(exc.code, str(exc)))
    if isinstance(exc, svc.NotApproverError | svc.SelfApprovalNotAllowedError | svc.NotAllowedError):
        raise HTTPException(403, _detail(exc.code, str(exc)))
    if isinstance(exc, _PROVIDER_ERRORS):
        # Mensaje generico: jamas se reenvia el cuerpo/mensaje del proveedor. Solo el codigo E-nnn, si lo hay.
        code = getattr(exc, "error_code", None)
        raise HTTPException(502, _detail(
            "provider_error", "VirtualPOS no respondió correctamente; no se escribió nada. Reintente más tarde.",
            provider_code=code if isinstance(code, str) and len(code) <= 10 else None))
    raise exc


_HANDLED = (
    PlanDriftError, InvalidRequestStateError, SubscriptionBusyError, SubscriptionBlockedError, ApplyFailedError,
    ReconciliationRequiredError, WriteDisabledError, FixedPlanChargeBlockedError, RequestNotFoundError,
    svc.BillingRequestError, *_PROVIDER_ERRORS,
)


# ----------------------------- serializacion -----------------------------


def _num(value: Any) -> int | float | None:
    if value is None:
        return None
    dec = Decimal(str(value))
    return int(dec) if dec == dec.to_integral_value() else float(dec)


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _request_json(r: BillingChangeRequest, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "id": str(r.id), "request_type": r.request_type, "platform": r.platform,
        "subscription_external_id": r.subscription_external_id, "status": r.status,
        "requested_by_user_id": str(r.requested_by_user_id), "requested_by": names.get(r.requested_by_user_id),
        "new_amount": _num(r.new_amount), "previous_amount": _num(r.previous_amount),
        "new_charge_day": r.new_charge_day, "previous_charge_day": r.previous_charge_day,
        "new_charge_date": _iso(r.new_charge_date), "horizon_months": r.horizon_months,
        "horizon_start_month": r.horizon_start_month,
        "approvals_required": r.approvals_required, "approvals_count": r.approvals_count,
        "requester_comment": r.requester_comment,
        "approved_by_user_id": str(r.approved_by_user_id) if r.approved_by_user_id else None,
        "approved_by": names.get(r.approved_by_user_id) if r.approved_by_user_id else None,
        "self_approved": r.self_approved, "decided_at": _iso(r.decided_at), "decision_comment": r.decision_comment,
        "write_run_id": str(r.write_run_id) if r.write_run_id else None, "expires_at": _iso(r.expires_at),
        "executed_at": _iso(r.executed_at), "error_message": r.error_message,
        "created_at": _iso(r.created_at), "updated_at": _iso(r.updated_at),
    }


def _event_json(e: BillingChangeRequestEvent, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "id": str(e.id), "event_type": e.event_type,
        "actor_user_id": str(e.actor_user_id) if e.actor_user_id else None,
        "actor": names.get(e.actor_user_id) if e.actor_user_id else "sistema",
        "detail": e.detail or {}, "created_at": _iso(e.created_at),
    }


def _detail_json(db: Session, r: BillingChangeRequest) -> dict[str, Any]:
    events = svc.get_events(db, r.id)
    names = svc.usernames(db, {r.requested_by_user_id, r.approved_by_user_id, *(e.actor_user_id for e in events)})
    return {**_request_json(r, names), "plan_preview": r.plan_preview or {}, "rules_snapshot": r.rules_snapshot or {},
            "events": [_event_json(e, names) for e in events]}


def _policy_json(p: BillingPolicy) -> dict[str, Any]:
    return {**svc.policy_values(p), "updated_by_user_id": str(p.updated_by_user_id) if p.updated_by_user_id else None,
            "updated_at": _iso(p.updated_at)}


def _audit_json(a: BillingPolicyAudit, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "id": str(a.id), "changed_by_user_id": str(a.changed_by_user_id) if a.changed_by_user_id else None,
        "changed_by": names.get(a.changed_by_user_id) if a.changed_by_user_id else None,
        "changed_at": _iso(a.changed_at), "before_values": a.before_values, "after_values": a.after_values,
        "reason": a.reason,
    }


def _apply_json(result: ApplyResult, request: BillingChangeRequest) -> dict[str, Any]:
    return {
        "request_id": str(result.request_id), "status": result.status, "request_status": request.status,
        "already_applied": result.already_applied, "reason": result.reason, "created": result.created,
        "cancelled": result.cancelled, "covered_late_months": result.covered_late_months,
        "manual_review_months": result.manual_review_months,
        "write_run_id": str(result.write_run_id) if result.write_run_id else None,
        "drift_accepted": result.drift_accepted,
        "plan_summary": (plan_to_preview_json(result.plan).get("summary") if result.plan is not None else None),
    }


# ----------------------------- solicitudes -----------------------------

Db = Annotated[Session, Depends(get_db)]
Requester = Annotated[User, Depends(require_permissions(svc.PERM_REQUEST))]
Approver = Annotated[User, Depends(require_permissions(svc.PERM_APPROVE))]
Viewer = Annotated[User, Depends(require_permissions(svc.PERM_VIEW))]
PolicyAdmin = Annotated[User, Depends(require_permissions(svc.PERM_POLICY))]
_CSRF = [Depends(require_csrf)]


@router.post("/changes/preview", dependencies=_CSRF, tags=TAGS)
async def preview_change_request(body: ChangeBody, current_user: Requester, db: Db) -> dict:
    """Vista previa de solo lectura (AP-29): calcula el plan con el estado actual del proveedor y NO guarda nada."""
    try:
        prepared = await svc.prepare_request(db, body.to_params())
    except _HANDLED as exc:
        raise _http(exc) from None
    req = prepared.request
    policy = prepared.policy
    open_req = svc.find_open_request(db, req.platform, req.subscription_external_id)
    return {
        "plan_preview": prepared.preview, "summary": prepared.preview.get("summary"),
        "approvals_required": prepared.approvals_required,
        "would_self_approve": bool(policy.self_approval_enabled and svc.is_approver(current_user, policy)),
        "expires_in_days": int(policy.request_expiry_days),
        "open_request": {"id": str(open_req.id), "status": open_req.status} if open_req else None,
    }


@router.post("/changes", status_code=201, dependencies=_CSRF, tags=TAGS)
async def create_change_request(body: ChangeBody, current_user: Requester, db: Db) -> dict:
    """Crea una solicitud. Si la politica lo permite y el solicitante es aprobador, queda autoaprobada (auditada)."""
    try:
        req = await svc.create_request(db, current_user, body.to_params())
    except _HANDLED as exc:
        raise _http(exc) from None
    return _detail_json(db, req)


@router.get("/changes", tags=TAGS)
def list_change_requests(
    _user: Viewer,
    db: Db,
    status: Annotated[list[StatusLiteral] | None, Query()] = None,
    platform: Literal["virtualpos1", "virtualpos2"] | None = None,
    subscription_id: Annotated[str | None, Query(max_length=255)] = None,
    request_type: RequestType | None = None,
    requested_by: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """Bandeja / historial con filtros (estado, plataforma, suscripción, tipo, solicitante, rango de fechas)."""
    filters = svc.RequestFilters(
        statuses=list(status) if status else None, platform=platform, subscription_external_id=subscription_id,
        request_type=request_type, requested_by_user_id=requested_by,
        created_from=datetime.combine(date_from, time.min, tzinfo=UTC) if date_from else None,
        created_to=datetime.combine(date_to, time.max, tzinfo=UTC) if date_to else None,
        limit=limit, offset=offset,
    )
    rows, total = svc.list_requests(db, filters)
    names = svc.usernames(db, {i for r in rows for i in (r.requested_by_user_id, r.approved_by_user_id)})
    return {"items": [_request_json(r, names) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/requesters", tags=TAGS)
def list_change_requesters(_user: Viewer, db: Db) -> dict:
    """Usuarios que han creado solicitudes (solo id y username), para el filtro de la bandeja."""
    return {"items": [{"id": str(uid), "username": name} for uid, name in svc.list_requesters(db)]}


@router.get("/changes/{request_id}", tags=TAGS)
def get_change_request(request_id: uuid.UUID, _user: Viewer, db: Db) -> dict:
    """Detalle con `plan_preview`, `rules_snapshot` y eventos."""
    try:
        return _detail_json(db, svc.get_request(db, request_id))
    except _HANDLED as exc:
        raise _http(exc) from None


@router.get("/changes/{request_id}/events", tags=TAGS)
def get_change_request_events(request_id: uuid.UUID, _user: Viewer, db: Db) -> dict:
    try:
        svc.get_request(db, request_id)
    except _HANDLED as exc:
        raise _http(exc) from None
    events = svc.get_events(db, request_id)
    names = svc.usernames(db, {e.actor_user_id for e in events})
    return {"items": [_event_json(e, names) for e in events], "total": len(events)}


@router.post("/changes/{request_id}/approve", dependencies=_CSRF, tags=TAGS)
def approve_change_request(request_id: uuid.UUID, current_user: Approver, db: Db, body: CommentBody | None = None) -> dict:
    """Aprueba (o autoaprueba si la política lo permite). Con doble aprobación hacen falta dos aprobadores distintos."""
    try:
        req = svc.approve(db, request_id, current_user, body.comment if body else None)
    except _HANDLED as exc:
        raise _http(exc) from None
    return _detail_json(db, req)


@router.post("/changes/{request_id}/reject", dependencies=_CSRF, tags=TAGS)
def reject_change_request(request_id: uuid.UUID, body: RequiredCommentBody, current_user: Approver, db: Db) -> dict:
    """Rechaza con comentario obligatorio."""
    try:
        req = svc.reject(db, request_id, current_user, body.comment)
    except _HANDLED as exc:
        raise _http(exc) from None
    return _detail_json(db, req)


@router.post("/changes/{request_id}/withdraw", dependencies=_CSRF, tags=TAGS)
def withdraw_change_request(request_id: uuid.UUID, current_user: Requester, db: Db, body: CommentBody | None = None) -> dict:
    """Retira una solicitud pendiente (solo su solicitante o un admin)."""
    try:
        req = svc.withdraw(db, request_id, current_user, body.comment if body else None)
    except _HANDLED as exc:
        raise _http(exc) from None
    return _detail_json(db, req)


@router.post("/changes/{request_id}/reopen", dependencies=_CSRF, tags=TAGS)
def reopen_change_request(
    request_id: uuid.UUID, body: RequiredCommentBody, db: Db,
    current_user: Annotated[User, Depends(require_any_permission(svc.PERM_POLICY, svc.PERM_APPROVE))],
) -> dict:
    """Reabre una solicitud `fallida` / `requiere_conciliacion` a `aprobada` (comentario obligatorio; sin reintento automático)."""
    try:
        req = svc.reopen(db, request_id, current_user, body.comment)
    except _HANDLED as exc:
        raise _http(exc) from None
    return _detail_json(db, req)


@router.post("/changes/{request_id}/apply", dependencies=_CSRF, tags=TAGS)
async def apply_change_request(request_id: uuid.UUID, current_user: Approver, db: Db, body: ApplyBody | None = None) -> dict:
    """Ejecuta una solicitud aprobada. Con deriva del plan responde 409 `plan_drift`; reintente con `accept_drift=true`."""
    try:
        result = await svc.apply_request(db, request_id, current_user, accept_drift=bool(body and body.accept_drift))
    except _HANDLED as exc:
        raise _http(exc) from None
    return _apply_json(result, svc.get_request(db, request_id))


# ----------------------------- politica -----------------------------


@router.get("/policy", tags=TAGS)
def get_billing_policy(_user: PolicyAdmin, db: Db) -> dict:
    """Política vigente de aprobadores (solo quien administra la política, AP-22)."""
    return _policy_json(svc.get_policy(db))


@router.put("/policy", dependencies=_CSRF, tags=TAGS)
def update_billing_policy(body: PolicyUpdateBody, current_user: PolicyAdmin, db: Db) -> dict:
    """Actualiza la política (parche parcial) y deja auditoría. 422 si queda sin aprobador (AP-23) o sin otro aprobador (AP-24)."""
    patch = body.to_patch()
    if not patch:
        raise HTTPException(422, _detail("policy_invalid", "Indique al menos un campo a modificar."))
    try:
        policy = svc.update_policy(db, current_user, patch, body.reason)
    except _HANDLED as exc:
        raise _http(exc) from None
    return _policy_json(policy)


@router.get("/policy/audit", tags=TAGS)
def get_billing_policy_audit(
    _user: PolicyAdmin, db: Db,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    rows, total = svc.list_policy_audit(db, limit=limit, offset=offset)
    names = svc.usernames(db, {a.changed_by_user_id for a in rows})
    return {"items": [_audit_json(a, names) for a in rows], "total": total, "limit": limit, "offset": offset}
