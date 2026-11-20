"""Jobs de los reportes por correo (REP-02): resumen semanal (lunes 07:30) y cierre mensual (primer dia habil 07:45).

Hora de Chile (America/Santiago). Cada uno va detras de su bandera (`REPORTS_WEEKLY_ENABLED`, `REPORTS_MONTHLY_ENABLED`,
apagadas por defecto): con la bandera apagada el job no abre sesion ni hace nada. El mensual se evalua todos los dias y
solo actua el primer dia habil del mes (`app/core/business_days.py`). Envio tardio: ademas del `misfire_grace_time` de
6 h con `coalesce`, un job de arranque (`report_catch_up`, 2 min despues de iniciar el scheduler) envia lo que quedo
vencido si el backend estuvo caido y aun estamos dentro de las 6 h posteriores a la hora programada (el registro de jobs
reemplaza los del almacen al arrancar, asi que el `misfire` por si solo no cubre un reinicio). La tabla `report_dispatches`
evita el doble envio.
Un fallo se reintenta hasta 3 veces con una espera entre intentos. No escribe en `sync_runs` ni `etl_runs`.
Ver `app/services/report_delivery.py` y docs/data/scheduled_reports.md.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.business_days import is_first_business_day
from app.core.config import settings
from app.db.session import SessionLocal
from app.services import report_delivery, scheduled_reports

logger = logging.getLogger(__name__)

JOB_REPORT_WEEKLY = "report_weekly"
JOB_REPORT_MONTHLY = "report_monthly"
JOB_REPORT_CATCHUP = "report_catch_up"
WEEKLY_MINUTE = 30
MONTHLY_MINUTE = 45
MISFIRE_GRACE_SECONDS = 6 * 3600
RETRY_DELAY_SECONDS = 120
CATCH_UP_WINDOW = timedelta(hours=6)
CATCH_UP_DELAY_SECONDS = 120


def _dispatch_sync(kind: str) -> report_delivery.DispatchResult:
    db = SessionLocal()
    try:
        return report_delivery.dispatch_report(db, kind)
    finally:
        db.close()


async def _run(kind: str) -> None:
    try:
        for attempt in range(1, report_delivery.MAX_ATTEMPTS + 1):
            result = await asyncio.to_thread(_dispatch_sync, kind)
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
    """Corre todos los dias; solo actua el primer dia habil del mes (hora de Chile)."""
    if not settings.reports_monthly_enabled:
        return
    if not is_first_business_day(scheduled_reports.chile_date(datetime.now(UTC))):
        return
    await _run("monthly")


def due_kinds(now: datetime) -> list[str]:
    """Reportes cuya hora programada de HOY (hora de Chile) ya paso hace menos de 6 h. Solo mira la hora y el calendario."""
    local = now.astimezone(ZoneInfo("America/Santiago"))
    out: list[str] = []
    checks = (
        ("weekly", local.weekday() == 0, settings.report_weekly_hour, WEEKLY_MINUTE),
        ("monthly", is_first_business_day(local.date()), settings.report_monthly_hour, MONTHLY_MINUTE),
    )
    for kind, day_ok, hour, minute in checks:
        if not day_ok:
            continue
        scheduled = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if scheduled <= local < scheduled + CATCH_UP_WINDOW:
            out.append(kind)
    return out


async def report_catch_up() -> None:
    """Al arrancar: envia lo vencido (dentro de 6 h) que el backend caido no alcanzo a enviar. Idempotente."""
    for kind in due_kinds(datetime.now(UTC)):
        enabled = settings.reports_weekly_enabled if kind == "weekly" else settings.reports_monthly_enabled
        if enabled:
            logger.info("report_catch_up: revisando el reporte %s vencido.", kind)
            await _run(kind)
