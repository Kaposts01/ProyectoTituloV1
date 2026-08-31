from fastapi import APIRouter

from app.api.v1.routes import sync_runs

api_router = APIRouter()
api_router.include_router(sync_runs.router, prefix="/sync-runs", tags=["sync-runs"])
