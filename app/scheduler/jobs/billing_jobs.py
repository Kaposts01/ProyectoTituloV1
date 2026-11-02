"""Jobs de facturacion gestionada (opcion A, pasos 6a/6b): chequeo de renovacion, expiracion de solicitudes y barrido de
solicitudes atascadas en `aplicando`.

Los tres son de SOLO LECTURA hacia el proveedor (no usan `VirtualPOSClient`): solo escriben tablas locales
(`billing_renewal_tasks`, estados `expirada` / `requiere_conciliacion` de `billing_change_requests`). Registran su corrida
en `sync_runs` (source = id del job, siempre con el prefijo `BILLING_JOB_PREFIX`), igual que las sincronizaciones, y no tocan
`etl_runs` (que usa `retry_failed_channels` para decidir que reintentar). Los KPI/listados de canales excluyen ese prefijo.

Fila `running`: se crea ANTES de trabajar (el endpoint manual la crea antes de lanzar la tarea y el job la adopta si ya
existe con el `run_id` recibido) para que el chequeo de 409 por ejecucion simultanea sea efectivo. Las corridas
programadas de expiracion y barrido que no hicieron nada borran su fila transitoria (evita 24 o 96 filas/dia vacias).

Estados de cierre en `sync_runs`: `completed`, `failed` (excepcion, o todos los registros fallaron) y `partial`
(el chequeo de renovacion termino con algunos registros fallidos; `error_message` = `errores=N`).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import text

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.sync_run import SyncRun

logger = logging.getLogger(__name__)

JOB_BILLING_RENEWAL = "billing_renewal_check"
JOB_BILLING_EXPIRE = "billing_expire_requests"
JOB_BILLING_SWEEP = "billing_sweep_applying"
BILLING_JOB_IDS = (JOB_BILLING_RENEWAL, JOB_BILLING_EXPIRE, JOB_BILLING_SWEEP)
# BILL-10: controles de consistencia (GB-CS-02..14). Fuera de BILLING_JOB_IDS: no se lanza a mano desde el panel ni
# escribe en `sync_runs`; solo lee (transaccion READ ONLY) y deja el resultado en el log, como la paridad VP-PAR-11.
JOB_BILLING_CONSISTENCY = "billing_consistency_check"

SWEEP_OLDER_THAN_MINUTES = 30


def _start_run(source: str, run_id: str | None) -> uuid.UUID:
    """Crea la fila `running`, o adopta la que ya creo el endpoint manual con ese `run_id`."""
    db = SessionLocal()
    try:
        if run_id:
            existing = db.get(SyncRun, uuid.UUID(run_id))
            if existing is not None:
                if existing.status != "running":
                    existing.status = "running"
                    db.commit()
                return existing.id
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


def _discard_run(run_pk: uuid.UUID) -> None:
    """Borra la fila transitoria de una corrida programada que no hizo nada."""
    db = SessionLocal()
    try:
        run = db.get(SyncRun, run_pk)
        if run is not None:
            db.delete(run)
            db.commit()
    finally:
        db.close()


def _renewal_sync(run_id: str | None) -> None:
    from app.services import billing_renewal

    run_pk = _start_run(JOB_BILLING_RENEWAL, run_id)
    db = SessionLocal()
    try:
        result = billing_renewal.run_renewal_check(db)
        note = f"errores={result.errors}" if result.errors else None
        # `failed` solo si TODOS los registros fallaron; con fallos parciales `partial` (no cuenta como exito y el
        # error queda anotado). `completed` solo sin errores.
        status = "completed" if not result.errors else ("failed" if result.errors >= result.examined else "partial")
        _finish_run(run_pk, status, result.opened + result.updated + result.closed + result.not_applicable, note)
    except Exception as exc:
        db.rollback()
        logger.exception("billing_renewal_check falló")
        _finish_run(run_pk, "failed", 0, type(exc).__name__)
    finally:
        db.close()


def _expire_sync(run_id: str | None) -> None:
    from app.services import billing_requests

    run_pk = _start_run(JOB_BILLING_EXPIRE, run_id)
    db = SessionLocal()
    try:
        expired = billing_requests.expire_pending_requests(db)
    except Exception as exc:
        db.rollback()
        logger.exception("billing_expire_requests falló")
        _finish_run(run_pk, "failed", 0, type(exc).__name__)
        return
    finally:
        db.close()
    logger.info("billing_expire_requests: %d solicitud(es) expirada(s).", len(expired))
    # Corre cada hora: solo deja registro cuando hizo algo o cuando se pidio manualmente (evita 24 filas/dia vacias).
    if expired or run_id:
        _finish_run(run_pk, "completed", len(expired), None)
    else:
        _discard_run(run_pk)


def _sweep_sync(run_id: str | None) -> None:
    from app.services import billing_apply

    run_pk = _start_run(JOB_BILLING_SWEEP, run_id)
    db = SessionLocal()
    try:
        swept = billing_apply.sweep_stuck_applying(db, older_than_minutes=SWEEP_OLDER_THAN_MINUTES)
    except Exception as exc:
        db.rollback()
        logger.exception("billing_sweep_applying falló")
        _finish_run(run_pk, "failed", 0, type(exc).__name__)
        return
    finally:
        db.close()
    logger.info("billing_sweep_applying: %d solicitud(es) barrida(s) a requiere_conciliacion.", len(swept))
    if swept or run_id:  # cada 15 min: solo deja registro cuando barrio algo o se pidio manualmente
        _finish_run(run_pk, "completed", len(swept), None)
    else:
        _discard_run(run_pk)


async def billing_renewal_check(run_id: str | None = None) -> None:
    """Chequeo diario de renovación (JB-25..JB-36). Crea/actualiza/cierra tareas; nunca escribe al proveedor."""
    await asyncio.to_thread(_renewal_sync, run_id)


async def billing_expire_requests(run_id: str | None = None) -> None:
    """Expira las solicitudes `pendiente` vencidas (AP-10). Idempotente."""
    await asyncio.to_thread(_expire_sync, run_id)


async def billing_sweep_applying(run_id: str | None = None) -> None:
    """Pasa a `requiere_conciliacion` las solicitudes atascadas en `aplicando` (proceso caído). Idempotente."""
    await asyncio.to_thread(_sweep_sync, run_id)


def _consistency_sync():
    from app.services import billing_consistency

    db = SessionLocal()
    try:
        db.execute(text("SET TRANSACTION READ ONLY"))  # garantia dura: el control no puede escribir
        return billing_consistency.run_consistency_checks(db)
    finally:
        db.rollback()
        db.close()


async def billing_consistency_check() -> None:
    """Controles diarios de consistencia (BILL-10). Detras de BILLING_CONSISTENCY_CHECK_ENABLED (apagada por defecto).

    Resultado al log sin PII (codigos, severidades y cantidades): WARNING si hay hallazgos, INFO si todo cuadra. Los
    hallazgos que bloquean (CS-03, CS-09) ya bloquean por si mismos en la creacion de solicitudes; aqui solo se alerta."""
    if not settings.billing_consistency_check_enabled:
        return
    try:
        report = await asyncio.to_thread(_consistency_sync)
    except Exception as exc:  # noqa: BLE001 - un tick fallido no debe tumbar el scheduler
        logger.warning("billing_consistency_check: fallo (%s)", type(exc).__name__)
        return
    if report.ok:
        logger.info("billing_consistency_check: OK (%d suscripciones gestionadas revisadas).", report.subscriptions_checked)
        return
    logger.warning(
        "billing_consistency_check: %d hallazgo(s) en %d suscripciones revisadas; severidad=%s codigos=%s bloqueadas=%d",
        len(report.findings), report.subscriptions_checked, report.by_severity(), report.counts(),
        len({(f.platform, f.subscription_external_id) for f in report.findings if f.blocks}),
    )
