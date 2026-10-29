"""Job del procesador de webhooks (RT-05): cada minuto drena la cola `webhook_events`.

Detras de `WEBHOOK_PROCESSOR_ENABLED` (apagada por defecto). La exclusion entre workers la da `FOR UPDATE SKIP LOCKED`
dentro del procesador, de modo que varios procesos o ticks solapados nunca toman el mismo evento.
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.webhook_processor import process_pending

logger = logging.getLogger(__name__)

JOB_WEBHOOK_PROCESSOR = "webhook_processor"
MAX_BATCHES_PER_TICK = 5


async def process_webhook_queue() -> None:
    if not settings.webhook_processor_enabled:
        return
    db = SessionLocal()
    try:
        for _ in range(MAX_BATCHES_PER_TICK):
            summary = await process_pending(db)
            if summary.claimed:
                logger.info(
                    "webhook_processor: reclamados=%d done=%d ignorados=%d reintentos=%d fallidos=%d refresh=%d",
                    summary.claimed, summary.done, summary.ignored, summary.retried, summary.failed, summary.refreshes,
                )
            if summary.claimed < settings.webhook_processor_batch_size:
                break
    except Exception as exc:  # noqa: BLE001 - un tick fallido no debe tumbar el scheduler
        logger.warning("webhook_processor: tick fallido (%s)", type(exc).__name__)
    finally:
        db.close()
