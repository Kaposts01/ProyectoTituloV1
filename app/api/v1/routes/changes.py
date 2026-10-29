"""Cambios de estado/monto detectados por la sincronizacion (SYNC-D-04). Solo lectura, sin datos personales."""

from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db
from app.core.security import require_permissions
from app.models.status_change import ENTITY_TYPES
from app.services import rejected_month
from app.services.status_history import daily_changes

router = APIRouter()

_SOURCES = ("virtualpos1", "virtualpos2", "toku", "payku", "tch")


@router.get("/daily", dependencies=[Depends(require_permissions("dashboard.view"))])
def get_daily_changes(
    db: Annotated[Session, Depends(get_db)],
    date_: Annotated[str | None, Query(alias="date", description="YYYY-MM-DD en hora de Chile; por defecto ayer")] = None,
    source: Annotated[str | None, Query(description="virtualpos1|virtualpos2|toku|payku|tch")] = None,
    entity_type: Annotated[str | None, Query(description="charge|subscription|payment|client")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    if date_ is None:
        day = rejected_month.now_chile().date() - timedelta(days=1)
    else:
        try:
            day = date.fromisoformat(date_)
        except ValueError:
            raise HTTPException(status_code=422, detail={"code": "invalid_date", "message": "date debe ser YYYY-MM-DD"}) from None
    if source is not None and source not in _SOURCES:
        raise HTTPException(status_code=422, detail={"code": "invalid_source", "message": "source no valido"})
    if entity_type is not None and entity_type not in ENTITY_TYPES:
        raise HTTPException(status_code=422, detail={"code": "invalid_entity_type", "message": "entity_type no valido"})
    return daily_changes(db, day, source=source, entity_type=entity_type, limit=limit, offset=offset)
