"""Chequeo diario de SOLO LECTURA de renovacion de calendario (opcion A, paso 6a).

Diseno: docs/designs/facturacion-gestionada-escenarios.md, JB-25..JB-36 (+ JB-19/JB-20/JB-29, AP-34).

Decision del usuario (2026-10-28): el chequeo SOLO crea/actualiza/cierra la TAREA `billing_renewal_tasks` (visible en la
bandeja con prioridad). NO genera solicitudes, NO envia correos y NO escribe en el proveedor. Lee unicamente tablas locales
(`vp_calendar_marks`, `vp_subscriptions`/`subscriptions`, `sync_runs`, `billing_change_requests`, `billing_policy`) y no
importa ningun cliente de VirtualPOS: por eso funciona igual con `VIRTUALPOS_WRITES_ENABLED` y las demas banderas apagadas
(JB-19) y nunca crea un `write_run` (JB-29).

Reglas (cada una con su escenario)
- Entrada: toda `VpCalendarMark` activa. Una suscripcion sin marca (solo automaticos de VP) nunca genera tarea (JB-28).
- Dias restantes = `last_scheduled_date` - hoy, con "hoy" en hora de Chile (America/Santiago), no UTC.
- Umbral N = `billing_policy.renewal_threshold_days` VIGENTE en cada corrida (JB-34); borde INCLUSIVO: dias <= N abre la
  tarea (N dias abre, N+1 no) (JB-25, JB-26). Una tarea ya abierta se sigue actualizando aunque N baje despues.
- Dedupe (JB-27): a lo mas una tarea `abierta|vencida` por suscripcion (indice unico parcial + busqueda previa). Una segunda
  corrida no duplica; solo refresca `days_remaining` y demas campos. Si hay una solicitud `renew_calendar` abierta para la
  suscripcion, la tarea queda enlazada a ella (`request_id`, AP-34); si esa solicitud se cierra sin ejecutarse, el enlace se quita.
- `due_date` = `last_scheduled_date` (fin del horizonte programado por el CRM; despues VP cobra el automatico con el monto antiguo).
- `vencida` cuando hoy > `due_date` (JB-31). Si el chequeo no corrio varios dias y ya paso, la tarea nace `vencida` (JB-33).
- Prioridad `alta` si esta `vencida` (JB-31) o faltan menos de `HIGH_PRIORITY_DAYS` (15) dias (JB-27, propuesta del doc); si no, `normal`.
- Suscripcion que deja de estar ACTIVA (CANCELADA, FINALIZADA, SUSCRIPCION_FALLIDA...) o marca desactivada/inexistente: no se
  crea tarea y la abierta se cierra como `no_aplica` con `close_reason` (JB-35).
- Renovacion ejecutada (AP-34, JB-30): si el calendario se extendio (la marca ya llega mas lejos que la tarea) o la solicitud
  enlazada quedo `ejecutada`, la tarea pasa a `cerrada` enlazando `request_id` (la `origin_request_id` de la marca si esta ejecutada).
- `data_stale` (JB-36): la ultima sincronizacion COMPLETADA de la plataforma (`sync_runs.source = platform`) tiene mas de
  `STALE_AFTER_HOURS` (48 h, valor del doc, constante configurable), no existe, o la ultima corrida terminada fallo. La tarea se
  genera igual, solo marcada. (El proveedor se sincroniza por plataforma, no por suscripcion: la antiguedad es la de la plataforma.)
- Robustez: se procesa por lotes (`BATCH_SIZE`) con commit por lote y un SAVEPOINT por registro; un registro malo se cuenta en
  `errors` y NO tumba el lote. Log agregado sin PII (solo ids internos de marca y contadores).
- JB-20 (allowlist del piloto) NO esta implementado en el proyecto (no existe tal lista/bandera): el chequeo revisa todas las marcas.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.billing import BillingChangeRequest, BillingRenewalTask, VpCalendarMark
from app.models.sync_run import SyncRun
from app.services import billing_apply as ba
from app.services import billing_requests as br

log = logging.getLogger(__name__)

OPEN_TASK_STATUSES = ("abierta", "vencida")
HIGH_PRIORITY_DAYS = 15  # JB-27 (propuesta): faltan menos de 15 dias -> prioridad alta
STALE_AFTER_HOURS = 48  # JB-36: ultimo sync con mas de 48 h
BATCH_SIZE = 200
_REASON_MAX = 500


@dataclass
class RenewalCheckResult:
    """Contadores de una corrida (sin datos personales)."""

    examined: int = 0  # marcas activas revisadas
    opened: int = 0  # tareas nuevas
    updated: int = 0  # tareas existentes cuyos campos cambiaron
    overdue: int = 0  # tareas que pasaron a (o nacieron) `vencida` en esta corrida
    closed: int = 0  # cerradas por renovacion ejecutada
    not_applicable: int = 0  # cerradas `no_aplica` (suscripcion no ACTIVA / sin marca activa)
    stale: int = 0  # tareas abiertas marcadas `data_stale` tras la corrida
    errors: int = 0  # registros que fallaron (aislados por SAVEPOINT)

    def merge(self, other: RenewalCheckResult) -> None:
        for name, value in asdict(other).items():
            setattr(self, name, getattr(self, name) + value)

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


# ----------------------------- helpers -----------------------------


def _platform_is_stale(db: Session, platform: str, now_utc: datetime, cache: dict[str, bool]) -> bool:
    if platform in cache:
        return cache[platform]
    last_ok = db.scalar(select(func.max(func.coalesce(SyncRun.finished_at, SyncRun.started_at))).where(
        SyncRun.source == platform, SyncRun.status == "completed"))
    last_done = db.execute(select(SyncRun.status).where(
        SyncRun.source == platform, SyncRun.status.in_(("completed", "failed")))
        .order_by(func.coalesce(SyncRun.finished_at, SyncRun.started_at).desc()).limit(1)).scalar()
    if last_ok is None:
        stale = True
    else:
        if last_ok.tzinfo is None:
            last_ok = last_ok.replace(tzinfo=UTC)
        stale = (now_utc - last_ok).total_seconds() > STALE_AFTER_HOURS * 3600 or last_done == "failed"
    cache[platform] = stale
    return stale


def _find_open_task(db: Session, platform: str, sub: str) -> BillingRenewalTask | None:
    return db.scalar(select(BillingRenewalTask).where(
        BillingRenewalTask.platform == platform, BillingRenewalTask.subscription_external_id == sub,
        BillingRenewalTask.status.in_(OPEN_TASK_STATUSES)).limit(1))


def _open_renewal_request(db: Session, platform: str, sub: str) -> BillingChangeRequest | None:
    return db.scalar(select(BillingChangeRequest).where(
        BillingChangeRequest.platform == platform, BillingChangeRequest.subscription_external_id == sub,
        BillingChangeRequest.request_type == "renew_calendar", BillingChangeRequest.status.in_(br.OPEN_STATUSES))
        .order_by(BillingChangeRequest.created_at.desc()).limit(1))


def _close(task: BillingRenewalTask, status: str, reason: str, now_utc: datetime, request_id: uuid.UUID | None = None) -> None:
    task.status = status
    task.close_reason = reason[:_REASON_MAX]
    task.closed_at = now_utc
    if request_id is not None:
        task.request_id = request_id


def _priority(status: str, days: int) -> str:
    return "alta" if status == "vencida" or days < HIGH_PRIORITY_DAYS else "normal"


def _executed_request(db: Session, *ids: uuid.UUID | None) -> BillingChangeRequest | None:
    for rid in ids:
        if rid is None:
            continue
        req = db.get(BillingChangeRequest, rid)
        if req is not None and req.status == "ejecutada":
            return req
    return None


# ----------------------------- una marca -----------------------------


def _process_mark(db: Session, mark: VpCalendarMark, *, today: date, now_utc: datetime, threshold: int,
                  stale_cache: dict[str, bool]) -> RenewalCheckResult:
    out = RenewalCheckResult(examined=1)
    platform, sub = mark.platform, mark.subscription_external_id
    task = _find_open_task(db, platform, sub)

    state = ba._subscription_state(db, platform, sub)
    status = (state[0] or "").strip().upper() if state else ""
    if status != "ACTIVA":  # JB-35
        if task is not None:
            _close(task, "no_aplica", f"La suscripción ya no está ACTIVA (estado: {status or 'desconocido'}).", now_utc)
            out.not_applicable += 1
        return out

    if task is not None:  # AP-34 / JB-30: renovacion ejecutada -> cierra y enlaza
        executed = _executed_request(db, mark.origin_request_id, task.request_id)
        extended = mark.last_scheduled_date > task.last_scheduled_date
        if extended or (task.request_id is not None and executed is not None and executed.id == task.request_id):
            reason = ("Renovación ejecutada: el calendario se extendió." if executed is not None
                      else "El calendario se extendió (sin solicitud de renovación asociada).")
            _close(task, "cerrada", reason, now_utc, executed.id if executed is not None else None)
            out.closed += 1
            db.flush()  # libera el indice unico parcial antes de evaluar una tarea nueva
            task = None

    days = (mark.last_scheduled_date - today).days
    if task is None and days > threshold:  # JB-26: N+1 no abre
        return out

    new_status = "vencida" if today > mark.last_scheduled_date else "abierta"
    linked = _open_renewal_request(db, platform, sub)
    desired: dict[str, Any] = {
        "status": new_status, "priority": _priority(new_status, days), "last_scheduled_date": mark.last_scheduled_date,
        "scheduled_amount": Decimal(mark.scheduled_amount), "due_date": mark.last_scheduled_date, "days_remaining": days,
        "data_stale": _platform_is_stale(db, platform, now_utc, stale_cache),
        "request_id": linked.id if linked is not None else None,
    }
    if task is None:
        db.add(BillingRenewalTask(platform=platform, subscription_external_id=sub, **desired))
        db.flush()
        out.opened += 1
        if new_status == "vencida":
            out.overdue += 1
    else:
        changed = [k for k, v in desired.items() if getattr(task, k) != v]
        if changed:
            if "status" in changed and new_status == "vencida":
                out.overdue += 1
            for k in changed:
                setattr(task, k, desired[k])
            out.updated += 1
    if desired["data_stale"]:
        out.stale += 1
    return out


def _process_orphan_task(db: Session, task: BillingRenewalTask, now_utc: datetime) -> RenewalCheckResult:
    """Tarea abierta cuya marca ya no existe o esta inactiva: no corresponde renovacion (JB-28/JB-35)."""
    _close(task, "no_aplica", "La suscripción ya no tiene un calendario modificado activo.", now_utc)
    return RenewalCheckResult(not_applicable=1)


# ----------------------------- corrida -----------------------------


def run_renewal_check(db: Session, now: datetime | None = None) -> RenewalCheckResult:
    """Ejecuta el chequeo (ver docstring del modulo). Solo lectura sobre el proveedor; escribe solo `billing_renewal_tasks`."""
    chile_now = ba._chile_now(now)
    today = chile_now.date()
    now_utc = chile_now.astimezone(UTC)
    threshold = int(br.get_policy(db).renewal_threshold_days)
    db.commit()  # persiste la politica si hubo que crearla y empieza limpio
    result = RenewalCheckResult()
    stale_cache: dict[str, bool] = {}

    mark_ids = list(db.scalars(select(VpCalendarMark.id).where(VpCalendarMark.is_active.is_(True)).order_by(VpCalendarMark.id)))
    for start in range(0, len(mark_ids), BATCH_SIZE):
        chunk = mark_ids[start:start + BATCH_SIZE]
        marks = db.scalars(select(VpCalendarMark).where(VpCalendarMark.id.in_(chunk)).order_by(VpCalendarMark.id)).all()
        for mark in marks:
            mark_id = mark.id
            try:
                with db.begin_nested():
                    result.merge(_process_mark(db, mark, today=today, now_utc=now_utc, threshold=threshold,
                                               stale_cache=stale_cache))
            except Exception as exc:  # noqa: BLE001 - un registro malo no tumba el lote
                result.examined += 1
                result.errors += 1
                log.warning("renovacion: error en marca %s (%s); se continua con el lote.", mark_id,
                            "carrera de unicidad" if isinstance(exc, IntegrityError) else type(exc).__name__)
        db.commit()

    orphan_ids = list(db.scalars(select(BillingRenewalTask.id).where(
        BillingRenewalTask.status.in_(OPEN_TASK_STATUSES),
        ~exists().where(VpCalendarMark.platform == BillingRenewalTask.platform,
                        VpCalendarMark.subscription_external_id == BillingRenewalTask.subscription_external_id,
                        VpCalendarMark.is_active.is_(True))).order_by(BillingRenewalTask.id)))
    for oid in orphan_ids:
        try:
            with db.begin_nested():
                task = db.get(BillingRenewalTask, oid)
                if task is not None and task.status in OPEN_TASK_STATUSES:
                    result.merge(_process_orphan_task(db, task, now_utc))
        except Exception as exc:  # noqa: BLE001
            result.errors += 1
            log.warning("renovacion: error cerrando tarea %s (%s).", oid, type(exc).__name__)
    db.commit()

    log.info("renovacion: revisadas=%d nuevas=%d actualizadas=%d vencidas=%d cerradas=%d no_aplica=%d desactualizadas=%d errores=%d",
             result.examined, result.opened, result.updated, result.overdue, result.closed, result.not_applicable,
             result.stale, result.errors)
    return result


# ----------------------------- consulta (bandeja) -----------------------------


@dataclass
class TaskFilters:
    statuses: list[str] | None = None
    priority: str | None = None
    platform: str | None = None
    subscription_external_id: str | None = None
    limit: int = 50
    offset: int = 0


def list_renewal_tasks(db: Session, f: TaskFilters) -> tuple[list[BillingRenewalTask], int]:
    """Tareas ordenadas por prioridad (alta primero), luego `due_date` ascendente y id. Sin datos del socio."""
    q = select(BillingRenewalTask)
    if f.statuses:
        q = q.where(BillingRenewalTask.status.in_(f.statuses))
    if f.priority:
        q = q.where(BillingRenewalTask.priority == f.priority)
    if f.platform:
        q = q.where(BillingRenewalTask.platform == br.normalize_platform(f.platform))
    if f.subscription_external_id:
        q = q.where(BillingRenewalTask.subscription_external_id == f.subscription_external_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(
        (BillingRenewalTask.priority != "alta"), BillingRenewalTask.due_date, BillingRenewalTask.id,
    ).limit(f.limit).offset(f.offset)).all()
    return list(rows), total


__all__ = [
    "BATCH_SIZE", "HIGH_PRIORITY_DAYS", "OPEN_TASK_STATUSES", "STALE_AFTER_HOURS",
    "RenewalCheckResult", "TaskFilters", "list_renewal_tasks", "run_renewal_check",
]
