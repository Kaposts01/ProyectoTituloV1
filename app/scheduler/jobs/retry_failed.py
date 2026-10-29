"""Job de reintento: re-sincroniza los canales que fallaron en el último run."""

from __future__ import annotations

import logging

from sqlalchemy import desc, select

from app.core.channel_errors import CONFIG_ERROR_PREFIX
from app.db.session import SessionLocal
from app.models.etl_run import EtlRun
from app.models.sync_run import SyncRun

logger = logging.getLogger(__name__)


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


async def retry_failed_channels() -> None:
    """Si el último EtlRun registró canales fallidos, los reintenta ahora.

    Solo actúa cuando:
    - El último run terminado tiene channels_failed no vacío.
    - No hay un run activo en este momento.
    """
    db = SessionLocal()
    try:
        active = db.scalar(select(EtlRun).where(EtlRun.status == "running").limit(1))
        if active:
            logger.info("retry_failed_channels: sync activa (run_id=%s), omitiendo reintento.", active.id)
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
        channels_to_retry = [c for c in failed if c not in config_broken]
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
