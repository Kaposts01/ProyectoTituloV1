import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import require_permissions
from app.db.session import SessionLocal
from app.models.etl_run import EtlRun
from app.models.sync_run import SyncRun

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("", dependencies=[Depends(require_permissions("sync_runs.view"))])
def list_sync_runs(db: Session = Depends(get_db)) -> list[dict[str, object]]:  # noqa: B008
    runs = db.scalars(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(50)).all()
    return [
        {
            "id": str(run.id),
            "source": run.source,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "records_processed": run.records_processed,
            "error_message": run.error_message,
        }
        for run in runs
    ]


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


def _source_health(db: Session, source: str, now: datetime) -> tuple[str, datetime | None, float | None]:
    if source == "tch":
        model, scope = EtlRun, EtlRun.channels_processed.any("tch")
    else:
        model, scope = SyncRun, SyncRun.source == source
    last = db.execute(
        select(model.status, model.finished_at, model.started_at)
        .where(scope, model.status != "running")
        .order_by(model.started_at.desc())
        .limit(1)
    ).first()
    hung = db.scalar(
        select(model.id).where(scope, model.status == "running", model.started_at < now - _ERROR_AFTER).limit(1)
    )
    finished = (last.finished_at or last.started_at) if last else None
    return _classify(last.status if last else None, finished, hung is not None, now)


def _compute_health(db: Session, now: datetime) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for channel, sources in _CHANNEL_SOURCES.items():
        parts = [_source_health(db, src, now) for src in (sources or (channel,))]
        level, finished_at, age_hours = max(parts, key=lambda part: _SEVERITY[part[0]])
        result.append({
            "channel": channel,
            "level": level,
            "last_finished_at": finished_at.isoformat() if finished_at else None,
            "age_hours": age_hours,
        })
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
