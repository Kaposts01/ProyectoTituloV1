"""EXP-06 (d114 opcion b): exportacion CSV en segundo plano para listados grandes.

Flujo: `/export/{entidad}/count` informa `background=true` si las filas superan `EXPORT_BACKGROUND_THRESHOLD_ROWS`; el
front pide entonces `POST /export/{entidad}/jobs` (mismos filtros), consulta `GET /export/jobs/{id}` hasta `completed`
y descarga con `GET /export/jobs/{id}/download`. El archivo caduca a las `EXPORT_JOB_TTL_HOURS` horas.

Reglas
------
* Reutiliza EXACTAMENTE las consultas de la exportacion directa (`export_queries.iter_rows`, mismas columnas, filtros,
  orden y permisos de vista por canal) y el mismo CSV (`exporter.csv_stream`: BOM, anti-inyeccion de formulas, columnas
  personales solo con `export.pii`).
* Datos personales: la tabla `export_jobs` guarda solo los filtros AUDITABLES (`ExportFilters.audit()`); los filtros
  completos (que pueden traer un RUT buscado) solo viven en memoria del proceso. Los logs llevan id del job, entidad y
  contadores; nunca filtros ni filas. El archivo puede llevar PII (si el usuario tiene `export.pii`): solo lo descarga
  quien lo pidio y se borra al caducar.
* Auditoria en `write_runs` al terminar (o fallar) la generacion y en cada descarga, igual que la exportacion directa.
* Ejecucion en un pool de hilos del proceso (`_EXECUTOR`). Si el proceso se reinicia, el job no se reanuda: pasadas 2
  horas sin terminar queda `failed` (`stale:not_finished`) y libera el cupo del usuario.
* Caducidad: `purge_expired` (se llama al crear, listar, consultar y descargar) borra el archivo y deja `expired`.
"""

from __future__ import annotations

import logging
import os
import tempfile
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import session as db_session
from app.models.auth import User
from app.models.export_job import ExportJob
from app.services.export_queries import ENTITY_COLUMNS, ExportFilters, iter_rows
from app.services.exporter import csv_stream, record_export_audit

logger = logging.getLogger(__name__)

ACTIVE_STATES = ("queued", "running")
STALE_AFTER = timedelta(hours=2)
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="export-job")


def threshold_rows() -> int:
    return max(0, int(settings.export_background_threshold_rows))


def needs_background(rows: int) -> bool:
    """True si la exportacion COMPLETA supera el umbral y debe ir en segundo plano."""
    return rows > threshold_rows()


def job_dir() -> Path:
    base = Path(settings.export_job_dir) if settings.export_job_dir else Path(tempfile.gettempdir()) / "crm_export_jobs"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _now() -> datetime:
    return datetime.now(UTC)


def _remove(path: str | None) -> None:
    if not path:
        return
    for candidate in (path, f"{path}.part"):
        try:
            os.remove(candidate)
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("No se pudo borrar un archivo de exportacion caducado")


def purge_expired(db: Session, now: datetime | None = None) -> int:
    """Caduca los jobs vencidos: borra su archivo y los deja `expired`. Devuelve cuantos caduco."""
    now = now or _now()
    # Un job vivo con mas de STALE_AFTER no avanza (p. ej. reinicio del proceso): se marca fallido para liberar el cupo.
    stale = db.scalars(
        select(ExportJob).where(ExportJob.status.in_(ACTIVE_STATES), ExportJob.created_at <= now - STALE_AFTER)
    ).all()
    for job in stale:
        _remove(job.file_path)
        job.status, job.error_label, job.finished_at, job.file_path = "failed", "stale:not_finished", now, None
    if stale:
        db.commit()
    jobs = db.scalars(
        select(ExportJob).where(ExportJob.status != "expired", ExportJob.expires_at <= now)
    ).all()
    for job in jobs:
        _remove(job.file_path)
        job.status = "expired"
        job.file_path = None
    if jobs:
        db.commit()
        logger.info("Exportaciones en segundo plano caducadas: %d", len(jobs))
    return len(jobs)


def active_jobs(db: Session, user_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count()).select_from(ExportJob).where(
            ExportJob.requested_by_user_id == user_id, ExportJob.status.in_(ACTIVE_STATES)
        )
    ) or 0


