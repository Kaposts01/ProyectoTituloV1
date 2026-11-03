"""EXP-03: exportacion CSV de Clientes, Suscripciones, Cobros y Pagos (streaming, filtros del listado, auditoria).

EXP-06 (d114 b): si la exportacion completa supera `EXPORT_BACKGROUND_THRESHOLD_ROWS`, `/count` lo indica
(`background`) y el front usa los jobs en segundo plano (`POST /{entidad}/jobs`, `GET /jobs/{id}`, `GET
/jobs/{id}/download`; ver `app/services/export_jobs.py`). Las rutas `/jobs...` se declaran antes de `/{entity}`.
"""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db
from app.core.config import settings
from app.core.security import get_current_user, require_csrf
from app.db import session as db_session
from app.models.auth import User
from app.services import export_jobs
from app.services.charge_stats import chile_today
from app.services.export_queries import (
    ENTITY_COLUMNS,
    FILTER_FIELDS,
    ExportFilters,
    iter_rows,
    select_specs,
    total_rows,
)
from app.services.exporter import CSV_MEDIA_TYPE, csv_stream, record_export_audit
from app.services.rbac import permission_codes

router = APIRouter()

Entity = Literal["clientes", "suscripciones", "cobros", "pagos"]
Channel = Literal["virtualpos", "virtualpos1", "virtualpos2", "toku", "payku", "tch"]
Outcome = Literal["paid", "rejected", "pending", "excluded", "other"]  # UX-09: resultado normalizado (charge_stats)
PII_PERMISSION = "export.pii"


def _parse_date(value: str | None, name: str) -> date | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{name} must use YYYY-MM-DD") from exc


def _resolve(
    entity: str, channel: str | None, user: User, query: str | None, filter_field: str, status: str | None,
    date_from: str | None, date_to: str | None, amount_min: float | None, amount_max: float | None,
    outcome: str | None = None,
) -> tuple[list, ExportFilters, bool, list[str]]:
    if filter_field not in FILTER_FIELDS[entity]:
        raise HTTPException(status_code=422, detail="Invalid filter field")
    if entity == "clientes" and (amount_min is not None or amount_max is not None):
        raise HTTPException(status_code=422, detail="Amount range is unsupported for this resource")
    if outcome is not None and entity not in ("cobros", "pagos"):
        raise HTTPException(status_code=422, detail="Outcome filter is unsupported for this resource")
    filters = ExportFilters(
        query=query, filter_field=filter_field, status=status, date_from=_parse_date(date_from, "date_from"),
        date_to=_parse_date(date_to, "date_to"), amount_min=amount_min, amount_max=amount_max, outcome=outcome,
    )
    codes = permission_codes(user)
    items, denied = select_specs(entity, channel, codes)
    if denied or not items:
        raise HTTPException(status_code=403, detail="Permission denied")
    channels = [src for _spec, sources in items for src in sources]
    return items, filters, PII_PERMISSION in codes, channels


def _filename(entity: str, channel: str | None) -> str:
    return f"{entity}{'-' + channel if channel else ''}-{chile_today():%Y%m%d}.csv"


# ----------------------------------------------------------------------------- EXP-06: jobs en segundo plano


def _job_or_404(db: Session, job_id: uuid.UUID, user: User):
    export_jobs.purge_expired(db)
    job = export_jobs.user_job(db, job_id, user.id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "export_job_not_found", "message": "La exportación no existe."})
    return job


