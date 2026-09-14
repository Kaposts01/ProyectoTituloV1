from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import require_permissions
from app.db.session import SessionLocal
from app.models.sync_run import SyncRun

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("", dependencies=[Depends(require_permissions("sync_runs.view"))])
def list_sync_runs(db: Session = Depends(get_db)) -> list[dict[str, object]]:  # noqa: B008
    runs = db.scalars(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(50)).all()
    return [
        {
            "id": str(run.id),
            "source": run.source,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "records_processed": run.records_processed,
            "error_message": run.error_message,
        }
        for run in runs
    ]
