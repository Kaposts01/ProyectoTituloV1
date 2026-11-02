import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import require_permissions
from app.db.session import SessionLocal
from app.models.core import CoreCharge
from app.models.etl_run import EtlRun
from app.models.sync_run import SyncRun
from app.services import core_etl_mark, sync_cursors, tch_report_registry

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("", dependencies=[Depends(require_permissions("sync_runs.view"))])
def list_sync_runs(
    etl_run_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),  # noqa: B008
) -> list[dict[str, object]]:
    """Corridas de canales (las de facturacion/bajas se ven en /scheduler/jobs).

    SYNC-D-17: `etl_run_id` filtra las corridas de canal de una corrida global; cada fila trae `resource_stats`
    (por recurso: modo, duracion, nuevas/actualizadas/sin cambio) y `duration_seconds`.
    """
    query = select(SyncRun).where(SyncRun.is_channel_source())
    if etl_run_id is not None:
        query = query.where(SyncRun.etl_run_id == etl_run_id)
    runs = db.scalars(query.order_by(SyncRun.started_at.desc()).limit(50)).all()
    return [
        {
            "id": str(run.id),
            "source": run.source,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "duration_seconds": _duration_seconds(run.started_at, run.finished_at),
            "records_processed": run.records_processed,
            "error_message": run.error_message,
            "etl_run_id": str(run.etl_run_id) if run.etl_run_id else None,
            "resource_stats": run.resource_stats,
        }
        for run in runs
    ]


def _duration_seconds(started_at: datetime | None, finished_at: datetime | None) -> float | None:
    if started_at is None or finished_at is None:
        return None
    return round((finished_at - started_at).total_seconds(), 1)


_WARN_AFTER = timedelta(hours=24)
_ERROR_AFTER = timedelta(hours=72)
_CACHE_TTL_SECONDS = 300
# Severidad para elegir el "peor nivel": error > warn > unknown > ok.
_SEVERITY = {"ok": 0, "unknown": 1, "warn": 2, "error": 3}
_CHANNEL_SOURCES: dict[str, tuple[str, ...]] = {
    "virtualpos": ("virtualpos1", "virtualpos2"),
    "toku": ("toku",),
    "payku": ("payku",),
    "tch": (),  # TCH no usa SyncRun: se lee de EtlRun
}
_health_cache: dict[str, object] = {"at": 0.0, "value": None}


def clear_sync_health_cache() -> None:
    _health_cache["at"] = 0.0
    _health_cache["value"] = None


def _classify(
    last_status: str | None, last_finished_at: datetime | None, has_hung_run: bool, now: datetime
) -> tuple[str, datetime | None, float | None]:
    """Nivel de salud de una fuente a partir de su ultimo run terminado y runs colgados."""
    if last_finished_at is not None and last_finished_at.tzinfo is None:
        last_finished_at = last_finished_at.replace(tzinfo=timezone.utc)
    age = (now - last_finished_at) if last_finished_at else None
    age_hours = round(age.total_seconds() / 3600, 1) if age is not None else None
    if last_status is None and not has_hung_run:
        return "unknown", None, None
    if has_hung_run or last_status == "failed":
        return "error", last_finished_at, age_hours
    if age is None:
        return "unknown", None, None
    if age < _WARN_AFTER:
        return "ok", last_finished_at, age_hours
    if age < _ERROR_AFTER:
        return "warn", last_finished_at, age_hours
    return "error", last_finished_at, age_hours


# Estado de fallos sostenidos (channel_failing_days): se suma a `level` sin cambiar su contrato.
_STATUS_SEVERITY = {"ok": 0, "unknown": 1, "degraded": 2, "failing": 3}
_STATUS_MIN_LEVEL = {"degraded": "warn", "failing": "error"}
_RECENT_RUNS = 30


