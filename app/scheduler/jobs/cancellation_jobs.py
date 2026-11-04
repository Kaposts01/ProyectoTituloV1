"""Jobs de bajas de suscripcion: expiracion de solicitudes `pending` y barrido de las atascadas en `applying`.

Usan solo tablas locales (no llaman al proveedor). Registran su corrida en `sync_runs` con `source` = id del job, siempre con
el prefijo `CANCELLATION_JOB_PREFIX`, que los KPI y listados de canales excluyen (igual que el prefijo `billing_`).
Reutilizan la mecanica de filas de `billing_jobs` (fila `running` antes de trabajar, adopcion por `run_id`, descarte de la
fila transitoria cuando una corrida programada no hizo nada, error persistido solo como nombre de la clase).
"""

from __future__ import annotations

import asyncio
import logging

from app.db.session import SessionLocal
from app.scheduler.jobs.billing_jobs import _discard_run, _finish_run, _start_run

logger = logging.getLogger(__name__)

JOB_CANCELLATION_EXPIRE = "cancellation_expire_requests"
JOB_CANCELLATION_SWEEP = "cancellation_sweep_applying"
CANCELLATION_JOB_IDS = (JOB_CANCELLATION_EXPIRE, JOB_CANCELLATION_SWEEP)

SWEEP_OLDER_THAN_MINUTES = 30


def _expire_sync(run_id: str | None) -> None:
    from app.services import cancellation_requests

    run_pk = _start_run(JOB_CANCELLATION_EXPIRE, run_id)
    db = SessionLocal()
    try:
        expired = cancellation_requests.expire_pending_cancellation_requests(db)
    except Exception as exc:
        db.rollback()
        logger.exception("cancellation_expire_requests falló")
        _finish_run(run_pk, "failed", 0, type(exc).__name__)
        return
    finally:
        db.close()
    logger.info("cancellation_expire_requests: %d solicitud(es) expirada(s).", len(expired))
    if expired or run_id:  # cada hora: solo deja registro cuando hizo algo o se pidio manualmente
        _finish_run(run_pk, "completed", len(expired), None)
    else:
        _discard_run(run_pk)


def _sweep_sync(run_id: str | None) -> None:
    from app.services import cancellation_apply

    run_pk = _start_run(JOB_CANCELLATION_SWEEP, run_id)
    db = SessionLocal()
    try:
        swept = cancellation_apply.sweep_stuck_applying(db, older_than_minutes=SWEEP_OLDER_THAN_MINUTES)
    except Exception as exc:
        db.rollback()
        logger.exception("cancellation_sweep_applying falló")
        _finish_run(run_pk, "failed", 0, type(exc).__name__)
        return
    finally:
        db.close()
    logger.info("cancellation_sweep_applying: %d solicitud(es) pasada(s) a requires_reconciliation.", len(swept))
    if swept or run_id:  # cada 15 min: solo deja registro cuando barrio algo o se pidio manualmente
        _finish_run(run_pk, "completed", len(swept), None)
    else:
        _discard_run(run_pk)


async def cancellation_expire_requests(run_id: str | None = None) -> None:
    """Pasa a `expired` las solicitudes de baja `pending` vencidas. Idempotente."""
    await asyncio.to_thread(_expire_sync, run_id)


async def cancellation_sweep_applying(run_id: str | None = None) -> None:
    """Pasa a `requires_reconciliation` las bajas atascadas en `applying` (proceso caido). Idempotente."""
    await asyncio.to_thread(_sweep_sync, run_id)
