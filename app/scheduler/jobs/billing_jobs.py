"""Jobs de facturacion gestionada (opcion A, paso 6a): chequeo de renovacion y expiracion de solicitudes.

Ambos son de SOLO LECTURA hacia el proveedor (no usan `VirtualPOSClient`): solo escriben tablas locales
(`billing_renewal_tasks`, estado `expirada` de `billing_change_requests`). Registran su corrida en `sync_runs`
(source = id del job), igual que las sincronizaciones, y no tocan `etl_runs` (que usa `retry_failed_channels`
para decidir que reintentar).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from app.db.session import SessionLocal
from app.models.sync_run import SyncRun

logger = logging.getLogger(__name__)

JOB_BILLING_RENEWAL = "billing_renewal_check"
JOB_BILLING_EXPIRE = "billing_expire_requests"
BILLING_JOB_IDS = (JOB_BILLING_RENEWAL, JOB_BILLING_EXPIRE)


def _start_run(source: str, run_id: str | None) -> uuid.UUID:
    db = SessionLocal()
    try:
        run = SyncRun(source=source, status="running")
        if run_id:
            run.id = uuid.UUID(run_id)
        db.add(run)
        db.commit()
        return run.id
    finally:
        db.close()


def _finish_run(run_pk: uuid.UUID, status: str, records: int, error: str | None) -> None:
    db = SessionLocal()
    try:
        run = db.get(SyncRun, run_pk)
        if run is not None:
            run.status = status
            run.records_processed = records
            run.error_message = error
            run.finished_at = datetime.now(UTC)
            db.commit()
    finally:
        db.close()


def _renewal_sync(run_id: str | None) -> None:
    from app.services.billing_renewal import run_renewal_check

    run_pk = _start_run(JOB_BILLING_RENEWAL, run_id)
    db = SessionLocal()
    try:
        result = run_renewal_check(db)
        note = f"errores={result.errors}" if result.errors else None
        _finish_run(run_pk, "completed", result.opened + result.updated + result.closed + result.not_applicable, note)
    except Exception as exc:
        db.rollback()
        logger.exception("billing_renewal_check falló")
        _finish_run(run_pk, "failed", 0, type(exc).__name__)
    finally:
        db.close()


def _expire_sync(run_id: str | None) -> None:
    from app.services.billing_requests import expire_pending_requests

    db = SessionLocal()
    try:
        expired = expire_pending_requests(db)
    except Exception as exc:
        db.rollback()
        logger.exception("billing_expire_requests falló")
        _finish_run(_start_run(JOB_BILLING_EXPIRE, run_id), "failed", 0, type(exc).__name__)
        return
    finally:
        db.close()
    logger.info("billing_expire_requests: %d solicitud(es) expirada(s).", len(expired))
    # Corre cada hora: solo deja registro cuando hizo algo o cuando se pidio manualmente (evita 24 filas/dia vacias).
    if expired or run_id:
        _finish_run(_start_run(JOB_BILLING_EXPIRE, run_id), "completed", len(expired), None)


async def billing_renewal_check(run_id: str | None = None) -> None:
    """Chequeo diario de renovacion (JB-25..JB-36). Crea/actualiza/cierra tareas; nunca escribe al proveedor."""
    await asyncio.to_thread(_renewal_sync, run_id)


async def billing_expire_requests(run_id: str | None = None) -> None:
    """Expira las solicitudes `pendiente` vencidas (AP-10). Idempotente."""
    await asyncio.to_thread(_expire_sync, run_id)
