"""Jobs de los reportes por correo (REP-02): resumen semanal (lunes 07:30) y cierre mensual (primer dia habil 07:45).

Hora de Chile (America/Santiago). Cada uno va detras de su bandera (`REPORTS_WEEKLY_ENABLED`, `REPORTS_MONTHLY_ENABLED`,
apagadas por defecto): con la bandera apagada el job no abre sesion ni hace nada.
Envio tardio: en CADA disparo (el semanal, el mensual que corre todos los dias, y `report_catch_up`, 2 min despues de
iniciar el scheduler) se calcula el ULTIMO periodo cuya hora programada ya paso (`last_due_ref`) y se intenta enviar,
aunque hayan pasado dias (equipo apagado, backend caido). Solo el ultimo periodo vencido, no los anteriores. La tabla
`report_dispatches` (unica por tipo y periodo) hace que sea idempotente: si ya salio, no se repite. El `misfire_grace_time`
de 6 h con `coalesce` sigue como respaldo. Los jobs se registran solo si faltan (`_register_report_jobs`): el almacen de
jobs es persistente y no se reemplaza al arrancar, por eso el catch-up corre en cada arranque.
Un fallo se reintenta hasta 3 veces con una espera entre intentos. No escribe en `sync_runs` ni `etl_runs`.
Ver `app/services/report_delivery.py` y docs/data/scheduled_reports.md.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.business_days import first_business_day
from app.core.config import settings
from app.db.session import SessionLocal
from app.services import report_delivery

logger = logging.getLogger(__name__)

JOB_REPORT_WEEKLY = "report_weekly"
JOB_REPORT_MONTHLY = "report_monthly"
JOB_REPORT_CATCHUP = "report_catch_up"
WEEKLY_MINUTE = 30
MONTHLY_MINUTE = 45
MISFIRE_GRACE_SECONDS = 6 * 3600
RETRY_DELAY_SECONDS = 120
CHILE = ZoneInfo("America/Santiago")
CATCH_UP_DELAY_SECONDS = 120


def last_due_ref(kind: str, now: datetime) -> datetime:
    """Instante que sirve de referencia para el ULTIMO periodo cuya hora programada ya paso (hora de Chile).

    Si la hora programada de este ciclo (lunes 07:30 / primer dia habil 07:45) ya paso, es `now`; si no, un instante del
    ciclo anterior, cuyo periodo es el ultimo vencido. Se pasa a `dispatch_report(period_at=...)` y a `period_key_for`."""
    local = now.astimezone(CHILE)
    if kind == "weekly":
        monday = local.date() - timedelta(days=local.weekday())
        due = datetime.combine(monday, time(settings.report_weekly_hour, WEEKLY_MINUTE), tzinfo=CHILE)
        return now if local >= due else now - timedelta(days=7)
    first = first_business_day(local.year, local.month)
    due = datetime.combine(first, time(settings.report_monthly_hour, MONTHLY_MINUTE), tzinfo=CHILE)
    return now if local >= due else local.replace(day=1) - timedelta(days=1)


def _dispatch_sync(kind: str, period_at: datetime) -> report_delivery.DispatchResult:
    db = SessionLocal()
    try:
        return report_delivery.dispatch_report(db, kind, period_at=period_at)
    finally:
        db.close()


async def _run(kind: str) -> None:
    try:
        period_at = last_due_ref(kind, datetime.now(UTC))
        for attempt in range(1, report_delivery.MAX_ATTEMPTS + 1):
            result = await asyncio.to_thread(_dispatch_sync, kind, period_at)
            if result.status != "failed" or result.reason == "claim_failed":
                return
            if attempt < report_delivery.MAX_ATTEMPTS:
                await asyncio.sleep(RETRY_DELAY_SECONDS)
        logger.warning("report_%s: agotó los %d intentos (%s).", kind, report_delivery.MAX_ATTEMPTS, result.error_class)
    except Exception as exc:  # noqa: BLE001 - un tick fallido no debe tumbar el scheduler
        logger.warning("report_%s: tick fallido (%s)", kind, type(exc).__name__)


async def report_weekly() -> None:
    if not settings.reports_weekly_enabled:
        return
    await _run("weekly")


async def report_monthly() -> None:
    """Corre todos los dias: envia el ultimo cierre mensual vencido si falta (el primer dia habil es el caso normal)."""
    if not settings.reports_monthly_enabled:
        return
    await _run("monthly")


async def report_catch_up() -> None:
    """Al arrancar: envia el ultimo periodo vencido que falte, aunque hayan pasado dias. Idempotente."""
    for kind, enabled in (("weekly", settings.reports_weekly_enabled), ("monthly", settings.reports_monthly_enabled)):
        if enabled:
            logger.info("report_catch_up: revisando el último reporte %s vencido.", kind)
            await _run(kind)
