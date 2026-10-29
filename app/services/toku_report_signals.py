"""Estado y senales de suscripcion de Toku desde los reportes (TK-PAR-06 y TK-20, DEC-16 a DEC-25).

Lee `tk_report_products`, `tk_report_payment_methods`, `tk_report_attempts` y `tk_report_debts` (sin datos personales) y
escribe `core_subscription_signals` (una fila por suscripcion core de Toku con fila en el reporte de Productos) mas el
`status` de `core_subscriptions` (reporte > API para estado, DEC-23).

Definiciones
------------
* Ciclo de vida: `deleted` si el producto tiene fecha de eliminacion; si no, `active`.
* Estado del medio de pago: fila de Medios de pago (con fecha de eliminacion -> `deleted`); si no hay, el `Estado` del
  producto. «Cobrable» = `chargeable`. **Suscripcion activa efectiva** = `active` y cobrable (DEC-18).
* Una **cuota** es una deuda (`in_`). Esta *pagada* si algun intento fue AUTORIZADO o la deuda esta pagada; se ignora si
  esta anulada; esta *en proceso* si tiene un intento EN PROCESO; esta *impaga en firme* si no esta pagada y (algun
  intento termino con codigo 2070, o el ultimo intento fue hace `firm_after_days` dias o mas respecto al corte, o nunca
  hubo intento y su vencimiento fue hace `firm_after_days` dias o mas). El resto (reintentos aun posibles) no cuenta.
* **Racha** (`consecutive_failed_debts`) = cuotas impagas en firme seguidas, de la mas nueva hacia atras, ignorando las
  que aun pueden reintentarse y las en proceso; una cuota pagada corta la racha. NO es la racha de intentos
  (`consecutive_failed_attempts`, solo informativa): 3 intentos de una sola cuota no son una racha de 3 (72 suscripciones
  por cuotas contra 138 por intentos en los datos reales).
* **Tarjeta bloqueada**: el ultimo intento fallo con 1019, 1051 o 2043 (y no hubo un pago despues), o el medio es
  `permanent_failed`. **Vencida**: el ultimo intento fallo con 1010, 2044 o 2063. Un medio con falla temporal sin racha no
  es recuperable (DEC-25).
* **Recuperable** = suscripcion `active` y (bloqueada, vencida o racha >= 3). Si varias aplican, el motivo es el primero
  de: `blocked_card`, `expired_card`, `streak`.
* Corte (`as_of`): la fecha de generacion mas reciente entre los reportes cargados (el dato es una foto de ese dia).

Estado de `core_subscriptions.status` (reporte > API): eliminada en el reporte -> `deleted_at_source`; viva con estado de
la API vacio -> `ACTIVE`; ACTIVE/PAUSED de la API se respetan (el reporte no conoce las pausas).

Solo corre por el ETL core con `TOKU_REPORT_SIGNALS_ENABLED=true` (apagada por defecto). `dry_run=True` calcula los mismos
contadores sin escribir. No imprime ni guarda datos personales.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.core import CoreSubscription
from app.models.toku_report import (
    CoreSubscriptionSignal,
    TkReportAttempt,
    TkReportDebt,
    TkReportPaymentMethod,
    TkReportProduct,
)

BLOCKED_CODES = frozenset({"1019", "1051", "2043"})
EXPIRED_CODES = frozenset({"1010", "2044", "2063"})
FIRM_CODE = "2070"
STREAK_THRESHOLD = 3
DEFAULT_FIRM_AFTER_DAYS = 7
_SOURCE = "toku"
_BATCH = 500


def _norm(value: str | None) -> str:
    return (value or "").strip().casefold()


def _is_paid(status: str | None) -> bool:
    return _norm(status) in {"autorizado", "authorized", "paid", "pagado"}


def _is_failed(status: str | None) -> bool:
    return _norm(status) in {"fallido", "failed", "rechazado"}


def _is_in_process(status: str | None) -> bool:
    return _norm(status) in {"en proceso", "processing", "in process", "pending"}


@dataclass
class _Cuota:
    due: date | None = None
    paid: bool = False
    voided: bool = False
    in_process: bool = False
    firm_code: bool = False
    last_attempt: datetime | None = None
    has_attempt: bool = False
    tiebreak: str = ""

    def is_firm(self, as_of: datetime, days: int) -> bool:
        if self.paid or self.voided or self.in_process:
            return False
        if self.firm_code:
            return True
        threshold = timedelta(days=days)
        if self.last_attempt is not None:
            return as_of - self.last_attempt >= threshold
        if self.due is not None:  # sin ningun intento: «tras cierto numero de dias» desde el vencimiento
            return as_of.date() - self.due >= threshold
        return False


@dataclass
class _SubData:
    attempts: list[Any] = field(default_factory=list)
    cuotas: dict[str, _Cuota] = field(default_factory=dict)


def _cuota(data: _SubData, debt_id: str) -> _Cuota:
    c = data.cuotas.get(debt_id)
    if c is None:
        c = data.cuotas[debt_id] = _Cuota(tiebreak=debt_id)
    return c


def _min_date(a: date | None, b: date | None) -> date | None:
    return b if a is None else a if b is None else min(a, b)


def _load_as_of(db: Session) -> datetime:
    latest = [
        db.scalar(select(func.max(model.source_generated_at)))
        for model in (TkReportAttempt, TkReportDebt, TkReportProduct)
    ]
    latest = [v for v in latest if v is not None]
    return max(latest) if latest else datetime.now(UTC)


def _payment_method_index(db: Session) -> dict[str, list[Any]]:
    index: dict[str, list[Any]] = defaultdict(list)
    for row in db.execute(
        select(
            TkReportPaymentMethod.payment_method_external_id,
            TkReportPaymentMethod.product_key_hash,
            TkReportPaymentMethod.status,
            TkReportPaymentMethod.deleted_at_source,
            TkReportPaymentMethod.source_generated_at,
        )
    ):
        index[row.payment_method_external_id].append(row)
    return index


def _payment_method_status(product: Any, index: dict[str, list[Any]]) -> str | None:
    rows = index.get(product.payment_method_external_id or "") or []
    if rows:
        same = [r for r in rows if r.product_key_hash == product.product_key_hash]
        best = max(same or rows, key=lambda r: r.source_generated_at)
        if best.deleted_at_source is not None:
            return "deleted"
        if best.status:
            return _norm(best.status)
    return _norm(product.payment_method_status) or None


def _load_subscription_data(db: Session) -> dict[str, _SubData]:
    data: dict[str, _SubData] = defaultdict(_SubData)
    attempts = db.execute(
        select(
            TkReportAttempt.subscription_external_id,
            TkReportAttempt.debt_external_id,
            TkReportAttempt.attempted_at,
            TkReportAttempt.status,
            TkReportAttempt.response_code,
            TkReportAttempt.severity,
            TkReportAttempt.due_date,
        ).where(
            TkReportAttempt.subscription_external_id.is_not(None),
            TkReportAttempt.deleted_at_source.is_(None),
        )
    )
    for a in attempts:
        sub = data[a.subscription_external_id]
        sub.attempts.append(a)
        c = _cuota(sub, a.debt_external_id)
        c.due = _min_date(c.due, a.due_date)
        c.has_attempt = True
        if _is_paid(a.status):
            c.paid = True
        elif _is_in_process(a.status):
            c.in_process = True
        elif _is_failed(a.status):
            if a.response_code == FIRM_CODE:
                c.firm_code = True
        if a.attempted_at is not None and (c.last_attempt is None or a.attempted_at > c.last_attempt):
            c.last_attempt = a.attempted_at
    debts = db.execute(
        select(
            TkReportDebt.subscription_external_id,
            TkReportDebt.debt_external_id,
            TkReportDebt.due_date,
            TkReportDebt.paid,
            TkReportDebt.voided,
        ).where(TkReportDebt.subscription_external_id.is_not(None), TkReportDebt.deleted_at_source.is_(None))
    )
    for d in debts:
        c = _cuota(data[d.subscription_external_id], d.debt_external_id)
        c.due = _min_date(c.due, d.due_date)
        c.paid = c.paid or bool(d.paid)
        c.voided = c.voided or bool(d.voided)
    return data


def _streak_of_cuotas(cuotas: dict[str, _Cuota], as_of: datetime, days: int) -> int:
    ordered = sorted(
        cuotas.values(),
        key=lambda c: (c.due or date.min, c.last_attempt or datetime.min.replace(tzinfo=UTC), c.tiebreak),
        reverse=True,
    )
    streak = 0
    for c in ordered:
        if c.voided:
            continue
        if c.paid:
            break
        if c.is_firm(as_of, days):
            streak += 1
        # en proceso o con reintentos aun posibles: ni cuenta ni corta la racha
    return streak


def _attempt_signals(attempts: list[Any]) -> dict[str, Any]:
    timed = sorted((a for a in attempts if a.attempted_at is not None), key=lambda a: a.attempted_at, reverse=True)
    failed_run = 0
    for a in timed:
        if _is_in_process(a.status):
            continue
        if _is_failed(a.status):
            failed_run += 1
        else:
            break
    last_failed = next((a for a in timed if _is_failed(a.status)), None)
    last_settled = next((a for a in timed if not _is_in_process(a.status)), None)
    last_failed_is_latest = last_failed is not None and last_settled is not None and last_failed is last_settled
    return {
        "consecutive_failed_attempts": failed_run,
        "last_attempt_at": timed[0].attempted_at if timed else None,
        "last_response_code": last_failed.response_code if last_failed else None,
        "last_response_severity": last_failed.severity if last_failed else None,
        "card_code": last_failed.response_code if last_failed_is_latest else None,
    }


def compute_report_signals(
    db: Session,
    *,
    as_of: datetime | None = None,
    firm_after_days: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Calcula y guarda las senales. Idempotente; devuelve solo contadores."""
    days = firm_after_days if firm_after_days is not None else settings.toku_report_firm_unpaid_days
    stats: dict[str, Any] = {
        "products_in_report": 0,
        "signals_written": 0,
        "no_core_subscription": 0,
        "active": 0,
        "effectively_active": 0,
        "recoverable": 0,
        "recoverable_by_reason": {"blocked_card": 0, "expired_card": 0, "streak": 0},
        "status_updated": 0,
        "dry_run": dry_run,
    }
    products = db.execute(
        select(
            TkReportProduct.subscription_external_id,
            TkReportProduct.product_key_hash,
            TkReportProduct.payment_method_external_id,
            TkReportProduct.payment_method_status,
            TkReportProduct.deleted_at_source,
            TkReportProduct.source_generated_at,
        )
    ).all()
    stats["products_in_report"] = len(products)
    if not products:
        return stats

    cutoff = as_of or _load_as_of(db)
    core = {
        r.external_id: r
        for r in db.execute(
            select(CoreSubscription.id, CoreSubscription.external_id, CoreSubscription.status).where(
                CoreSubscription.source == _SOURCE
            )
        )
    }
    pm_index = _payment_method_index(db)
    per_sub = _load_subscription_data(db)
    now = datetime.now(UTC)

    rows: list[dict[str, Any]] = []
    status_changes: list[tuple[Any, str]] = []
    for p in products:
        core_row = core.get(p.subscription_external_id)
        if core_row is None:
            stats["no_core_subscription"] += 1
            continue
        lifecycle = "deleted" if p.deleted_at_source is not None else "active"
        pm_status = _payment_method_status(p, pm_index)
        chargeable = pm_status == "chargeable"
        data = per_sub.get(p.subscription_external_id) or _SubData()
        att = _attempt_signals(data.attempts)
        streak = _streak_of_cuotas(data.cuotas, cutoff, days)
        blocked = att["card_code"] in BLOCKED_CODES or pm_status == "permanent_failed"
        expired = att["card_code"] in EXPIRED_CODES
        reason = (
            "blocked_card" if blocked else "expired_card" if expired else "streak" if streak >= STREAK_THRESHOLD else None
        )
        recoverable = lifecycle == "active" and reason is not None
        effective = lifecycle == "active" and chargeable
        rows.append({
            "subscription_id": core_row.id,
            "source": _SOURCE,
            "external_id": p.subscription_external_id,
            "lifecycle_status": lifecycle,
            "payment_method_status": pm_status,
            "is_chargeable": chargeable,
            "is_effectively_active": effective,
            "consecutive_failed_debts": streak,
            "consecutive_failed_attempts": att["consecutive_failed_attempts"],
            "last_attempt_at": att["last_attempt_at"],
            "last_response_code": att["last_response_code"],
            "last_response_severity": att["last_response_severity"],
            "recoverable_reason": reason if recoverable else None,
            "is_recoverable": recoverable,
            "report_generated_at": p.source_generated_at,
            "computed_at": now,
        })
        stats["active"] += lifecycle == "active"
        stats["effectively_active"] += effective
        if recoverable:
            stats["recoverable"] += 1
            stats["recoverable_by_reason"][reason] += 1
        # Estado de la suscripcion: reporte > API
        if lifecycle == "deleted" and core_row.status != "deleted_at_source":
            status_changes.append((core_row.id, "deleted_at_source"))
        elif lifecycle == "active" and not core_row.status:
            status_changes.append((core_row.id, "ACTIVE"))
    stats["signals_written"] = len(rows)
    stats["status_updated"] = len(status_changes)
    if dry_run:
        return stats

    for i in range(0, len(rows), _BATCH):
        stmt = insert(CoreSubscriptionSignal).values(rows[i : i + _BATCH])
        updatable = {
            k: stmt.excluded[k]
            for k in rows[0]
            if k not in ("subscription_id", "source", "external_id")
        }
        updatable["updated_at"] = now
        db.execute(stmt.on_conflict_do_update(constraint="uq_core_subscription_signals_subscription", set_=updatable))
    for sub_id, status in status_changes:
        db.execute(update(CoreSubscription).where(CoreSubscription.id == sub_id).values(status=status, updated_at=now))
    return stats
