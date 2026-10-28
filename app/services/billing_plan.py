"""Calculo PURO del plan de cambio de cobros VirtualPOS (opcion A). Sin I/O, sin BD, sin cliente.

Recibe cobros ya cargados y devuelve que crear / cancelar / dejar cubierto / revisar a mano.
Referencias: docs/designs/facturacion-gestionada-escenarios.md (decisiones 2026-10-28, CO-xx, RA-xx, JB-xx).

Reglas clave:
- Orden seguro (CO-11, RA-01): primero TODOS los 'create'; cada 'cancel' depende de todos los 'create'.
- Mes con cobro pagado/procesando/rechazado (o estado desconocido, conservador) = cubierto (CO-06..08, RZ-28).
- Solo se cancelan pendientes automaticos (sin internal_code) o manuales del CRM (is_crm), dentro del
  horizonte. Manuales ajenos y automaticos posteriores al horizonte quedan intactos (CO-14, hallazgo 2).
- Ventana de 31 dias (JB-03..06): fecha del mes ya pasada hace <= window_days -> reemplazo con fecha de
  manana (Chile); mas antigua -> manual_review. Varios meses atrasados se espacian un dia (JB-09).
- charge_day 29-31 se ajusta al ultimo dia del mes (CO-24): feb 2027 -> 28, feb 2028 -> 29.
- internal_code determinista `{sub}-{YYYYMM}-{amount}`; en cambio de fecha lleva sufijo `-d{DD}` (ver nota
  en `_code`): sin el, el codigo coincidiria con el del cobro viejo y write_virtualpos lo "adoptaria".
"""

from __future__ import annotations

import calendar
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from app.services.rejected_month import now_chile

RequestType = Literal["change_amount", "change_date", "renew_calendar", "one_off"]

PENDING_STATES = frozenset({"pendiente", "pending"})
CANCELLED_STATES = frozenset({"cancelado", "cancelada", "cancelled", "canceled"})
# internal_code que genera `build_one_off_plan`: `{sub}-T{tarea}-{YYYYMMDD}-{monto}` o `{sub}-{YYYYMMDD}-{monto}-oneoff`.
_ONE_OFF_CODE = re.compile(r"-T.+-\d{8}-\d+$|-\d{8}-\d+-oneoff$")


def norm_state(status: Any) -> str:
    """Normalizacion UNICA de estados del proveedor (strip + minusculas)."""
    return str(status or "").strip().lower()


def is_pending_status(status: Any) -> bool:
    return norm_state(status) in PENDING_STATES


def is_cancelled_status(status: Any) -> bool:
    return norm_state(status) in CANCELLED_STATES


def is_one_off_code(internal_code: str | None) -> bool:
    return bool(internal_code and _ONE_OFF_CODE.search(internal_code))
COVERING_STATES = frozenset({"pagado", "procesando", "rechazado"})
_COVER_ALIASES = {"paid": "pagado", "processing": "procesando", "rejected": "rechazado"}


@dataclass(frozen=True)
class PlanIssue:
    code: str
    message: str
    month: str | None = None


@dataclass(frozen=True)
class PlanCharge:
    """Cobro existente. Automatico = sin internal_code; manual = con internal_code; is_crm = lo creo el CRM."""

    charge_id: str | None
    status: str
    charge_date: date
    amount: int
    internal_code: str | None = None
    is_crm: bool = False
    is_one_off: bool = False  # cobro puntual por tarea: ajeno al calendario regular (ver `is_puntual`)

    @property
    def is_puntual(self) -> bool:
        """Puntual por bandera (solicitud one_off_charge de origen) o por el patron de internal_code de build_one_off_plan."""
        return self.is_one_off or is_one_off_code(self.internal_code)

    @property
    def is_manual(self) -> bool:
        return bool(self.internal_code)

    @property
    def month(self) -> str:
        return self.charge_date.strftime("%Y-%m")

    @property
    def state(self) -> str:
        return str(self.status or "").strip().lower()


