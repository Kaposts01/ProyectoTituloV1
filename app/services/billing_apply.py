"""Aplicacion de cambios de cobro VirtualPOS aprobados (opcion A, fase 3b).

Toma una `BillingChangeRequest` en estado `aprobada`, relee el estado ACTUAL del proveedor, recalcula el plan
(`billing_plan.build_plan`), lo compara con el `plan_preview` aprobado (AP-30) y lo ejecuta en orden seguro:

1. CREAR todos los cobros nuevos (idempotente por `internal_code`, RA-14) y registrarlos en `vp_managed_charges`.
2. Solo si TODOS se crearon, CANCELAR los antiguos UNO POR UNO por `charge_id` (nunca el DELETE plural, CO-16),
   releyendo el estado antes de cada DELETE. E-059 -> se omite y se cancela el manual nuevo de ese mes (RA-11);
   E-079 -> no-op.
3. Si falla el create k: se compensan (cancelan) los ya creados; si la compensacion tambien falla -> `requiere_conciliacion`
   (RA-09). Si falla el DELETE de un antiguo tras crear todos: UN reintento (releyendo estado) y, si persiste,
   `requiere_conciliacion` SIN tocar los creados (queda un doble pendiente temporal documentado, RA-10).
4. Verificacion final: se relee y se exige exactamente UN pendiente por mes del horizonte (salvo meses cubiertos o en
   revision manual). Solo si cuadra -> `ejecutada` y upsert de `vp_calendar_marks` (RA-28).

Concurrencia: lock `pg_try_advisory_xact_lock` por (plataforma, suscripcion) tomado en una conexion DEDICADA que
mantiene su transaccion abierta durante toda la aplicacion (los servicios de escritura hacen commit y un lock
`xact` sobre la sesion principal se soltaria en el primer commit). La transicion aprobada->aplicando es un UPDATE
condicional (AP-14). Estado incierto (timeout) -> nunca se reintenta a ciegas: se relee el proveedor (RZ-31).

`retry_charge` no usa este lock todavia (RZ-30/RA-27 quedan para otra fase).
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.billing import (
    BillingChangeRequest,
    BillingChangeRequestEvent,
    VpCalendarMark,
    VpManagedCharge,
)
from app.models.crm import Subscription
from app.models.vp import VpSubscription
from app.models.write_run import WriteRun
from app.services import write_virtualpos as wv
from app.services.billing_plan import (
    CANCELLED_STATES,
    PENDING_STATES,
    PlanAction,
    PlanCharge,
    PlanInput,
    PlanResult,
    build_plan,
    is_cancelled_status,
    norm_state,
    plan_to_preview_json,
)
from app.services.read_only_provider_sync import safe_error_message
from app.services.rejected_month import CHILE_TZ, now_chile
from app.services.write_virtualpos import (
    ProviderListingError,
    ReconciliationRequiredError,
)

log = logging.getLogger(__name__)

ALIVE_MANAGED = ("creado", "requiere_conciliacion")
ACTIVE_STATUSES = frozenset({"activa", "activo", "active"})
_REQUEST_TYPE_TO_PLAN = {
    "change_amount": "change_amount", "change_date": "change_date",
    "renew_calendar": "renew_calendar", "one_off_charge": "one_off",
}


# ----------------------------- errores tipados -----------------------------


class BillingApplyError(Exception):
    """Base de los errores de aplicacion."""


class RequestNotFoundError(BillingApplyError):
    pass


class InvalidRequestStateError(BillingApplyError):
    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"La solicitud no se puede aplicar en estado {status!r} (se exige 'aprobada').")


class SubscriptionBusyError(BillingApplyError):
    """Otra operacion tiene el lock de la suscripcion (la API la traduce a 409)."""


class UnparseableChargesError(BillingApplyError):
    """El proveedor devolvió cobros con id, fecha o monto no interpretables: se aborta el plan (nada se escribió)."""

    def __init__(self, count: int, by_status: dict[str, int]) -> None:
        self.count = count
        self.by_status = by_status
        detail = ", ".join(f"{st or 'sin estado'}: {n}" for st, n in sorted(by_status.items()))
        super().__init__(f"{count} cobro(s) del proveedor no son interpretables (id, fecha o monto inválidos; estados: {detail}).")


class SubscriptionBlockedError(BillingApplyError):
    """La suscripcion tiene cobros en `requiere_conciliacion` de otra solicitud (RA-09)."""


class PlanDriftError(BillingApplyError):
    """El plan recalculado difiere del aprobado (AP-30): nada se escribio; la API debe pedir confirmacion."""

    def __init__(self, diff: dict[str, Any], new_preview: dict[str, Any]) -> None:
        self.diff = diff
        self.new_preview = new_preview
        super().__init__("El estado en VirtualPOS cambio desde la aprobacion: el plan recalculado difiere del aprobado.")


class ApplyFailedError(BillingApplyError):
    """Fallo con compensacion limpia: la solicitud queda `fallida` y el calendario original intacto."""

    def __init__(self, request_id: uuid.UUID, cause: BaseException | None, compensated: list[str]) -> None:
        self.request_id = request_id
        self.cause = cause
        self.compensated = compensated
        super().__init__(f"No se pudo aplicar la solicitud {request_id}; se compensaron {len(compensated)} cobro(s).")


# ----------------------------- resultado -----------------------------


@dataclass
class ApplyResult:
    request_id: uuid.UUID
    status: str  # ejecutada | no_ejecutable
    already_applied: bool = False
    reason: str | None = None
    created: list[dict[str, Any]] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    covered_late_months: list[str] = field(default_factory=list)  # RA-11
    manual_review_months: list[str] = field(default_factory=list)
    write_run_id: uuid.UUID | None = None
    plan: PlanResult | None = None
    drift_accepted: dict[str, Any] | None = None


@dataclass
class _Ctx:
    db: Session
    req: BillingChangeRequest
    platform: str
    sub: str
    actor: uuid.UUID | None
    run: WriteRun | None = None
    last_error: BaseException | None = None
    created_by_month: dict[str, list[str]] = field(default_factory=dict)
    created_ids: list[str] = field(default_factory=list)
    lock_conn: Any = None  # conexion dedicada del advisory lock (comprobacion `SELECT 1` antes de cancelar)


# ----------------------------- utilidades -----------------------------


def _secrets() -> tuple[str | None, ...]:
    return (settings.virtualpos_api_key, settings.virtualpos_secret_key,
            settings.virtualpos2_api_key, settings.virtualpos2_secret_key)


def _err(exc: BaseException) -> str:
    return safe_error_message(exc, _secrets())  # type: ignore[arg-type]


_SAFE_ERROR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,60}(?: (?:E-\d{1,4}|HTTP \d{3}))*$")
_PROVIDER_CODE_RE = re.compile(r"^E-\d{1,4}$")
_ERR_CODE_IN_TEXT = re.compile(r"\bE-\d{1,4}\b")
LEGACY_ERROR_LABEL = "error_registrado"


def error_label(exc: BaseException | None) -> str:
    """Etiqueta SIN texto libre para `billing_change_requests.error_message` y los eventos: solo el nombre del tipo y,
    si existe en la cadena de causas, el codigo E-nnn de VirtualPOS o el estado HTTP. El detalle completo (saneado) queda
    unicamente en `write_runs`. Nunca incluye el mensaje de la excepcion (puede traer correos, RUT, URLs con ids)."""
    if exc is None:
        return "ErrorDesconocido"
    parts = [type(exc).__name__]
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        code = getattr(cur, "error_code", None)
        if isinstance(code, str) and _PROVIDER_CODE_RE.match(code):
            parts.append(code)
            break
        status = getattr(getattr(cur, "response", None), "status_code", None)
        if isinstance(status, int) and 100 <= status <= 599:
            parts.append(f"HTTP {status}")
            break
        cur = cur.__cause__
    return " ".join(parts)


def reduce_stored_error(value: Any) -> str | None:
    """Misma reduccion para lo ya persistido (filas anteriores a la tanda 2 con texto libre): conserva una etiqueta valida
    y, si no lo es, deja solo un marcador (mas el codigo E-nnn si el texto lo traia)."""
    if value is None or value == "":
        return None
    text = str(value).strip()
    if _SAFE_ERROR_RE.match(text):
        return text
    code = _ERR_CODE_IN_TEXT.search(text)
    return f"{LEGACY_ERROR_LABEL} {code.group(0)}" if code else LEGACY_ERROR_LABEL


def is_active_status(status: Any) -> bool:
    """`ACTIVA` en cualquier capitalizacion/idioma (vp_subscriptions guarda 'ACTIVA'; `subscriptions` puede traer
    'activa' o 'active' segun el ETL)."""
    return str(status or "").strip().lower() in ACTIVE_STATUSES


def _chile_now(now: datetime | None) -> datetime:
    ref = now_chile()
    if now is None:
        return ref
    if now.tzinfo is None:
        return now.replace(tzinfo=ref.tzinfo)
    return now.astimezone(ref.tzinfo)


def lock_key(platform: str, subscription_id: str) -> int:
    """Clave int64 determinista (hash estable, no `hash()` de Python) para el advisory lock."""
    digest = hashlib.blake2b(f"billing:{platform}:{subscription_id}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


@contextmanager
def subscription_lock(db: Session, platform: str, subscription_id: str) -> Iterator[Any]:
    """`pg_try_advisory_xact_lock` en una conexion dedicada, retenida hasta salir del bloque. Cede la conexion
    para poder comprobar que sigue viva (`idle_in_transaction_session_timeout` la mataria y soltaria el lock)."""
    engine = db.get_bind().engine
    conn = engine.connect()
    try:
        conn.begin()
        got = conn.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": lock_key(platform, subscription_id)}).scalar()
        if not got:
            raise SubscriptionBusyError(f"La suscripción {subscription_id} está siendo modificada por otra operación.")
        yield conn
    finally:
        try:
            conn.rollback()  # libera el lock xact
        finally:
            conn.close()


def is_subscription_blocked(db: Session, platform: str, subscription_id: str, *, exclude_request: uuid.UUID | None = None) -> bool:
    """RA-09/CS-09: hay cobros del CRM en `requiere_conciliacion` (de otra solicitud)."""
    q = select(VpManagedCharge.id).where(
        VpManagedCharge.platform == platform,
        VpManagedCharge.subscription_external_id == subscription_id,
        VpManagedCharge.status == "requiere_conciliacion",
    )
    if exclude_request is not None:
        q = q.where(VpManagedCharge.request_id.is_distinct_from(exclude_request))
    return db.scalar(q.limit(1)) is not None


def _month(d: date) -> str:
    return d.strftime("%Y-%m")


def _to_int(value: Any) -> int | None:
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return int(dec) if dec == dec.to_integral_value() else None


def _to_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _months_from(start: str, n: int) -> list[str]:
    year, month = int(start[:4]), int(start[5:7])
    out = []
    for i in range(n):
        idx = year * 12 + (month - 1) + i
        out.append(f"{idx // 12:04d}-{idx % 12 + 1:02d}")
    return out


# ----------------------------- lectura del proveedor -----------------------------


async def _fetch_charges(platform: str, subscription_id: str) -> list[dict[str, Any]]:
    """Todos los cargos de la suscripcion (todas las paginas, todos los estados). Fail-closed: un fallo, una forma
    inesperada o un listado posiblemente incompleto lanzan (`ProviderListingError`) en vez de seguir con parte."""
    async with wv.VirtualPOSClient(platform=platform) as provider:
        return await wv.fetch_all_charge_pages(provider, subscription_id)


def _alive_managed_ids(db: Session, platform: str, sub: str) -> set[str]:
    return set(db.scalars(select(VpManagedCharge.charge_id).where(
        VpManagedCharge.platform == platform, VpManagedCharge.subscription_external_id == sub,
        VpManagedCharge.status.in_(ALIVE_MANAGED))))


def _own_managed_ids(db: Session, request_id: uuid.UUID) -> set[str]:
    return set(db.scalars(select(VpManagedCharge.charge_id).where(
        VpManagedCharge.request_id == request_id, VpManagedCharge.status.in_(ALIVE_MANAGED))))


def _crm_codes(db: Session, platform: str, sub: str, request_id: uuid.UUID | None = None) -> set[str]:
    """internal_code de los `create_charge` que el CRM ordeno (WriteRuns con solicitud). Registro previo al POST sin
    esquema nuevo: el WriteRun se confirma ANTES de llamar al proveedor, asi un cobro creado cuyo registro en
    `vp_managed_charges` fallo igual se reconoce como del CRM por su internal_code."""
    q = select(WriteRun.request_payload["internal_code"].astext).where(
        WriteRun.source == platform, WriteRun.operation == "create_charge", WriteRun.request_id.is_not(None),
        WriteRun.request_payload["suscription_id"].astext == sub,
    )
    if request_id is not None:
        q = q.where(WriteRun.request_id == request_id)
    return {c for c in db.scalars(q) if c}


def _one_off_managed_ids(db: Session, platform: str, sub: str) -> set[str]:
    """charge_id de los cobros registrados cuya solicitud de origen es un cobro puntual (`one_off_charge`)."""
    return set(db.scalars(
        select(VpManagedCharge.charge_id)
        .join(BillingChangeRequest, BillingChangeRequest.id == VpManagedCharge.request_id)
        .where(VpManagedCharge.platform == platform, VpManagedCharge.subscription_external_id == sub,
               BillingChangeRequest.request_type == "one_off_charge")))


def _window_replacement_ids(db: Session, platform: str, sub: str) -> set[str]:
    """Reemplazos de ventana: cobros del CRM fechados el dia siguiente a su creacion (JB-03). Sin esquema nuevo."""
    out: set[str] = set()
    for cid, charge_date, created_at in db.execute(
        select(VpManagedCharge.charge_id, VpManagedCharge.charge_date, VpManagedCharge.created_at).where(
            VpManagedCharge.platform == platform, VpManagedCharge.subscription_external_id == sub)):
        if charge_date is not None and created_at is not None and (
                charge_date - created_at.astimezone(CHILE_TZ).date() == timedelta(days=1)):
            out.add(cid)
    return out


@dataclass
class _Known:
    """Lo que el CRM sabe de sus propios cobros (para marcar is_crm / is_one_off)."""

    managed: set[str] = field(default_factory=set)
    one_off: set[str] = field(default_factory=set)
    codes: set[str] = field(default_factory=set)
    replacements: set[str] = field(default_factory=set)


def _known(db: Session, platform: str, sub: str) -> _Known:
    return _Known(managed=_alive_managed_ids(db, platform, sub), one_off=_one_off_managed_ids(db, platform, sub),
                  codes=_crm_codes(db, platform, sub), replacements=_window_replacement_ids(db, platform, sub))


def _to_plan_charges(
    items: list[dict[str, Any]], known: _Known | set[str], exclude: set[str] | frozenset[str] = frozenset(),
) -> list[PlanCharge]:
    """Convierte el listado del proveedor. Un cobro (no cancelado) con id, fecha o monto no interpretable NO se
    descarta en silencio: se lanza `UnparseableChargesError` (sin valores de montos ni ids)."""
    kn = known if isinstance(known, _Known) else _Known(managed=set(known))
    out: list[PlanCharge] = []
    bad: Counter[str] = Counter()
    for item in items:
        cid = wv._as_text(item.get("id"))
        status = str(item.get("status") or "")
        if cid and cid in exclude:
            continue
        charge_date, amount = _to_date(item.get("charge_date")), _to_int(item.get("amount"))
        if not cid or charge_date is None or amount is None:
            if not is_cancelled_status(status):  # un cancelado ilegible no cambia ningun mes
                bad[norm_state(status)] += 1
            continue
        code = wv._as_text(item.get("internal_code")) or None
        out.append(PlanCharge(
            charge_id=cid, status=status, charge_date=charge_date, amount=amount, internal_code=code,
            is_crm=cid in kn.managed or (code is not None and code in kn.codes), is_one_off=cid in kn.one_off,
        ))
    if bad:
        raise UnparseableChargesError(sum(bad.values()), dict(bad))
    return out


_PAID_OR_PENDING = frozenset({"pagado", "paid"}) | PENDING_STATES


def _resolve_charge_day(db: Session, inp: PlanInput, charges: list[PlanCharge], kn: _Known) -> int | None:
    """Dia de cobro: `previous_charge_day` de la solicitud (ya en inp.charge_day) > marca activa de la suscripcion >
    dia mas frecuente (empate: el mayor) entre los 12 cobros pagados/pendientes mas recientes, sin puntuales ni
    reemplazos de ventana. None si no hay base (el planificador devuelve `missing_charge_day`)."""
    if inp.request_type == "one_off" or inp.new_charge_day is not None or inp.charge_day is not None:
        return inp.charge_day
    mark_day = db.scalar(select(VpCalendarMark.charge_day).where(
        VpCalendarMark.platform == inp.platform, VpCalendarMark.subscription_external_id == inp.subscription_external_id,
        VpCalendarMark.is_active.is_(True)))
    if mark_day:
        return int(mark_day)
    cands = [c for c in charges if c.state in _PAID_OR_PENDING and not c.is_puntual and c.charge_id not in kn.replacements]
    recent = sorted(cands, key=lambda c: c.charge_date, reverse=True)[:12]
    if not recent:
        return None
    freq = Counter(c.charge_date.day for c in recent)
    return max(freq, key=lambda d: (freq[d], d))


def _request_to_input(req: BillingChangeRequest, today: date) -> PlanInput:
    snap = req.rules_snapshot or {}
    amount = _to_int(req.new_amount) if req.new_amount is not None else 0
    window = snap.get("window_days")
    return PlanInput(
        request_type=_REQUEST_TYPE_TO_PLAN.get(req.request_type, req.request_type),  # type: ignore[arg-type]
        subscription_external_id=req.subscription_external_id, platform=req.platform,
        new_amount=amount if amount is not None else 0,
        new_charge_day=req.new_charge_day, charge_day=req.previous_charge_day,
        effective_month=req.horizon_start_month, horizon_months=req.horizon_months,
        window_days=window if isinstance(window, int) else 31,
        previous_amount=_to_int(req.previous_amount) if req.previous_amount is not None else None,
        today=today, one_off_date=req.new_charge_date, task_ref=snap.get("task_ref"),
    )


@dataclass
class _Current:
    inp: PlanInput
    plan: PlanResult
    items: list[dict[str, Any]]
    previous_charge_day: int | None  # dia vigente ANTES del cambio (aunque el cambio traiga un dia nuevo)


async def _current_plan_full(db: Session, inp: PlanInput, *, exclude_own: uuid.UUID | None) -> _Current:
    """Plan recalculado con el estado actual. `exclude_own`: oculta los cobros ya creados por esta solicitud
    (reaplicacion tras fallo parcial) para que el plan sea el mismo y `create_charge` los adopte; incluye los que
    no llegaron a registrarse (se reconocen por el internal_code de los create_charge de la solicitud)."""
    items = await _fetch_charges(inp.platform, inp.subscription_external_id)
    kn = _known(db, inp.platform, inp.subscription_external_id)
    exclude: set[str] = set()
    if exclude_own:
        exclude = _own_managed_ids(db, exclude_own)
        own_codes = _crm_codes(db, inp.platform, inp.subscription_external_id, exclude_own)
        exclude |= {cid for it in items
                    if (cid := wv._as_text(it.get("id"))) and (wv._as_text(it.get("internal_code")) or "") in own_codes}
    charges = _to_plan_charges(items, kn, exclude)
    day = _resolve_charge_day(db, inp, charges, kn)
    previous_day = day if inp.new_charge_day is None else _resolve_charge_day(db, replace(inp, new_charge_day=None), charges, kn)
    full = replace(inp, charge_day=day, charges=tuple(charges))
    return _Current(full, build_plan(full), items, previous_day)


async def _current_plan(
    db: Session, inp: PlanInput, *, exclude_own: uuid.UUID | None
) -> tuple[PlanInput, PlanResult, list[dict[str, Any]]]:
    cur = await _current_plan_full(db, inp, exclude_own=exclude_own)
    return cur.inp, cur.plan, cur.items


async def preview_change_with_day(
    db: Session, request_or_input: BillingChangeRequest | uuid.UUID | PlanInput, *, now: datetime | None = None
) -> tuple[PlanResult, int | None]:
    """Como `preview_change` y ademas el dia de cobro vigente resuelto (solicitud > marca activa > dia modal sin
    puntuales ni reemplazos): `create_request` lo guarda en `previous_charge_day` para que el dia quede fijo."""
    today = _chile_now(now).date()
    if isinstance(request_or_input, PlanInput):
        inp = replace(request_or_input, today=request_or_input.today or today)
        exclude_own = None
    else:
        req = request_or_input if isinstance(request_or_input, BillingChangeRequest) else db.get(BillingChangeRequest, request_or_input)
        if req is None:
            raise RequestNotFoundError(str(request_or_input))
        inp = _request_to_input(req, today)
        exclude_own = req.id
    cur = await _current_plan_full(db, inp, exclude_own=exclude_own)
    return cur.plan, cur.previous_charge_day


async def preview_change(
    db: Session, request_or_input: BillingChangeRequest | uuid.UUID | PlanInput, *, now: datetime | None = None
) -> PlanResult:
    """dry_run de solo lectura (AP-29): plan con el estado actual del proveedor. No escribe ni cambia estados."""
    plan, _day = await preview_change_with_day(db, request_or_input, now=now)
    return plan


# ----------------------------- drift (AP-30) -----------------------------


def _create_key(a: dict[str, Any]) -> tuple:
    return (a.get("month"), a.get("charge_date"), a.get("amount"), a.get("internal_code"))


def _cancel_key(a: dict[str, Any]) -> tuple:
    return (a.get("month"), a.get("charge_id"), a.get("amount"))


def compute_drift(approved: dict[str, Any], new: dict[str, Any], cancelled_ids: set[str]) -> dict[str, Any] | None:
    """Diferencias de ACCIONES entre el plan aprobado y el recalculado. Un cancel aprobado que ya no aparece porque
    el cobro ya esta cancelado (avance de esta misma solicitud) no cuenta como drift."""
    a_cre, n_cre = {_create_key(x) for x in approved.get("create", [])}, {_create_key(x) for x in new.get("create", [])}
    a_can = {_cancel_key(x): x for x in approved.get("cancel", [])}
    n_can = {_cancel_key(x): x for x in new.get("cancel", [])}
    diff = {
        "create_added": sorted(map(list, n_cre - a_cre), key=str),
        "create_removed": sorted(map(list, a_cre - n_cre), key=str),
        "cancel_added": sorted((list(k) for k in n_can.keys() - a_can.keys()), key=str),
        "cancel_removed": sorted((list(k) for k in a_can.keys() - n_can.keys() if k[1] not in cancelled_ids), key=str),
        "manual_review_added": sorted({m["month"] for m in new.get("manual_review", [])} - {m["month"] for m in approved.get("manual_review", [])}),
        "manual_review_removed": sorted({m["month"] for m in approved.get("manual_review", [])} - {m["month"] for m in new.get("manual_review", [])}),
    }
    return diff if any(diff.values()) else None


# ----------------------------- estado de la solicitud -----------------------------


def _event(db: Session, req_id: uuid.UUID, event_type: str, actor: uuid.UUID | None, detail: dict[str, Any] | None = None) -> None:
    db.add(BillingChangeRequestEvent(request_id=req_id, event_type=event_type, actor_user_id=actor, detail=detail or {},
                                        created_at=datetime.now(UTC)))  # reloj real: orden estable dentro de una transaccion


def _claim_request(db: Session, request_id: uuid.UUID) -> bool:
    """Transicion ATOMICA aprobada -> aplicando (AP-14): solo una llamada concurrente obtiene True."""
    result = db.execute(
        update(BillingChangeRequest)
        .where(BillingChangeRequest.id == request_id, BillingChangeRequest.status == "aprobada")
        .values(status="aplicando", updated_at=func.now())
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def _subscription_state(db: Session, platform: str, sub: str) -> tuple[str | None, str | None] | None:
    row = db.execute(select(VpSubscription.status, VpSubscription.plan_external_id).where(
        VpSubscription.platform == platform, VpSubscription.external_id == sub)).first()
    if row is None:
        row = db.execute(select(Subscription.status, Subscription.plan_external_id).where(
            Subscription.source == platform, Subscription.external_id == sub)).first()
    return (row[0], row[1]) if row else None


def _not_executable(db: Session, req: BillingChangeRequest, actor: uuid.UUID | None, reason: str, detail: dict[str, Any] | None = None) -> ApplyResult:
    updated = db.execute(
        update(BillingChangeRequest)
        .where(BillingChangeRequest.id == req.id, BillingChangeRequest.status == "aprobada")
        .values(status="no_ejecutable", error_message=reason[:2000], updated_at=func.now())
        .execution_options(synchronize_session=False)
    ).rowcount
    if updated == 1:
        _event(db, req.id, "no_ejecutable", actor, {"reason": reason, **(detail or {})})
    db.commit()
    return ApplyResult(request_id=req.id, status="no_ejecutable", reason=reason)


# ----------------------------- registro propio -----------------------------


def _upsert_managed(ctx: _Ctx, charge_id: str, action: PlanAction, status: str = "creado") -> None:
    db = ctx.db
    row = db.scalar(select(VpManagedCharge).where(VpManagedCharge.platform == ctx.platform, VpManagedCharge.charge_id == charge_id))
    if row is None:
        row = VpManagedCharge(platform=ctx.platform, charge_id=charge_id)
        db.add(row)
    row.subscription_external_id = ctx.sub
    row.internal_code = action.internal_code or ""
    row.month = action.month
    row.charge_date = action.charge_date
    row.amount = Decimal(action.amount)
    row.request_id = ctx.req.id
    row.write_run_id = ctx.run.id if ctx.run else None
    row.status = status
    row.cancelled_at = None
    db.commit()


def _mark_managed(ctx: _Ctx, charge_id: str, status: str) -> None:
    row = ctx.db.scalar(select(VpManagedCharge).where(VpManagedCharge.platform == ctx.platform, VpManagedCharge.charge_id == charge_id))
    if row is None:
        return
    row.status = status
    if status in ("cancelado", "compensado"):
        row.cancelled_at = datetime.now(UTC)
    ctx.db.commit()


# ----------------------------- cancelacion individual -----------------------------


async def _status_of(ctx: _Ctx, charge_id: str) -> str | None:
    for item in await _fetch_charges(ctx.platform, ctx.sub):
        if wv._as_text(item.get("id")) == charge_id:
            return norm_state(item.get("status"))
    return None


def _annotate_applied_after_timeout(ctx: _Ctx, charge_id: str) -> None:
    """El WriteRun hijo de un intento de cancelacion fallido (timeout) que luego resulto aplicado se anota
    (solo trazabilidad: no cambia el comportamiento)."""
    try:
        for run in ctx.db.scalars(select(WriteRun).where(
                WriteRun.request_id == ctx.req.id, WriteRun.operation == "cancel_future_charges",
                WriteRun.external_id == ctx.sub, WriteRun.status == "failed")):
            if (run.request_payload or {}).get("charge_ids") == [charge_id]:
                run.response_payload = {**(run.response_payload or {}), "applied_after_timeout": True, "charge_id": charge_id}
        ctx.db.commit()
    except Exception as exc:  # noqa: BLE001 - anotacion best-effort
        ctx.db.rollback()
        log.warning("no se pudo anotar el WriteRun de %s: %s", charge_id, _err(exc))


async def _cancel_one(ctx: _Ctx, charge_id: str) -> str:
    """Cancela UN cargo por id (nunca el DELETE plural). Devuelve
    cancelled | already_cancelled | covered | noop | failed. Hasta 2 intentos; antes de cada uno
    `cancel_future_charges` relee los pendientes, asi que tras un timeout no se repite un DELETE ya aplicado.
    E-079 y "no pendiente" se resuelven igual: se consulta el estado real (cancelado -> already_cancelled;
    pendiente -> failed; otro, p. ej. pagado/procesando -> covered)."""
    errored = False
    for _attempt in (1, 2):
        try:
            res = await wv.cancel_future_charges(
                ctx.db, ctx.sub, platform=ctx.platform, charge_ids=[charge_id],
                request_id=ctx.req.id, requested_by_user_id=ctx.actor,
            )
            if res["cancelled"]:
                return "cancelled"
            reason = (res["skipped"] or [{}])[0].get("reason")
            if reason == "E-059":
                return "covered"
            state = await _status_of(ctx, charge_id)  # E-079 / no_pendiente: ver que es
            if state is None:
                return "noop"
            if state in CANCELLED_STATES:
                if errored:
                    _annotate_applied_after_timeout(ctx, charge_id)
                return "already_cancelled"
            if state in PENDING_STATES:
                ctx.last_error = RuntimeError(f"El cobro {charge_id} figura pendiente pero no se pudo cancelar.")
                return "failed"
            return "covered"
        except Exception as exc:  # noqa: BLE001 - estado incierto: se relee en el siguiente intento
            errored = True
            ctx.last_error = exc
            log.warning("cancel %s fallo: %s", charge_id, _err(exc))
    return "failed"


async def _compensate(ctx: _Ctx, charge_ids: list[str]) -> list[str]:
    """Cancela los cobros creados y verifica releyendo. Devuelve los que NO quedaron cancelados."""
    for cid in charge_ids:
        await _cancel_one(ctx, cid)
    try:
        items = await _fetch_charges(ctx.platform, ctx.sub)
    except Exception as exc:  # noqa: BLE001
        ctx.last_error = exc
        return list(charge_ids)
    status = {wv._as_text(i.get("id")): norm_state(i.get("status")) for i in items}
    left = [cid for cid in charge_ids if status.get(cid) not in CANCELLED_STATES]
    for cid in charge_ids:
        _mark_managed(ctx, cid, "requiere_conciliacion" if cid in left else "compensado")
    return left


# ----------------------------- cierres de estado -----------------------------


def _finish_run(ctx: _Ctx, status: str, message: str | None = None, payload: dict[str, Any] | None = None) -> None:
    if ctx.run is None:
        return
    ctx.run.status = status
    ctx.run.error_message = message[:2000] if message else None
    ctx.run.response_payload = payload
    ctx.run.finished_at = datetime.now(UTC)


def _event_detail(detail: dict[str, Any], cause: BaseException | None) -> dict[str, Any]:
    """Detalle para el EVENTO: sin texto libre (la clave `error` pasa a la etiqueta del tipo). El detalle completo va
    solo al WriteRun (`_finish_run`)."""
    out = dict(detail)
    if "error" in out:
        out["error"] = error_label(cause)
    return out


def _set_request(ctx: _Ctx, status: str, event: str, error: str | None, detail: dict[str, Any],
                 cause: BaseException | None = None) -> None:
    """`error` ya es una etiqueta segura (`error_label` o un codigo fijo); nunca el mensaje de la excepcion."""
    req = ctx.req
    req.status = status
    req.error_message = error[:200] if error else None
    _event(ctx.db, req.id, event, ctx.actor, _event_detail(detail, cause))


def _reconciliation(ctx: _Ctx, message: str, detail: dict[str, Any], cause: BaseException | None = None) -> ReconciliationRequiredError:
    # Cobros creados que siguen vivos quedan marcados: bloquean la suscripcion (RA-09).
    for cid in ctx.created_ids:
        row = ctx.db.scalar(select(VpManagedCharge).where(VpManagedCharge.platform == ctx.platform, VpManagedCharge.charge_id == cid))
        if row is not None and row.status == "creado":
            row.status = "requiere_conciliacion"
    _set_request(ctx, "requiere_conciliacion", "requiere_conciliacion",
                 error_label(cause) if cause is not None else "ReconciliationRequired", detail, cause)
    _finish_run(ctx, "reconciliation_required", message, detail)
    ctx.db.commit()
    err = ReconciliationRequiredError(message)
    err.__cause__ = cause
    return err


# ----------------------------- ejecucion -----------------------------


async def _create_all(ctx: _Ctx, plan: PlanResult) -> None:
    for k, action in enumerate(plan.create, start=1):
        data = {"charge_date": action.charge_date.isoformat(), "amount": action.amount, "internal_code": action.internal_code}
        try:
            charge = await wv.create_charge(
                ctx.db, ctx.sub, data, platform=ctx.platform,
                request_id=ctx.req.id, requested_by_user_id=ctx.actor,
            )
        except Exception as exc:
            raise await _handle_create_failure(ctx, action, k, exc) from exc
        cid = charge.external_id
        _upsert_managed(ctx, cid, action)
        ctx.created_ids.append(cid)
        ctx.created_by_month.setdefault(action.month, []).append(cid)


async def _handle_create_failure(ctx: _Ctx, action: PlanAction, k: int, exc: BaseException) -> BaseException:
    """Fallo en el create k: releer (el POST pudo haberse aplicado, RA-08), compensar y cerrar el estado."""
    ctx.db.rollback()
    uncertain = False
    try:
        for item in await _fetch_charges(ctx.platform, ctx.sub):
            cid = wv._as_text(item.get("id"))
            if (cid and cid not in ctx.created_ids and wv._as_text(item.get("internal_code")) == action.internal_code
                    and norm_state(item.get("status")) in PENDING_STATES):
                _upsert_managed(ctx, cid, action)  # huerfano de un POST con timeout
                ctx.created_ids.append(cid)
    except Exception as read_exc:  # noqa: BLE001
        uncertain = True
        ctx.last_error = read_exc
    to_compensate = list(ctx.created_ids)
    left = await _compensate(ctx, to_compensate) if to_compensate else []
    base = {"failed_create_index": k, "failed_internal_code": action.internal_code, "error": _err(exc),
            "compensated": [c for c in to_compensate if c not in left], "not_compensated": left}
    if left or uncertain:
        why = "no se pudo releer el estado del proveedor" if uncertain else "falló la compensación"
        return _reconciliation(ctx, f"Falló el cobro {k} ({action.month}) y {why}; revisar duplicados. {_err(exc)}", base, exc)
    msg = f"No se creó el cobro {k} ({action.month}); se compensaron {len(to_compensate)} y no se canceló ningún cobro anterior. {_err(exc)}"
    _set_request(ctx, "fallida", "fallida", error_label(exc), base, exc)
    _finish_run(ctx, "failed", msg, base)
    ctx.db.commit()
    return ApplyFailedError(ctx.req.id, exc, base["compensated"])


async def _cancel_all(ctx: _Ctx, plan: PlanResult) -> tuple[list[str], list[str]]:
    cancelled: list[str] = []
    covered_late: list[str] = []
    rolled_back: set[str] = set()
    for action in plan.cancel:
        cid = action.charge_id
        assert cid is not None
        outcome = await _cancel_one(ctx, cid)
        if outcome in ("cancelled", "already_cancelled", "noop"):
            _mark_managed(ctx, cid, "cancelado")
            if outcome != "noop":
                cancelled.append(cid)
        elif outcome == "covered":  # RA-11: el antiguo ya no es cancelable -> cancelar el manual nuevo del mes
            if action.month in rolled_back:
                continue
            rolled_back.add(action.month)
            covered_late.append(action.month)
            for new_id in ctx.created_by_month.get(action.month, []):
                res = await _cancel_one(ctx, new_id)
                if res in ("failed", "covered"):
                    raise _reconciliation(
                        ctx, f"El cobro {cid} ({action.month}) ya no es cancelable y no se pudo cancelar el manual nuevo {new_id}: "
                             "riesgo de doble cobro.",
                        {"month": action.month, "old_charge_id": cid, "new_charge_id": new_id, "cancelled_before": cancelled},
                        ctx.last_error)
                _mark_managed(ctx, new_id, "cancelado")
        else:
            raise _reconciliation(
                ctx, f"No se pudo cancelar el cobro antiguo {cid} ({action.month}) tras crear los nuevos: hay doble pendiente temporal. "
                     f"{_err(ctx.last_error) if ctx.last_error else ''}",
                {"month": action.month, "charge_id": cid, "cancelled_before": cancelled, "created": ctx.created_ids},
                ctx.last_error)
    return cancelled, covered_late


async def _verify(ctx: _Ctx, inp: PlanInput, plan: PlanResult) -> tuple[list[str], list[PlanCharge]]:
    """Relee y exige exactamente un pendiente por mes esperado. Devuelve (problemas, cargos actuales)."""
    items = await _fetch_charges(ctx.platform, ctx.sub)
    charges = _to_plan_charges(items, _known(ctx.db, ctx.platform, ctx.sub))
    problems: list[str] = []
    if inp.request_type == "one_off":
        codes = {a.internal_code for a in plan.create}
        found = {c.internal_code for c in charges if c.internal_code in codes and c.state in PENDING_STATES}
        problems = [f"falta el cobro puntual {code}" for code in sorted(codes - found)]
        return problems, charges
    assert plan.summary is not None and plan.summary.horizon_start is not None
    vtype = "change_date" if inp.request_type == "change_date" else "change_amount"  # renovacion: mismo horizonte, modo monto
    vplan = build_plan(replace(inp, request_type=vtype, effective_month=plan.summary.horizon_start, charges=tuple(charges)))
    if vplan.errors:
        problems.append("el plan de verificación tiene errores: " + ", ".join(e.code for e in vplan.errors))
    if vplan.create or vplan.cancel:
        problems.append("quedan acciones pendientes: " + ", ".join(sorted({a.month for a in vplan.create + vplan.cancel})))
    own = set(ctx.created_ids) | _own_managed_ids(ctx.db, ctx.req.id)
    double = sorted({c.month for c in charges if c.charge_id in own and c.state in PENDING_STATES
                     and c.month in {cm.month for cm in vplan.covered}})
    if double:  # mes cubierto (pagado/procesando/rechazado) que ademas tiene un pendiente creado por esta solicitud
        problems.append("meses cubiertos con un cobro nuevo pendiente (doble cobro): " + ", ".join(double))
    skip = {c.month for c in vplan.covered} | {m.month for m in vplan.manual_review} | set(vplan.kept_due_today)
    unchanged = set(vplan.unchanged)
    bad = [m for m in _months_from(plan.summary.horizon_start, inp.horizon_months) if m not in skip and m not in unchanged]
    if bad:
        problems.append("meses sin exactamente un pendiente con el monto/fecha nuevo: " + ", ".join(bad))
    return problems, charges


def _upsert_mark(ctx: _Ctx, inp: PlanInput, charges: list[PlanCharge]) -> dict[str, Any] | None:
    crm = [c for c in charges if c.is_crm and not c.is_puntual and c.state in PENDING_STATES]  # sin puntuales
    if not crm:
        return None
    last = max(crm, key=lambda c: c.charge_date)
    day = inp.new_charge_day or inp.charge_day or max({c.charge_date.day for c in crm}, key=lambda d: sum(c.charge_date.day == d for c in crm))
    mark = ctx.db.scalar(select(VpCalendarMark).where(
        VpCalendarMark.platform == ctx.platform, VpCalendarMark.subscription_external_id == ctx.sub))
    if mark is None:
        mark = VpCalendarMark(platform=ctx.platform, subscription_external_id=ctx.sub)
        ctx.db.add(mark)
    mark.last_scheduled_month = _month(last.charge_date)
    mark.last_scheduled_date = last.charge_date
    mark.scheduled_amount = Decimal(inp.new_amount)
    mark.charge_day = day
    mark.origin_request_id = ctx.req.id
    mark.is_active = True
    return {"last_scheduled_month": mark.last_scheduled_month, "charge_day": day, "amount": inp.new_amount}


def _check_lock_alive(ctx: _Ctx) -> None:
    """Comprobacion barata (`SELECT 1`) de la conexion dedicada del lock antes de la fase de cancelaciones: si el
    servidor la cerro (p. ej. `idle_in_transaction_session_timeout`), el advisory lock ya no esta y no se cancela nada."""
    if ctx.lock_conn is None:
        return
    try:
        ctx.lock_conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise _reconciliation(
            ctx, f"Se perdió la conexión del lock de la suscripción antes de cancelar los cobros antiguos: {_err(exc)}",
            {"created": ctx.created_ids, "phase": "before_cancellations"}, exc) from exc


async def _execute(ctx: _Ctx, inp: PlanInput, plan: PlanResult, drift: dict[str, Any] | None) -> ApplyResult:
    await _create_all(ctx, plan)
    if plan.cancel:
        _check_lock_alive(ctx)
    cancelled, covered_late = await _cancel_all(ctx, plan)
    try:
        problems, charges = await _verify(ctx, inp, plan)
    except Exception as exc:
        raise _reconciliation(ctx, f"No se pudo verificar el resultado: {_err(exc)}", {"created": ctx.created_ids}, exc) from exc
    if problems:
        raise _reconciliation(ctx, "La verificación final no cuadra: " + "; ".join(problems),
                              {"problems": problems, "created": ctx.created_ids, "cancelled": cancelled})
    mark = None if inp.request_type == "one_off" else _upsert_mark(ctx, inp, charges)
    now = datetime.now(UTC)
    ctx.req.executed_at = now
    detail = {"created": ctx.created_ids, "cancelled": cancelled, "covered_late_months": covered_late,
              "manual_review_months": [m.month for m in plan.manual_review], "calendar_mark": mark,
              "write_run_id": str(ctx.run.id) if ctx.run else None}
    _set_request(ctx, "ejecutada", "aplicada", None, detail)
    _finish_run(ctx, "completed", None, detail)
    ctx.db.commit()
    return ApplyResult(
        request_id=ctx.req.id, status="ejecutada", created=[{"charge_id": c} for c in ctx.created_ids], cancelled=cancelled,
        covered_late_months=covered_late, manual_review_months=[m.month for m in plan.manual_review],
        write_run_id=ctx.run.id if ctx.run else None, plan=plan, drift_accepted=drift,
    )


# ----------------------------- API publica -----------------------------


async def apply_change_request(
    db: Session,
    request_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None,
    now: datetime | None = None,
    accept_drift: bool = False,
) -> ApplyResult:
    """Aplica una solicitud `aprobada` (ver docstring del modulo).

    Errores: RequestNotFoundError, InvalidRequestStateError, WriteDisabledError / FixedPlanChargeBlockedError (antes
    de cambiar de estado: la solicitud sigue `aprobada`), SubscriptionBusyError (lock ocupado), SubscriptionBlockedError,
    PlanDriftError (nada escrito; reintentar con `accept_drift=True` tras confirmar), ApplyFailedError (fallo con
    compensacion limpia -> `fallida`), ReconciliationRequiredError (-> `requiere_conciliacion`).
    Resultado `no_ejecutable` (suscripcion no ACTIVA / plan cambiado / plan invalido) se devuelve sin escribir al proveedor.
    Reaplicar una solicitud `ejecutada` es un no-op (`already_applied`).
    """
    today = _chile_now(now).date()
    req = db.get(BillingChangeRequest, request_id)
    if req is None:
        raise RequestNotFoundError(str(request_id))
    if req.status == "ejecutada":
        return ApplyResult(request_id=req.id, status="ejecutada", already_applied=True, write_run_id=req.write_run_id)
    if req.status != "aprobada":
        raise InvalidRequestStateError(req.status)

    # Banderas: ANTES de cambiar de estado (la solicitud sigue `aprobada`, sin llamadas al proveedor).
    if not settings.virtualpos_writes_enabled:
        raise wv.WriteDisabledError
    platform, sub = req.platform, req.subscription_external_id
    wv.ensure_charge_allowed_on_plan(db, sub, platform)

    with subscription_lock(db, platform, sub) as lock_conn:
        db.refresh(req)
        if req.status == "ejecutada":
            return ApplyResult(request_id=req.id, status="ejecutada", already_applied=True, write_run_id=req.write_run_id)
        if req.status != "aprobada":
            raise InvalidRequestStateError(req.status)
        if is_subscription_blocked(db, platform, sub, exclude_request=req.id):
            raise SubscriptionBlockedError(f"La suscripción {sub} tiene cobros en conciliación pendiente (RA-09).")

        # Revalidacion (RA-22 / JB-17 / AP-13): suscripcion ACTIVA y mismo plan.
        state = _subscription_state(db, platform, sub)
        if state is None or not is_active_status(state[0]):
            return _not_executable(db, req, actor_user_id, "subscription_not_active", {"status": state[0] if state else None})
        expected_plan = (req.rules_snapshot or {}).get("plan_external_id")
        if expected_plan and state[1] != expected_plan:
            return _not_executable(db, req, actor_user_id, "plan_changed", {"expected": expected_plan, "current": state[1]})

        inp, plan, items = await _current_plan(db, _request_to_input(req, today), exclude_own=req.id)
        if plan.errors:
            return _not_executable(db, req, actor_user_id, "invalid_plan", {"errors": [e.code for e in plan.errors]})
        new_preview = plan_to_preview_json(plan)
        cancelled_ids = {wv._as_text(i.get("id")) for i in items if is_cancelled_status(i.get("status"))}
        drift = compute_drift(req.plan_preview or {}, new_preview, {c for c in cancelled_ids if c})
        if drift is not None and not accept_drift:
            raise PlanDriftError(drift, new_preview)

        if not _claim_request(db, req.id):
            db.rollback()
            raise InvalidRequestStateError("no aprobada (transición concurrente)")
        db.refresh(req)
        run = WriteRun(
            source=platform, resource_type="subscription_charges", external_id=sub,
            operation="apply_billing_change_request", status="pending",
            request_payload={"request_id": str(req.id), "request_type": req.request_type,
                             "summary": new_preview.get("summary"), "drift_accepted": drift},
            requested_by_user_id=actor_user_id, request_id=req.id,
        )
        db.add(run)
        db.flush()
        req.write_run_id = run.id
        if drift is not None:
            req.plan_preview = new_preview
        _event(db, req.id, "aplicando", actor_user_id, {"write_run_id": str(run.id), "drift_accepted": drift})
        db.commit()

        ctx = _Ctx(db=db, req=req, platform=platform, sub=sub, actor=actor_user_id, run=run, lock_conn=lock_conn)
        try:
            return await _execute(ctx, inp, plan, drift)
        except (ApplyFailedError, ReconciliationRequiredError):
            raise
        except Exception as exc:
            db.rollback()
            ctx.req = db.get(BillingChangeRequest, req.id) or req
            ctx.run = db.get(WriteRun, run.id)
            raise _reconciliation(ctx, f"Error inesperado al aplicar: {_err(exc)}", {"created": ctx.created_ids}, exc) from exc
        except BaseException as exc:
            # CancelledError / KeyboardInterrupt tras el claim: la solicitud no puede quedar en 'aplicando'.
            try:
                db.rollback()
                ctx.req = db.get(BillingChangeRequest, req.id) or req
                ctx.run = db.get(WriteRun, run.id)
                _reconciliation(ctx, f"Aplicación interrumpida ({type(exc).__name__}); revisar el estado en el proveedor.",
                                {"created": ctx.created_ids, "interrupted": type(exc).__name__}, exc)
            except Exception as rec_exc:  # noqa: BLE001 - se relanza igual la excepcion original
                log.error("no se pudo registrar la interrupcion de %s: %s", req.id, _err(rec_exc))
            raise


STUCK_APPLYING_MINUTES = 30


def sweep_stuck_applying(
    db: Session, *, older_than_minutes: int = STUCK_APPLYING_MINUTES, now: datetime | None = None
) -> list[uuid.UUID]:
    """Barredor: solicitudes en 'aplicando' sin actividad hace mas de `older_than_minutes` (proceso caido) pasan a
    `requiere_conciliacion` con evento 'requiere_conciliacion' (actor sistema); sus cobros vivos quedan bloqueando la
    suscripcion. Si el lock de la suscripcion esta tomado (aplicacion viva) se omite. Devuelve los ids barridos.
    Registrado en el scheduler como `billing_sweep_applying` (cada 15 min). En la solicitud solo queda el codigo
    `StuckApplying`; el mensaje completo va al WriteRun."""
    cutoff = (now or datetime.now(UTC)) - timedelta(minutes=older_than_minutes)
    stuck = list(db.execute(select(BillingChangeRequest.id, BillingChangeRequest.platform,
                                   BillingChangeRequest.subscription_external_id).where(
        BillingChangeRequest.status == "aplicando", BillingChangeRequest.updated_at < cutoff)))
    swept: list[uuid.UUID] = []
    for req_id, platform, sub in stuck:
        try:
            with subscription_lock(db, platform, sub):
                msg = f"Solicitud en 'aplicando' sin actividad por más de {older_than_minutes} min: requiere conciliación."
                changed = db.execute(
                    update(BillingChangeRequest)
                    .where(BillingChangeRequest.id == req_id, BillingChangeRequest.status == "aplicando",
                           BillingChangeRequest.updated_at < cutoff)
                    .values(status="requiere_conciliacion", error_message="StuckApplying", updated_at=func.now())
                    .execution_options(synchronize_session=False)).rowcount
                if changed != 1:
                    db.rollback()
                    continue
                db.execute(update(VpManagedCharge).where(
                    VpManagedCharge.request_id == req_id, VpManagedCharge.status == "creado").values(status="requiere_conciliacion"))
                db.execute(update(WriteRun).where(WriteRun.request_id == req_id, WriteRun.status == "pending").values(
                    status="reconciliation_required", error_message=msg, finished_at=datetime.now(UTC)))
                _event(db, req_id, "requiere_conciliacion", None, {"reason": "stuck_applying", "older_than_minutes": older_than_minutes})
                db.commit()
                swept.append(req_id)
        except SubscriptionBusyError:
            db.rollback()
    return swept


__all__ = [
    "ApplyFailedError",
    "ApplyResult",
    "BillingApplyError",
    "InvalidRequestStateError",
    "PlanDriftError",
    "ProviderListingError",
    "RequestNotFoundError",
    "SubscriptionBlockedError",
    "SubscriptionBusyError",
    "UnparseableChargesError",
    "apply_change_request",
    "compute_drift",
    "error_label",
    "is_active_status",
    "is_subscription_blocked",
    "lock_key",
    "preview_change",
    "preview_change_with_day",
    "reduce_stored_error",
    "subscription_lock",
    "sweep_stuck_applying",
]
