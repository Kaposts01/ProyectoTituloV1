"""SYNC-O-11: arranque atomico y exclusivo de una sincronizacion / ETL (`etl_runs`).

Antes: `SELECT ... WHERE status='running'` y luego `INSERT` (ventana TOCTOU: con 2 workers o 2 clics ambos pasaban),
y un `running` abandonado bloqueaba hasta reiniciar el servidor.

Ahora: la comprobacion y el INSERT de la fila `running` ocurren bajo `pg_advisory_xact_lock` (el mismo mecanismo
de PostgreSQL que usa `billing_apply`), de modo que de N intentos simultaneos solo uno crea la fila y los demas
reciben `ActiveRunError`. La fila `running` es el marcador durable; el lock solo serializa su creacion. Un `running`
mas viejo que `settings.sync_run_stale_hours` se da por abandonado (se marca `failed`) y deja de bloquear.

Aplica al job nocturno, al reintento, a /scheduler/jobs/*/run, a /etl/full-sync, a /etl/core/* y a la importacion
TCH. Destino futuro (D11): un worker separado con lider por advisory lock; este modulo sigue siendo el guardian.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.etl_run import EtlRun

logger = logging.getLogger(__name__)

ABANDONED_MESSAGE = "Corrida abandonada: sin finalizar tras el limite de horas (proceso caido)."
# Texto con que el arranque del servidor cierra las corridas que quedaron `running` (app.main._cleanup_zombie_runs).
RESTART_MESSAGE = "Servidor reiniciado durante la sincronización."
# 13B: corridas cerradas como `failed` por el propio CRM (reinicio o abandono), no por un fallo del proveedor. La salud
# de sincronizacion no las cuenta como «falló»: el canal queda «atrasado» segun su ultimo exito.
INTERRUPTED_MESSAGES = (RESTART_MESSAGE, ABANDONED_MESSAGE)


def _lock_key() -> int:
    digest = hashlib.blake2b(b"sync:etl_runs:start", digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


ACTIVE_RUN_LOCK_KEY = _lock_key()


class ActiveRunError(Exception):
    """Ya hay una sincronizacion/ETL en curso; `run_id` es la corrida activa."""

    def __init__(self, run_id: uuid.UUID | None) -> None:
        self.run_id = run_id
        super().__init__(f"Ya hay una sincronización activa (run_id={run_id}). Espera a que termine.")


def expire_stale_runs(db: Session, stale_hours: float | None = None) -> int:
    """Marca `failed` los `etl_runs` en `running` mas viejos que el limite. No hace commit. Devuelve cuantos."""
    hours = settings.sync_run_stale_hours if stale_hours is None else stale_hours
    result = db.execute(
        update(EtlRun)
        .where(EtlRun.status == "running", EtlRun.started_at < func.now() - timedelta(hours=hours))
        .values(status="failed", phase=None, error_message=ABANDONED_MESSAGE, finished_at=func.now())
    )
    count = result.rowcount or 0
    if count:
        logger.warning("Se expiraron %d etl_run(s) 'running' abandonados (mas de %s h).", count, hours)
    return count


def find_active_run(db: Session) -> EtlRun | None:
    """Corrida `running` vigente (tras expirar las abandonadas). Solo lectura salvo la expiracion."""
    if expire_stale_runs(db):
        db.commit()
    return db.scalar(select(EtlRun).where(EtlRun.status == "running").order_by(EtlRun.started_at).limit(1))


def start_exclusive_runs(db: Session, specs: list[dict[str, Any]]) -> list[EtlRun]:
    """Crea, de forma atomica, una fila `running` por cada spec; falla si ya hay una corrida activa.

    Los `specs` son kwargs de `EtlRun` (p. ej. `phase`, `channels_processed`, `id`). Todas se crean bajo el mismo
    lock: una secuencia de ETL (`/core/all`) reserva sus filas de una vez sin pelearse consigo misma.
    """
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": ACTIVE_RUN_LOCK_KEY})  # se libera en commit/rollback
    expire_stale_runs(db)
    active = db.scalar(select(EtlRun).where(EtlRun.status == "running").order_by(EtlRun.started_at).limit(1))
    if active is not None:
        active_id = active.id
        db.commit()  # persiste la expiracion y libera el lock
        raise ActiveRunError(active_id)
    runs = []
    for spec in specs:
        fields = {"status": "running", "records_upserted": 0, **spec}
        runs.append(EtlRun(**fields))
    db.add_all(runs)
    db.commit()
    for run in runs:
        db.refresh(run)
    return runs


def start_exclusive_run(db: Session, **fields: Any) -> EtlRun:
    """Version de una sola fila de `start_exclusive_runs`."""
    return start_exclusive_runs(db, [fields])[0]
