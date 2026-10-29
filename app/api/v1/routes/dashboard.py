"""Resumen unificado de la jefatura (UX-07): `GET /api/v1/dashboard/general`. Solo lectura, sin datos personales."""

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db
from app.core.security import get_current_user, require_permissions
from app.models.auth import User
from app.services.dashboard_general import CHANNELS, build_general_summary
from app.services.rbac import permission_codes

router = APIRouter()

_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _422(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": code, "message": message})


@router.get("/general", dependencies=[Depends(require_permissions("dashboard.view"))], tags=["Dashboard"])
def get_general_summary(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    month: Annotated[str | None, Query(description="YYYY-MM (hora de Chile); por defecto el mes actual")] = None,
    channels: Annotated[str | None, Query(description="virtualpos,toku,payku,tch; por defecto todos")] = None,
) -> dict[str, Any]:
    if month is not None and not _MONTH.match(month):
        raise _422("invalid_month", "month debe ser YYYY-MM")
    requested = list(CHANNELS)
    if channels:
        requested = [c.strip().lower() for c in channels.split(",") if c.strip()]
        if any(c not in CHANNELS for c in requested) or not requested:
            raise _422("invalid_channel", "channels admite virtualpos, toku, payku y tch")
    codes = permission_codes(current_user)
    # El filtro de permisos se resuelve en el servidor: un canal sin permiso no aparece ni se calcula.
    allowed = [c for c in requested if f"{c}.dashboard.view" in codes]
    return build_general_summary(db, month, allowed)
