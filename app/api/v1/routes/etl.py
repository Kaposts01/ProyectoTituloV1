import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_csrf, require_permissions
from app.db.session import SessionLocal
from app.models.core import ClientMatchCandidate
from app.models.etl_run import EtlRun
from app.scheduler.run_lock import (
    ActiveRunError,
    start_exclusive_run,
    start_exclusive_runs,
)
from app.services import core_etl_mark
from app.services.channel_consolidation import consolidate_to_centralized
from app.services.client_match_detector import detect_matches
from app.services.core_payku_etl import run_payku_core_etl
from app.services.core_tch_etl import run_tch_core_etl
from app.services.core_toku_etl import run_toku_core_etl
from app.services.core_vp_etl import run_vp_core_etl
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
    # REV-01 (origin/sprint-5/estabilizacion-dashboard 1005a26): una lista vacia no lanza una corrida sin canales.
    providers: Annotated[list[str], Field(default_factory=lambda: list(_ALL_PROVIDERS), min_length=1)]


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


def _active_run_conflict(busy: ActiveRunError) -> HTTPException:
    return HTTPException(status_code=409, detail=str(busy))


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


def full_sync_status(done: list[str], failed: list[str], consolidation_failures: list[str]) -> str:
    """Estado final de un full-sync: `completed` solo sin fallos; `partial` con algun canal ok; `failed` si ninguno."""
    if not failed and not consolidation_failures:
        return "completed"
    return "partial" if done else "failed"


async def _run_full_sync_background(run_id: uuid.UUID, providers: list[str]) -> None:
    """BackgroundTask: sync APIs → source_records → materialización (Pipeline B)."""
    total = 0
    done: list[str] = []
    failed: list[str] = []
    try:
        for provider in providers:
            if provider not in _SYNC_FN:
                logger.warning("Proveedor desconocido: %s. Omitido.", provider)
                continue
            if not settings.channel_enabled(provider):
                logger.warning("Canal %s omitido: deshabilitado en %s.", provider, settings.env_mode)
                continue
            _update_run(run_id, phase=f"sync_{provider}")
            logger.info("Iniciando sync Pipeline B: %s", provider)
            try:
                db = SessionLocal()
                try:
                    sync_run = await _SYNC_FN[provider](db)
                    total += sync_run.records_processed or 0
                    done.append(provider)
                    logger.info("Sync completado %s: %d registros", provider, sync_run.records_processed)
                finally:
                    db.close()
            except Exception:
                failed.append(provider)
                logger.exception("Error en sync de %s", provider)

        # Consolidación desde tablas canal → tablas centralizadas
        _update_run(run_id, phase="consolidating")
        consolidation_failures: list[str] = []
        db = SessionLocal()
        try:
            consolidated = consolidate_to_centralized(db, providers, failures=consolidation_failures)
            total += consolidated
            if consolidation_failures:
                logger.error("Consolidacion con errores: %s", consolidation_failures)
            logger.info("Consolidación completada: %d registros", consolidated)
        finally:
            db.close()

        # d139b (audit_sync §0.6): nunca `completed` si fallo la sync de un canal o la consolidacion; `partial` si algun
        # canal sincronizo, `failed` si ninguno. Misma regla que el job nocturno (`sync_all_channels`).
        error_parts = []
        if failed:
            error_parts.append(f"Canales con error: {', '.join(failed)}")
        if consolidation_failures:
            error_parts.append(f"Consolidacion con error: {', '.join(consolidation_failures)}")
        _update_run(
            run_id,
            status=full_sync_status(done, failed, consolidation_failures),
            phase=None,
            channels_processed=done,
            channels_failed=failed or None,
            records_upserted=total,
            finished_at=datetime.now(timezone.utc),
            error_message="; ".join(error_parts) or None,
        )
    except Exception:
        logger.exception("Error en full-sync (run_id=%s)", run_id)
        _update_run(
            run_id,
            status="failed",
            phase=None,
            # REV-01 (1005a26): conserva lo que alcanzo a sincronizar antes del error.
            channels_processed=done,
            channels_failed=failed or None,
            records_upserted=total,
            error_message="Error durante la sincronización.",
            finished_at=datetime.now(timezone.utc),
        )


@router.post("/run", dependencies=[Depends(require_permissions("etl.run")), Depends(require_csrf)], tags=["ETL"])
def trigger_etl() -> dict:
    """DEPRECADO: la materializacion legacy esta desactivada; usar /full-sync o /core/{provider}."""
    raise HTTPException(
        status_code=410,
        detail="Endpoint deprecado: la materializacion legacy (crm_materialization) fue desactivada. "
        "Use /etl/full-sync, que consolida desde las tablas canal.",
    )


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
    providers = list(dict.fromkeys(body.providers))
    skipped = [p for p in providers if not settings.channel_enabled(p)]
    providers = [p for p in providers if p not in skipped]
    if not providers:
        raise HTTPException(
            status_code=409,
            detail=f"Canal(es) deshabilitado(s) en {settings.env_mode}: {', '.join(skipped) or 'ninguno solicitado'}.",
        )
    db = _get_db()
    try:
        run = start_exclusive_run(db, phase=f"sync_{providers[0]}")
        run_id = run.id
    except ActiveRunError as busy:
        raise _active_run_conflict(busy) from busy
    finally:
        db.close()

    background_tasks.add_task(_run_full_sync_background, run_id, providers)
    return {"run_id": str(run_id), "status": "running", "providers": providers, "skipped_providers": skipped}


