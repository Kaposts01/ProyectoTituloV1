"""Orquestador de sync completo: BDlocales sync → ETL consolidación.

Fase 1: Fetch desde APIs de proveedores → BDlocales PostgreSQL locales.
Fase 2: ETL BDlocales → tablas canónicas del CRM.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.models.etl_run import EtlRun
from app.services import bdlocales_sync
from app.services.etl_consolidation import run_etl_background

logger = logging.getLogger(__name__)

_SYNC_FN = {
    "virtualpos": bdlocales_sync.sync_virtualpos,
    "toku": bdlocales_sync.sync_toku,
    "payku": bdlocales_sync.sync_payku,
}


def _update_run(db, run_id: uuid.UUID, **kwargs) -> None:
    run = db.get(EtlRun, run_id)
    if not run:
        return
    for key, value in kwargs.items():
        setattr(run, key, value)
    db.commit()


def run_full_sync_background(run_id: uuid.UUID, providers: list[str]) -> None:
    """BackgroundTask: sync APIs → BDlocales → ETL consolidación."""
    db = SessionLocal()
    sync_total = 0
    try:
        for provider in providers:
            if provider not in _SYNC_FN:
                logger.warning("Proveedor desconocido: %s. Omitido.", provider)
                continue
            _update_run(db, run_id, phase=f"sync_{provider}")
            logger.info("Iniciando sync BDlocales: %s", provider)
            try:
                counts = _SYNC_FN[provider]()
                provider_total = sum(counts.values())
                sync_total += provider_total
                logger.info("Sync completado %s: %d registros", provider, provider_total)
            except Exception:
                logger.exception("Error en sync BDlocales de %s", provider)

        _update_run(db, run_id, phase="etl", records_upserted=sync_total)
        logger.info("Iniciando ETL consolidación (run_id=%s)", run_id)
    except Exception:
        _update_run(
            db, run_id,
            status="failed",
            phase=None,
            error_message="Error durante la sincronización o consolidación.",
            finished_at=datetime.now(timezone.utc),
        )
        logger.exception("Error en orquestación (run_id=%s)", run_id)
        return
    finally:
        db.close()

    # La ETL consolidación maneja su propio estado (completed/failed) en el mismo EtlRun
    run_etl_background(run_id)
