"""UX-08: Suscripciones unificadas de los 4 canales (VirtualPOS, Toku, Payku, TCH), paginadas en SQL.

Reemplaza en la pantalla «Suscripciones» a `/staging/dashboard/general/subscriptions` (que carga todo en memoria; el
endpoint viejo se mantiene sin cambios). Reutiliza las consultas de la exportacion (EXP-03): mismas exclusiones
(VirtualPOS SUSCRIPCION_FALLIDA, Payku REGISTER, TCH RECHAZADA), mismo «estado secundario» y mismo orden, asi que
«Exportar» descarga lo que se ve. Cada canal exige su permiso de vista de suscripciones; el filtro es del servidor.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db
from app.core.security import get_current_user
from app.models.auth import User
from app.services.unified_views import build_filters, entity_statuses, list_entity

router = APIRouter()

Channel = Literal["virtualpos", "virtualpos1", "virtualpos2", "toku", "payku", "tch"]
ChannelQuery = Annotated[Channel | None, Query(alias="canal")]


@router.get("/subscriptions", tags=["General"])
def unified_subscriptions(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    channel: ChannelQuery = None,
    query: str | None = Query(None, max_length=200),
    filter_field: str = "all",
    status: str | None = Query(None, max_length=50),
    date_from: str | None = None,
    date_to: str | None = None,
    amount_min: float | None = Query(None, ge=0),
    amount_max: float | None = Query(None, ge=0),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    filters = build_filters("suscripciones", query=query, filter_field=filter_field, status=status, date_from=date_from,
                            date_to=date_to, amount_min=amount_min, amount_max=amount_max)
    return list_entity(db, user, "suscripciones", channel, filters, offset, limit)


@router.get("/subscriptions/statuses", tags=["General"])
def unified_subscription_statuses(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    channel: ChannelQuery = None,
) -> dict[str, Any]:
    filters = build_filters("suscripciones", query=None, filter_field="all", status=None, date_from=None, date_to=None)
    return entity_statuses(db, user, "suscripciones", channel, filters)
