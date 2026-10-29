"""Reconciliacion dirigida por ventana de riesgo (RT-06), sin webhooks.

Cada pasada refresca con `refresh_subscription` (MGT-06, solo GET) las suscripciones donde un cambio es mas probable,
en vez de repetir la sincronizacion completa (1,9 a 2,8 h). Una suscripcion esta en ventana de riesgo si esta viva
(no cancelada/eliminada) y tiene, en `charges`:
  * un cobro programado en los ultimos `targeted_reconcile_due_days` dias (5) hasta hoy, o
  * un cobro rechazado en los ultimos `targeted_reconcile_rejection_days` dias (15), o
  * un cobro pendiente ya vencido (fecha de cobro <= hoy; los pendientes futuros no son riesgo, VirtualPOS los crea por adelantado).
Prioridad: rechazo, luego cobro reciente, luego pendiente; empate por cobro mas reciente. Solo canales con refresh
(virtualpos1/2, toku, payku). Tope por corrida (`targeted_reconcile_max_per_run`, 200), pausa entre peticiones y
respeto del lock: si hay una sincronizacion/ETL en curso (`find_active_run`) no hace nada. No escribe en `sync_runs`
(un source nuevo apareceria como canal en los KPI); el resultado va al log y los cambios de estado a `status_change_events`.
Detras de `TARGETED_RECONCILE_ENABLED` (apagada por defecto).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import case, func, literal, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.crm import Charge, Subscription
from app.scheduler.run_lock import find_active_run
from app.services.billing_plan import PENDING_STATES
from app.services.rejected_month import now_chile
from app.services.subscription_refresh import RefreshError, refresh_subscription

logger = logging.getLogger(__name__)

RISK_SOURCES = ("virtualpos1", "virtualpos2", "toku", "payku")
REJECTED_STATES = frozenset({"rechazado", "rechazada", "rejected", "failed", "permanent_failed"})
PENDING_LIKE_STATES = frozenset(PENDING_STATES | {"unpaid", "partially_paid", "retry"})
DEAD_SUBSCRIPTION_STATES = frozenset({
    "cancelada", "cancelado", "cancelled", "canceled", "cancel", "deleted", "delete", "ended", "finish", "finished", "baja"})
MAX_CONSECUTIVE_FAILURES = 5  # el proveedor esta caido o nos limita: se corta la pasada
LOCK_RECHECK_EVERY = 20

RefreshFn = Callable[..., Awaitable[Any]]
SleepFn = Callable[[float], Awaitable[None]]


@dataclass
class ReconcileSummary:
    selected: int = 0
    refreshed: int = 0
    failed: int = 0
    skipped_reason: str | None = None
    codes: dict[str, int] = field(default_factory=dict)


def select_risk_subscriptions(db: Session, limit: int, today: date | None = None) -> list[tuple[str, str]]:
    """[(source, subscription_external_id)] en ventana de riesgo, por prioridad y con tope `limit`."""
    day = today or now_chile().date()
    due_from = (day - timedelta(days=settings.targeted_reconcile_due_days)).isoformat()
    rej_from = (day - timedelta(days=settings.targeted_reconcile_rejection_days)).isoformat()
    today_s = day.isoformat()

    status = func.lower(func.coalesce(Charge.status, ""))
    cdate = func.substr(func.coalesce(Charge.charge_date, ""), 1, 10)
    is_rejected = (status.in_(REJECTED_STATES)) & (cdate >= rej_from) & (cdate <= today_s)
    is_due = (cdate >= due_from) & (cdate <= today_s)
    is_pending = (status.in_(PENDING_LIKE_STATES)) & (cdate != "") & (cdate <= today_s)

    priority = func.min(case((is_rejected, 0), (is_due, 1), (is_pending, 2), else_=literal(9))).label("priority")
    latest = func.max(cdate).label("latest")
    stmt = (
        select(Charge.source, Charge.subscription_external_id, priority, latest)
        .join(Subscription, (Subscription.source == Charge.source)
              & (Subscription.external_id == Charge.subscription_external_id))
        .where(
            Charge.source.in_(RISK_SOURCES),
            Charge.subscription_external_id.is_not(None),
            func.lower(func.coalesce(Subscription.status, "")).not_in(DEAD_SUBSCRIPTION_STATES),
            is_rejected | is_due | is_pending,
        )
        .group_by(Charge.source, Charge.subscription_external_id)
        .order_by(priority, latest.desc(), Charge.source, Charge.subscription_external_id)
        .limit(limit)
    )
    return [(row[0], row[1]) for row in db.execute(stmt)]


async def run_targeted_reconcile(
    db: Session,
    *,
    limit: int | None = None,
    pause_seconds: float | None = None,
    refresh: RefreshFn | None = None,
    sleep: SleepFn = asyncio.sleep,
    today: date | None = None,
) -> ReconcileSummary:
    """Una pasada: selecciona y refresca, con pausa entre peticiones, respetando el lock de sincronizacion."""
    refresh_fn = refresh or refresh_subscription
    cap = settings.targeted_reconcile_max_per_run if limit is None else limit
    pause = settings.targeted_reconcile_pause_seconds if pause_seconds is None else pause_seconds
    summary = ReconcileSummary()

    if find_active_run(db) is not None:
        summary.skipped_reason = "sync_active"
        return summary
    targets = select_risk_subscriptions(db, cap, today)
    summary.selected = len(targets)

    consecutive = 0
    for i, (source, sub_id) in enumerate(targets):
        if i and i % LOCK_RECHECK_EVERY == 0 and find_active_run(db) is not None:
            summary.skipped_reason = "sync_active"
            break
        if i and pause > 0:
            await sleep(pause)
        try:
            await refresh_fn(db, source, sub_id, run_id=uuid.uuid4())
            summary.refreshed += 1
            consecutive = 0
        except RefreshError as exc:
            summary.failed += 1
            summary.codes[exc.code] = summary.codes.get(exc.code, 0) + 1
            consecutive += 1
        except Exception as exc:  # noqa: BLE001 - un fallo no debe cortar la pasada; el codigo es fijo
            db.rollback()
            summary.failed += 1
            summary.codes["UNEXPECTED"] = summary.codes.get("UNEXPECTED", 0) + 1
            logger.warning("targeted_reconcile: fallo inesperado en %s (%s)", source, type(exc).__name__)
            consecutive += 1
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            summary.skipped_reason = "provider_failing"
            break
    return summary
