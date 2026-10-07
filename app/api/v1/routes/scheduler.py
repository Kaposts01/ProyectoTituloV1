"""Endpoints del orquestador: lista de jobs, trigger manual, historial de runs y SSE."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.security import get_current_user, get_db, require_permissions
from app.models.etl_run import EtlRun
from app.scheduler import event_bus
from app.scheduler.engine import JOB_SYNC_ALL, get_scheduler
from app.scheduler.jobs.sync_all import sync_all_channels

_VALID_CHANNELS = frozenset({"virtualpos1", "virtualpos2", "toku", "payku", "tch"})


class TriggerBody(BaseModel):
    channels: list[str] | None = None

logger = logging.getLogger(__name__)
router = APIRouter()


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


@router.get("/jobs", tags=["Scheduler"])
def list_jobs(
    _user=Depends(require_permissions("sync_runs.view")),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Lista los jobs programados con su estado y último run."""
    sched = get_scheduler()
    result = []
    for job in sched.get_jobs():
        # Último EtlRun completado o fallido para este job
        last_run = db.scalar(
            select(EtlRun)
            .where(EtlRun.status.in_(["completed", "failed"]))
            .order_by(desc(EtlRun.started_at))
            .limit(1)
        )
        # Run activo (running)
        active_run = db.scalar(
            select(EtlRun)
            .where(EtlRun.status == "running")
            .order_by(desc(EtlRun.started_at))
            .limit(1)
        )
        job_status = "running" if active_run else "scheduled"
        next_run = job.next_run_time
        result.append({
            "id": job.id,
            "name": job.name,
            "cron": "0 2 * * *",
            "next_run": next_run.isoformat() if next_run else None,
            "last_run": _serialize_run(last_run) if last_run else None,
            "status": job_status,
            "active_run_id": str(active_run.id) if active_run else None,
        })
    return result


@router.post("/jobs/{job_id}/run", tags=["Scheduler"], status_code=status.HTTP_202_ACCEPTED)
async def trigger_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    body: TriggerBody = Body(default_factory=TriggerBody),
    _user=Depends(require_permissions("sync.run")),
    db: Session = Depends(get_db),
) -> dict:
    """Ejecuta un job inmediatamente y retorna el run_id para seguir el progreso."""
    sched = get_scheduler()
    if not sched.get_job(job_id):
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' no encontrado.")

    # Validar canales si se pasan
    if body.channels is not None:
        invalid = set(body.channels) - _VALID_CHANNELS
        if invalid:
            raise HTTPException(status_code=422, detail=f"Canales inválidos: {sorted(invalid)}")
        if not body.channels:
            raise HTTPException(status_code=422, detail="La lista de canales no puede estar vacía.")

    # Bloquear si hay una sync activa
    active = db.scalar(
        select(EtlRun).where(EtlRun.status == "running").limit(1)
    )
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"Ya hay una sincronización activa (run_id={active.id}). Espera a que termine.",
        )

    run_id = str(uuid.uuid4())
    if job_id == JOB_SYNC_ALL:
        background_tasks.add_task(sync_all_channels, run_id, body.channels)
    else:
        raise HTTPException(status_code=400, detail="Job no soporta ejecución manual.")

    return {"run_id": run_id, "status": "accepted"}


@router.get("/runs", tags=["Scheduler"])
def list_runs(
    offset: int = 0,
    limit: int = 20,
    _user=Depends(require_permissions("sync_runs.view")),
    db: Session = Depends(get_db),
) -> dict:
    """Últimas ejecuciones del orquestador e importaciones TCH."""
    from sqlalchemy import func as sqlfunc

    base = select(EtlRun)

    runs = db.scalars(
        base.order_by(desc(EtlRun.started_at)).offset(offset).limit(limit)
    ).all()
    count_q = db.scalar(select(sqlfunc.count()).select_from(EtlRun))
    return {
        "total": count_q or 0,
        "offset": offset,
        "limit": limit,
        "items": [_serialize_run(r) for r in runs],
    }


@router.get("/runs/{run_id}/stream", tags=["Scheduler"])
async def stream_run(
    run_id: str,
    _user=Depends(get_current_user),
) -> StreamingResponse:
    """SSE: emite eventos de progreso de un run en tiempo real."""
    # Validar formato UUID
    try:
        uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="run_id inválido.") from None

    # Padding de 4 KB para forzar flush del buffer de Cloudflare/proxies
    _PAD = ": " + ("p" * 4096) + "\n"

    async def event_generator():
        # Flush inicial: fuerza al proxy a abrir el stream antes del primer evento
        yield _PAD
        q = await event_bus.subscribe(run_id)
        if q is None:
            yield "data: {\"type\": \"not_found\"}\n\n" + _PAD
            return
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=25.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n" + _PAD
                    continue
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n" + _PAD
        finally:
            event_bus.unsubscribe(run_id, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
        },
    )
