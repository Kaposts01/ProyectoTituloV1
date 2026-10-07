from fastapi import APIRouter, Depends

from app.api.v1.routes import (
    admin,
    catalog,
    crm,
    etl,
    recovery,
    reports,
    scheduler,
    staging,
    sync_runs,
    tch,
    writes,
)
from app.core.security import get_current_user

api_router = APIRouter(dependencies=[Depends(get_current_user)])
api_router.include_router(crm.router)
api_router.include_router(sync_runs.router, prefix="/sync-runs", tags=["Sync runs"])
api_router.include_router(staging.router, prefix="/staging")
api_router.include_router(etl.router, prefix="/etl")
api_router.include_router(writes.router, prefix="/writes")
api_router.include_router(recovery.router, prefix="/recovery")
api_router.include_router(admin.router, prefix="/admin")
api_router.include_router(catalog.router, prefix="/catalog")
api_router.include_router(tch.router, prefix="/tch")
api_router.include_router(reports.router, prefix="/reports")
api_router.include_router(scheduler.router, prefix="/scheduler", tags=["Scheduler"])
