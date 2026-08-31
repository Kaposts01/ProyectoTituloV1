from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import settings

OPENAPI_TAGS = [
    {"name": "Cliente", "description": "Consultas CRM para clientes de VirtualPOS."},
    {"name": "Plan", "description": "Los planes se conservan actualmente en staging."},
    {"name": "Suscription", "description": "Consultas CRM para suscripciones de VirtualPOS."},
    {"name": "Charge", "description": "Consultas CRM para cargos de VirtualPOS."},
    {"name": "Payment", "description": "Consultas CRM para pagos de VirtualPOS."},
    {"name": "Sync runs", "description": "Ejecuciones de sincronizacion read-only."},
    {"name": "Staging", "description": "Registros saneados almacenados por canal."},
    {"name": "health", "description": "Estado de la API."},
]

app = FastAPI(title=settings.app_name, debug=settings.debug, version="0.1.0", openapi_tags=OPENAPI_TAGS)
app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}
