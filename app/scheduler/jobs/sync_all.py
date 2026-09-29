"""Rutina de sincronización diaria: VP1 + VP2 + Toku + Payku → consolidar → reconciliar."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.models.etl_run import EtlRun
from app.scheduler import event_bus
from app.services.channel_consolidation import consolidate_to_canonical
from app.services.payku_sync import sync_payku
from app.services.toku_sync import sync_toku
from app.services.virtualpos_sync import sync_virtualpos

logger = logging.getLogger(__name__)

_VIRTUALPOS_PLATFORMS = ("virtualpos1", "virtualpos2")
_ALL_CHANNELS = frozenset({"virtualpos1", "virtualpos2", "toku", "payku", "tch"})


def _update_run(run_id: uuid.UUID, **kwargs) -> None:
    db = SessionLocal()
    try:
        run = db.get(EtlRun, run_id)
        if run:
            for k, v in kwargs.items():
                setattr(run, k, v)
            db.commit()
    finally:
        db.close()


def _make_progress_callback(run_id: str, phase: str):
    def callback(resource: str, page: int, records: int, total_records: int | None, total_pages: int | None) -> None:
        if total_records is not None and total_records > 0:
            pct = min(100, records * 100 // total_records)
        elif total_pages is not None and total_pages > 0:
            pct = min(100, page * 100 // total_pages)
        else:
            pct = None
        event_bus.emit(run_id, {
            "type": "progress",
            "phase": phase,
            "resource": resource,
            "pct": pct,
            "records": records,
        })

    return callback


async def sync_all_channels(run_id: str | None = None, channels: list[str] | None = None) -> None:
    """Sincroniza los canales indicados y emite progreso al bus SSE.

    channels=None → todos los canales (virtualpos1, virtualpos2, toku, payku, tch).
    """
    requested = frozenset(channels) if channels else _ALL_CHANNELS

    if run_id is None:
        run_id = str(uuid.uuid4())

    event_bus.create_bus(run_id)

    db_run_id = uuid.UUID(run_id)
    db = SessionLocal()
    try:
        run = EtlRun(id=db_run_id, status="running", phase="starting")
        db.add(run)
        db.commit()
    finally:
        db.close()

    total_records = 0
    started = datetime.now(timezone.utc)
    channels_done: list[str] = []

    try:
        # — VirtualPOS VP1 y VP2 —
        for platform in _VIRTUALPOS_PLATFORMS:
            if platform not in requested:
                continue
            phase = f"sync_{platform}"
            _update_run(db_run_id, phase=phase)
            event_bus.emit(run_id, {"type": "phase_start", "phase": phase})
            logger.info("Iniciando %s", phase)
            db = SessionLocal()
            try:
                sync_run = await sync_virtualpos(db, platform, _make_progress_callback(run_id, phase))
                n = sync_run.records_processed or 0
                total_records += n
                channels_done.append(platform)
                event_bus.emit(run_id, {"type": "phase_done", "phase": phase, "records": n})
                logger.info("%s completado: %d registros", phase, n)
            except Exception:
                logger.exception("Error en %s", phase)
                event_bus.emit(run_id, {"type": "error", "phase": phase, "msg": f"Error en {phase}"})
            finally:
                db.close()

        # — Toku —
        if "toku" in requested:
            phase = "sync_toku"
            _update_run(db_run_id, phase=phase)
            event_bus.emit(run_id, {"type": "phase_start", "phase": phase})
            logger.info("Iniciando %s", phase)
            db = SessionLocal()
            try:
                sync_run = await sync_toku(db, _make_progress_callback(run_id, phase))
                n = sync_run.records_processed or 0
                total_records += n
                channels_done.append("toku")
                event_bus.emit(run_id, {"type": "phase_done", "phase": phase, "records": n})
                logger.info("%s completado: %d registros", phase, n)
            except Exception:
                logger.exception("Error en %s", phase)
                event_bus.emit(run_id, {"type": "error", "phase": phase, "msg": "Error en sync_toku"})
            finally:
                db.close()

        # — Payku —
        if "payku" in requested:
            phase = "sync_payku"
            _update_run(db_run_id, phase=phase)
            event_bus.emit(run_id, {"type": "phase_start", "phase": phase})
            logger.info("Iniciando %s", phase)
            db = SessionLocal()
            try:
                sync_run = await sync_payku(db, _make_progress_callback(run_id, phase))
                n = sync_run.records_processed or 0
                total_records += n
                channels_done.append("payku")
                event_bus.emit(run_id, {"type": "phase_done", "phase": phase, "records": n})
                logger.info("%s completado: %d registros", phase, n)
            except Exception:
                logger.exception("Error en %s", phase)
                event_bus.emit(run_id, {"type": "error", "phase": phase, "msg": "Error en sync_payku"})
            finally:
                db.close()

        # — Consolidación canónica —
        consolidate_sources: list[str] | None = None
        if channels is not None:
            consolidate_sources = []
            if "virtualpos1" in requested or "virtualpos2" in requested:
                consolidate_sources.append("virtualpos")
            if "toku" in requested:
                consolidate_sources.append("toku")
            if "payku" in requested:
                consolidate_sources.append("payku")
            if "tch" in requested:
                consolidate_sources.append("tch")
            if not consolidate_sources:
                consolidate_sources = None

        phase = "consolidating"
        _update_run(db_run_id, phase=phase)
        event_bus.emit(run_id, {"type": "phase_start", "phase": phase})
        logger.info("Consolidando canales: %s", consolidate_sources or "todos")
        db = SessionLocal()
        try:
            consolidated = consolidate_to_canonical(db, consolidate_sources)
            total_records += consolidated
            if "tch" in requested:
                channels_done.append("tch")
            event_bus.emit(run_id, {"type": "phase_done", "phase": phase, "records": consolidated})
            logger.info("Consolidación completada: %d registros", consolidated)
        except Exception:
            logger.exception("Error en consolidación")
            event_bus.emit(run_id, {"type": "error", "phase": phase, "msg": "Error en consolidación"})
        finally:
            db.close()

        duration_s = int((datetime.now(timezone.utc) - started).total_seconds())
        _update_run(
            db_run_id,
            status="completed",
            phase=None,
            channels_processed=channels_done,
            records_upserted=total_records,
            finished_at=datetime.now(timezone.utc),
        )
        event_bus.emit(run_id, {
            "type": "completed",
            "total_records": total_records,
            "duration_s": duration_s,
        })
        logger.info("sync_all_channels completado: %d registros en %ds", total_records, duration_s)

    except Exception as exc:
        logger.exception("Error fatal en sync_all_channels (run_id=%s)", run_id)
        _update_run(
            db_run_id,
            status="failed",
            phase=None,
            error_message=str(exc)[:2000],
            finished_at=datetime.now(timezone.utc),
        )
        event_bus.emit(run_id, {"type": "error", "phase": "fatal", "msg": str(exc)[:500]})

    finally:
        event_bus.close_bus(run_id)
