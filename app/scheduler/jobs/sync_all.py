"""Rutina de sincronización diaria: VP1 + VP2 + Toku + Payku → consolidar → reconciliar."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app.core.channel_errors import ChannelConfigError
from app.core.config import settings
from app.db.session import SessionLocal
from app.integrations.virtualpos.client import VirtualPOSClient
from app.models.etl_run import EtlRun
from app.models.sync_run import SyncRun
from app.scheduler import event_bus
from app.scheduler.run_lock import ActiveRunError, start_exclusive_run
from app.services import core_etl_mark, status_events, sync_metrics
from app.services import tch_report_registry as tch_registry
from app.services.channel_consolidation import consolidate_to_centralized
from app.services.charge_recovery import reconcile_charge_recoveries
from app.services.core_payku_etl import run_payku_core_etl
from app.services.core_toku_etl import run_toku_core_etl
from app.services.core_vp_etl import run_vp_core_etl
from app.services.payku_sync import sync_payku
from app.services.sync_metrics import RunMetrics
from app.services.toku_sync import sync_toku
from app.services.virtualpos_sync import sync_virtualpos
from app.services.vp_rejection_capture import capture_vp_rejections

logger = logging.getLogger(__name__)

_VIRTUALPOS_PLATFORMS = ("virtualpos1", "virtualpos2")
# SYNC-O-16: ETL Core por canal (el mismo que /etl/core/{provider}); TCH no entra (se alimenta de reportes).
_CORE_ETL_RUNNERS = {"virtualpos": run_vp_core_etl, "toku": run_toku_core_etl, "payku": run_payku_core_etl}
_ALL_CHANNELS = frozenset({"virtualpos1", "virtualpos2", "toku", "payku", "tch"})


def channel_is_enabled(channel: str) -> bool:
    """virtualpos1/virtualpos2 -> canal 'virtualpos' (cuenta 2 solo existe en produccion)."""
    if channel == "virtualpos2":
        return settings.is_production
    return settings.channel_enabled("virtualpos" if channel == "virtualpos1" else channel)


def skip_disabled_channel(channel: str) -> bool:
    """True (con log claro, sin error) si el canal esta deshabilitado en el ambiente actual."""
    if channel_is_enabled(channel):
        return False
    logger.warning("Canal %s omitido: deshabilitado en %s (sin variables *_SANDBOX_*).", channel, settings.env_mode)
    return True


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


def _mark_sync_run_failed(sync_run_id: uuid.UUID, message: str) -> None:
    """Deja `failed` la fila de sync de un canal (p. ej. si su consolidacion final fallo) para que el reintento actue."""
    db = SessionLocal()
    try:
        sync_run = db.get(SyncRun, sync_run_id)
        if sync_run is not None:
            sync_run.status = "failed"
            sync_run.error_message = message
            sync_run.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


async def _capture_vp_rejections(platform: str, run_id: uuid.UUID) -> dict:
    """RJ-06: captura la glosa de rechazo de una cuenta VirtualPOS (sesion propia; los eventos llevan el `run_id`)."""
    db = SessionLocal()
    try:
        client_factory = VirtualPOSClient if platform == "virtualpos1" else lambda: VirtualPOSClient(platform)
        async with client_factory() as client:
            with status_events.event_context(run_id=run_id):
                return await capture_vp_rejections(db, platform, client)
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

    # SYNC-O-11: arranque atomico. Si el endpoint ya reservo la fila `running` con este run_id, se adopta; si no,
    # se crea bajo el lock. Con otra corrida activa (otro worker, ETL core, importacion TCH) no se ejecuta nada.
    adopt = None
    if run_id is not None:
        db = SessionLocal()
        try:
            existing = db.get(EtlRun, uuid.UUID(run_id))
            if existing is not None and existing.status == "running":
                adopt = existing.id
        finally:
            db.close()
    if adopt is None:
        db = SessionLocal()
        try:
            started_run = start_exclusive_run(
                db, **({"id": uuid.UUID(run_id)} if run_id else {}), phase="starting"
            )
            adopt = started_run.id
        except ActiveRunError as busy:
            logger.warning(
                "sync_all_channels: run activo (run_id=%s), abortando para evitar ejecución concurrente.", busy.run_id
            )
            return
        finally:
            db.close()
    run_id = str(adopt)

    event_bus.create_bus(run_id)

    db_run_id = uuid.UUID(run_id)

    total_records = 0
    started = datetime.now(timezone.utc)
    channels_done: list[str] = []
    channels_failed: list[str] = []
    config_failed: list[str] = []
    metrics = RunMetrics(run_id)
    metrics_token = sync_metrics.activate(metrics)
    vp_synced: dict[str, uuid.UUID] = {}  # cuenta VP -> id de su SyncRun (para reconciliar tras la consolidacion final)

    try:
        # — VirtualPOS VP1 y VP2 —
        for platform in _VIRTUALPOS_PLATFORMS:
            if platform not in requested or skip_disabled_channel(platform):
                continue
            phase = f"sync_{platform}"
            _update_run(db_run_id, phase=phase)
            event_bus.emit(run_id, {"type": "phase_start", "phase": phase})
            logger.info("Iniciando %s", phase)
            db = SessionLocal()
            try:
                # SYNC-O-04: no consolida aqui; la consolidacion de VP corre una sola vez, mas abajo.
                with metrics.timed("sync", platform):
                    sync_run = await sync_virtualpos(
                        db, platform, _make_progress_callback(run_id, phase), consolidate=False
                    )
                n = sync_run.records_processed or 0
                total_records += n
                channels_done.append(platform)
                vp_synced[platform] = sync_run.id
                event_bus.emit(run_id, {"type": "phase_done", "phase": phase, "records": n})
                logger.info("%s completado: %d registros", phase, n)
            except Exception as exc:
                logger.exception("Error en %s", phase)
                channels_failed.append(platform)
                if isinstance(exc, ChannelConfigError):
                    config_failed.append(platform)
                event_bus.emit(run_id, {"type": "error", "phase": phase, "msg": f"Error en {phase}"})
            finally:
                db.close()

        # — Toku —
        if "toku" in requested and not skip_disabled_channel("toku"):
            phase = "sync_toku"
            _update_run(db_run_id, phase=phase)
            event_bus.emit(run_id, {"type": "phase_start", "phase": phase})
            logger.info("Iniciando %s", phase)
            db = SessionLocal()
            try:
                with metrics.timed("sync", "toku"):
                    sync_run = await sync_toku(db, _make_progress_callback(run_id, phase))
                n = sync_run.records_processed or 0
                total_records += n
                channels_done.append("toku")
                event_bus.emit(run_id, {"type": "phase_done", "phase": phase, "records": n})
                logger.info("%s completado: %d registros", phase, n)
            except Exception as exc:
                logger.exception("Error en %s", phase)
                channels_failed.append("toku")
                if isinstance(exc, ChannelConfigError):
                    config_failed.append("toku")
                event_bus.emit(run_id, {"type": "error", "phase": phase, "msg": "Error en sync_toku"})
            finally:
                db.close()

        # — Payku —
        if "payku" in requested and not skip_disabled_channel("payku"):
            phase = "sync_payku"
            _update_run(db_run_id, phase=phase)
            event_bus.emit(run_id, {"type": "phase_start", "phase": phase})
            logger.info("Iniciando %s", phase)
            db = SessionLocal()
            try:
                with metrics.timed("sync", "payku"):
                    sync_run = await sync_payku(db, _make_progress_callback(run_id, phase))
                n = sync_run.records_processed or 0
                total_records += n
                channels_done.append("payku")
                event_bus.emit(run_id, {"type": "phase_done", "phase": phase, "records": n})
                logger.info("%s completado: %d registros", phase, n)
            except Exception as exc:
                logger.exception("Error en %s", phase)
                channels_failed.append("payku")
                if isinstance(exc, ChannelConfigError):
                    config_failed.append("payku")
                event_bus.emit(run_id, {"type": "error", "phase": phase, "msg": "Error en sync_payku"})
            finally:
                db.close()

        # — Captura de glosa de rechazo de VirtualPOS (RJ-06) —: tras sincronizar y ANTES de consolidar, para que el
        # vinculo pago-cobro llegue a `payments`. Apagada por defecto (VP_REJECTION_CAPTURE_ENABLED); auxiliar: un fallo
        # se registra en las metricas y NO cambia el estado del run ni obliga a reintentar el sync.
        if settings.vp_rejection_capture_enabled and vp_synced:
            _update_run(db_run_id, phase="capture_vp_rejections")
            event_bus.emit(run_id, {"type": "phase_start", "phase": "capture_vp_rejections"})
            for platform in vp_synced:
                try:
                    with metrics.timed("capture_rejections", platform) as info:
                        captured = await _capture_vp_rejections(platform, db_run_id)
                        info["records"] = captured.get("details_new", 0)
                        info["failed"] = captured.get("subscriptions_failed", 0)
                        info["pending"] = captured.get("subscriptions_pending", 0)
                    if captured.get("aborted"):
                        metrics.note(f"vp_rejection_capture_{platform}", f"cortada: {captured['aborted']}")
                except Exception:
                    logger.exception("Error en la captura de glosas de %s (no afecta al run)", platform)
                    metrics.add("capture_rejections", platform, error=True)

        # — Consolidación centralizada —
        consolidate_sources: list[str] = []
        if channels is None:
            consolidate_sources = ["virtualpos", "toku", "payku", "tch"]
        else:
            if "virtualpos1" in requested or "virtualpos2" in requested:
                consolidate_sources.append("virtualpos")
            if "toku" in requested:
                consolidate_sources.append("toku")
            if "payku" in requested:
                consolidate_sources.append("payku")
            if "tch" in requested:
                consolidate_sources.append("tch")
            if not consolidate_sources:
                consolidate_sources = ["virtualpos", "toku", "payku", "tch"]

        # SYNC-O-03: la importacion TCH escribe solo en tch_*; las tablas centralizadas las alimenta esta
        # consolidacion. La corrida nocturna (channels=None) la omite si no hubo reporte nuevo desde la ultima
        # consolidacion TCH exitosa; un pedido explicito de "tch" siempre consolida. Ante duda (error al leer el
        # registro) se consolida.
        tch_snapshot: dict | None = None
        tch_skipped = False
        if "tch" in consolidate_sources:
            db = SessionLocal()
            try:
                tch_snapshot = tch_registry.consolidation_snapshot(db)
                if (
                    channels is None
                    and settings.sync_tch_consolidate_only_after_load
                    and not tch_registry.needs_consolidation(db, tch_snapshot)
                ):
                    consolidate_sources.remove("tch")
                    tch_skipped = True
            except Exception:
                logger.exception("No se pudo leer el registro de reportes TCH; se consolida TCH por seguridad.")
                tch_snapshot = None
            finally:
                db.close()
        if tch_skipped:
            logger.info("Consolidación TCH omitida: sin reporte Excel nuevo desde la última consolidación exitosa.")
            event_bus.emit(run_id, {"type": "phase_skipped", "phase": "consolidating_tch", "reason": "sin_carga_nueva"})
            metrics.note("tch_consolidation", "omitida: sin reporte Excel nuevo desde la ultima consolidacion")

        phase = "consolidating"
        _update_run(db_run_id, phase=phase)
        event_bus.emit(run_id, {"type": "phase_start", "phase": phase})
        logger.info("Consolidando canales: %s", consolidate_sources)
        consolidation_failures: list[str] = []
        consolidation_error = False
        db = SessionLocal()
        try:
            consolidation_timings: list[dict] = []
            with metrics.timed("consolidate_total") as consolidate_info:
                consolidated = consolidate_to_centralized(
                    db, consolidate_sources, failures=consolidation_failures, timings=consolidation_timings,
                    run_id=db_run_id,
                )
                consolidate_info["records"] = consolidated
            for item in consolidation_timings:
                metrics.add(
                    "consolidate", f"{item['source']}.{item['fn']}", item["seconds"], records=item["records"],
                    **({"written": item["written"]} if "written" in item else {}),
                )
            total_records += consolidated
            if "tch" in consolidate_sources and tch_snapshot is not None and not any(
                f.startswith("tch.") for f in consolidation_failures
            ):
                tch_registry.mark_consolidated(db, tch_snapshot)  # solo si TCH consolido sin fallos
                db.commit()
            if "tch" in requested:
                channels_done.append("tch")
            event_bus.emit(run_id, {"type": "phase_done", "phase": phase, "records": consolidated})
            logger.info("Consolidación completada: %d registros", consolidated)
        except Exception:
            logger.exception("Error en consolidación")
            consolidation_error = True
            event_bus.emit(run_id, {"type": "error", "phase": phase, "msg": "Error en consolidación"})
        finally:
            db.close()

        # Cuentas VP: si su consolidacion fallo quedan `failed` (el reintento las toma, como antes, cuando la
        # consolidacion iba dentro de su sync); si no, se reconcilian las recuperaciones sobre los cobros ya consolidados.
        vp_consolidation_failed = consolidation_error or any(f.startswith("virtualpos.") for f in consolidation_failures)
        for platform, sync_run_id in vp_synced.items():
            if vp_consolidation_failed:
                channels_done.remove(platform)
                channels_failed.append(platform)
                _mark_sync_run_failed(sync_run_id, "Consolidacion de VirtualPOS fallida.")
                continue
            db = SessionLocal()
            try:
                reconcile_charge_recoveries(db, platform)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Error reconciliando recuperaciones de %s", platform)
                consolidation_failures.append(f"virtualpos.reconcile_{platform}")
            finally:
                db.close()

        # — ETL Core (SYNC-O-16) —: tras consolidar, solo de los canales que sincronizaron y consolidaron bien.
        core_failures: list[str] = []
        if settings.sync_core_etl_enabled and not consolidation_error:
            core_targets: list[str] = []
            if any(platform in channels_done for platform in _VIRTUALPOS_PLATFORMS):
                core_targets.append("virtualpos")
            for channel in ("toku", "payku"):
                if channel in channels_done and not any(f.startswith(f"{channel}.") for f in consolidation_failures):
                    core_targets.append(channel)
            core_targets = [c for c in core_targets if c in _CORE_ETL_RUNNERS]
            if core_targets:
                _update_run(db_run_id, phase="core_etl")
                event_bus.emit(run_id, {"type": "phase_start", "phase": "core_etl"})
            for channel in core_targets:
                db = SessionLocal()
                try:
                    with metrics.timed("core_etl", channel) as info:
                        result = _CORE_ETL_RUNNERS[channel](db)
                        core_etl_mark.record(db, channel, result)
                        db.commit()
                        info["records"] = sum(v for v in result.values() if isinstance(v, int))
                    logger.info("ETL Core %s completado: %s", channel, result)
                except Exception:
                    db.rollback()
                    logger.exception("Error en ETL Core %s", channel)
                    core_failures.append(channel)
                    metrics.add("core_etl", channel, error=True)
                    event_bus.emit(run_id, {"type": "error", "phase": "core_etl", "msg": f"Error en ETL Core {channel}"})
                finally:
                    db.close()

        duration_s = int((datetime.now(timezone.utc) - started).total_seconds())
        failed_parts = []
        if channels_failed:
            failed_parts.append(f"Canales con error: {', '.join(channels_failed)}")
        if config_failed:
            failed_parts.append(
                f"Error de configuracion (no se reintenta; revisar variables de entorno): {', '.join(config_failed)}"
            )
        if consolidation_failures:
            failed_parts.append(f"Consolidacion con error: {', '.join(consolidation_failures)}")
        if consolidation_error:
            failed_parts.append("Consolidacion fallida")
        if core_failures:
            failed_parts.append(f"ETL Core con error: {', '.join(core_failures)}")
        failed_msg = "; ".join(failed_parts) or None
        # Nunca 'completed' si algo fallo: 'partial' si hubo exito en algun canal, 'failed' si ninguno.
        if not (channels_failed or consolidation_failures or consolidation_error or core_failures):
            final_status = "completed"
        elif channels_done:
            final_status = "partial"
        else:
            final_status = "failed"
        db = SessionLocal()
        try:
            metrics.persist(db)
            db.commit()
        except Exception:
            logger.exception("No se pudieron guardar las metricas del run")
            db.rollback()
        finally:
            db.close()
        _update_run(
            db_run_id,
            status=final_status,
            phase=None,
            channels_processed=channels_done,
            channels_failed=channels_failed or None,
            records_upserted=total_records,
            finished_at=datetime.now(timezone.utc),
            error_message=failed_msg,
        )
        event_bus.emit(run_id, {
            "type": "completed",
            "total_records": total_records,
            "duration_s": duration_s,
            "channels_done": channels_done,
            "channels_failed": channels_failed,
            "status": final_status,
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
        sync_metrics.deactivate(metrics_token)
        event_bus.close_bus(run_id)
