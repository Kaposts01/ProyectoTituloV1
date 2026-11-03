"""API de tareas manuales de suscripcion (MGT-11/13/14; `/api/v1/manual-tasks`).

Rutas finas sobre `app/services/manual_tasks.py`. Permisos: leer `subscriptions.manual_tasks.view`; confirmar,
asignar, descartar y exportar el CSV de TCH `subscriptions.manual_tasks.confirm`; registrar el cambio de monto de
Payku `virtualpos.billing_changes.request` (el mismo permiso de «Solicitar cambio de cobro», d108). El actor sale
siempre del token y toda escritura exige CSRF. Errores `detail = {code, message}` con mensajes fijos.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.billing_changes import _NoEchoRoute
from app.api.v1.routes.crm import get_db
from app.core.security import require_csrf, require_permissions
from app.models.auth import User
from app.models.manual_task import SubscriptionManualTask, SubscriptionManualTaskEvent
from app.services import manual_tasks as mt
from app.services.billing_requests import PERM_REQUEST as BILLING_REQUEST
from app.services.rbac import MANUAL_TASKS_CONFIRM, MANUAL_TASKS_VIEW, permission_codes

router = APIRouter(route_class=_NoEchoRoute)
TAGS = ["Manual tasks"]

TaskTypeLiteral = Literal["payment_method_retained", "tch_bank_mandate", "payku_amount_change"]
StatusLiteral = Literal["pending", "confirmed", "verified", "dismissed"]
ChannelLiteral = Literal["virtualpos1", "virtualpos2", "toku", "payku", "tch"]


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


class AssignBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assigned_to_user_id: uuid.UUID


class PaykuAmountBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subscription_external_id: str = Field(min_length=1, max_length=255)
    new_amount: int = Field(ge=1, le=10**10)
    comment: str | None = Field(default=None, max_length=2000)
    assigned_to_user_id: uuid.UUID | None = None


def _detail(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **extra}


def _http(exc: BaseException) -> NoReturn:
    if isinstance(exc, mt.TaskNotFoundError):
        raise HTTPException(404, _detail(exc.code, "Tarea no encontrada."))
    if isinstance(exc, mt.SubscriptionUnknownError):
        raise HTTPException(404, _detail(exc.code, "Suscripción no encontrada."))
    if isinstance(exc, mt.TaskStateError):
        raise HTTPException(409, _detail(exc.code, str(exc), current_status=exc.current_status,
                                         expected=list(exc.expected)))
    if isinstance(exc, mt.OpenTaskExistsError):
        raise HTTPException(409, _detail(exc.code, str(exc), open_task_id=str(exc.task_id) if exc.task_id else None,
                                         open_task_status=exc.status))
    if isinstance(exc, mt.SubscriptionNotActiveError):
        raise HTTPException(422, _detail(exc.code, str(exc)))
    if isinstance(exc, mt.CommentRequiredError | mt.InvalidTaskFieldsError | mt.NoChangesError
                  | mt.AssigneeNotFoundError):
        raise HTTPException(422, _detail(exc.code, str(exc)))
    raise exc


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _num(value: Decimal | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


def _uid(value: uuid.UUID | None) -> str | None:
    return str(value) if value else None


def _task_json(t: SubscriptionManualTask, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "id": str(t.id), "task_type": t.task_type, "channel": t.channel,
        "subscription_external_id": t.subscription_external_id, "status": t.status,
        "cancellation_request_id": _uid(t.cancellation_request_id),
        "target_amount": _num(t.target_amount), "previous_amount": _num(t.previous_amount),
        "created_by_user_id": _uid(t.created_by_user_id),
        "created_by": names.get(t.created_by_user_id) if t.created_by_user_id else "sistema",
        "assigned_to_user_id": _uid(t.assigned_to_user_id),
        "assigned_to": names.get(t.assigned_to_user_id) if t.assigned_to_user_id else None,
        "confirmed_by_user_id": _uid(t.confirmed_by_user_id),
        "confirmed_by": names.get(t.confirmed_by_user_id) if t.confirmed_by_user_id else None,
        "confirmed_at": _iso(t.confirmed_at), "confirmation_comment": t.confirmation_comment,
        "verified_at": _iso(t.verified_at), "verification_source": t.verification_source,
        "dismissed_by_user_id": _uid(t.dismissed_by_user_id),
        "dismissed_by": names.get(t.dismissed_by_user_id) if t.dismissed_by_user_id else None,
        "dismissed_at": _iso(t.dismissed_at), "dismiss_comment": t.dismiss_comment,
        "code": (t.detail or {}).get("code"),
        "created_at": _iso(t.created_at), "updated_at": _iso(t.updated_at),
    }


def _ids(t: SubscriptionManualTask) -> set[uuid.UUID | None]:
    return {t.created_by_user_id, t.assigned_to_user_id, t.confirmed_by_user_id, t.dismissed_by_user_id}


def _event_json(e: SubscriptionManualTaskEvent, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {"id": str(e.id), "event_type": e.event_type, "actor_user_id": _uid(e.actor_user_id),
            "actor": names.get(e.actor_user_id) if e.actor_user_id else "sistema", "detail": e.detail or {},
            "created_at": _iso(e.created_at)}


def _detail_json(db: Session, t: SubscriptionManualTask) -> dict[str, Any]:
    events = mt.get_events(db, t.id)
    names = mt.usernames(db, _ids(t) | {e.actor_user_id for e in events})
    return {**_task_json(t, names), "events": [_event_json(e, names) for e in events]}


Db = Annotated[Session, Depends(get_db)]
Viewer = Annotated[User, Depends(require_permissions(MANUAL_TASKS_VIEW))]
Confirmer = Annotated[User, Depends(require_permissions(MANUAL_TASKS_CONFIRM))]
AmountRequester = Annotated[User, Depends(require_permissions(BILLING_REQUEST))]
_CSRF = [Depends(require_csrf)]


@router.get("", tags=TAGS)
def list_manual_tasks(
    _user: Viewer,
    db: Db,
    status: Annotated[list[StatusLiteral] | None, Query()] = None,
    task_type: TaskTypeLiteral | None = None,
    channel: ChannelLiteral | None = None,
    subscription_id: Annotated[str | None, Query(max_length=255)] = None,
    cancellation_request_id: uuid.UUID | None = None,
    assigned_to: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    rows, total = mt.list_tasks(db, mt.TaskFilters(
        statuses=list(status) if status else None, task_type=task_type, channel=channel,
        subscription_external_id=subscription_id, cancellation_request_id=cancellation_request_id,
        assigned_to_user_id=assigned_to, limit=limit, offset=offset))
    names = mt.usernames(db, {i for t in rows for i in _ids(t)})
    return {"items": [_task_json(t, names) for t in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/assignees", tags=TAGS)
def list_assignees(_user: Viewer, db: Db) -> dict:
    """Usuarios activos que pueden confirmar tareas (posibles responsables): solo id y username."""
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.username)).all()
    return {"items": [{"id": str(u.id), "username": u.username} for u in users
                      if MANUAL_TASKS_CONFIRM in permission_codes(u)]}


@router.get("/tch-export", tags=TAGS)
def export_tch_pending(current_user: Confirmer, db: Db) -> Response:
    """CSV de las bajas TCH «en trámite» para el ejecutivo que revoca el mandato (sin PAN ni datos de cuenta)."""
    content, _rows = mt.export_tch_pending_csv(db, current_user)
    return Response(content="﻿" + content, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="bajas_tch_en_tramite.csv"',
                             "Cache-Control": "no-store"})


@router.post("/payku-amount", status_code=201, dependencies=_CSRF, tags=TAGS)
def create_payku_amount_task(body: PaykuAmountBody, current_user: AmountRequester, db: Db) -> dict:
    """MGT-14: registra el cambio de monto de Payku como tarea manual (Payku no tiene API para cambiarlo)."""
    try:
        task = mt.create_payku_amount_task(db, current_user, body.subscription_external_id, body.new_amount,
                                           body.comment, assigned_to=body.assigned_to_user_id)
    except mt.ManualTaskError as exc:
        raise _http(exc) from None
    return _detail_json(db, task)


@router.get("/{task_id}", tags=TAGS)
def get_manual_task(task_id: uuid.UUID, _user: Viewer, db: Db) -> dict:
    try:
        return _detail_json(db, mt.get_task(db, task_id))
    except mt.ManualTaskError as exc:
        raise _http(exc) from None


@router.post("/{task_id}/confirm", dependencies=_CSRF, tags=TAGS)
def confirm_manual_task(task_id: uuid.UUID, current_user: Confirmer, db: Db, body: CommentBody | None = None) -> dict:
    """El ejecutivo confirma que hizo la acción manual: queda su usuario y la fecha (evento inmutable)."""
    try:
        task = mt.confirm_task(db, task_id, current_user, body.comment if body else None)
    except mt.ManualTaskError as exc:
        raise _http(exc) from None
    return _detail_json(db, task)


@router.post("/{task_id}/assign", dependencies=_CSRF, tags=TAGS)
def assign_manual_task(task_id: uuid.UUID, body: AssignBody, current_user: Confirmer, db: Db) -> dict:
    try:
        task = mt.assign_task(db, task_id, current_user, body.assigned_to_user_id)
    except mt.ManualTaskError as exc:
        raise _http(exc) from None
    return _detail_json(db, task)


@router.post("/{task_id}/dismiss", dependencies=_CSRF, tags=TAGS)
def dismiss_manual_task(task_id: uuid.UUID, body: RequiredCommentBody, current_user: Confirmer, db: Db) -> dict:
    try:
        task = mt.dismiss_task(db, task_id, current_user, body.comment)
    except mt.ManualTaskError as exc:
        raise _http(exc) from None
    return _detail_json(db, task)
