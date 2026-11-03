"""Tareas manuales de suscripcion: ciclo de vida, confirmacion auditada y verificacion externa (MGT-11/13/14).

Modelo: `app/models/manual_task.py`. Reglas:
- Crear es idempotente: si ya hay una tarea ABIERTA del mismo tipo para la suscripcion, se devuelve esa (indice unico
  parcial en la base).
- Confirmar (`pending -> confirmed`) exige el permiso `subscriptions.manual_tasks.confirm` (lo valida la ruta) y deja
  el usuario y la fecha en la tarea y en un evento inmutable. Lo puede hacer el responsable u otra persona (d107).
- Verificar (`pending|confirmed -> verified`) lo hace el SISTEMA cuando una fuente externa prueba el cambio: la
  sincronizacion de Payku (monto nuevo, MGT-14) o el Excel de TCH (ficha eliminada, MGT-13). Actor NULL.
- Descartar (`pending|confirmed -> dismissed`) exige comentario.
- La exportacion de bajas TCH en tramite es un CSV SIN PAN ni datos de cuenta o tarjeta (lista blanca de columnas).
Los errores llevan `code` fijo; nunca texto del proveedor.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.auth import User
from app.models.cancellation import SubscriptionCancellationRequest
from app.models.crm import Subscription
from app.models.manual_task import (
    CHANNELS,
    OPEN_STATUSES,
    STATUSES,
    TASK_TYPES,
    SubscriptionManualTask,
    SubscriptionManualTaskEvent,
)
from app.models.payku_channel import PaykuSubscription
from app.models.tch import TchSubscription

log = logging.getLogger(__name__)

TASK_PAYMENT_METHOD = "payment_method_retained"
TASK_TCH_MANDATE = "tch_bank_mandate"
TASK_PAYKU_AMOUNT = "payku_amount_change"
SOURCE_PAYKU_SYNC = "payku_sync"
SOURCE_TCH_REPORT = "tch_report"
PAYKU_ACTIVE_STATES = frozenset({"active", "activa", "activo"})
_THOUSANDS_RE = re.compile(r"\d{1,3}([.,]\d{3})+")
_DECIMAL_RE = re.compile(r"\d+([.,]\d{1,2})?")


# ----------------------------- errores -----------------------------


class ManualTaskError(Exception):
    code = "manual_task_error"


class TaskNotFoundError(ManualTaskError):
    code = "task_not_found"

    def __init__(self) -> None:
        super().__init__("Tarea no encontrada.")


class TaskStateError(ManualTaskError):
    code = "invalid_task_state"

    def __init__(self, current: str, expected: tuple[str, ...]) -> None:
        self.current_status = current
        self.expected = expected
        super().__init__(f"La tarea está en estado {current!r}; se esperaba uno de: {', '.join(expected)}.")


class CommentRequiredError(ManualTaskError):
    code = "comment_required"

    def __init__(self) -> None:
        super().__init__("El comentario es obligatorio y no puede estar vacío.")


class InvalidTaskFieldsError(ManualTaskError):
    code = "invalid_fields"


class SubscriptionUnknownError(ManualTaskError):
    code = "subscription_not_found"

    def __init__(self) -> None:
        super().__init__("Suscripción no encontrada.")


class SubscriptionNotActiveError(ManualTaskError):
    code = "subscription_not_active"

    def __init__(self, status: str | None) -> None:
        self.status = status
        super().__init__("La suscripción no está activa.")


class NoChangesError(ManualTaskError):
    code = "no_changes"

    def __init__(self) -> None:
        super().__init__("El monto nuevo es igual al monto vigente.")


class OpenTaskExistsError(ManualTaskError):
    code = "open_task_exists"

    def __init__(self, task_id: uuid.UUID | None, status: str | None) -> None:
        self.task_id = task_id
        self.status = status
        super().__init__("Ya hay una tarea abierta del mismo tipo para esta suscripción.")


class AssigneeNotFoundError(ManualTaskError):
    code = "assignee_not_found"

    def __init__(self) -> None:
        super().__init__("El responsable indicado no existe o no está activo.")


# ----------------------------- utilidades -----------------------------


def _now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    return now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)


def _event(db: Session, task_id: uuid.UUID, event_type: str, actor: uuid.UUID | None,
           detail: dict[str, Any] | None = None) -> None:
    db.add(SubscriptionManualTaskEvent(task_id=task_id, event_type=event_type, actor_user_id=actor,
                                       detail=detail or {}, created_at=datetime.now(UTC)))


def _clean(comment: str | None, *, required: bool) -> str | None:
    text = (comment or "").strip()
    if required and not text:
        raise CommentRequiredError()
    return text[:2000] or None


def parse_amount(value: Any) -> Decimal | None:
    """Monto del proveedor (texto) a Decimal; None si no es un numero positivo."""
    if value is None:
        return None
    raw = str(value).strip().replace("$", "").replace(" ", "")
    if not raw:
        return None
    if _THOUSANDS_RE.fullmatch(raw):  # 15.000 / 15,000 (separador de miles)
        raw = raw.replace(".", "").replace(",", "")
    elif _DECIMAL_RE.fullmatch(raw):  # 15000 / 15000.00 / 15000,5
        raw = raw.replace(",", ".")
    else:
        return None
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return None
    return amount if amount > 0 else None


def find_open_task(db: Session, task_type: str, channel: str, sub: str) -> SubscriptionManualTask | None:
    return db.scalar(select(SubscriptionManualTask).where(
        SubscriptionManualTask.task_type == task_type, SubscriptionManualTask.channel == channel,
        SubscriptionManualTask.subscription_external_id == sub,
        SubscriptionManualTask.status.in_(OPEN_STATUSES)).limit(1))


def _lock(db: Session, task_id: uuid.UUID) -> SubscriptionManualTask:
    task = db.scalar(select(SubscriptionManualTask).where(SubscriptionManualTask.id == task_id)
                     .with_for_update().execution_options(populate_existing=True))
    if task is None:
        raise TaskNotFoundError()
    return task


# ----------------------------- creacion -----------------------------


def ensure_task(
    db: Session,
    task_type: str,
    channel: str,
    sub: str,
    *,
    actor: uuid.UUID | None,
    cancellation_request_id: uuid.UUID | None = None,
    assigned_to: uuid.UUID | None = None,
    target_amount: Decimal | None = None,
    previous_amount: Decimal | None = None,
    detail: dict[str, Any] | None = None,
) -> SubscriptionManualTask:
    """Crea la tarea `pending` (evento `created`) o devuelve la abierta existente. NO hace commit (lo hace el llamador),
    para que la tarea quede en la misma transaccion que el paso que la origina."""
    if task_type not in TASK_TYPES or channel not in CHANNELS:
        raise InvalidTaskFieldsError("Tipo de tarea o canal no válidos.")
    existing = find_open_task(db, task_type, channel, sub)
    if existing is not None:
        return existing
    task = SubscriptionManualTask(
        id=uuid.uuid4(), task_type=task_type, channel=channel, subscription_external_id=sub, status="pending",
        cancellation_request_id=cancellation_request_id, created_by_user_id=actor, assigned_to_user_id=assigned_to,
        target_amount=target_amount, previous_amount=previous_amount, detail=dict(detail or {}))
    with db.begin_nested():
        db.add(task)
        db.flush()
    _event(db, task.id, "created", actor, {
        "task_type": task_type, "channel": channel, **({"code": detail["code"]} if detail and "code" in detail else {}),
        "assigned_to_user_id": str(assigned_to) if assigned_to else None})
    return task


def current_payku_amount(db: Session, sub: str) -> tuple[Decimal | None, str | None]:
    """(monto, estado) de la suscripcion Payku segun la ultima sincronizacion local (tabla del canal o central)."""
    row = db.execute(select(PaykuSubscription.amount, PaykuSubscription.status).where(
        PaykuSubscription.external_id == sub).limit(1)).first()
    if row is None:
        row = db.execute(select(Subscription.amount, Subscription.status).where(
            Subscription.source == "payku", Subscription.external_id == sub).limit(1)).first()
    if row is None:
        return None, None
    return parse_amount(row[0]), row[1]


def _exists_payku(db: Session, sub: str) -> bool:
    return db.scalar(select(func.count()).select_from(PaykuSubscription).where(
        PaykuSubscription.external_id == sub)) or db.scalar(select(func.count()).select_from(Subscription).where(
            Subscription.source == "payku", Subscription.external_id == sub))


def create_payku_amount_task(
    db: Session, actor: User, sub: str, new_amount: int, comment: str | None = None, *,
    assigned_to: uuid.UUID | None = None,
) -> SubscriptionManualTask:
    """MGT-14 (d108): Payku no tiene API para cambiar el monto. Se registra una tarea manual (el ejecutivo cambia el
    monto en el portal de Payku y confirma); la sincronizacion de Payku la cierra al ver el monto nuevo."""
    sub = (sub or "").strip()
    if not sub:
        raise InvalidTaskFieldsError("subscription_external_id es obligatorio.")
    if isinstance(new_amount, bool) or not isinstance(new_amount, int) or new_amount <= 0:
        raise InvalidTaskFieldsError("new_amount debe ser un entero positivo.")
    if not _exists_payku(db, sub):
        raise SubscriptionUnknownError()
    current, status = current_payku_amount(db, sub)
    if (status or "").strip().lower() not in PAYKU_ACTIVE_STATES:
        raise SubscriptionNotActiveError(status)
    if current is not None and current == Decimal(new_amount):
        raise NoChangesError()
    existing = find_open_task(db, TASK_PAYKU_AMOUNT, "payku", sub)
    if existing is not None:
        raise OpenTaskExistsError(existing.id, existing.status)
    if assigned_to is not None:
        _require_active_user(db, assigned_to)
    try:
        task = ensure_task(db, TASK_PAYKU_AMOUNT, "payku", sub, actor=actor.id, assigned_to=assigned_to or actor.id,
                           target_amount=Decimal(new_amount), previous_amount=current,
                           detail={"code": "PAYKU_AMOUNT_NO_API", "comment": _clean(comment, required=False)})
        db.commit()
    except IntegrityError:
        db.rollback()
        other = find_open_task(db, TASK_PAYKU_AMOUNT, "payku", sub)
        raise OpenTaskExistsError(other.id if other else None, other.status if other else None) from None
    db.refresh(task)
    return task


# ----------------------------- transiciones -----------------------------


def _require_active_user(db: Session, user_id: uuid.UUID) -> None:
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AssigneeNotFoundError()


def confirm_task(db: Session, task_id: uuid.UUID, actor: User, comment: str | None = None, *,
                 now: datetime | None = None) -> SubscriptionManualTask:
    """El ejecutivo confirma que hizo la accion manual: `pending -> confirmed` con su usuario y la fecha (auditado)."""
    text = _clean(comment, required=False)
    when = _now(now)
    task = _lock(db, task_id)
    if task.status != "pending":
        db.rollback()
        raise TaskStateError(task.status, ("pending",))
    updated = db.execute(
        update(SubscriptionManualTask)
        .where(SubscriptionManualTask.id == task.id, SubscriptionManualTask.status == "pending")
        .values(status="confirmed", confirmed_by_user_id=actor.id, confirmed_at=when, confirmation_comment=text,
                updated_at=func.now())
        .execution_options(synchronize_session=False)).rowcount
    if updated != 1:
        db.rollback()
        raise TaskStateError(_status_of(db, task_id), ("pending",))
    _event(db, task.id, "confirmed", actor.id, {
        "confirmed_at": when.isoformat(timespec="seconds"), "comment": text,
        "assigned_to_user_id": str(task.assigned_to_user_id) if task.assigned_to_user_id else None,
        "by_assignee": task.assigned_to_user_id == actor.id})
    db.commit()
    db.refresh(task)
    return task


def assign_task(db: Session, task_id: uuid.UUID, actor: User, assignee_id: uuid.UUID) -> SubscriptionManualTask:
    """Fija el responsable de una tarea abierta (d107: otro ejecutivo o el mismo)."""
    _require_active_user(db, assignee_id)
    task = _lock(db, task_id)
    if task.status not in OPEN_STATUSES:
        db.rollback()
        raise TaskStateError(task.status, OPEN_STATUSES)
    previous = task.assigned_to_user_id
    task.assigned_to_user_id = assignee_id
    _event(db, task.id, "assigned", actor.id, {
        "from_user_id": str(previous) if previous else None, "to_user_id": str(assignee_id)})
    db.commit()
    db.refresh(task)
    return task


def dismiss_task(db: Session, task_id: uuid.UUID, actor: User, comment: str | None, *,
                 now: datetime | None = None) -> SubscriptionManualTask:
    text = _clean(comment, required=True)
    task = _lock(db, task_id)
    if task.status not in OPEN_STATUSES:
        db.rollback()
        raise TaskStateError(task.status, OPEN_STATUSES)
    previous = task.status
    task.status = "dismissed"
    task.dismissed_by_user_id = actor.id
    task.dismissed_at = _now(now)
    task.dismiss_comment = text
    _event(db, task.id, "dismissed", actor.id, {"from_status": previous, "comment": text})
    db.commit()
    db.refresh(task)
    return task


def verify_task(db: Session, task: SubscriptionManualTask, source: str, detail: dict[str, Any] | None = None, *,
                now: datetime | None = None) -> bool:
    """Cierre por fuente externa (actor sistema). Idempotente: solo actua sobre tareas abiertas. NO hace commit."""
    if task.status not in OPEN_STATUSES:
        return False
    previous = task.status
    task.status = "verified"
    task.verified_at = _now(now)
    task.verification_source = source
    _event(db, task.id, "verified", None, {"source": source, "from_status": previous,
                                           "confirmed_before": previous == "confirmed", **(detail or {})})
    return True


def _status_of(db: Session, task_id: uuid.UUID) -> str:
    return str(db.scalar(select(SubscriptionManualTask.status).where(SubscriptionManualTask.id == task_id))
               or "desconocido")


# ----------------------------- verificacion por fuentes externas -----------------------------


def verify_payku_amount_tasks(db: Session, *, now: datetime | None = None) -> list[uuid.UUID]:
    """MGT-14: tras la sincronizacion de Payku, cierra (`verified`) las tareas de monto cuyo monto local YA es el
    pedido. Solo lectura de tablas locales; nunca llama al proveedor. Devuelve los ids cerrados."""
    closed: list[uuid.UUID] = []
    rows = db.scalars(select(SubscriptionManualTask).where(
        SubscriptionManualTask.task_type == TASK_PAYKU_AMOUNT,
        SubscriptionManualTask.status.in_(OPEN_STATUSES)).with_for_update(skip_locked=True)).all()
    for task in rows:
        current, _status = current_payku_amount(db, task.subscription_external_id)
        if current is not None and task.target_amount is not None and current == Decimal(task.target_amount):
            if verify_task(db, task, SOURCE_PAYKU_SYNC, {"observed_amount": int(current)}, now=now):
                closed.append(task.id)
    db.commit()
    return closed


def verify_tch_mandate_task(db: Session, request_id: uuid.UUID, *, now: datetime | None = None) -> bool:
    """MGT-13: el Excel de TCH trajo la ficha eliminada: la tarea del mandato queda `verified`. NO hace commit."""
    task = db.scalar(select(SubscriptionManualTask).where(
        SubscriptionManualTask.task_type == TASK_TCH_MANDATE,
        SubscriptionManualTask.cancellation_request_id == request_id,
        SubscriptionManualTask.status.in_(OPEN_STATUSES)).limit(1))
    return bool(task and verify_task(db, task, SOURCE_TCH_REPORT, {"cancellation_request_id": str(request_id)},
                                     now=now))


# ----------------------------- consulta -----------------------------


@dataclass
class TaskFilters:
    statuses: list[str] | None = None
    task_type: str | None = None
    channel: str | None = None
    subscription_external_id: str | None = None
    cancellation_request_id: uuid.UUID | None = None
    assigned_to_user_id: uuid.UUID | None = None
    limit: int = 50
    offset: int = 0


def list_tasks(db: Session, f: TaskFilters) -> tuple[list[SubscriptionManualTask], int]:
    q = select(SubscriptionManualTask)
    if f.statuses:
        q = q.where(SubscriptionManualTask.status.in_([s for s in f.statuses if s in STATUSES]))
    if f.task_type:
        q = q.where(SubscriptionManualTask.task_type == f.task_type)
    if f.channel:
        q = q.where(SubscriptionManualTask.channel == f.channel)
    if f.subscription_external_id:
        q = q.where(SubscriptionManualTask.subscription_external_id == f.subscription_external_id.strip())
    if f.cancellation_request_id:
        q = q.where(SubscriptionManualTask.cancellation_request_id == f.cancellation_request_id)
    if f.assigned_to_user_id:
        q = q.where(SubscriptionManualTask.assigned_to_user_id == f.assigned_to_user_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(SubscriptionManualTask.created_at.desc(), SubscriptionManualTask.id)
                      .limit(f.limit).offset(f.offset)).all()
    return list(rows), int(total)


def get_task(db: Session, task_id: uuid.UUID) -> SubscriptionManualTask:
    task = db.get(SubscriptionManualTask, task_id)
    if task is None:
        raise TaskNotFoundError()
    return task


def get_events(db: Session, task_id: uuid.UUID) -> list[SubscriptionManualTaskEvent]:
    return list(db.scalars(select(SubscriptionManualTaskEvent).where(SubscriptionManualTaskEvent.task_id == task_id)
                           .order_by(SubscriptionManualTaskEvent.created_at, SubscriptionManualTaskEvent.id)))


def usernames(db: Session, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    return {uid: name for uid, name in db.execute(select(User.id, User.username).where(User.id.in_(wanted)))}


# ----------------------------- exportacion TCH sin PAN (MGT-13) -----------------------------

# Lista BLANCA de columnas: nada de numero de cuenta/tarjeta (PAN), titular, RUT ni contacto. Agregar una columna exige
# revisar que no sea un dato de pago ni personal (lo vigila tests/test_manual_tasks.py).
TCH_EXPORT_COLUMNS = (
    "solicitud_id", "numero_ficha", "numero_mandato", "banco", "tipo_mandato", "monto", "moneda", "motivo",
    "solicitada_en", "aprobada_en", "responsable", "estado_tarea", "confirmada_por", "confirmada_en", "tarea_id",
)


def _safe_cell(value: Any) -> str:
    """Celda CSV sin inyeccion de formulas (=,+,-,@ al inicio) ni saltos de linea."""
    text = "" if value is None else str(value)
    text = text.replace("\r", " ").replace("\n", " ").strip()
    if text[:1] in ("=", "+", "-", "@", "\t"):
        text = "'" + text
    return text


def export_tch_pending_csv(db: Session, actor: User) -> tuple[str, int]:
    """CSV de las bajas TCH «en tramite» (`pending_external`) con su tarea de mandato. Devuelve (csv, filas).

    Deja un evento `exported` en cada tarea (quien exporto y cuando). Nunca incluye PAN ni datos de cuenta o tarjeta."""
    reqs = db.scalars(select(SubscriptionCancellationRequest).where(
        SubscriptionCancellationRequest.channel == "tch",
        SubscriptionCancellationRequest.status == "pending_external")
        .order_by(SubscriptionCancellationRequest.created_at)).all()
    tasks = {t.cancellation_request_id: t for t in db.scalars(select(SubscriptionManualTask).where(
        SubscriptionManualTask.task_type == TASK_TCH_MANDATE,
        SubscriptionManualTask.cancellation_request_id.in_([r.id for r in reqs]))).all()} if reqs else {}
    names = usernames(db, {t.assigned_to_user_id for t in tasks.values()} | {t.confirmed_by_user_id for t in tasks.values()})
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(TCH_EXPORT_COLUMNS)
    when = datetime.now(UTC)
    for r in reqs:
        ficha = int(r.subscription_external_id) if r.subscription_external_id.isdigit() else None
        sub = db.scalar(select(TchSubscription).where(TchSubscription.file_number == ficha).limit(1)) if ficha else None
        task = tasks.get(r.id)
        row = {
            "solicitud_id": str(r.id), "numero_ficha": ficha,
            "numero_mandato": sub.mandate_number if sub else None,
            "banco": sub.bank_name if sub else None, "tipo_mandato": sub.mandate_type if sub else None,
            "monto": sub.amount if sub else None, "moneda": sub.currency if sub else None, "motivo": r.reason_code,
            "solicitada_en": r.created_at.isoformat(timespec="seconds") if r.created_at else None,
            "aprobada_en": r.decided_at.isoformat(timespec="seconds") if r.decided_at else None,
            "responsable": names.get(task.assigned_to_user_id) if task and task.assigned_to_user_id else None,
            "estado_tarea": task.status if task else None,
            "confirmada_por": names.get(task.confirmed_by_user_id) if task and task.confirmed_by_user_id else None,
            "confirmada_en": task.confirmed_at.isoformat(timespec="seconds") if task and task.confirmed_at else None,
            "tarea_id": str(task.id) if task else None,
        }
        writer.writerow([_safe_cell(row[c]) for c in TCH_EXPORT_COLUMNS])
        if task is not None:
            _event(db, task.id, "exported", actor.id, {"format": "csv", "at": when.isoformat(timespec="seconds")})
    db.commit()
    return buf.getvalue(), len(reqs)
