"""RUT y nombre en las pestañas Toku, TCH y Payku del Recuperador general (decisión d119, opción b).

Mismo patrón que las vistas unificadas de Cartera (`unified_views`) y las listas por canal: el RUT y el nombre se
muestran solo a quien tiene el permiso que hoy protege los datos personales de ese canal (ver clientes del canal). Sin
ese permiso las claves `rut` y `name` van en `null` y el resultado lleva `pii_included = false`: el dato no se carga ni se
transporta. La exportación CSV no cambia (sigue exigiendo su propio permiso).

Fuentes: Toku y Payku desde `subscriptions` + `clients` (RUT de la suscripción o del cliente; nombre del cliente), como
`export_queries._subs_cclient` / `_subs_payku`. TCH desde `tch_suscripciones` (RUT por número de ficha) + `tch_clientes`
(nombre por RUT normalizado), como `export_queries._subs_tch`. Nunca se registra en el log.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.auth import User
from app.models.crm import Client as CClient
from app.models.crm import Subscription as CSub
from app.models.tch import TchClient, TchSubscription
from app.services.rbac import permission_codes

PII_PERMISSIONS = {"toku": "toku.customers.view", "payku": "payku.clients.view", "tch": "tch.clientes.view"}


def can_view_pii(user: User | None, source: str) -> bool:
    """True si el usuario tiene el permiso de datos personales del canal (ver clientes de ese canal)."""
    return user is not None and PII_PERMISSIONS[source] in permission_codes(user)


def _join_name(first: str | None, last: str | None) -> str | None:
    name = " ".join(p.strip() for p in (first, last) if p and p.strip())
    return name or None


def _rut_key(value: str | None) -> str:
    return "".join(ch for ch in (value or "").upper() if ch.isdigit() or ch == "K")


def _crm_people(db: Session, source: str, sub_ids: list[str]) -> dict[str, tuple[str | None, str | None]]:
    rows = db.execute(
        select(CSub.external_id, CSub.client_social_id, CClient.social_id, CClient.first_name, CClient.last_name)
        .outerjoin(CClient, and_(CClient.source == CSub.source, CClient.external_id == CSub.client_external_id))
        .where(CSub.source == source, CSub.external_id.in_(sub_ids))
    )
    out: dict[str, tuple[str | None, str | None]] = {}
    for ext, sub_rut, client_rut, first, last in rows:
        out.setdefault(ext, (sub_rut or client_rut, _join_name(first, last)))
    return out


def _tch_people(db: Session, sub_ids: list[str]) -> dict[str, tuple[str | None, str | None]]:
    files = sorted({int(s) for s in sub_ids if s and s.isdigit()})
    if not files:
        return {}
    ruts: dict[str, str] = {}
    for file_number, rut in db.execute(
        select(TchSubscription.file_number, TchSubscription.client_rut)
        .where(TchSubscription.file_number.in_(files), TchSubscription.client_rut.is_not(None))
        .order_by(TchSubscription.file_number)
    ):
        ruts.setdefault(str(file_number), rut)
    keys = {_rut_key(r) for r in ruts.values()} - {""}
    names: dict[str, str | None] = {}
    if keys:
        key_sql = func.regexp_replace(func.upper(func.coalesce(TchClient.rut, "")), "[^0-9K]", "", "g")
        for rut, first, last in db.execute(select(TchClient.rut, TchClient.name, TchClient.last_name).where(key_sql.in_(keys))):
            names.setdefault(_rut_key(rut), _join_name(first, last))
    return {f: (rut, names.get(_rut_key(rut))) for f, rut in ruts.items()}


def attach_people(db: Session, source: str, result: dict[str, Any], include_pii: bool) -> dict[str, Any]:
    """Agrega `rut` y `name` a cada fila (por `subscription_id`) y `pii_included` al resultado. Sin permiso: `null`."""
    items: Iterable[dict[str, Any]] = result.get("items") or []
    people: dict[str, tuple[str | None, str | None]] = {}
    if include_pii:
        sub_ids = sorted({str(i["subscription_id"]) for i in items if i.get("subscription_id")})
        if sub_ids:
            people = _tch_people(db, sub_ids) if source == "tch" else _crm_people(db, source, sub_ids)
    for item in result.get("items") or []:
        rut, name = people.get(str(item.get("subscription_id") or ""), (None, None))
        item["rut"] = rut if include_pii else None
        item["name"] = name if include_pii else None
    result["pii_included"] = include_pii
    return result


__all__ = ["PII_PERMISSIONS", "attach_people", "can_view_pii"]
