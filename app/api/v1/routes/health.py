"""d139c (L5-ALERTAS): latido para un monitor externo. Ver docs/data/alerts.md («Heartbeat»).

`GET /api/v1/health/heartbeat` NO pide sesion (lo consulta un monitor o `scripts/maintenance/heartbeat_check.py`) y por
eso solo entrega metadatos operativos: fechas del ultimo exito de sync por canal y del scheduler, y un estado global.
Nunca datos personales, mensajes de error, ids ni conteos de negocio.

`status`: `ok`; `degraded` si la ultima sync exitosa (de cualquier canal) tiene mas de `HEARTBEAT_MAX_SYNC_AGE_HOURS`
horas, si el scheduler deberia estar corriendo y no lo esta, o (QA-15) si la ultima corrida de un canal que ya habia
sincronizado bien termino `failed` (`sync_failing`, con el canal en `sync.failing_channels`); `error` (HTTP 503) si la
base no responde. Un canal que nunca sincronizo bien (p. ej. sin credenciales) no marca `sync_failing`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.etl_run import EtlRun
from app.models.sync_run import SyncRun
from app.scheduler import engine
from app.scheduler.run_lock import INTERRUPTED_MESSAGES

router = APIRouter()

_SOURCE_CHANNEL = {"virtualpos1": "virtualpos", "virtualpos2": "virtualpos", "toku": "toku", "payku": "payku"}
_SUCCESS = ("completed", "partial")


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def _scheduler_expected() -> bool:
    # Misma regla que `app.main.scheduler_should_start` (no se importa main para no crear un ciclo).
    return bool(settings.is_production or settings.sandbox_scheduler_enabled)


def heartbeat_payload(now: datetime | None = None) -> tuple[int, dict[str, Any]]:
    moment = now or datetime.now(UTC)
    channels: dict[str, datetime | None] = {"virtualpos": None, "toku": None, "payku": None, "tch": None}
    last_etl: datetime | None = None
    db = SessionLocal()
    try:
        rows = db.execute(
            select(SyncRun.source, func.max(SyncRun.finished_at))
            .where(SyncRun.source.in_(tuple(_SOURCE_CHANNEL)), SyncRun.status == "completed")
            .group_by(SyncRun.source)
        ).all()
        for source, finished in rows:
            channel = _SOURCE_CHANNEL[source]
            finished = _aware(finished)
            if finished and (channels[channel] is None or finished > channels[channel]):  # type: ignore[operator]
                channels[channel] = finished
        channels["tch"] = _aware(db.scalar(
            select(func.max(EtlRun.finished_at)).where(EtlRun.status.in_(_SUCCESS), EtlRun.channels_processed.any("tch"))
        ))
        last_etl = _aware(db.scalar(select(func.max(EtlRun.finished_at)).where(EtlRun.status.in_(_SUCCESS))))
        failing = sorted({
            _SOURCE_CHANNEL[source] for source in _SOURCE_CHANNEL
            if channels[_SOURCE_CHANNEL[source]] is not None and db.scalar(
                select(SyncRun.status).where(
                    SyncRun.source == source, SyncRun.status != "running",
                    # 13B: el cierre por reinicio/abandono no es un fallo del canal
                    SyncRun.error_message.is_(None) | SyncRun.error_message.not_in(INTERRUPTED_MESSAGES),
                ).order_by(SyncRun.started_at.desc()).limit(1)
            ) == "failed"
        })
    except Exception:  # noqa: BLE001 - sin base no hay latido sano; no se expone el detalle
        return 503, {"status": "error", "checked_at": moment.isoformat(), "environment": settings.env_mode,
                     "database": "error"}
    finally:
        db.close()

    known = [c for c in channels.values() if c is not None]
    last_success = max(known) if known else None
    age_hours = round((moment - last_success).total_seconds() / 3600, 1) if last_success else None
    expected = _scheduler_expected()
    running = engine.scheduler_running()
    problems: list[str] = []
    if age_hours is None or age_hours > int(settings.heartbeat_max_sync_age_hours):
        problems.append("sync_stale")
    if expected and not running:
        problems.append("scheduler_stopped")
    if failing:
        problems.append("sync_failing")
    return 200, {
        "status": "degraded" if problems else "ok",
        "problems": problems,
        "checked_at": moment.isoformat(),
        "environment": settings.env_mode,
        "database": "ok",
        "sync": {
            "last_success_at": _iso(last_success),
            "age_hours": age_hours,
            "max_age_hours": int(settings.heartbeat_max_sync_age_hours),
            "channels": {name: _iso(value) for name, value in channels.items()},
            "failing_channels": failing,
        },
        "scheduler": {
            "expected": expected,
            "running": running,
            "last_job_success_at": _iso(engine.last_job_success_at()),
            "last_etl_run_success_at": _iso(last_etl),
        },
    }


@router.get("/heartbeat")
def heartbeat() -> JSONResponse:
    """Latido sin sesion para un monitor externo. Solo fechas y estados; nunca datos personales."""
    status_code, payload = heartbeat_payload()
    return JSONResponse(payload, status_code=status_code, headers={"Cache-Control": "no-store"})
