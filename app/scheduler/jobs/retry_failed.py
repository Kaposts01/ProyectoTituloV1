"""Job de reintento: re-sincroniza los canales que fallaron en el último run.

SYNC-D-10 (cierra SYNC-O-17):
- Desacoplado de la ventana: si la sync principal sigue corriendo a las 04:00, el reintento no se pierde; se pospone
  `SYNC_RETRY_DEFER_MINUTES` (job de una sola vez) hasta `SYNC_RETRY_MAX_DEFERRALS` veces.
- Tope: un canal con `SYNC_RETRY_MAX_FAILURES_PER_DAY` corridas fallidas hoy (dia de Chile) no se vuelve a reintentar;
  hay que revisarlo a mano (un fallo que se repite no es transitorio).
- Los errores de configuracion nunca se reintentan (SYNC-D-09).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, select

from app.core.channel_errors import CONFIG_ERROR_PREFIX
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.etl_run import EtlRun
from app.models.sync_run import SyncRun
from app.scheduler.run_lock import find_active_run
from app.services.rejected_month import CHILE_TZ

logger = logging.getLogger(__name__)

JOB_SYNC_RETRY_DEFERRED = "retry_failed_channels_deferred"


def _chile_day_start_utc(now: datetime | None = None) -> datetime:
    local = (now or datetime.now(timezone.utc)).astimezone(CHILE_TZ)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _exhausted_sources(db, channels: list[str]) -> set[str]:
    """Canales que ya acumulan el tope de corridas fallidas hoy (dia de Chile): no se reintentan mas."""
    limit = max(1, int(settings.sync_retry_max_failures_per_day))
    query = (
        select(SyncRun.source, func.count())
        .where(SyncRun.source.in_(channels), SyncRun.status == "failed", SyncRun.started_at >= _chile_day_start_utc())
        .group_by(SyncRun.source)
    )
    return {source for source, failures in db.execute(query) if isinstance(failures, int) and failures >= limit}


def _defer_retry(deferrals: int) -> bool:
    """Programa un reintento de una sola vez dentro de N minutos. False si se agoto el tope o no hay scheduler activo."""
    if deferrals >= max(0, int(settings.sync_retry_max_deferrals)):
        logger.error("retry_failed_channels: la sync principal sigue activa tras %d esperas; se omite el reintento.", deferrals)
        return False
    from app.scheduler.engine import get_scheduler

    scheduler = get_scheduler()
    if not scheduler.running:
        logger.info("retry_failed_channels: scheduler detenido, no se pospone el reintento.")
        return False
    run_date = datetime.now(timezone.utc) + timedelta(minutes=max(1, int(settings.sync_retry_defer_minutes)))
    scheduler.add_job(
        retry_failed_channels,
        trigger="date",
        run_date=run_date,
        kwargs={"deferrals": deferrals + 1},
        id=JOB_SYNC_RETRY_DEFERRED,
        name="Reintento canales fallidos (pospuesto)",
        replace_existing=True,
    )
    logger.info("retry_failed_channels: sync activa; reintento pospuesto a %s (espera %d).", run_date.isoformat(), deferrals + 1)
    return True


def _config_failed_sources(db, channels: list[str]) -> set[str]:
    """Canales cuyo ultimo SyncRun fallo por configuracion incompleta."""
    latest = (
        select(SyncRun.source, SyncRun.error_message)
        .where(SyncRun.source.in_(channels))
        .distinct(SyncRun.source)
        .order_by(SyncRun.source, SyncRun.started_at.desc())
    )
    return {
        source
        for source, message in db.execute(latest)
        if message and message.startswith(CONFIG_ERROR_PREFIX)
    }


async def retry_failed_channels(deferrals: int = 0) -> None:
    """Si el último EtlRun registró canales fallidos, los reintenta ahora.

    Solo actúa cuando:
    - El último run terminado tiene channels_failed no vacío.
    - No hay un run activo en este momento (si lo hay, se pospone; ver `_defer_retry`).
    - El canal no falló por configuración ni alcanzó el tope de fallos del día.
    """
    db = SessionLocal()
    try:
        active = find_active_run(db)  # expira los `running` abandonados (SYNC-O-11)
        if active:
            logger.info("retry_failed_channels: sync activa (run_id=%s), no se reintenta ahora.", active.id)
            _defer_retry(deferrals)
            return

        last = db.scalar(
            select(EtlRun)
            .where(EtlRun.status.in_(["completed", "partial", "failed"]))
            .order_by(desc(EtlRun.started_at))
            .limit(1)
        )
        if last is None or not last.channels_failed:
            logger.debug("retry_failed_channels: sin canales fallidos en el último run, nada que reintentar.")
            return

        failed = list(last.channels_failed)
        # Un error de configuracion es determinista: reintentar no lo arregla (hay que corregir el .env).
        config_broken = _config_failed_sources(db, failed)
        if config_broken:
            logger.error(
                "retry_failed_channels: canal(es) con error de configuracion, no se reintentan: %s",
                sorted(config_broken),
            )
        exhausted = _exhausted_sources(db, [c for c in failed if c not in config_broken])
        if exhausted:
            logger.error(
                "retry_failed_channels: canal(es) con %d+ fallos hoy, no se reintentan mas: %s",
                settings.sync_retry_max_failures_per_day,
                sorted(exhausted),
            )
        channels_to_retry = [c for c in failed if c not in config_broken and c not in exhausted]
        if not channels_to_retry:
            return
        logger.warning(
            "retry_failed_channels: reintentando %d canal(es) fallidos del run %s: %s",
            len(channels_to_retry),
            last.id,
            channels_to_retry,
        )
    finally:
        db.close()

    from app.scheduler.jobs.sync_all import sync_all_channels
    await sync_all_channels(channels=channels_to_retry)
    logger.info("retry_failed_channels: reintento completado para %s.", channels_to_retry)
