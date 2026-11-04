"""UX-09: Cobros unificados de los canales (cargos y pagos), paginados en SQL y con la definicion unica de rechazo.

* `GET /general/charges`: cobros de VirtualPOS (cargos), Toku (deudas), Payku (ciclos de cobro `p_cycles`, PK-06,
  cuando existen; d124 b) y TCH (transacciones), la misma fuente de «cobro» por canal que la exportacion (EXP-03).
* `GET /general/payments`: pagos/transacciones de VirtualPOS, Toku y Payku.
* `GET /general/charges/summary`: tasa de rechazo por canal con `charge_stats` (universo unico, UI-22/UI-29).
* `.../statuses`: estados presentes (para el filtro de estado), sin el filtro de estado activo.

Permisos (d124 opcion c): `general.charges.view` da todos los canales de cobros y pagos. Sin el (compatibilidad mientras
la migracion 20261102_0064 no este aplicada, o roles parciales) cada canal exige su permiso de VISTA de siempre
(`virtualpos.charges.view`, `toku.invoices.view`, `payku.transactions.view`, `tch.transacciones.view`,
`*.payments/transactions.view`); sin ninguno, 403. El filtro de canal es del servidor (`export_queries.select_specs`).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db
from app.core.security import get_current_user
from app.models.auth import User
from app.services.unified_views import (
    build_filters,
    entity_statuses,
    list_entity,
    parse_date,
    rejection_summary,
)

router = APIRouter()

Channel = Literal["virtualpos", "virtualpos1", "virtualpos2", "toku", "payku", "tch"]
Outcome = Literal["paid", "rejected", "pending", "excluded", "other"]
ChannelQuery = Annotated[Channel | None, Query(alias="canal")]


@router.get("/charges", tags=["General"])
def unified_charges(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    channel: ChannelQuery = None,
    query: str | None = Query(None, max_length=200),
    filter_field: str = "all",
    status: str | None = Query(None, max_length=50),
    outcome: Outcome | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    amount_min: float | None = Query(None, ge=0),
    amount_max: float | None = Query(None, ge=0),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    filters = build_filters("cobros", query=query, filter_field=filter_field, status=status, date_from=date_from,
                            date_to=date_to, amount_min=amount_min, amount_max=amount_max, outcome=outcome)
    return list_entity(db, user, "cobros", channel, filters, offset, limit)


@router.get("/charges/statuses", tags=["General"])
def unified_charge_statuses(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    channel: ChannelQuery = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    filters = build_filters("cobros", query=None, filter_field="all", status=None, date_from=date_from, date_to=date_to)
    return entity_statuses(db, user, "cobros", channel, filters)


@router.get("/charges/summary", tags=["General"])
def unified_charge_summary(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    channel: ChannelQuery = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    return rejection_summary(db, user, channel, parse_date(date_from, "date_from"), parse_date(date_to, "date_to"))


@router.get("/payments", tags=["General"])
def unified_payments(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    channel: ChannelQuery = None,
    query: str | None = Query(None, max_length=200),
    filter_field: str = "all",
    status: str | None = Query(None, max_length=50),
    outcome: Outcome | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    amount_min: float | None = Query(None, ge=0),
    amount_max: float | None = Query(None, ge=0),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    filters = build_filters("pagos", query=query, filter_field=filter_field, status=status, date_from=date_from,
                            date_to=date_to, amount_min=amount_min, amount_max=amount_max, outcome=outcome)
    return list_entity(db, user, "pagos", channel, filters, offset, limit)


@router.get("/payments/statuses", tags=["General"])
def unified_payment_statuses(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    channel: ChannelQuery = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    filters = build_filters("pagos", query=None, filter_field="all", status=None, date_from=date_from, date_to=date_to)
    return entity_statuses(db, user, "pagos", channel, filters)
