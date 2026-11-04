"""Vistas unificadas de Cartera (UX-08 Suscripciones, UX-09 Cobros): listado multicanal paginado EN SQL.

Reutiliza las consultas por canal de la exportacion (`export_queries`, EXP-03): mismas columnas, mismos filtros, mismo
orden y mismos permisos de VISTA por canal. Asi el boton «Exportar» de la vista (que llama a `/export/{entidad}` con
los mismos parametros) descarga exactamente lo que se ve, y un usuario solo ve filas de los canales que ya podia ver
(el filtro es del servidor, no del front).

Datos personales: RUT y nombre se muestran en la tabla con el MISMO permiso que hoy los protege en las listas por
canal (el permiso de vista del recurso en ese canal). La exportacion sigue exigiendo `export.pii` para incluirlos.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from app.models.auth import User
from app.services.charge_stats import (
    REJECTION_BASIS,
    REJECTION_BASIS_LABELS,
    charge_rejection_stats,
    chile_today,
)
from app.services.export_queries import (
    FILTER_FIELDS,
    ExportFilters,
    fetch_page,
    select_specs,
    status_facets,
)
from app.services.rbac import permission_codes

PROVIDER_LABELS = {"virtualpos": "VirtualPOS", "toku": "Toku", "payku": "Payku", "tch": "TCH"}


def parse_date(value: str | None, name: str) -> date | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{name} must use YYYY-MM-DD") from exc


def build_filters(
    entity: str, *, query: str | None, filter_field: str, status: str | None, date_from: str | None,
    date_to: str | None, amount_min: float | None = None, amount_max: float | None = None, outcome: str | None = None,
) -> ExportFilters:
    if filter_field not in FILTER_FIELDS[entity]:
        raise HTTPException(status_code=422, detail="Invalid filter field")
    return ExportFilters(
        query=query, filter_field=filter_field, status=status, date_from=parse_date(date_from, "date_from"),
        date_to=parse_date(date_to, "date_to"), amount_min=amount_min, amount_max=amount_max, outcome=outcome,
    )


def permitted_specs(entity: str, channel: str | None, user: User) -> list:
    items, denied = select_specs(entity, channel, permission_codes(user))
    if denied or not items:
        raise HTTPException(status_code=403, detail={"code": "permission_denied", "message": "No tienes permiso para realizar esta acción."})
    return items


def _channels(items: list) -> list[str]:
    return [src for _spec, sources in items for src in sources]


def list_entity(
    db: Session, user: User, entity: str, channel: str | None, filters: ExportFilters, offset: int, limit: int,
) -> dict[str, Any]:
    items = permitted_specs(entity, channel, user)
    rows, totals = fetch_page(db, items, filters, True, offset, limit)
    return {
        "items": rows,
        "total": sum(totals.values()),
        "offset": offset,
        "limit": limit,
        "by_channel": totals,
        "canales": _channels(items),
    }


def entity_statuses(db: Session, user: User, entity: str, channel: str | None, filters: ExportFilters) -> dict[str, Any]:
    items = permitted_specs(entity, channel, user)
    return {"statuses": status_facets(db, items, filters), "canales": _channels(items)}


# Entidad y columna de fecha de la base de rechazo de cada canal (charge_stats.REJECTION_BASIS, UI-29).
_BASIS_ENTITY = {"cargos": ("cobros", "charge_date"), "transacciones": ("pagos", "payment_date")}


def rejection_summary(
    db: Session, user: User, channel: str | None, date_from: date | None, date_to: date | None,
) -> dict[str, Any]:
    """Tasa de rechazo por canal con la definicion UNICA (`charge_stats.charge_rejection_stats`).

    Universo: fecha <= hoy (hora de Chile), sin cancelados/expirados/anulados; tasa = rechazados / (pagados +
    rechazados). VirtualPOS y TCH cuentan cargos; Toku y Payku cuentan transacciones (el canal no marca el cargo como
    rechazado). Solo entran los canales que el usuario puede ver en esa base. Se agrega en SQL por (estado, dia).
    """
    today = chile_today()
    codes = permission_codes(user)
    base = ExportFilters(date_from=date_from, date_to=date_to)
    out: list[dict[str, Any]] = []
    for provider, basis in REJECTION_BASIS.items():
        if channel is not None and channel != provider and not (provider == "virtualpos" and channel.startswith("virtualpos")):
            continue
        entity, date_col = _BASIS_ENTITY[basis]
        items, _denied = select_specs(entity, channel if channel and channel != provider else provider, codes)
        items = [(spec, sources) for spec, sources in items if spec.provider == provider]
        if not items:
            continue
        rows: list[dict[str, Any]] = []
        for spec, sources in items:
            sub = spec.build(sources, base, False).order_by(None).subquery()
            day = func.substr(cast(sub.c[date_col], String), 1, 10)
            stmt = select(sub.c.status, day, func.count()).group_by(sub.c.status, day)
            rows += [{"status": status, "date": d, "count": n} for status, d, n in db.execute(stmt)]
        stats = charge_rejection_stats(rows, today, since=date_from)
        out.append({
            "channel": provider, "label": PROVIDER_LABELS[provider], "basis": basis,
            "basis_label": REJECTION_BASIS_LABELS[basis], **stats,
        })
    if not out:
        raise HTTPException(status_code=403, detail={"code": "permission_denied", "message": "No tienes permiso para realizar esta acción."})
    paid = sum(item["paid"] for item in out)
    rejected = sum(item["rejected"] for item in out)
    evaluable = paid + rejected
    return {
        "today": today.isoformat(),
        "channels": out,
        "total": {"paid": paid, "rejected": rejected, "evaluable": evaluable,
                  "rate": round(100 * rejected / evaluable, 1) if evaluable else None},
    }
