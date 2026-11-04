"""Job de alertas por correo (SYNC-D-08): cada 15 minutos evalua las condiciones y avisa. Ver `app/services/alerts.py`.

Detras de `ALERTS_ENABLED` (apagada por defecto). No escribe en `sync_runs` (un `source` nuevo apareceria como canal en los
KPI) ni en `etl_runs`: el resultado va al log y el estado de deduplicacion a `source_records` (`alert_state`). Un tick
fallido jamas tumba el scheduler ni la sincronizacion.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.db.session import SessionLocal
from app.services import alerts

logger = logging.getLogger(__name__)

JOB_ALERTS = "alerts_check"


def _check_sync() -> None:
    db = SessionLocal()
    try:
        result = alerts.run_alert_check(db)
        if result.sent or result.failed:
            logger.info("alerts_check: enviados=%d fallidos=%d activas=%d", result.sent, result.failed, result.active)
    finally:
        db.close()


async def check_alerts() -> None:
    if not settings.alerts_enabled:
        return
    try:
        await asyncio.to_thread(_check_sync)
    except Exception as exc:  # noqa: BLE001 - un tick fallido no debe tumbar el scheduler
        logger.warning("alerts_check: tick fallido (%s)", type(exc).__name__)
