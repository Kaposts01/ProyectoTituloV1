from fastapi import APIRouter, Depends

from app.api.v1.routes import (
    admin,
    billing_changes,
    cancellations,
    catalog,
    changes,
    charges_unified,
    crm,
    dashboard,
    etl,
    events,
    export,
    identity,
    imports,
    manual_tasks,
    recovery,
    reports,
    scheduler,
    staging,
    subscriptions,
    sync_runs,
    tch,
    webhooks_admin,
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
api_router.include_router(export.router, prefix="/export")
api_router.include_router(admin.router, prefix="/admin")
api_router.include_router(catalog.router, prefix="/catalog")
api_router.include_router(tch.router, prefix="/tch")
api_router.include_router(reports.router, prefix="/reports")
api_router.include_router(scheduler.router, prefix="/scheduler", tags=["Scheduler"])
api_router.include_router(identity.router, prefix="/core")
api_router.include_router(billing_changes.router, prefix="/billing")
api_router.include_router(cancellations.router, prefix="/cancellations")
api_router.include_router(manual_tasks.router, prefix="/manual-tasks")
api_router.include_router(imports.router, prefix="/imports")
api_router.include_router(changes.router, prefix="/changes", tags=["Changes"])
api_router.include_router(dashboard.router, prefix="/dashboard")
api_router.include_router(events.router, prefix="/events")
api_router.include_router(webhooks_admin.router, prefix="/admin/webhooks")
api_router.include_router(charges_unified.router, prefix="/general")
api_router.include_router(subscriptions.router, prefix="/general")
