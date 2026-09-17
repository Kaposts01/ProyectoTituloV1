from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.api.v1.routes import auth
from app.core.config import settings

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
    {"name": "health", "description": "Estado de la API."},
]

app = FastAPI(title=settings.app_name, debug=settings.debug, version="0.1.0", openapi_tags=OPENAPI_TAGS)
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