@dataclass(frozen=True)
class PlanInput:
    request_type: RequestType
    subscription_external_id: str
    platform: str
    new_amount: int
    charges: tuple[PlanCharge, ...] = ()
    new_charge_day: int | None = None  # obligatorio en change_date
    charge_day: int | None = None  # dia propio actual; si falta se deduce del ultimo cargo
    effective_month: str | None = None  # 'YYYY-MM' inicio del horizonte; por defecto mes de hoy (Chile)
    horizon_months: int = 12
    window_days: int = 31
    previous_amount: int | None = None  # base del % de variacion; si falta se deduce de los pendientes
    today: date | None = None  # inyectable; por defecto now_chile().date()
    one_off_date: date | None = None  # solo one_off
    task_ref: str | None = None  # solo one_off: id de la tarea (internal_code propio, RA-29)


@dataclass(frozen=True)
class PlanAction:
    kind: Literal["create", "cancel"]
    month: str
    charge_date: date
    amount: int
    internal_code: str | None
    charge_id: str | None = None
    depends_on: tuple[str, ...] = ()  # internal_codes de los 'create' que deben haber terminado OK


@dataclass(frozen=True)
class CoveredMonth:
    month: str
    reason: str  # pagado | procesando | rechazado | unknown_status
    charge_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ManualReviewMonth:
    month: str
    target_date: date
    days_overdue: int
    reason: str = "older_than_window"


@dataclass(frozen=True)
class KeptCharge:
    month: str
    charge_id: str | None
    charge_date: date
    amount: int


@dataclass(frozen=True)
class PlanSummary:
    creates: int
    cancels: int
    covered_months: int
    manual_review_months: int
    unchanged_months: int
    affected_charges: int
    previous_amount: int | None
    new_amount: int
    amount_delta: int | None  # new - previous (por cobro)
    total_delta: int  # suma creados - suma cancelados
    variation_pct: float | None  # |new-previous|/previous*100 (fase 4: doble aprobacion >50%)
    horizon_start: str | None
    horizon_end: str | None


@dataclass(frozen=True)
class PlanResult:
    request_type: str
    subscription_external_id: str
    create: tuple[PlanAction, ...] = ()
    cancel: tuple[PlanAction, ...] = ()
    covered: tuple[CoveredMonth, ...] = ()
    manual_review: tuple[ManualReviewMonth, ...] = ()
    unchanged: tuple[str, ...] = ()
    kept_automatic_after_horizon: tuple[KeptCharge, ...] = ()
    kept_due_today: tuple[str, ...] = ()  # meses con un pendiente fechado HOY: no se toca (riesgo de doble cobro)
    warnings: tuple[PlanIssue, ...] = ()
    errors: tuple[PlanIssue, ...] = ()
    noop: bool = False
    summary: PlanSummary | None = None

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def ordered_actions(self) -> tuple[PlanAction, ...]:
        """Orden de ejecucion seguro: todos los create (por mes) y luego los cancel (por mes)."""
        return self.create + self.cancel


# ----------------------------- helpers -----------------------------


def _parse_month(value: str) -> tuple[int, int]:
    year_s, month_s = value.split("-")
    year, month = int(year_s), int(month_s)
    if not (1 <= month <= 12 and 1900 <= year <= 9999) or len(year_s) != 4 or len(month_s) != 2:
        raise ValueError(value)
    return year, month


def _add_months(ym: tuple[int, int], n: int) -> tuple[int, int]:
    idx = ym[0] * 12 + (ym[1] - 1) + n
    return idx // 12, idx % 12 + 1


def _fmt(ym: tuple[int, int]) -> str:
    return f"{ym[0]:04d}-{ym[1]:02d}"


def month_date(ym: tuple[int, int], charge_day: int) -> date:
    """Fecha del cobro del mes: charge_day ajustado al ultimo dia del mes (29-31 en meses cortos)."""
    return date(ym[0], ym[1], min(charge_day, calendar.monthrange(ym[0], ym[1])[1]))


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _code(sub: str, month: str, amount: int, day: int | None = None) -> str:
    """`{sub}-{YYYYMM}-{amount}` (default de write_virtualpos). Con `day` agrega `-d{DD}` (cambio de fecha)."""
    base = f"{sub}-{month.replace('-', '')}-{amount}"
    return f"{base}-d{day:02d}" if day is not None else base


