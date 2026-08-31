from fastapi import APIRouter

from app.api.v1.routes import crm, payku, sync_runs, toku

api_router = APIRouter()
api_router.include_router(crm.router)
api_router.include_router(sync_runs.router, prefix="/sync-runs", tags=["Sync runs"])
api_router.include_router(toku.router, prefix="/toku")
api_router.include_router(payku.router, prefix="/payku")