@router.get("/jobs", tags=["Export"])
def list_export_jobs(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """Exportaciones en segundo plano del usuario (las 20 mas recientes). Solo metadatos."""
    export_jobs.purge_expired(db)
    return {"items": [export_jobs.serialize(job) for job in export_jobs.list_user_jobs(db, user.id)]}


@router.get("/jobs/{job_id}", tags=["Export"])
def get_export_job(
    job_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    return export_jobs.serialize(_job_or_404(db, job_id, user))


@router.get("/jobs/{job_id}/download", tags=["Export"])
def download_export_job(
    job_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FileResponse:
    job = _job_or_404(db, job_id, user)
    if job.status == "expired":
        raise HTTPException(status_code=410, detail={"code": "export_job_expired", "message": "La exportación caducó. Vuelve a generarla."})
    if job.status != "completed" or not job.file_path or not Path(job.file_path).is_file():
        raise HTTPException(status_code=409, detail={"code": "export_job_not_ready", "message": "La exportación aún no está lista."})
    export_jobs.record_download(job)
    return FileResponse(
        job.file_path, media_type=CSV_MEDIA_TYPE, filename=job.file_name or f"{job.entity}.csv",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/{entity}/jobs", status_code=202, dependencies=[Depends(require_csrf)], tags=["Export"])
def create_export_job(
    entity: Entity,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    channel: Annotated[Channel | None, Query(alias="canal")] = None,
    query: str | None = Query(None, max_length=200),
    filter_field: str = "all",
    status: str | None = Query(None, max_length=50),
    date_from: str | None = None,
    date_to: str | None = None,
    amount_min: float | None = Query(None, ge=0),
    amount_max: float | None = Query(None, ge=0),
    outcome: Outcome | None = None,
) -> dict[str, Any]:
    """Encola la exportacion COMPLETA (con los filtros activos) en segundo plano. Mismos permisos que `/{entity}`."""
    items, filters, include_pii, channels = _resolve(
        entity, channel, user, query, filter_field, status, date_from, date_to, amount_min, amount_max, outcome)
    export_jobs.purge_expired(db)
    if export_jobs.active_jobs(db, user.id) >= max(1, settings.export_job_max_active_per_user):
        raise HTTPException(status_code=429, detail={
            "code": "too_many_export_jobs", "message": "Ya tienes exportaciones en curso. Espera a que terminen.",
        })
    job = export_jobs.create_job(
        db, user=user, entity=entity, channel=channel, include_pii=include_pii,
        rows_estimated=total_rows(db, items, filters),
        audit_filters={"canales": channels, "all": True, **filters.audit()}, file_name=_filename(entity, channel),
    )
    export_jobs.enqueue(job.id, items, filters, include_pii)
    db.refresh(job)
    return export_jobs.serialize(job)


# ----------------------------------------------------------------------------- EXP-03


@router.get("/{entity}/count", tags=["Export"])
def export_count(
    entity: Entity,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    channel: Annotated[Channel | None, Query(alias="canal")] = None,  # el parametro de URL sigue llamandose `canal`
    query: str | None = Query(None, max_length=200),
    filter_field: str = "all",
    status: str | None = Query(None, max_length=50),
    date_from: str | None = None,
    date_to: str | None = None,
    amount_min: float | None = Query(None, ge=0),
    amount_max: float | None = Query(None, ge=0),
    outcome: Outcome | None = None,
) -> dict[str, Any]:
    items, filters, include_pii, channels = _resolve(
        entity, channel, user, query, filter_field, status, date_from, date_to, amount_min, amount_max, outcome)
    rows = total_rows(db, items, filters)
    return {
        "entity": entity, "rows": rows, "canales": channels, "include_pii": include_pii,
        # EXP-06: la exportacion completa con mas filas que el umbral va en segundo plano.
        "background": export_jobs.needs_background(rows), "background_threshold": export_jobs.threshold_rows(),
    }


@router.get("/{entity}", tags=["Export"])
def export_entity(
    entity: Entity,
    user: Annotated[User, Depends(get_current_user)],
    channel: Annotated[Channel | None, Query(alias="canal")] = None,  # el parametro de URL sigue llamandose `canal`
    query: str | None = Query(None, max_length=200),
    filter_field: str = "all",
    status: str | None = Query(None, max_length=50),
    date_from: str | None = None,
    date_to: str | None = None,
    amount_min: float | None = Query(None, ge=0),
    amount_max: float | None = Query(None, ge=0),
    outcome: Outcome | None = None,
    export_all: bool = Query(False, alias="all"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
) -> StreamingResponse:
    items, filters, include_pii, channels = _resolve(
        entity, channel, user, query, filter_field, status, date_from, date_to, amount_min, amount_max, outcome)
    # El usuario se captura ya: la respuesta se genera despues de cerrar la sesion de la peticion.
    actor = SimpleNamespace(id=user.id, username=user.username)
    endpoint = f"export/{entity}"
    audit_filters: dict[str, Any] = {"canales": channels, "all": export_all, **filters.audit()}
    if not export_all:
        audit_filters.update({"offset": offset, "limit": limit})

    def audit(rows: int, completed: bool) -> None:
        session = db_session.SessionLocal()
        try:
            record_export_audit(
                session, actor, endpoint, audit_filters, rows, include_pii,
                source="export", resource_type=entity, status="completed" if completed else "aborted",
            )
        finally:
            session.close()

    rows = iter_rows(db_session.SessionLocal, items, filters, include_pii, paged=None if export_all else (offset, limit))
    body = csv_stream(ENTITY_COLUMNS[entity], include_pii, rows, on_finish=audit)
    headers = {"Content-Disposition": f'attachment; filename="{_filename(entity, channel)}"', "Cache-Control": "no-store"}
    return StreamingResponse(body, media_type=CSV_MEDIA_TYPE, headers=headers)