def _issue(code: str, message: str, month: str | None = None) -> PlanIssue:
    return PlanIssue(code, message, month)


def _failed(inp: PlanInput, errors: list[PlanIssue]) -> PlanResult:
    return PlanResult(request_type=inp.request_type, subscription_external_id=inp.subscription_external_id,
                      errors=tuple(errors), summary=None)


def _validate(inp: PlanInput) -> list[PlanIssue]:
    errs: list[PlanIssue] = []
    if not _is_int(inp.new_amount) or inp.new_amount <= 0:
        errs.append(_issue("invalid_amount", "El monto debe ser un entero positivo (CO-28)."))
    for name, val in (("new_charge_day", inp.new_charge_day), ("charge_day", inp.charge_day)):
        if val is not None and (not _is_int(val) or not 1 <= val <= 31):
            errs.append(_issue("invalid_charge_day", f"{name} debe estar entre 1 y 31."))
    if not _is_int(inp.horizon_months) or inp.horizon_months < 1:
        errs.append(_issue("invalid_horizon", "horizon_months debe ser >= 1."))
    if not _is_int(inp.window_days) or inp.window_days < 0:
        errs.append(_issue("invalid_window", "window_days debe ser >= 0."))
    if inp.effective_month is not None:
        try:
            _parse_month(inp.effective_month)
        except (ValueError, AttributeError):
            errs.append(_issue("invalid_effective_month", "effective_month debe ser 'YYYY-MM'."))
    if inp.request_type == "change_date" and inp.new_charge_day is None:
        errs.append(_issue("missing_charge_day", "El cambio de fecha requiere new_charge_day."))
    if inp.request_type not in ("change_amount", "change_date", "renew_calendar", "one_off"):
        errs.append(_issue("invalid_request_type", f"request_type desconocido: {inp.request_type!r}."))
    return errs


def _resolve_charge_day(inp: PlanInput, today: date) -> int | None:
    """new_charge_day > charge_day propio > dia del ultimo cargo pagado/procesando (<= hoy) > ultimo cargo."""
    if inp.new_charge_day is not None:
        return inp.new_charge_day
    if inp.charge_day is not None:
        return inp.charge_day
    live = [c for c in inp.charges if c.state not in CANCELLED_STATES and not c.is_puntual]
    paid = [c for c in live if _COVER_ALIASES.get(c.state, c.state) in ("pagado", "procesando") and c.charge_date <= today]
    pool = paid or live
    return max(pool, key=lambda c: c.charge_date).charge_date.day if pool else None


def _cover_reason(state: str) -> str:
    state = _COVER_ALIASES.get(state, state)
    return state if state in COVERING_STATES else "unknown_status"


# ----------------------------- nucleo mensual -----------------------------