# ── Core ETL endpoints ────────────────────────────────────────────────────────

_CORE_ETL_FN = {
    "tch": run_tch_core_etl,
    "toku": run_toku_core_etl,
    "payku": run_payku_core_etl,
    "virtualpos": run_vp_core_etl,
}


def _run_core_etl_background(run_id: uuid.UUID, provider: str) -> None:
    """BackgroundTask: materializa tablas de proveedor → entidades Core (Layer 3)."""
    fn = _CORE_ETL_FN[provider]
    _update_run(run_id, phase=f"core_{provider}")
    db = SessionLocal()
    try:
        result = fn(db)
        db.commit()
        if provider != "tch":  # marca de frescura del ETL Core (la lee /sync-runs/health)
            core_etl_mark.record(db, provider, result)
            db.commit()
        total = sum(result.values())
        _update_run(
            run_id,
            status="completed",
            phase=None,
            channels_processed=[provider],
            records_upserted=total,
            finished_at=datetime.now(timezone.utc),
        )
        logger.info("Core ETL %s completado: %s", provider, result)
    except Exception:
        logger.exception("Error en Core ETL %s (run_id=%s)", provider, run_id)
        db.rollback()
        _update_run(
            run_id,
            status="failed",
            phase=None,
            error_message=f"Error durante Core ETL {provider}.",
            finished_at=datetime.now(timezone.utc),
        )
    finally:
        db.close()


@router.post(
    "/core/all",
    dependencies=[Depends(require_permissions("etl.run")), Depends(require_csrf)],
    tags=["ETL Core"],
)
def trigger_core_etl_all(background_tasks: BackgroundTasks) -> dict:
    """Ejecuta el Core ETL para todos los proveedores en secuencia.

    Orden: tch → toku → payku → virtualpos. Idempotente.
    """
    db = _get_db()
    try:  # las cuatro filas se reservan juntas, bajo el mismo lock
        runs = start_exclusive_runs(db, [{"phase": f"core_{provider}"} for provider in _CORE_ETL_FN])
        run_ids = [str(run.id) for run in runs]
    except ActiveRunError as busy:
        raise _active_run_conflict(busy) from busy
    finally:
        db.close()
    for run_id, provider in zip(run_ids, _CORE_ETL_FN, strict=True):
        background_tasks.add_task(_run_core_etl_background, uuid.UUID(run_id), provider)

    return {"run_ids": run_ids, "status": "running", "providers": list(_CORE_ETL_FN)}


@router.post(
    "/core/detect-matches",
    dependencies=[Depends(require_permissions("etl.run")), Depends(require_csrf)],
    tags=["ETL Core"],
)
def trigger_detect_matches() -> dict:
    """Detecta pares de CoreClient de fuentes distintas que comparten RUT o email.

    Genera candidatos en client_match_candidates para revisión manual.
    No realiza merges automáticos (ADR-001). Idempotente: re-ejecutar es seguro.
    """
    db = _get_db()
    try:
        counts = detect_matches(db)
    finally:
        db.close()
    return {"status": "ok", "counts": counts}


@router.post(
    "/core/{provider}",
    dependencies=[Depends(require_permissions("etl.run")), Depends(require_csrf)],
    tags=["ETL Core"],
)
def trigger_core_etl(provider: str, background_tasks: BackgroundTasks) -> dict:
    """Materializa tablas de proveedor (tch/toku/payku/virtualpos) → entidades Core (Layer 3).

    Idempotente: seguro re-ejecutar. Retorna inmediatamente; la ejecución ocurre en background.
    """
    if provider not in _CORE_ETL_FN:
        raise HTTPException(
            status_code=422,
            detail=f"Proveedor desconocido: '{provider}'. Opciones: {sorted(_CORE_ETL_FN)}",
        )
    db = _get_db()
    try:
        run = start_exclusive_run(db, phase=f"core_{provider}")
        run_id = run.id
    except ActiveRunError as busy:
        raise _active_run_conflict(busy) from busy
    finally:
        db.close()

    background_tasks.add_task(_run_core_etl_background, run_id, provider)
    return {"run_id": str(run_id), "status": "running", "provider": provider}


@router.get(
    "/core/match-candidates",
    dependencies=[Depends(require_permissions("etl.run"))],
    tags=["ETL Core"],
)
def list_match_candidates(status: str = "pending", limit: int = 100) -> list[dict]:
    """Lista candidatos de match pendientes de revisión manual."""
    db = _get_db()
    try:
        rows = (
            db.query(ClientMatchCandidate)
            .filter(ClientMatchCandidate.status == status)
            .order_by(ClientMatchCandidate.match_level, ClientMatchCandidate.created_at.desc())
            .limit(min(limit, 500))
            .all()
        )
        return [
            {
                "id": str(r.id),
                "client_id_a": str(r.client_id_a),
                "client_id_b": str(r.client_id_b),
                "match_level": r.match_level,
                "match_signals": r.match_signals,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    finally:
        db.close()
