import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import require_csrf, require_permissions
from app.db.session import SessionLocal
from app.models.etl_run import EtlRun
from app.models.source_record import SourceRecord
from app.services.channel_consolidation import consolidate_to_canonical
from app.services.crm_materialization import materialize_records
from app.services.payku_sync import sync_payku
from app.services.toku_sync import sync_toku
from app.services.virtualpos_sync import sync_virtualpos

logger = logging.getLogger(__name__)

router = APIRouter()

_ALL_PROVIDERS = ["virtualpos", "toku", "payku"]

_SYNC_FN = {
    "virtualpos": sync_virtualpos,
    "toku": sync_toku,
    "payku": sync_payku,
}


class FullSyncRequest(BaseModel):
    providers: Annotated[list[str], Field(default_factory=lambda: list(_ALL_PROVIDERS))]


def _get_db() -> Session:
    return SessionLocal()


def _update_run(run_id: uuid.UUID, **kwargs) -> None:
    db = SessionLocal()
    try:
        run = db.get(EtlRun, run_id)
        if run:
            for key, value in kwargs.items():
                setattr(run, key, value)
            db.commit()
    finally:
        db.close()


def _serialize_run(run: EtlRun) -> dict:
    return {
        "id": str(run.id),
        "status": run.status,
        "phase": run.phase,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "channels_processed": run.channels_processed,
        "records_upserted": run.records_upserted,
        "error_message": run.error_message,
    }


async def _run_full_sync_background(run_id: uuid.UUID, providers: list[str]) -> None:
    """BackgroundTask: sync APIs → source_records → materialización (Pipeline B)."""
    total = 0
    try:
        for provider in providers:
            if provider not in _SYNC_FN:
                logger.warning("Proveedor desconocido: %s. Omitido.", provider)
                continue
            _update_run(run_id, phase=f"sync_{provider}")
            logger.info("Iniciando sync Pipeline B: %s", provider)
            try:
                db = SessionLocal()
                try:
                    sync_run = await _SYNC_FN[provider](db)
                    total += sync_run.records_processed or 0
                    logger.info("Sync completado %s: %d registros", provider, sync_run.records_processed)
                finally:
                    db.close()
            except Exception:
                logger.exception("Error en sync de %s", provider)

        # Consolidación desde tablas canal → tablas canónicas
        _update_run(run_id, phase="consolidating")
        db = SessionLocal()
        try:
            consolidated = consolidate_to_canonical(db, providers)
            total += consolidated
            logger.info("Consolidación completada: %d registros", consolidated)
        finally:
            db.close()

        _update_run(
            run_id,
            status="completed",
            phase=None,
            channels_processed=providers,
            records_upserted=total,
            finished_at=datetime.now(timezone.utc),
        )
    except Exception:
        logger.exception("Error en full-sync (run_id=%s)", run_id)
        _update_run(
            run_id,
            status="failed",
            phase=None,
            error_message="Error durante la sincronización.",
            finished_at=datetime.now(timezone.utc),
        )


async def _run_materialization_background(run_id: uuid.UUID) -> None:
    """BackgroundTask: materializa source_records existentes en entidades canónicas."""
    try:
        _update_run(run_id, phase="materializing")
        db = SessionLocal()
        try:
            staged = db.scalars(select(SourceRecord)).all()
            materialize_records(db, staged)
            _update_run(
                run_id,
                status="completed",
                phase=None,
                records_upserted=len(staged),
                finished_at=datetime.now(timezone.utc),
            )
        finally:
            db.close()
    except Exception:
        logger.exception("Error en materialización (run_id=%s)", run_id)
        _update_run(
            run_id,
            status="failed",
            phase=None,
            error_message="Error durante la materialización.",
            finished_at=datetime.now(timezone.utc),
        )


@router.post("/run", dependencies=[Depends(require_permissions("etl.run")), Depends(require_csrf)], tags=["ETL"])
def trigger_etl(background_tasks: BackgroundTasks) -> dict:
    """Materializa source_records existentes en entidades canónicas."""
    db = _get_db()
    try:
        run = EtlRun(status="running", records_upserted=0, phase="materializing")
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()

    background_tasks.add_task(_run_materialization_background, run_id)
    return {"run_id": str(run_id), "status": "running"}


@router.get("/runs", dependencies=[Depends(require_permissions("sync_runs.view"))], tags=["ETL"])
def list_etl_runs() -> list[dict]:
    """Lista los últimos 20 runs del ETL."""
    db = _get_db()
    try:
        runs = db.scalars(select(EtlRun).order_by(EtlRun.started_at.desc()).limit(20)).all()
        return [_serialize_run(r) for r in runs]
    finally:
        db.close()


@router.get("/runs/{run_id}", dependencies=[Depends(require_permissions("sync_runs.view"))], tags=["ETL"])
def get_etl_run(run_id: uuid.UUID) -> dict:
    """Detalle de un run específico."""
    db = _get_db()
    try:
        run = db.get(EtlRun, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="ETL run no encontrado")
        return _serialize_run(run)
    finally:
        db.close()


@router.post("/full-sync", dependencies=[Depends(require_permissions("etl.run")), Depends(require_csrf)], tags=["ETL"])
def trigger_full_sync(body: FullSyncRequest, background_tasks: BackgroundTasks) -> dict:
    """Sync desde APIs de proveedores → source_records → materialización (Pipeline B)."""
    unknown = set(body.providers) - set(_ALL_PROVIDERS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Proveedores desconocidos: {sorted(unknown)}")
    db = _get_db()
    try:
        run = EtlRun(status="running", records_upserted=0, phase=f"sync_{body.providers[0]}")
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()

    background_tasks.add_task(_run_full_sync_background, run_id, body.providers)
    return {"run_id": str(run_id), "status": "running", "providers": body.providers}