def _plan_months(inp: PlanInput, mode: Literal["amount", "date"], start: tuple[int, int], today: date) -> PlanResult:
    day = _resolve_charge_day(inp, today)
    if day is None:
        return _failed(inp, [_issue("missing_charge_day", "No hay charge_day ni cargos para deducirlo.")])
    tomorrow = today + timedelta(days=1)
    horizon = [_add_months(start, i) for i in range(inp.horizon_months)]
    horizon_keys = [_fmt(h) for h in horizon]
    last_key = horizon_keys[-1]
    amount = inp.new_amount

    by_month: dict[str, list[PlanCharge]] = {}
    for c in inp.charges:
        if c.state in CANCELLED_STATES:
            continue
        by_month.setdefault(c.month, []).append(c)

    warnings: list[PlanIssue] = []
    covered: list[CoveredMonth] = []
    review: list[ManualReviewMonth] = []
    unchanged: list[str] = []
    kept_today: list[str] = []
    creates: list[PlanAction] = []
    cancel_plan: list[tuple[str, PlanCharge]] = []
    shifted = 0  # cuantos reemplazos de ventana ya usaron 'manana' (espaciado JB-09)

    for ym in horizon:
        key = _fmt(ym)
        cs = by_month.get(key, [])
        blocking = [c for c in cs if c.state not in PENDING_STATES]
        if blocking:
            covered.append(CoveredMonth(key, _cover_reason(blocking[0].state),
                                        tuple(c.charge_id for c in blocking if c.charge_id)))
            for c in blocking:
                if _cover_reason(c.state) == "unknown_status":
                    warnings.append(_issue("unknown_status", "Estado de cobro desconocido para el CRM: mes tratado como cubierto.", key))
            continue
        pend = [c for c in cs if c.state in PENDING_STATES and not c.is_puntual]  # puntuales: ni cancel ni keep
        due_today = [c for c in pend if c.charge_date == today]
        if due_today:  # puede estar ya en proceso en VP: ni cancelar ni reemplazar (riesgo de doble cobro)
            warnings.append(_issue("due_today_kept", "Cobro pendiente fechado hoy: no se toca.", key))
            kept_today.append(key)
            continue
        if len(pend) > 1:
            warnings.append(_issue("multiple_pending", f"{len(pend)} cobros pendientes en el mes (CO-02).", key))
        foreign = [c for c in pend if c.is_manual and not c.is_crm]
        if foreign:
            warnings.append(_issue("foreign_manual_kept", "Cobro manual ajeno al CRM: no se toca.", key))

        target = month_date(ym, day)

        def _matches(c: PlanCharge, target: date = target) -> bool:
            if c.amount != amount:
                return False
            if mode == "amount":
                return True
            return c.charge_date == target or (target < tomorrow and c.charge_date >= tomorrow)  # RA-17

        # Preferir conservar un pendiente ya correcto (CRM > automatico > ajeno): idempotencia / noop.
        matching = sorted((c for c in pend if _matches(c)), key=lambda c: (not c.is_crm, c.is_manual, c.charge_date))
        keep = matching[0] if matching else None
        creating = False
        if keep is None:
            if target < tomorrow:
                overdue = (today - target).days
                if overdue > inp.window_days:
                    review.append(ManualReviewMonth(key, target, overdue))
                    continue  # sin create => no se cancela nada de ese mes
                cdate = tomorrow + timedelta(days=shifted)
                if (cdate.year, cdate.month) != ym:  # el reemplazo debe caer en SU mes (de lo contrario duplicaria el siguiente)
                    review.append(ManualReviewMonth(key, target, overdue, "replacement_outside_month"))
                    continue
                shifted += 1
            else:
                cdate = target
            code = _code(inp.subscription_external_id, key, amount, cdate.day if mode == "date" else None)
            creates.append(PlanAction("create", key, cdate, amount, code))
            creating = True
        for c in pend:
            if c is keep or (c.is_manual and not c.is_crm) or not c.charge_id:
                continue
            cancel_plan.append((key, c))
        if keep is not None and not creating and len(pend) == 1:
            unchanged.append(key)

    create_codes = tuple(a.internal_code for a in creates if a.internal_code)
    cancels = tuple(
        PlanAction("cancel", key, c.charge_date, c.amount, c.internal_code, c.charge_id, create_codes)
        for key, c in cancel_plan
    )

    kept_after = tuple(
        KeptCharge(c.month, c.charge_id, c.charge_date, c.amount)
        for key in sorted(by_month) if key > last_key
        for c in by_month[key] if c.state in PENDING_STATES and not c.is_manual
    )

    previous = inp.previous_amount
    if previous is None and cancels:
        previous = Counter(a.amount for a in cancels).most_common(1)[0][0]
    return _finish(inp, tuple(creates), cancels, tuple(covered), tuple(review), tuple(unchanged), kept_after,
                   tuple(warnings), previous, horizon_keys[0], last_key, tuple(kept_today))


