"""Controles de consistencia de la Opcion A (BILL-10, GB-CS-02..14) y cola de reconciliacion (GB-CS-09).

Diseno: docs/designs/facturacion-gestionada-escenarios.md, seccion "Consistencia" (CS-xx) y criterios del piloto (PI-05).

SOLO LECTURA: los controles leen unicamente tablas locales (`vp_charges`, `vp_payments`, `charges`, `vp_subscriptions` /
`subscriptions`, `vp_managed_charges`, `vp_calendar_marks`, `billing_change_requests` y sus eventos,
`billing_renewal_tasks`, `write_runs`). No importan ningun cliente del proveedor, no reponen, no cancelan y no escriben:
devuelven hallazgos (`Finding`) que el job diario manda al log y la API muestra. Los datos del proveedor son los de la
ultima sincronizacion (el listado de suscripciones no trae `internal_code`, VP-C28: los cobros del CRM se reconocen por
`charge_id` en `vp_managed_charges`, CS-05).

Alcance: suscripciones "gestionadas" = con marca de calendario activa o con cobros vivos del CRM en `vp_managed_charges`.
Los cobros puntuales (`one_off_charge`) conviven con el pendiente del mes (CO-01) y no cuentan como doble pendiente.

Controles (escenario -> codigo de hallazgo):
- CS-02 `amount_mismatch`: pendiente del horizonte con monto distinto del programado en la marca.
- CS-03 `double_pending` (P0, BLOQUEA): un mes con dos o mas pendientes. `imminent` si el primero cae en <= 3 dias (D-3).
  `has_double_pending` lo usa `billing_requests.prepare_request` para bloquear nuevos cambios hasta resolverlo.
- CS-04 `missing_month` / `overdue_pending`: mes del horizonte sin pendiente ni cobro que lo cubra, o pendiente vencido.
  El CRM NO repone: se resuelve con una solicitud aprobada.
- CS-05 `managed_not_synced`: cobro del CRM que tras `SYNC_GRACE_HOURS` aun no aparece en la base. Los duplicados en
  `vp_charges`/`charges` ya los impide el esquema (UNIQUE por plataforma/fuente + `external_id`): no hace falta control.
- CS-06 `unregistered_charge` (P0): cargo no cancelado en un mes gestionado que no esta en el registro propio (posible doble
  cobro, p. ej. creado desde el panel de VP). No se cancela automaticamente.
- CS-07 `managed_cancelled_externally`: cobro vivo del CRM que la base ya ve cancelado (hueco). No se repone.
- CS-08 `subscription_not_active`: suscripcion no ACTIVA con solicitud abierta, tarea de renovacion abierta o marca activa.
- CS-09 `reconciliation_required` (P0, BLOQUEA): solicitud, cobro del CRM o `write_run` en conciliacion (ver
  `reconciliation_queue`); `stale` si lleva mas de 24 h (criterio de abort del piloto, PI-05).
- CS-10 `payment_amount_mismatch`: cuota pagada cuyo pago enlazado tiene otro monto.
- CS-11 `double_paid` (P0): dos cobros pagados en el mismo mes (devolucion manual: no hay endpoint de reembolso).
- CS-12: el desempate determinista por `external_id` ya esta cubierto en `vp_current_amount` (sin control propio).
- CS-13 `current_amount_family_mismatch`: `load_current_amount` da distinto en la familia `vp` y en la `crm`.
- CS-14 `managed_without_approval` (P0) / `reverted_to_old_amount` (P0): cobro del CRM sin solicitud aprobada asociada;
  calendario modificado cuyo horizonte termino y que ya cobro un mes con otro monto (JB-31).

Sin PII: los hallazgos llevan plataforma, id de suscripcion, mes, ids de cargo y montos.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from app.models.billing import (
    EVENT_APPROVED,
    EVENT_AUTO_APPROVED,
    MANAGED_CREATED,
    MANAGED_NEEDS_RECONCILIATION,
    STATUS_NEEDS_RECONCILIATION,
    TASK_OPEN,
    TASK_OVERDUE,
    BillingChangeRequest,
    BillingChangeRequestEvent,
    BillingRenewalTask,
    VpCalendarMark,
    VpManagedCharge,
)
from app.models.crm import Subscription
from app.models.vp import VpCharge, VpPayment, VpSubscription
from app.models.write_run import WriteRun
from app.services.billing_plan import (
    CANCELLED_STATES,
    PENDING_STATES,
    is_one_off_code,
    norm_state,
)
from app.services.rejected_month import CHILE_TZ, now_chile
from app.services.vp_current_amount import load_current_amount, parse_amount

log = logging.getLogger(__name__)

P0, P1, P2 = "P0", "P1", "P2"
PAID_STATES = frozenset({"pagado", "paid"})
COVERING_STATES = frozenset({"pagado", "paid", "procesando", "processing", "rechazado", "rejected"})
IMMINENT_DAYS = 3  # CS-03: control D-3 antes de charge_date
SYNC_GRACE_HOURS = 48  # CS-05: un cobro del CRM deberia aparecer en la base tras la siguiente sync
RECONCILIATION_STALE_HOURS = 24  # PI-05: 0 reconciliation_required abiertos mas de 24 h
OPEN_REQUEST_STATUSES = ("pendiente", "aprobada", "aplicando", STATUS_NEEDS_RECONCILIATION)
ALIVE_MANAGED = (MANAGED_CREATED, MANAGED_NEEDS_RECONCILIATION)


@dataclass(frozen=True)
class Finding:
    scenario: str  # p. ej. "GB-CS-03"
    code: str
    severity: str  # P0 / P1 / P2
    platform: str
    subscription_external_id: str
    month: str | None = None
    blocks: bool = False  # bloquea nuevos cambios de la suscripcion hasta resolverlo
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"scenario": self.scenario, "code": self.code, "severity": self.severity, "platform": self.platform,
                "subscription_external_id": self.subscription_external_id, "month": self.month, "blocks": self.blocks,
                "detail": self.detail}


@dataclass
class ConsistencyReport:
    generated_at: datetime
    today: date
    subscriptions_checked: int = 0
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings

    def counts(self) -> dict[str, int]:
        return dict(sorted(Counter(f.code for f in self.findings).items()))

    def by_severity(self) -> dict[str, int]:
        return dict(sorted(Counter(f.severity for f in self.findings).items()))

    def as_dict(self) -> dict[str, Any]:
        return {"generated_at": self.generated_at.isoformat(), "today": self.today.isoformat(), "ok": self.ok,
                "subscriptions_checked": self.subscriptions_checked, "counts": self.counts(),
                "by_severity": self.by_severity(), "findings": [f.as_dict() for f in self.findings]}


# ----------------------------- lectura -----------------------------


@dataclass(frozen=True)
class _LocalCharge:
    charge_id: str
    month: str
    charge_date: date
    amount: Decimal | None
    state: str


def _month(d: date) -> str:
    return d.strftime("%Y-%m")


def _to_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _num(value: Decimal | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


def _local_charges(db: Session, keys: set[tuple[str, str]]) -> dict[tuple[str, str], list[_LocalCharge]]:
    out: dict[tuple[str, str], list[_LocalCharge]] = defaultdict(list)
    if not keys:
        return out
    rows = db.execute(select(VpCharge.platform, VpCharge.subscription_external_id, VpCharge.external_id, VpCharge.charge_date,
                             VpCharge.amount, VpCharge.status)
                      .where(tuple_(VpCharge.platform, VpCharge.subscription_external_id).in_(list(keys))))
    for platform, sub, cid, raw_date, amount, status in rows:
        d = _to_date(raw_date)
        if d is None or not cid:
            continue
        out[(platform, sub)].append(_LocalCharge(str(cid), _month(d), d, parse_amount(amount), norm_state(status)))
    return out


def _managed_keys(db: Session) -> set[tuple[str, str]]:
    marks = db.execute(select(VpCalendarMark.platform, VpCalendarMark.subscription_external_id)
                       .where(VpCalendarMark.is_active.is_(True)))
    managed = db.execute(select(VpManagedCharge.platform, VpManagedCharge.subscription_external_id)
                         .where(VpManagedCharge.status.in_(ALIVE_MANAGED)).distinct())
    return {(p, s) for p, s in marks} | {(p, s) for p, s in managed}


def _one_off_request_ids(db: Session, request_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    if not request_ids:
        return set()
    return set(db.scalars(select(BillingChangeRequest.id).where(
        BillingChangeRequest.id.in_(request_ids), BillingChangeRequest.request_type == "one_off_charge")))


def _subscription_status(db: Session, platform: str, sub: str) -> str | None:
    """Igual que `billing_apply._subscription_state` (vp_subscriptions y luego subscriptions), sin importar ese modulo:
    este servicio no depende de nada que hable con el proveedor."""
    row = db.execute(select(VpSubscription.status).where(
        VpSubscription.platform == platform, VpSubscription.external_id == sub)).first()
    if row is None:
        row = db.execute(select(Subscription.status).where(
            Subscription.source == platform, Subscription.external_id == sub)).first()
    return row[0] if row else None


def _is_active(status: str | None) -> bool:
    return norm_state(status) in ("activa", "activo", "active")


# ----------------------------- controles por suscripcion -----------------------------


def _attribute(charges: list[_LocalCharge], origin: dict[str, str]) -> list[_LocalCharge]:
    """DEC-30 (BILL-18): un cobro del CRM cuenta para el mes de su `internal_code` (guardado en `vp_managed_charges.month`),
    no para el de su fecha. El reemplazo de un mes atrasado fechado al mes siguiente no es un doble pendiente de ese mes."""
    out = []
    for c in charges:
        month = origin.get(c.charge_id)
        out.append(replace(c, month=month) if month and month != c.month else c)
    return out


def _pending_by_month(charges: list[_LocalCharge], one_off: set[str]) -> dict[str, list[_LocalCharge]]:
    out: dict[str, list[_LocalCharge]] = defaultdict(list)
    for c in charges:
        if c.state in PENDING_STATES and c.charge_id not in one_off:
            out[c.month].append(c)
    return out


def _double_pending(platform: str, sub: str, charges: list[_LocalCharge], one_off: set[str], today: date) -> list[Finding]:
    """CS-03: meses actuales o futuros con dos o mas pendientes (sin contar cobros puntuales del CRM)."""
    out = []
    for month, rows in sorted(_pending_by_month(charges, one_off).items()):
        if len(rows) < 2 or month < _month(today):
            continue
        first = min(r.charge_date for r in rows)
        out.append(Finding("GB-CS-03", "double_pending", P0, platform, sub, month, blocks=True, detail={
            "count": len(rows), "charge_ids": sorted(r.charge_id for r in rows),
            "imminent": (first - today).days <= IMMINENT_DAYS}))
    return out


def has_double_pending(db: Session, platform: str, sub: str, today: date | None = None) -> bool:
    """CS-03 para UNA suscripcion con los datos locales (lo usa la creacion de solicitudes para bloquear)."""
    today = today or now_chile().date()
    charges = _local_charges(db, {(platform, sub)}).get((platform, sub), [])
    if not charges:
        return False
    managed = list(db.execute(select(VpManagedCharge.charge_id, VpManagedCharge.internal_code, VpManagedCharge.request_id,
                                     VpManagedCharge.month)
                              .where(VpManagedCharge.platform == platform, VpManagedCharge.subscription_external_id == sub)))
    one_off_reqs = _one_off_request_ids(db, {r for _c, _i, r, _m in managed if r is not None})
    one_off = {c for c, code, r, _m in managed if is_one_off_code(code) or r in one_off_reqs}
    charges = _attribute(charges, {c: m for c, _i, _r, m in managed if m})
    return bool(_double_pending(platform, sub, charges, one_off, today))


def _check_subscription(
    db: Session, platform: str, sub: str, *, mark: VpCalendarMark | None, managed: list[VpManagedCharge],
    charges: list[_LocalCharge], one_off_reqs: set[uuid.UUID], approved_reqs: set[uuid.UUID],
    payments: dict[str, list[Decimal | None]], today: date, now_utc: datetime,
) -> list[Finding]:
    out: list[Finding] = []
    one_off = {m.charge_id for m in managed if is_one_off_code(m.internal_code) or m.request_id in one_off_reqs}
    charges = _attribute(charges, {m.charge_id: m.month for m in managed if m.month})
    by_id = {c.charge_id: c for c in charges}
    current = _month(today)

    # CS-02 / CS-04 (horizonte de la marca activa)
    if mark is not None:
        scheduled = Decimal(mark.scheduled_amount)
        last = mark.last_scheduled_month
        in_horizon = [c for c in charges if current <= c.month <= last]
        for c in in_horizon:
            if c.state in PENDING_STATES and c.charge_id not in one_off and c.amount is not None and c.amount != scheduled:
                out.append(Finding("GB-CS-02", "amount_mismatch", P0, platform, sub, c.month, detail={
                    "charge_id": c.charge_id, "amount": _num(c.amount), "scheduled_amount": _num(scheduled)}))
        months, y, m = [], int(current[:4]), int(current[5:7])
        while f"{y:04d}-{m:02d}" <= last and len(months) < 120:
            months.append(f"{y:04d}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        for month in months:
            rows = [c for c in in_horizon if c.month == month and c.state not in CANCELLED_STATES]
            if not any(c.state in PENDING_STATES or c.state in COVERING_STATES for c in rows):
                out.append(Finding("GB-CS-04", "missing_month", P0, platform, sub, month))
        for c in charges:
            if c.state in PENDING_STATES and c.charge_date < today and c.month <= last:
                out.append(Finding("GB-CS-04", "overdue_pending", P0, platform, sub, c.month, detail={
                    "charge_id": c.charge_id, "charge_date": c.charge_date.isoformat()}))

    # CS-03
    out.extend(_double_pending(platform, sub, charges, one_off, today))

    # CS-05 (no sincronizado) / CS-07 (cancelado desde el panel)
    for m in managed:
        if m.status not in ALIVE_MANAGED:
            continue
        local = by_id.get(m.charge_id)
        created = m.created_at.replace(tzinfo=UTC) if m.created_at and m.created_at.tzinfo is None else m.created_at
        if local is None:
            if created is not None and now_utc - created > timedelta(hours=SYNC_GRACE_HOURS):
                out.append(Finding("GB-CS-05", "managed_not_synced", P1, platform, sub, m.month,
                                   detail={"charge_id": m.charge_id}))
        elif local.state in CANCELLED_STATES and m.status == MANAGED_CREATED:
            out.append(Finding("GB-CS-07", "managed_cancelled_externally", P1, platform, sub, m.month,
                               detail={"charge_id": m.charge_id}))

    # CS-06: cargo ajeno en un mes gestionado
    registered = {m.charge_id for m in managed}
    managed_months = {m.month for m in managed if m.status in ALIVE_MANAGED and m.charge_id not in one_off}
    for c in charges:
        if c.month in managed_months and c.charge_id not in registered and c.state not in CANCELLED_STATES:
            out.append(Finding("GB-CS-06", "unregistered_charge", P0, platform, sub, c.month, detail={
                "charge_id": c.charge_id, "state": c.state[:30], "amount": _num(c.amount)}))

    # CS-10 / CS-11: cuadratura de pagados
    paid = [c for c in charges if c.state in PAID_STATES]
    for c in paid:
        linked = payments.get(c.charge_id)
        if linked and c.amount is not None and not any(a == c.amount for a in linked if a is not None):
            out.append(Finding("GB-CS-10", "payment_amount_mismatch", P1, platform, sub, c.month, detail={
                "charge_id": c.charge_id, "charge_amount": _num(c.amount),
                "payment_amounts": sorted({_num(a) for a in linked if a is not None})}))
    paid_by_month: dict[str, list[_LocalCharge]] = defaultdict(list)
    for c in paid:
        if c.charge_id not in one_off:
            paid_by_month[c.month].append(c)
    for month, rows in sorted(paid_by_month.items()):
        if len(rows) >= 2:
            out.append(Finding("GB-CS-11", "double_paid", P0, platform, sub, month, detail={
                "count": len(rows), "charge_ids": sorted(r.charge_id for r in rows)}))

    # CS-14: cobro del CRM sin solicitud aprobada / vuelta al monto antiguo tras el horizonte
    for m in managed:
        if m.request_id is None or m.request_id not in approved_reqs:
            out.append(Finding("GB-CS-14", "managed_without_approval", P0, platform, sub, m.month, detail={
                "charge_id": m.charge_id, "request_id": str(m.request_id) if m.request_id else None}))
    if mark is not None and today > mark.last_scheduled_date:
        scheduled = Decimal(mark.scheduled_amount)
        for c in paid:
            if c.month > mark.last_scheduled_month and c.amount is not None and c.amount != scheduled:
                out.append(Finding("GB-CS-14", "reverted_to_old_amount", P0, platform, sub, c.month, detail={
                    "charge_id": c.charge_id, "amount": _num(c.amount), "scheduled_amount": _num(scheduled)}))
    return out


# ----------------------------- controles globales -----------------------------


def _not_active(db: Session, keys: set[tuple[str, str]], marks: dict[tuple[str, str], VpCalendarMark]) -> list[Finding]:
    """CS-08: suscripcion no ACTIVA (cancelada en el panel) que sigue con solicitud, tarea o marca abierta."""
    out: list[Finding] = []
    open_reqs = {(p, s) for p, s in db.execute(select(BillingChangeRequest.platform, BillingChangeRequest.subscription_external_id)
                                               .where(BillingChangeRequest.status.in_(OPEN_REQUEST_STATUSES)))}
    open_tasks = {(p, s) for p, s in db.execute(select(BillingRenewalTask.platform, BillingRenewalTask.subscription_external_id)
                                                .where(BillingRenewalTask.status.in_((TASK_OPEN, TASK_OVERDUE))))}
    for key in sorted(keys | open_reqs | open_tasks):
        status = _subscription_status(db, *key)
        if status is None or _is_active(status):
            continue
        out.append(Finding("GB-CS-08", "subscription_not_active", P0, key[0], key[1], detail={
            "status": norm_state(status)[:30], "open_request": key in open_reqs, "open_renewal_task": key in open_tasks,
            "active_mark": key in marks}))
    return out


def _family_mismatch(db: Session, keys: set[tuple[str, str]], today: date) -> list[Finding]:
    """CS-13: el monto vigente debe ser igual en las tablas `vp_*` y en las centralizadas."""
    out: list[Finding] = []
    if not keys:
        return out
    subs = sorted({s for _p, s in keys})
    sources = sorted({p for p, _s in keys})
    vp = load_current_amount(db, family="vp", sources=sources, today=today, subscription_ids=subs)
    crm = load_current_amount(db, family="crm", sources=sources, today=today, subscription_ids=subs)
    for key in sorted(keys):
        a, b = vp.get(key), crm.get(key)
        if a is not None and b is not None and a != b:
            out.append(Finding("GB-CS-13", "current_amount_family_mismatch", P2, key[0], key[1], detail={
                "vp": _num(a), "crm": _num(b)}))
    return out


# ----------------------------- cola de reconciliacion (CS-09) -----------------------------


@dataclass(frozen=True)
class QueueItem:
    kind: str  # request / managed_charge / write_run
    id: str
    platform: str
    subscription_external_id: str
    since: datetime | None
    request_id: str | None = None
    charge_id: str | None = None
    month: str | None = None
    stale: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "id": self.id, "platform": self.platform,
                "subscription_external_id": self.subscription_external_id,
                "since": self.since.isoformat() if self.since else None, "request_id": self.request_id,
                "charge_id": self.charge_id, "month": self.month, "stale": self.stale}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def reconciliation_queue(db: Session, now: datetime | None = None) -> list[QueueItem]:
    """Todo lo que quedo en conciliacion (solicitudes, cobros del CRM y `write_runs` de la Opcion A). SOLO LECTURA.

    Cada elemento bloquea su suscripcion (los cobros via `billing_apply.is_subscription_blocked`, las solicitudes via el
    indice de una abierta por suscripcion). `stale` = mas de 24 h abierto (abort del piloto, PI-05)."""
    now_utc = _aware(now) or datetime.now(UTC)
    cutoff = now_utc - timedelta(hours=RECONCILIATION_STALE_HOURS)

    def stale(since: datetime | None) -> bool:
        since = _aware(since)
        return since is not None and since < cutoff

    items: list[QueueItem] = []
    for r in db.scalars(select(BillingChangeRequest).where(BillingChangeRequest.status == STATUS_NEEDS_RECONCILIATION)
                        .order_by(BillingChangeRequest.updated_at, BillingChangeRequest.id)):
        items.append(QueueItem("request", str(r.id), r.platform, r.subscription_external_id, _aware(r.updated_at),
                               request_id=str(r.id), stale=stale(r.updated_at)))
    for m in db.scalars(select(VpManagedCharge).where(VpManagedCharge.status == MANAGED_NEEDS_RECONCILIATION)
                        .order_by(VpManagedCharge.updated_at, VpManagedCharge.id)):
        items.append(QueueItem("managed_charge", str(m.id), m.platform, m.subscription_external_id, _aware(m.updated_at),
                               request_id=str(m.request_id) if m.request_id else None, charge_id=m.charge_id,
                               month=m.month, stale=stale(m.updated_at)))
    runs = db.execute(select(WriteRun.id, WriteRun.source, WriteRun.external_id, WriteRun.request_id,
                             func.coalesce(WriteRun.finished_at, WriteRun.started_at))
                      .join(BillingChangeRequest, BillingChangeRequest.id == WriteRun.request_id)
                      .where(WriteRun.status == "reconciliation_required",
                             BillingChangeRequest.status != STATUS_NEEDS_RECONCILIATION)
                      .order_by(WriteRun.started_at, WriteRun.id))
    for run_id, source, external_id, request_id, when in runs:
        items.append(QueueItem("write_run", str(run_id), source, external_id, _aware(when),
                               request_id=str(request_id), stale=stale(when)))
    return items


def _queue_findings(items: list[QueueItem]) -> list[Finding]:
    return [Finding("GB-CS-09", "reconciliation_required", P0, i.platform, i.subscription_external_id, i.month,
                    blocks=True, detail={"kind": i.kind, "id": i.id, "request_id": i.request_id, "stale": i.stale})
            for i in items]


# ----------------------------- corrida -----------------------------


def run_consistency_checks(db: Session, now: datetime | None = None) -> ConsistencyReport:
    """Ejecuta CS-02..CS-14 sobre las suscripciones gestionadas. SOLO LECTURA (no hace commit ni escribe)."""
    chile_now = now_chile() if now is None else (now if now.tzinfo else now.replace(tzinfo=CHILE_TZ)).astimezone(CHILE_TZ)
    today = chile_now.date()
    now_utc = chile_now.astimezone(UTC)
    report = ConsistencyReport(generated_at=now_utc, today=today)

    keys = _managed_keys(db)
    marks = {(m.platform, m.subscription_external_id): m
             for m in db.scalars(select(VpCalendarMark).where(VpCalendarMark.is_active.is_(True)))}
    managed_by_key: dict[tuple[str, str], list[VpManagedCharge]] = defaultdict(list)
    if keys:
        for m in db.scalars(select(VpManagedCharge).where(
                tuple_(VpManagedCharge.platform, VpManagedCharge.subscription_external_id).in_(list(keys)))
                .order_by(VpManagedCharge.month, VpManagedCharge.charge_id)):
            managed_by_key[(m.platform, m.subscription_external_id)].append(m)
    request_ids = {m.request_id for rows in managed_by_key.values() for m in rows if m.request_id is not None}
    one_off_reqs = _one_off_request_ids(db, request_ids)
    approved_reqs = set(db.scalars(select(BillingChangeRequestEvent.request_id).where(
        BillingChangeRequestEvent.request_id.in_(request_ids),
        BillingChangeRequestEvent.event_type.in_((EVENT_APPROVED, EVENT_AUTO_APPROVED))))) if request_ids else set()
    charges_by_key = _local_charges(db, keys)
    paid_ids = {c.charge_id for rows in charges_by_key.values() for c in rows if c.state in PAID_STATES}
    payments: dict[str, list[Decimal | None]] = defaultdict(list)
    if paid_ids:
        for cid, amount in db.execute(select(VpPayment.charge_external_id, VpPayment.amount)
                                      .where(VpPayment.charge_external_id.in_(paid_ids))):
            payments[str(cid)].append(parse_amount(amount))

    for key in sorted(keys):
        report.subscriptions_checked += 1
        report.findings.extend(_check_subscription(
            db, key[0], key[1], mark=marks.get(key), managed=managed_by_key.get(key, []),
            charges=charges_by_key.get(key, []), one_off_reqs=one_off_reqs, approved_reqs=approved_reqs,
            payments=payments, today=today, now_utc=now_utc))
    report.findings.extend(_not_active(db, keys, marks))
    report.findings.extend(_family_mismatch(db, keys, today))
    report.findings.extend(_queue_findings(reconciliation_queue(db, now_utc)))
    return report


def blocked_subscriptions(report: ConsistencyReport) -> set[tuple[str, str]]:
    return {(f.platform, f.subscription_external_id) for f in report.findings if f.blocks}


__all__ = [
    "ConsistencyReport",
    "Finding",
    "QueueItem",
    "blocked_subscriptions",
    "has_double_pending",
    "reconciliation_queue",
    "run_consistency_checks",
]
