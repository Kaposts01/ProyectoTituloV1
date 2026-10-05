import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.api.v1.routes import auth
from app.core.config import settings
from app.scheduler.engine import get_scheduler, register_jobs

logger = logging.getLogger(__name__)

_DIST = Path(__file__).parent.parent / "frontend" / "dist"

OPENAPI_TAGS = [
    {"name": "Cliente", "description": "Consultas CRM para clientes de VirtualPOS."},
    {"name": "Plan", "description": "Los planes se conservan actualmente en staging."},
    {"name": "Suscription", "description": "Consultas CRM para suscripciones de VirtualPOS."},
    {"name": "Charge", "description": "Consultas CRM para cargos de VirtualPOS."},
    {"name": "Payment", "description": "Consultas CRM para pagos de VirtualPOS."},
    {"name": "Sync runs", "description": "Ejecuciones de sincronizacion read-only."},
    {"name": "Staging", "description": "Registros saneados almacenados por canal."},
    {"name": "Writes - VirtualPOS", "description": "Operaciones internas autorizadas de VirtualPOS."},
    {"name": "Authentication", "description": "Sesión del CRM."},
    {"name": "Administration", "description": "Usuarios, roles y permisos."},
    {"name": "Scheduler", "description": "Orquestador de sincronizaciones programadas."},
    {"name": "health", "description": "Estado de la API."},
]


def _cleanup_zombie_runs() -> None:
    """Marca como failed los runs que quedaron en estado 'running' tras un reinicio.

    Cubre `etl_runs` y `sync_runs`: una corrida interrumpida deja un registro por
    canal en `sync_runs`, y sin limpiarlos quedan en 'running' indefinidamente.
    """
    from datetime import datetime, timezone

    from sqlalchemy import update

    from app.db.session import SessionLocal
    from app.models.etl_run import EtlRun
    from app.models.sync_run import SyncRun

    mensaje = "Servidor reiniciado durante la sincronización."
    finished_at = datetime.now(timezone.utc)

    db = SessionLocal()
    try:
        etl_result = db.execute(
            update(EtlRun)
            .where(EtlRun.status == "running")
            .values(
                status="failed",
                phase=None,
                error_message=mensaje,
                finished_at=finished_at,
            )
        )
        sync_result = db.execute(
            update(SyncRun)
            .where(SyncRun.status == "running")
            .values(
                status="failed",
                error_message=mensaje,
                finished_at=finished_at,
            )
        )
        if etl_result.rowcount or sync_result.rowcount:
            logger.warning(
                "Se marcaron %d etl_runs y %d sync_runs zombie como failed.",
                etl_result.rowcount,
                sync_result.rowcount,
            )
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _cleanup_zombie_runs()
    sched = get_scheduler()
    register_jobs(sched)
    sched.start()
    logger.info("Scheduler iniciado.")
    yield
    sched.shutdown(wait=False)
    logger.info("Scheduler detenido.")


app = FastAPI(title=settings.app_name, debug=settings.debug, version="0.1.0", openapi_tags=OPENAPI_TAGS, lifespan=lifespan)
app.include_router(auth.router, prefix="/api/v1/auth")
app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}


if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="spa_assets")

    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon() -> FileResponse:
        return FileResponse(_DIST / "favicon.svg")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_index(full_path: str) -> FileResponse:
        return FileResponse(_DIST / "index.html")