def _finish(
    inp: PlanInput, creates: tuple[PlanAction, ...], cancels: tuple[PlanAction, ...],
    covered: tuple[CoveredMonth, ...], review: tuple[ManualReviewMonth, ...], unchanged: tuple[str, ...],
    kept_after: tuple[KeptCharge, ...], warnings: tuple[PlanIssue, ...], previous: int | None,
    h_start: str | None, h_end: str | None, kept_due_today: tuple[str, ...] = (),
) -> PlanResult:
    delta = inp.new_amount - previous if previous is not None else None
    pct = round(abs(delta) / previous * 100, 2) if previous else None
    summary = PlanSummary(
        creates=len(creates), cancels=len(cancels), covered_months=len(covered),
        manual_review_months=len(review), unchanged_months=len(unchanged),
        affected_charges=len(creates) + len(cancels), previous_amount=previous, new_amount=inp.new_amount,
        amount_delta=delta, total_delta=sum(a.amount for a in creates) - sum(a.amount for a in cancels),
        variation_pct=pct, horizon_start=h_start, horizon_end=h_end,
    )
    return PlanResult(
        request_type=inp.request_type, subscription_external_id=inp.subscription_external_id,
        create=creates, cancel=cancels, covered=covered, manual_review=review, unchanged=unchanged,
        kept_automatic_after_horizon=kept_after, kept_due_today=kept_due_today, warnings=warnings,
        noop=not creates and not cancels and not review, summary=summary,
    )


def _today(inp: PlanInput) -> date:
    return inp.today if inp.today is not None else now_chile().date()


# ----------------------------- API publica -----------------------------


def build_amount_change_plan(inp: PlanInput) -> PlanResult:
    """Cambio de monto (RA-01..RA-14, CO-14): horizonte desde effective_month (o el mes de hoy)."""
    errs = _validate(inp)
    if errs:
        return _failed(inp, errs)
    today = _today(inp)
    start = _parse_month(inp.effective_month) if inp.effective_month else (today.year, today.month)
    return _plan_months(inp, "amount", start, today)


def build_date_change_plan(inp: PlanInput) -> PlanResult:
    """Cambio de fecha (RA-16, RA-17): reprograma el horizonte al new_charge_day con el mismo monto."""
    errs = _validate(inp)
    if errs:
        return _failed(inp, errs)
    today = _today(inp)
    start = _parse_month(inp.effective_month) if inp.effective_month else (today.year, today.month)
    return _plan_months(inp, "date", start, today)


def build_renewal_plan(inp: PlanInput) -> PlanResult:
    """Renovacion (JB-30): parte el mes siguiente al ultimo mes programado por el CRM y extiende el horizonte."""
    errs = _validate(inp)
    if errs:
        return _failed(inp, errs)
    crm_months = [c.month for c in inp.charges if c.is_crm and not c.is_puntual and c.state not in CANCELLED_STATES]
    if not crm_months:
        return _failed(inp, [_issue("no_crm_calendar", "Sin cobros del CRM: la suscripcion no tiene calendario modificado.")])
    start = _add_months(_parse_month(max(crm_months)), 1)
    return _plan_months(inp, "amount", start, _today(inp))


def build_one_off_plan(inp: PlanInput) -> PlanResult:
    """Cobro puntual por tarea (RA-29): un solo create, sin cancelar nada ni marcar calendario modificado."""
    errs = _validate(inp)
    today = _today(inp)
    if inp.one_off_date is None:
        errs.append(_issue("missing_one_off_date", "El cobro puntual requiere one_off_date."))
    elif inp.one_off_date <= today:
        errs.append(_issue("past_charge_date", "La fecha debe ser >= manana (E-078, CO-27)."))
    if errs:
        return _failed(inp, errs)
    assert inp.one_off_date is not None
    d = inp.one_off_date
    sub = inp.subscription_external_id
    code = f"{sub}-T{inp.task_ref}-{d:%Y%m%d}-{inp.new_amount}" if inp.task_ref else f"{sub}-{d:%Y%m%d}-{inp.new_amount}-oneoff"
    live = [c for c in inp.charges if c.state not in CANCELLED_STATES]
    existing = [c for c in live if c.internal_code == code]
    warnings: tuple[PlanIssue, ...] = ()
    if existing:  # idempotente (CO-12): ya existe
        return _finish(inp, (), (), (), (), (), (), (), inp.new_amount, d.strftime("%Y-%m"), d.strftime("%Y-%m"))
    if any(c.state in PENDING_STATES and c.month == d.strftime("%Y-%m") for c in live):
        warnings = (_issue("pending_same_month", "El mes ya tiene un pendiente; el puntual convive (CO-01).", d.strftime("%Y-%m")),)
    action = PlanAction("create", d.strftime("%Y-%m"), d, inp.new_amount, code)
    return _finish(inp, (action,), (), (), (), (), (), warnings, None, action.month, action.month)