def _failure_status(
    recent: list[tuple[str, datetime | None]], now: datetime
) -> tuple[str, int, int | None]:
    """(status, corridas fallidas seguidas, dias sin exito) a partir de las corridas recientes (nuevas primero).

    degraded: >=2 corridas fallidas seguidas, o >=1 dia sin exito. failing: ambas a la vez.
    Una corrida `partial` (solo EtlRun) cuenta como exito.
    """
    if not recent:
        return "unknown", 0, None
    consecutive = 0
    for status, _ in recent:
        if status != "failed":
            break
        consecutive += 1
    last_success = next((fin for status, fin in recent if status in ("completed", "partial")), None)
    days: int | None = None
    if last_success is not None:
        if last_success.tzinfo is None:
            last_success = last_success.replace(tzinfo=timezone.utc)
        days = max(0, int((now - last_success).total_seconds() // 86400))
    long_without = days is None or days >= 1
    if consecutive >= 2 and long_without:
        status_name = "failing"
    elif consecutive >= 2 or (days is not None and days >= 1):
        status_name = "degraded"
    else:
        status_name = "ok"
    return status_name, consecutive, days


def _source_health(db: Session, source: str, now: datetime) -> dict[str, object]:
    if source == "tch":
        model, scope = EtlRun, EtlRun.channels_processed.any("tch")
    else:
        model, scope = SyncRun, SyncRun.source == source
    rows = db.execute(
        select(model.status, model.finished_at, model.started_at)
        .where(scope, model.status != "running")
        .order_by(model.started_at.desc())
        .limit(_RECENT_RUNS)
    ).all()
    last = rows[0] if rows else None
    hung = db.scalar(
        select(model.id).where(scope, model.status == "running", model.started_at < now - _ERROR_AFTER).limit(1)
    )
    finished = (last.finished_at or last.started_at) if last else None
    level, level_finished, age_hours = _classify(last.status if last else None, finished, hung is not None, now)
    status, consecutive, days = _failure_status([(r.status, r.finished_at or r.started_at) for r in rows], now)
    min_level = _STATUS_MIN_LEVEL.get(status)
    if min_level and _SEVERITY[level] < _SEVERITY[min_level]:
        level = min_level
    return {
        "level": level, "finished_at": level_finished, "age_hours": age_hours,
        "status": status, "consecutive_failures": consecutive, "days_without_success": days,
    }


# SYNC-O-16: el ETL Core de estos canales corre tras cada sync; si queda mas de 24 h detras, el canal esta degradado.
_CORE_CHANNELS = ("virtualpos", "toku", "payku")
_CORE_LAG_DEGRADED_AFTER = timedelta(hours=24)


def _core_lag_hours(db: Session, channel: str, sources: tuple[str, ...]) -> float | None:
    """Horas que el ETL Core va detras del ultimo sync EXITOSO del canal (None si no hay con que comparar).

    Ultimo ETL Core = su marca (`core_etl_mark`); sin marca, el `updated_at` mas reciente de `core_charges` de
    ese canal (cubre el estado previo a la marca: p. ej. Core de Toku que no se actualiza desde hace dias).
    """
    last_sync = db.scalar(
        select(func.max(SyncRun.finished_at)).where(SyncRun.source.in_(sources), SyncRun.status == "completed")
    )
    core_last = core_etl_mark.last_finished_at(db, channel) or db.scalar(
        select(func.max(CoreCharge.updated_at)).where(CoreCharge.source.in_(sources))
    )
    if last_sync is None or core_last is None:
        return None
    if last_sync.tzinfo is None:
        last_sync = last_sync.replace(tzinfo=timezone.utc)
    if core_last.tzinfo is None:
        core_last = core_last.replace(tzinfo=timezone.utc)
    return round(max(0.0, (last_sync - core_last).total_seconds() / 3600), 1)


def _resources_health(db: Session, channel: str, sources: tuple[str, ...]) -> list[dict[str, object]]:
    """SYNC-O-08: `last_success_at` por recurso (marcas de `sync_cursors`; TCH: ultima carga de reporte)."""
    if channel != "tch":
        return sync_cursors.resources_health(db, sources)
    try:
        with db.begin_nested():
            loaded = tch_report_registry.last_loaded_at(db)
    except SQLAlchemyError:
        return []
    if loaded is None:
        return []
    return [{"source": "tch", "resource": "file", "mode": "load", "last_success_at": loaded.isoformat()}]


def _compute_health(db: Session, now: datetime) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for channel, sources in _CHANNEL_SOURCES.items():
        parts = [_source_health(db, src, now) for src in (sources or (channel,))]
        worst = max(parts, key=lambda p: (_SEVERITY[p["level"]], _STATUS_SEVERITY[p["status"]]))  # type: ignore[index]
        finished_at = worst["finished_at"]
        item: dict[str, object] = {
            "channel": channel,
            "level": worst["level"],
            "last_finished_at": finished_at.isoformat() if finished_at else None,  # type: ignore[union-attr]
            "age_hours": worst["age_hours"],
            "status": worst["status"],
            "consecutive_failures": worst["consecutive_failures"],
            "days_without_success": worst["days_without_success"],
        }
        resources = _resources_health(db, channel, sources)
        if resources:  # SYNC-O-08: solo con marcas (sin ellas el contrato de la fila no cambia)
            item["resources"] = resources
        if channel in _CORE_CHANNELS:
            lag = _core_lag_hours(db, channel, sources)
            if lag is not None:
                item["core_lag_hours"] = lag
                if lag > _CORE_LAG_DEGRADED_AFTER.total_seconds() / 3600 and item["status"] == "ok":
                    item["status"] = "degraded"
                    if _SEVERITY[str(item["level"])] < _SEVERITY["warn"]:
                        item["level"] = "warn"
        result.append(item)
    return result


@router.get("/health", dependencies=[Depends(require_permissions("dashboard.view"))])
def sync_health(db: Session = Depends(get_db)) -> list[dict[str, object]]:  # noqa: B008
    """Salud de sincronizacion por canal. Sin error_message ni datos personales; cache de 5 min."""
    cached = _health_cache["value"]
    if cached is not None and time.monotonic() - float(_health_cache["at"]) < _CACHE_TTL_SECONDS:  # type: ignore[arg-type]
        return cached  # type: ignore[return-value]
    value = _compute_health(db, datetime.now(timezone.utc))
    _health_cache["at"] = time.monotonic()
    _health_cache["value"] = value
    return value
