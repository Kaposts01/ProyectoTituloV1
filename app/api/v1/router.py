from fastapi import APIRouter

from app.api.v1.routes import crm, etl, staging, sync_runs

api_router = APIRouter()
api_router.include_router(crm.router)
api_router.include_router(sync_runs.router, prefix="/sync-runs", tags=["Sync runs"])
api_router.include_router(staging.router, prefix="/staging")
api_router.include_router(etl.router, prefix="/etl")