def build_plan(inp: PlanInput) -> PlanResult:
    """Despacha por request_type."""
    builders = {
        "change_amount": build_amount_change_plan, "change_date": build_date_change_plan,
        "renew_calendar": build_renewal_plan, "one_off": build_one_off_plan,
    }
    fn = builders.get(inp.request_type)
    return fn(inp) if fn else _failed(inp, [_issue("invalid_request_type", f"request_type desconocido: {inp.request_type!r}.")])


# ----------------------------- serializacion -----------------------------


def _action_json(a: PlanAction) -> dict[str, Any]:
    out: dict[str, Any] = {"month": a.month, "charge_date": a.charge_date.isoformat(), "amount": a.amount,
                           "internal_code": a.internal_code}
    if a.kind == "cancel":
        out["charge_id"] = a.charge_id
        out["depends_on"] = list(a.depends_on)
    return out


def _issues_json(items: Iterable[PlanIssue]) -> list[dict[str, Any]]:
    return [{"code": i.code, "message": i.message, "month": i.month} for i in items]


def plan_to_preview_json(result: PlanResult) -> dict[str, Any]:
    """Formato JSON-serializable para billing_change_requests.plan_preview."""
    s = result.summary
    return {
        "version": 1,
        "request_type": result.request_type,
        "subscription_external_id": result.subscription_external_id,
        "noop": result.noop,
        "create": [_action_json(a) for a in result.create],
        "cancel": [_action_json(a) for a in result.cancel],
        "covered": [{"month": c.month, "reason": c.reason, "charge_ids": list(c.charge_ids)} for c in result.covered],
        "manual_review": [
            {"month": m.month, "target_date": m.target_date.isoformat(), "days_overdue": m.days_overdue, "reason": m.reason}
            for m in result.manual_review
        ],
        "unchanged": list(result.unchanged),
        "kept_due_today": list(result.kept_due_today),
        "kept_automatic_after_horizon": [
            {"month": k.month, "charge_id": k.charge_id, "charge_date": k.charge_date.isoformat(), "amount": k.amount}
            for k in result.kept_automatic_after_horizon
        ],
        "warnings": _issues_json(result.warnings),
        "errors": _issues_json(result.errors),
        "summary": None if s is None else {
            "creates": s.creates, "cancels": s.cancels, "covered_months": s.covered_months,
            "manual_review_months": s.manual_review_months, "unchanged_months": s.unchanged_months,
            "affected_charges": s.affected_charges, "previous_amount": s.previous_amount, "new_amount": s.new_amount,
            "amount_delta": s.amount_delta, "total_delta": s.total_delta, "variation_pct": s.variation_pct,
            "horizon_start": s.horizon_start, "horizon_end": s.horizon_end,
        },
    }


__all__ = [
    "CoveredMonth",
    "KeptCharge",
    "ManualReviewMonth",
    "PlanAction",
    "PlanCharge",
    "PlanInput",
    "PlanIssue",
    "PlanResult",
    "PlanSummary",
    "build_amount_change_plan",
    "build_date_change_plan",
    "build_one_off_plan",
    "build_plan",
    "build_renewal_plan",
    "is_cancelled_status",
    "is_one_off_code",
    "is_pending_status",
    "month_date",
    "norm_state",
    "plan_to_preview_json",
]
