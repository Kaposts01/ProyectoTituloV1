"""Job de reintento: re-sincroniza los canales que fallaron en el último run."""

from __future__ import annotations

import logging

from sqlalchemy import desc, select

from app.db.session import SessionLocal
from app.models.etl_run import EtlRun

logger = logging.getLogger(__name__)


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
            .where(EtlRun.status.in_(["completed", "failed"]))
            .order_by(desc(EtlRun.started_at))
            .limit(1)
        )
        if last is None or not last.channels_failed:
            logger.debug("retry_failed_channels: sin canales fallidos en el último run, nada que reintentar.")
            return

        channels_to_retry = list(last.channels_failed)
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
