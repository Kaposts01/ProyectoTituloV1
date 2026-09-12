import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.etl_run import EtlRun
from app.services.etl_consolidation import run_etl_background
from app.services.etl_orchestration import run_full_sync_background

router = APIRouter()


def _get_db() -> Session:
    return SessionLocal()


_ALL_PROVIDERS = ["virtualpos", "toku", "payku"]


class FullSyncRequest(BaseModel):
    providers: Annotated[list[str], Field(default_factory=lambda: list(_ALL_PROVIDERS))]


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


@router.post("/run", tags=["ETL"])
def trigger_etl(background_tasks: BackgroundTasks) -> dict:
    """Lanza el ETL de BDlocales como tarea de fondo y retorna el run_id."""
    db = _get_db()
    try:
        run = EtlRun(status="running", records_upserted=0)
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()

    background_tasks.add_task(run_etl_background, run_id)
    return {"run_id": str(run_id), "status": "running"}


@router.get("/runs", tags=["ETL"])
def list_etl_runs() -> list[dict]:
    """Lista los últimos 20 runs del ETL."""
    db = _get_db()
    try:
        runs = db.scalars(select(EtlRun).order_by(EtlRun.started_at.desc()).limit(20)).all()
        return [_serialize_run(r) for r in runs]
    finally:
        db.close()


@router.get("/runs/{run_id}", tags=["ETL"])
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


@router.post("/full-sync", tags=["ETL"])
def trigger_full_sync(body: FullSyncRequest, background_tasks: BackgroundTasks) -> dict:
    """Sync desde APIs de proveedores → BDlocales → ETL consolidación."""
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

    background_tasks.add_task(run_full_sync_background, run_id, body.providers)
    return {"run_id": str(run_id), "status": "running", "providers": body.providers}