def create_job(
    db: Session, *, user: Any, entity: str, channel: str | None, include_pii: bool, rows_estimated: int,
    audit_filters: dict[str, Any], file_name: str,
) -> ExportJob:
    now = _now()
    job = ExportJob(
        requested_by_user_id=user.id, entity=entity, channel=channel, status="queued", include_pii=include_pii,
        filters=audit_filters, rows_estimated=rows_estimated, file_name=file_name, created_at=now,
        expires_at=now + timedelta(hours=max(1, int(settings.export_job_ttl_hours))),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _submit(fn: Callable[..., None], *args: Any) -> None:
    """Punto de ejecucion (las pruebas lo reemplazan por una llamada directa)."""
    _EXECUTOR.submit(fn, *args)


def enqueue(job_id: uuid.UUID, items: list, filters: ExportFilters, include_pii: bool) -> None:
    _submit(run_job, job_id, items, filters, include_pii)


def run_job(job_id: uuid.UUID, items: list, filters: ExportFilters, include_pii: bool) -> None:
    """Genera el CSV del job en disco. Nunca lanza: un fallo deja `failed` con una etiqueta tecnica sin PII."""
    session = db_session.SessionLocal()
    path: Path | None = None
    try:
        job = session.get(ExportJob, job_id)
        if job is None or job.status != "queued":
            return
        job.status = "running"
        job.started_at = _now()
        session.commit()
        entity, actor_id = job.entity, job.requested_by_user_id
        audit_filters = dict(job.filters or {})
        path = job_dir() / f"{job_id}.csv"
        part = Path(f"{path}.part")
        written: dict[str, Any] = {"rows": 0, "completed": False}

        def on_finish(rows: int, completed: bool) -> None:
            written.update(rows=rows, completed=completed)

        rows = iter_rows(db_session.SessionLocal, items, filters, include_pii)
        with open(part, "wb") as fh:
            for chunk in csv_stream(ENTITY_COLUMNS[entity], include_pii, rows, on_finish=on_finish):
                fh.write(chunk)
        os.replace(part, path)
        session.execute(
            update(ExportJob).where(ExportJob.id == job_id).values(
                status="completed", rows_written=written["rows"], file_path=str(path),
                file_bytes=path.stat().st_size, finished_at=_now(), error_label=None,
            )
        )
        session.commit()
        logger.info("Exportacion en segundo plano %s completada: %d filas", job_id, written["rows"])
        _audit(actor_id, entity, {**audit_filters, "job_id": str(job_id), "background": True}, written["rows"],
               include_pii, "completed")
    except Exception as exc:  # noqa: BLE001 - se etiqueta sin PII y el job queda failed
        session.rollback()
        label = f"run:{type(exc).__name__}"[:100]
        logger.warning("Exportacion en segundo plano %s fallida (%s)", job_id, label)
        if path is not None:
            _remove(str(path))
        try:
            job = session.get(ExportJob, job_id)
            if job is not None:
                job.status, job.error_label, job.finished_at, job.file_path = "failed", label, _now(), None
                session.commit()
                _audit(job.requested_by_user_id, job.entity, {**(job.filters or {}), "job_id": str(job_id),
                       "background": True}, 0, job.include_pii, "failed")
        except Exception:  # noqa: BLE001
            session.rollback()
            logger.warning("No se pudo marcar como fallida la exportacion %s", job_id)
    finally:
        session.close()


def _audit(user_id: uuid.UUID | None, entity: str, filters: dict[str, Any], rows: int, include_pii: bool,
           status: str, endpoint_suffix: str = "jobs") -> None:
    if user_id is None:
        return
    session = db_session.SessionLocal()
    try:
        user = session.get(User, user_id)
        actor = SimpleNamespace(id=user_id, username=user.username if user else None)
        record_export_audit(
            session, actor, f"export/{entity}/{endpoint_suffix}", filters, rows, include_pii,
            source="export", resource_type=entity, status=status,
        )
    finally:
        session.close()


def record_download(job: ExportJob) -> None:
    _audit(job.requested_by_user_id, job.entity, {**(job.filters or {}), "job_id": str(job.id), "background": True},
           job.rows_written or 0, job.include_pii, "completed", endpoint_suffix="jobs/download")


def user_job(db: Session, job_id: uuid.UUID, user_id: uuid.UUID) -> ExportJob | None:
    """El job si pertenece al usuario (un job ajeno se trata como inexistente)."""
    job = db.get(ExportJob, job_id)
    if job is None or job.requested_by_user_id != user_id:
        return None
    return job


def list_user_jobs(db: Session, user_id: uuid.UUID, limit: int = 20) -> list[ExportJob]:
    return list(db.scalars(
        select(ExportJob).where(ExportJob.requested_by_user_id == user_id)
        .order_by(ExportJob.created_at.desc()).limit(limit)
    ))


def serialize(job: ExportJob) -> dict[str, Any]:
    def iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    return {
        "id": str(job.id),
        "entity": job.entity,
        "canal": job.channel,
        "status": job.status,
        "include_pii": job.include_pii,
        "rows_estimated": job.rows_estimated,
        "rows_written": job.rows_written,
        "file_name": job.file_name,
        "file_bytes": job.file_bytes,
        "error_label": job.error_label,
        "created_at": iso(job.created_at),
        "started_at": iso(job.started_at),
        "finished_at": iso(job.finished_at),
        "expires_at": iso(job.expires_at),
        "download_url": f"/api/v1/export/jobs/{job.id}/download" if job.status == "completed" else None,
    }
