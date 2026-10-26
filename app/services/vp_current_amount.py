"""Monto vigente de una suscripcion VirtualPOS.

En VirtualPOS el monto de una suscripcion de plan fijo no se puede editar, por lo
que el "monto de la suscripcion" en el CRM es el ULTIMO MONTO COBRADO:

* ``amount`` del ultimo cargo de la suscripcion con status ``pagado`` o
  ``procesando`` y ``charge_date <= hoy`` (hay cargos programados hasta 2031),
  el de ``charge_date`` mas reciente (desempate determinista por ``external_id``);
* si no existe ninguno (o su monto no es numerico): ``amount`` de la suscripcion
  y, en su defecto, el del plan.

``load_monto_vigente`` resuelve todo con UNA consulta agregada de cargos
(``DISTINCT ON``, PostgreSQL) mas una de suscripciones/planes: sin N+1.
Sirve tanto a las tablas VP (``vp_*``, columna ``platform``) como a las
centralizadas (``subscriptions``/``charges``/``plans``, columna ``source``).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.crm import Charge, Plan, Subscription
from app.models.vp import VpCharge, VpPlan, VpSubscription

VIGENTE_CHARGE_STATUSES: tuple[str, ...] = ("pagado", "procesando")

MontoVigenteMap = dict[tuple[str, str], Decimal]


def parse_amount(value: object) -> Decimal | None:
    """Parsea un monto guardado como texto; None si vacio o no numerico."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def pick_monto_vigente(
    charges: Iterable[tuple[str | None, str | None, str | None, object]],
    fallback: object = None,
    today: date | None = None,
) -> Decimal | None:
    """Version pura de la regla sobre ``(external_id, status, charge_date, amount)``.

    Util para quien ya tiene los cargos en memoria; ``load_monto_vigente`` aplica
    la misma regla en SQL.
    """
    cutoff = (today or datetime.now(tz=UTC).date()).isoformat()
    best: tuple[str, str, Decimal] | None = None
    for external_id, status, charge_date, amount in charges:
        if str(status or "").strip().lower() not in VIGENTE_CHARGE_STATUSES:
            continue
        day = str(charge_date or "")[:10]
        parsed = parse_amount(amount)
        if not day or day > cutoff or parsed is None:
            continue
        key = (str(charge_date), str(external_id or ""))
        if best is None or key > (best[0], best[1]):
            best = (key[0], key[1], parsed)
    return best[2] if best else parse_amount(fallback)


def load_monto_vigente(
    db: Session,
    *,
    family: Literal["vp", "crm"] = "vp",
    sources: Iterable[str] | None = None,
    today: date | None = None,
) -> MontoVigenteMap:
    """Mapa ``{(source, subscription_external_id): monto_vigente}``.

    ``family="vp"`` lee ``vp_charges``/``vp_subscriptions``/``vp_plans`` (columna
    ``platform``); ``family="crm"`` lee ``charges``/``subscriptions``/``plans``
    (columna ``source``). Las suscripciones sin cargo valido ni monto de
    suscripcion/plan quedan fuera del mapa.
    """
    if family == "vp":
        charge_m, sub_m, plan_m = VpCharge, VpSubscription, VpPlan
        src = "platform"
    else:
        charge_m, sub_m, plan_m = Charge, Subscription, Plan
        src = "source"
    charge_src = getattr(charge_m, src)
    sub_src = getattr(sub_m, src)
    plan_src = getattr(plan_m, src)
    source_list = list(sources) if sources is not None else None
    cutoff = (today or datetime.now(tz=UTC).date()).isoformat()

    result: MontoVigenteMap = {}

    # 1) Ultimo cargo cobrado por suscripcion (una sola consulta, DISTINCT ON).
    day = func.substr(charge_m.charge_date, 1, 10)
    charge_q = (
        select(charge_src, charge_m.subscription_external_id, charge_m.amount)
        .where(
            charge_m.subscription_external_id.isnot(None),
            charge_m.charge_date.isnot(None),
            func.lower(func.trim(charge_m.status)).in_(VIGENTE_CHARGE_STATUSES),
            day <= cutoff,
            charge_m.amount.op("~")(r"^\s*\d+(\.\d+)?\s*$"),
        )
        .distinct(charge_src, charge_m.subscription_external_id)
        .order_by(
            charge_src,
            charge_m.subscription_external_id,
            charge_m.charge_date.desc(),
            charge_m.external_id.desc(),
        )
    )
    if source_list is not None:
        charge_q = charge_q.where(charge_src.in_(source_list))
    for source, sub_id, amount in db.execute(charge_q):
        parsed = parse_amount(amount)
        if parsed is not None:
            result[(source, sub_id)] = parsed

    # 2) Fallback: monto de la suscripcion y, si falta, del plan (una consulta).
    plan_amounts: dict[tuple[str, str], str | None] = {}
    plan_q = select(plan_src, plan_m.external_id, plan_m.amount)
    if source_list is not None:
        plan_q = plan_q.where(plan_src.in_(source_list))
    for source, plan_id, amount in db.execute(plan_q):
        plan_amounts[(source, plan_id)] = amount

    sub_q = select(sub_src, sub_m.external_id, sub_m.amount, sub_m.plan_external_id)
    if source_list is not None:
        sub_q = sub_q.where(sub_src.in_(source_list))
    for source, sub_id, amount, plan_id in db.execute(sub_q):
        if (source, sub_id) in result:
            continue
        parsed = parse_amount(amount)
        if parsed is None and plan_id:
            parsed = parse_amount(plan_amounts.get((source, plan_id)))
        if parsed is not None:
            result[(source, sub_id)] = parsed
    return result
