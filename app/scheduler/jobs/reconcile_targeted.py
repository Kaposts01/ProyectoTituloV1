"""Job de reconciliacion dirigida (RT-06): cada 3 horas de 07:00 a 22:00 (D10), detras de TARGETED_RECONCILE_ENABLED."""

from __future__ import annotations

import logging

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.targeted_reconcile import run_targeted_reconcile

logger = logging.getLogger(__name__)


async def reconcile_targeted() -> None:
    if not settings.targeted_reconcile_enabled:
        return
    db = SessionLocal()
    try:
        summary = await run_targeted_reconcile(db)
        logger.info(
            "reconcile_targeted: seleccionadas=%d refrescadas=%d fallidas=%d omitida=%s codigos=%s",
            summary.selected, summary.refreshed, summary.failed, summary.skipped_reason, summary.codes,
        )
    except Exception as exc:  # noqa: BLE001 - una pasada fallida no debe tumbar el scheduler
        logger.warning("reconcile_targeted: pasada fallida (%s)", type(exc).__name__)
    finally:
        db.close()
