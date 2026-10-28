"""Solicitudes de cambio de cobro VirtualPOS y politica de aprobadores (opcion A, paso 4).

Logica de negocio detras de `app/api/v1/routes/billing_changes.py` (las rutas son finas).
Diseno: docs/designs/facturacion-gestionada-escenarios.md, seccion 5 (AP-01..AP-36), RA-xx, JB-xx.

Reglas principales
- Una sola solicitud abierta por suscripcion (indice unico parcial + chequeo previo -> `OpenRequestExistsError`).
- `create_request` calcula el plan CONTRA EL ESTADO ACTUAL del proveedor (solo lectura) y guarda `plan_preview` y
  `rules_snapshot` (AP-27: la regla vigente al crear queda fijada; cambiar la politica no reescribe pendientes).
- Aprobacion: el actor debe tener el permiso `approve` Y ser aprobador segun la politica VIGENTE al aprobar (AP-25).
  Autoaprobacion solo si la politica la permite (AP-01/AP-26); con doble aprobacion el solicitante cuenta como UNA
  aprobacion y la otra debe venir de un aprobador distinto (AP-07, AP-36).
- Transiciones de estado con SELECT ... FOR UPDATE + UPDATE condicional (AP-14): el perdedor de una carrera recibe
  `RequestStateConflictError` (409).
- Cada transicion deja un evento inmutable con el actor. `reabierta` no existe en el CHECK de `event_type`
  (no se cambia el esquema): se registra como `reintentada` con `detail.action = "reabierta"`.
- Este modulo NUNCA escribe en el proveedor, salvo `apply_request`, que delega en `billing_apply.apply_change_request`.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.auth import Role, User
from app.models.billing import (
    PLATFORMS,
    REQUEST_TYPES,
    BillingChangeRequest,
    BillingChangeRequestEvent,
    BillingPolicy,
    BillingPolicyAudit,
    VpCalendarMark,
)
from app.services import billing_apply as ba
from app.services.billing_apply import (
    ApplyResult,
    InvalidRequestStateError,
    RequestNotFoundError,
    SubscriptionBlockedError,
)
from app.services.billing_plan import PENDING_STATES, PlanResult, plan_to_preview_json
from app.services.rbac import permission_codes

log = logging.getLogger(__name__)

PERM_REQUEST = "virtualpos.billing_changes.request"
PERM_APPROVE = "virtualpos.billing_changes.approve"
PERM_VIEW = "virtualpos.billing_changes.view"
PERM_POLICY = "virtualpos.billing_policy.manage"
ADMIN_ROLE = "admin"

OPEN_STATUSES = ("pendiente", "aprobada", "aplicando", "requiere_conciliacion")
REOPENABLE_STATUSES = ("fallida", "requiere_conciliacion")
_MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")

POLICY_FIELDS = (
    "approver_roles", "approver_user_ids", "self_approval_enabled", "dual_approval_enabled",
    "dual_threshold_subscriptions", "dual_threshold_variation_pct", "renewal_threshold_days",
    "request_expiry_days", "horizon_months", "window_days",
)
_INT_BOUNDS = {  # campo -> (minimo, maximo): minimos = CHECK del modelo; maximos = cotas de cordura
    "dual_threshold_subscriptions": (1, 100_000),
    "renewal_threshold_days": (1, 3650),
    "request_expiry_days": (1, 365),
    "horizon_months": (1, 60),
    "window_days": (1, 365),
}
_BOOL_FIELDS = ("self_approval_enabled", "dual_approval_enabled")


# ----------------------------- errores tipados -----------------------------


class BillingRequestError(Exception):
    """Base de los errores de este modulo. `code` es estable y lo expone la API."""

    code = "billing_request_error"


class InvalidRequestFieldsError(BillingRequestError):
    code = "invalid_fields"


class CommentRequiredError(BillingRequestError):
    code = "comment_required"


class SubscriptionUnknownError(BillingRequestError):
    code = "subscription_not_found"


class SubscriptionNotActiveError(BillingRequestError):
    code = "subscription_not_active"

    def __init__(self, status: str | None) -> None:
        self.status = status
        super().__init__("La suscripción no está ACTIVA; no admite cambios de cobro.")


class OpenRequestExistsError(BillingRequestError):
    code = "open_request_exists"

    def __init__(self, request_id: uuid.UUID | None, status: str | None) -> None:
        self.request_id = request_id
        self.status = status
        super().__init__("Ya existe una solicitud abierta para esta suscripción.")


class NoChangesError(BillingRequestError):
    code = "no_changes"

    def __init__(self, message: str = "Sin cambios: el estado actual ya coincide con lo solicitado.") -> None:
        super().__init__(message)


class PlanInvalidError(BillingRequestError):
    code = "plan_errors"

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        self.errors = errors
        super().__init__("El plan calculado contiene errores; no se puede crear la solicitud.")


class NotApproverError(BillingRequestError):
    code = "not_approver"

    def __init__(self, message: str = "No eres aprobador según la política vigente.") -> None:
        super().__init__(message)


class SelfApprovalNotAllowedError(BillingRequestError):
    code = "self_approval_not_allowed"

    def __init__(self) -> None:
        super().__init__("Autoaprobación no permitida por la política vigente.")


class DuplicateApproverError(BillingRequestError):
    code = "duplicate_approver"

    def __init__(self) -> None:
        super().__init__("Ya aprobaste esta solicitud; se necesita otro aprobador distinto.")


class RequestStateConflictError(BillingRequestError):
    """La solicitud no esta en el estado requerido (o fue decidida por otra operacion concurrente, AP-14)."""

    code = "invalid_request_state"

    def __init__(self, current: str, expected: Sequence[str]) -> None:
        self.current_status = current
        self.expected = tuple(expected)
        super().__init__(f"La solicitud está en estado {current!r}; se requiere {' o '.join(expected)}.")


class RequestExpiredError(BillingRequestError):
    code = "request_expired"

    def __init__(self) -> None:
        super().__init__("La solicitud expiró y ya no se puede aprobar.")


class NotAllowedError(BillingRequestError):
    code = "forbidden"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class PolicyValidationError(BillingRequestError):
    code = "policy_invalid"

    def __init__(self, code: str, message: str) -> None:
        self.policy_code = code
        super().__init__(message)


# ----------------------------- politica -----------------------------


def get_policy(db: Session, *, for_update: bool = False) -> BillingPolicy:
    """Politica vigente (fila unica). Si faltara (BD sin migrar el seed) se crea con los valores por defecto."""
    q = select(BillingPolicy).where(BillingPolicy.singleton.is_(True))
    if for_update:
        q = q.with_for_update().execution_options(populate_existing=True)
    policy = db.scalar(q)
    if policy is None:
        policy = BillingPolicy(singleton=True, approver_roles=[ADMIN_ROLE], approver_user_ids=[])
        db.add(policy)
        db.flush()
        db.refresh(policy)
    return policy


def policy_values(policy: BillingPolicy) -> dict[str, Any]:
    """Valores editables de la politica en forma JSON-serializable (snapshot / auditoria / respuesta)."""
    return {
        "approver_roles": sorted(policy.approver_roles or []),
        "approver_user_ids": sorted(str(x) for x in (policy.approver_user_ids or [])),
        "self_approval_enabled": bool(policy.self_approval_enabled),
        "dual_approval_enabled": bool(policy.dual_approval_enabled),
        "dual_threshold_subscriptions": int(policy.dual_threshold_subscriptions),
        "dual_threshold_variation_pct": float(policy.dual_threshold_variation_pct),
        "renewal_threshold_days": int(policy.renewal_threshold_days),
        "request_expiry_days": int(policy.request_expiry_days),
        "horizon_months": int(policy.horizon_months),
        "window_days": int(policy.window_days),
    }


def is_approver(user: User, policy: BillingPolicy) -> bool:
    """Aprobador = usuario activo con el permiso `approve` Y (rol en `approver_roles` O id en `approver_user_ids`)."""
    if not getattr(user, "is_active", True) or PERM_APPROVE not in permission_codes(user):
        return False
    roles = set(policy.approver_roles or [])
    ids = {str(x) for x in (policy.approver_user_ids or [])}
    return bool({r.name for r in user.roles} & roles) or str(user.id) in ids


def effective_approver_ids(db: Session, roles: Sequence[str], user_ids: Sequence[str]) -> set[uuid.UUID]:
    """Usuarios activos que serian aprobadores con esa configuracion (permiso `approve` + rol o id listado)."""
    conds = [User.id.in_([uuid.UUID(x) for x in user_ids])] if user_ids else []
    if roles:
        conds.append(User.roles.any(Role.name.in_(list(roles))))
    if not conds:
        return set()
    users = db.scalars(
        select(User).options(selectinload(User.roles).selectinload(Role.permissions))
        .where(User.is_active.is_(True), or_(*conds))
    ).all()
    return {u.id for u in users if PERM_APPROVE in permission_codes(u)}


def _validate_policy(db: Session, after: dict[str, Any], actor_id: uuid.UUID | None) -> dict[str, Any]:
    out = dict(after)
    for name in _BOOL_FIELDS:
        if not isinstance(out[name], bool):
            raise PolicyValidationError("invalid_value", f"{name} debe ser booleano.")
    for name, (lo, hi) in _INT_BOUNDS.items():
        value = out[name]
        if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
            raise PolicyValidationError("out_of_range", f"{name} debe ser un entero entre {lo} y {hi}.")
    try:
        pct = Decimal(str(out["dual_threshold_variation_pct"]))
    except (InvalidOperation, ValueError):
        raise PolicyValidationError("out_of_range", "dual_threshold_variation_pct debe ser numérico.") from None
    if not pct.is_finite() or not Decimal(0) <= pct <= Decimal("9999.99"):
        raise PolicyValidationError("out_of_range", "dual_threshold_variation_pct debe estar entre 0 y 9999.99.")
    out["dual_threshold_variation_pct"] = float(round(pct, 2))

    roles = out["approver_roles"]
    if not isinstance(roles, list) or any(not isinstance(r, str) or not r.strip() for r in roles):
        raise PolicyValidationError("invalid_value", "approver_roles debe ser una lista de nombres de rol.")
    out["approver_roles"] = sorted({r.strip() for r in roles})
    raw_ids = out["approver_user_ids"]
    if not isinstance(raw_ids, list):
        raise PolicyValidationError("invalid_value", "approver_user_ids debe ser una lista de ids de usuario.")
    try:
        ids = sorted({str(uuid.UUID(str(x))) for x in raw_ids})
    except ValueError:
        raise PolicyValidationError("invalid_value", "approver_user_ids contiene ids inválidos.") from None
    out["approver_user_ids"] = ids

    if not out["approver_roles"] and not ids:  # AP-23
        raise PolicyValidationError("no_approvers", "La política debe tener al menos un rol o usuario aprobador (AP-23).")
    if out["approver_roles"]:
        found = set(db.scalars(select(Role.name).where(Role.name.in_(out["approver_roles"]))))
        missing = sorted(set(out["approver_roles"]) - found)
        if missing:
            raise PolicyValidationError("unknown_role", f"Roles inexistentes: {', '.join(missing)}.")
    if ids:
        active = {str(u) for u in db.scalars(select(User.id).where(User.id.in_([uuid.UUID(x) for x in ids]), User.is_active.is_(True)))}
        bad = sorted(set(ids) - active)
        if bad:
            raise PolicyValidationError("unknown_user", f"Usuarios aprobadores inexistentes o inactivos: {', '.join(bad)}.")
    effective = effective_approver_ids(db, out["approver_roles"], ids)
    if not effective:  # AP-23: SIEMPRE al menos un aprobador EFECTIVO (activo, con el permiso `approve` y listado por rol o id)
        raise PolicyValidationError(
            "no_approvers",
            "La política no tendría ningún aprobador efectivo: hace falta al menos un usuario activo con el permiso "
            "'approve' que sea aprobador por rol o por id (AP-23).",
        )
    if out["self_approval_enabled"] is False:  # AP-24
        if not effective - ({actor_id} if actor_id else set()):
            raise PolicyValidationError(
                "no_other_approver",
                "Sin autoaprobación, las solicitudes de quien edita no tendrían quién las apruebe: "
                "no existe otro aprobador activo distinto (AP-24).",
            )
    if out["dual_approval_enabled"]:
        # El solicitante cuenta como UNA aprobacion solo con autoaprobacion; sin ella el solicitante puede ser uno de los
        # efectivos y aun asi deben quedar 2 distintos: hacen falta 3 (con autoaprobacion bastan 2).
        needed = 2 if out["self_approval_enabled"] else 3
        if len(effective) < needed:
            raise PolicyValidationError(
                "dual_insufficient_approvers",
                f"Con doble aprobación hacen falta al menos {needed} aprobadores efectivos distintos "
                f"(hay {len(effective)}).",
            )
    return out


def policy_effective_approvers(db: Session) -> set[uuid.UUID] | None:
    """Aprobadores efectivos de la politica vigente SIN crearla; None si aun no existe la fila (nada que proteger)."""
    policy = db.scalar(select(BillingPolicy).where(BillingPolicy.singleton.is_(True)))
    if policy is None:
        return None
    return effective_approver_ids(db, list(policy.approver_roles or []), [str(x) for x in (policy.approver_user_ids or [])])


def update_policy(db: Session, actor: User, patch: dict[str, Any], reason: str | None = None) -> BillingPolicy:
    """Edita la politica (parche parcial) y escribe `billing_policy_audit` en la MISMA transaccion (AP-35)."""
    unknown = sorted(set(patch) - set(POLICY_FIELDS))
    if unknown:
        raise PolicyValidationError("unknown_field", f"Campos no editables: {', '.join(unknown)}.")
    policy = get_policy(db, for_update=True)
    before = policy_values(policy)
    after = _validate_policy(db, {**before, **patch}, actor.id)
    if after == before:
        raise NoChangesError("La política no cambia con este parche.")
    policy.approver_roles = after["approver_roles"]
    policy.approver_user_ids = after["approver_user_ids"]
    policy.self_approval_enabled = after["self_approval_enabled"]
    policy.dual_approval_enabled = after["dual_approval_enabled"]
    policy.dual_threshold_subscriptions = after["dual_threshold_subscriptions"]
    policy.dual_threshold_variation_pct = Decimal(str(after["dual_threshold_variation_pct"]))
    policy.renewal_threshold_days = after["renewal_threshold_days"]
    policy.request_expiry_days = after["request_expiry_days"]
    policy.horizon_months = after["horizon_months"]
    policy.window_days = after["window_days"]
    policy.updated_by_user_id = actor.id
    clean_reason = (reason or "").strip() or None
    db.add(BillingPolicyAudit(
        policy_id=policy.id, changed_by_user_id=actor.id, before_values=before, after_values=after,
        reason=clean_reason, changed_at=datetime.now(UTC),
    ))
    db.commit()
    db.refresh(policy)
    log.info("billing_policy actualizada por %s (campos: %s)", actor.id, ", ".join(sorted(k for k in patch if before[k] != after[k])))
    return policy


def list_policy_audit(db: Session, *, limit: int = 50, offset: int = 0) -> tuple[list[BillingPolicyAudit], int]:
    total = db.scalar(select(func.count()).select_from(BillingPolicyAudit)) or 0
    rows = db.scalars(select(BillingPolicyAudit).order_by(BillingPolicyAudit.changed_at.desc(), BillingPolicyAudit.id)
                      .limit(limit).offset(offset)).all()
    return list(rows), total


def required_approvals(policy: BillingPolicy, *, subscriptions: int, variation_pct: float | None) -> int:
    """AP-07..AP-09: 2 solo con doble aprobacion ENCENDIDA y (suscripciones > umbral o variacion > umbral %)."""
    if not policy.dual_approval_enabled:
        return 1
    if subscriptions > int(policy.dual_threshold_subscriptions):
        return 2
    if variation_pct is not None and Decimal(str(variation_pct)) > Decimal(policy.dual_threshold_variation_pct):
        return 2
    return 1


# ----------------------------- creacion / vista previa -----------------------------


@dataclass
class RequestParams:
    request_type: str
    platform: str
    subscription_external_id: str
    new_amount: int | None = None
    new_charge_day: int | None = None
    new_charge_date: date | None = None
    horizon_months: int | None = None
    horizon_start_month: str | None = None
    requester_comment: str | None = None
    task_ref: str | None = None


@dataclass
class PreparedRequest:
    request: BillingChangeRequest  # transitorio (no agregado a la sesion)
    plan: PlanResult
    preview: dict[str, Any]
    policy: BillingPolicy
    approvals_required: int
    warnings: list[str] = field(default_factory=list)


def normalize_platform(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if raw in ("virtualpos", "vp", "vp1"):
        raw = "virtualpos1"
    elif raw in ("vp2",):
        raw = "virtualpos2"
    if raw not in PLATFORMS:
        raise InvalidRequestFieldsError(f"platform debe ser una de: {', '.join(PLATFORMS)}.")
    return raw


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 de febrero
        return d.replace(year=d.year + years, day=28)


def _month_index(ym: str) -> int:
    return int(ym[:4]) * 12 + int(ym[5:7]) - 1


def _validate_params(p: RequestParams, today: date) -> None:
    if p.request_type not in REQUEST_TYPES:
        raise InvalidRequestFieldsError(f"request_type debe ser uno de: {', '.join(REQUEST_TYPES)}.")
    if not (p.subscription_external_id or "").strip():
        raise InvalidRequestFieldsError("subscription_external_id es obligatorio.")
    if p.new_amount is not None and (isinstance(p.new_amount, bool) or not isinstance(p.new_amount, int) or p.new_amount <= 0):
        raise InvalidRequestFieldsError("new_amount debe ser un entero positivo.")
    if p.new_charge_day is not None and not 1 <= p.new_charge_day <= 31:
        raise InvalidRequestFieldsError("new_charge_day debe estar entre 1 y 31.")
    if p.horizon_months is not None and not 1 <= p.horizon_months <= 60:
        raise InvalidRequestFieldsError("horizon_months debe estar entre 1 y 60.")
    if p.horizon_start_month is not None:
        if not _MONTH_RE.match(p.horizon_start_month):
            raise InvalidRequestFieldsError("horizon_start_month debe tener formato YYYY-MM.")
        current = _month_index(today.strftime("%Y-%m"))
        if not current - 1 <= _month_index(p.horizon_start_month) <= current + 24:
            raise InvalidRequestFieldsError(
                "horizon_start_month debe estar entre el mes anterior al actual y 24 meses hacia adelante.")
    if p.new_charge_date is not None and not today + timedelta(days=1) <= p.new_charge_date <= _add_years(today, 5):
        raise InvalidRequestFieldsError("new_charge_date debe estar entre mañana y 5 años desde hoy (hora de Chile).")
    t = p.request_type
    if t == "change_amount":
        if p.new_amount is None:
            raise InvalidRequestFieldsError("change_amount requiere new_amount.")
        if p.new_charge_day is not None or p.new_charge_date is not None:
            raise InvalidRequestFieldsError("change_amount no admite new_charge_day ni new_charge_date.")
    elif t == "change_date":
        if p.new_charge_day is None:
            raise InvalidRequestFieldsError("change_date requiere new_charge_day.")
        if p.new_charge_date is not None:
            raise InvalidRequestFieldsError("change_date no admite new_charge_date.")
    elif t == "renew_calendar":
        if p.new_charge_day is not None or p.new_charge_date is not None:
            raise InvalidRequestFieldsError("renew_calendar no admite new_charge_day ni new_charge_date.")
    elif t == "one_off_charge":
        if p.new_amount is None or p.new_charge_date is None:
            raise InvalidRequestFieldsError("one_off_charge requiere new_amount y new_charge_date.")
        if p.new_charge_day is not None:
            raise InvalidRequestFieldsError("one_off_charge no admite new_charge_day.")
    if t != "one_off_charge" and p.task_ref is not None:
        raise InvalidRequestFieldsError("task_ref solo aplica a one_off_charge.")


async def _derive_current_amount(db: Session, platform: str, sub: str, today: date) -> int | None:
    """Monto vigente a partir del proveedor: el pendiente mas frecuente o, si no hay, el ultimo pagado/procesando."""
    items = await ba._fetch_charges(platform, sub)
    charges = ba._to_plan_charges(items, ba._alive_managed_ids(db, platform, sub))
    pending = [c.amount for c in charges if c.state in PENDING_STATES]
    if pending:
        return Counter(pending).most_common(1)[0][0]
    paid = [c for c in charges if c.state in ("pagado", "procesando", "paid", "processing") and c.charge_date <= today]
    return max(paid, key=lambda c: c.charge_date).amount if paid else None


async def prepare_request(db: Session, params: RequestParams, *, now: datetime | None = None) -> PreparedRequest:
    """Valida, resuelve defaults y calcula el plan con el estado ACTUAL del proveedor (solo lectura)."""
    p = params
    p.platform = normalize_platform(p.platform)
    p.subscription_external_id = p.subscription_external_id.strip()
    today = ba._chile_now(now).date()
    _validate_params(p, today)
    state = ba._subscription_state(db, p.platform, p.subscription_external_id)
    if state is None:
        raise SubscriptionUnknownError("Suscripción no encontrada.")
    if not ba.is_active_status(state[0]):
        raise SubscriptionNotActiveError(state[0])
    if ba.is_subscription_blocked(db, p.platform, p.subscription_external_id):
        raise SubscriptionBlockedError("La suscripción tiene cobros en conciliación pendiente; resuélvalo antes de pedir cambios.")

    policy = get_policy(db)
    amount = p.new_amount
    if amount is None:  # change_date / renew_calendar: el monto es el actual
        if p.request_type == "renew_calendar":
            mark = db.scalar(select(VpCalendarMark).where(
                VpCalendarMark.platform == p.platform, VpCalendarMark.subscription_external_id == p.subscription_external_id,
                VpCalendarMark.is_active.is_(True)))
            amount = int(mark.scheduled_amount) if mark is not None else None
        else:
            amount = await _derive_current_amount(db, p.platform, p.subscription_external_id, today)
        if amount is None:
            raise InvalidRequestFieldsError("No se pudo determinar el monto actual de la suscripción; indique new_amount.")

    horizon_start = p.horizon_start_month
    if horizon_start is None and p.request_type in ("change_amount", "change_date"):
        horizon_start = today.strftime("%Y-%m")  # se fija ahora: aprobar otro dia/mes no desplaza el horizonte
    snapshot: dict[str, Any] = {
        **policy_values(policy), "plan_external_id": state[1], "task_ref": p.task_ref,
    }
    req = BillingChangeRequest(
        id=uuid.uuid4(), request_type=p.request_type, platform=p.platform, subscription_external_id=p.subscription_external_id,
        status="pendiente", new_amount=Decimal(amount), new_charge_day=p.new_charge_day, new_charge_date=p.new_charge_date,
        horizon_months=p.horizon_months or int(policy.horizon_months), horizon_start_month=horizon_start,
        plan_preview={}, rules_snapshot=snapshot, requester_comment=(p.requester_comment or "").strip() or None,
        approvals_required=1, approvals_count=0, self_approved=False,
    )
    if p.request_type == "change_date":
        req.previous_amount = Decimal(amount)
    plan, charge_day = await ba.preview_change_with_day(db, req, now=now)
    req.previous_charge_day = charge_day  # el dia vigente queda fijo desde la solicitud (no cambia al aplicar)
    preview = plan_to_preview_json(plan)
    if plan.errors:
        raise PlanInvalidError(preview["errors"])
    if plan.noop:
        raise NoChangesError()
    summary = plan.summary
    if summary is not None and summary.previous_amount is not None and req.previous_amount is None:
        req.previous_amount = Decimal(summary.previous_amount)
    if p.request_type == "renew_calendar" and summary is not None:
        req.horizon_start_month = summary.horizon_start
    req.plan_preview = preview
    req.approvals_required = required_approvals(
        policy, subscriptions=1, variation_pct=summary.variation_pct if summary else None)
    return PreparedRequest(request=req, plan=plan, preview=preview, policy=policy, approvals_required=req.approvals_required)


def find_open_request(db: Session, platform: str, sub: str) -> BillingChangeRequest | None:
    return db.scalar(select(BillingChangeRequest).where(
        BillingChangeRequest.platform == platform, BillingChangeRequest.subscription_external_id == sub,
        BillingChangeRequest.status.in_(OPEN_STATUSES)).limit(1))


def _event(db: Session, req_id: uuid.UUID, event_type: str, actor_id: uuid.UUID | None, detail: dict[str, Any] | None = None) -> None:
    db.add(BillingChangeRequestEvent(
        request_id=req_id, event_type=event_type, actor_user_id=actor_id, detail=detail or {},
        created_at=datetime.now(UTC)))  # reloj real: orden estable dentro de una transaccion (igual que billing_apply)


def _utc(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    return now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)


async def create_request(
    db: Session, actor: User, params: RequestParams, *, now: datetime | None = None
) -> BillingChangeRequest:
    """Crea la solicitud (estado `pendiente`, o `aprobada` si se autoaprueba). Lee el proveedor; no escribe en el."""
    p_platform = normalize_platform(params.platform)
    existing = find_open_request(db, p_platform, (params.subscription_external_id or "").strip())
    if existing is not None:
        raise OpenRequestExistsError(existing.id, existing.status)
    prepared = await prepare_request(db, params, now=now)
    req, policy = prepared.request, prepared.policy
    created = _utc(now)
    req.requested_by_user_id = actor.id
    req.expires_at = created + timedelta(days=int(policy.request_expiry_days))
    summary = prepared.preview.get("summary") or {}
    db.add(req)
    db.flush()
    _event(db, req.id, "creada", actor.id, {
        "request_type": req.request_type, "approvals_required": req.approvals_required,
        "summary": {k: summary.get(k) for k in ("creates", "cancels", "covered_months", "manual_review_months", "variation_pct")},
    })
    if policy.self_approval_enabled and is_approver(actor, policy):  # AP-02 / AP-36
        req.approvals_count = 1
        req.self_approved = True
        final = req.approvals_count >= req.approvals_required
        if final:
            req.status = "aprobada"
            req.approved_by_user_id = actor.id
            req.decided_at = created
        _event(db, req.id, "autoaprobada", actor.id, {
            "self_approved": True, "approvals_count": req.approvals_count, "approvals_required": req.approvals_required,
            "final": final})
    try:
        db.commit()
    except IntegrityError:  # carrera con otra creacion: indice unico parcial
        db.rollback()
        other = find_open_request(db, req.platform, req.subscription_external_id)
        raise OpenRequestExistsError(other.id if other else None, other.status if other else None) from None
    db.refresh(req)
    return req


# ----------------------------- transiciones -----------------------------


def _lock_request(db: Session, request_id: uuid.UUID) -> BillingChangeRequest:
    req = db.scalar(select(BillingChangeRequest).where(BillingChangeRequest.id == request_id)
                    .with_for_update().execution_options(populate_existing=True))
    if req is None:
        raise RequestNotFoundError(str(request_id))
    return req


def _approver_ids(db: Session, request_id: uuid.UUID) -> set[uuid.UUID]:
    """Aprobadores de la ronda vigente: tras una reapertura (evento `reintentada`) las aprobaciones anteriores no cuentan."""
    last_reopen = db.scalar(select(func.max(BillingChangeRequestEvent.created_at)).where(
        BillingChangeRequestEvent.request_id == request_id, BillingChangeRequestEvent.event_type == "reintentada"))
    q = select(BillingChangeRequestEvent.actor_user_id).where(
        BillingChangeRequestEvent.request_id == request_id,
        BillingChangeRequestEvent.event_type.in_(("aprobada", "autoaprobada")))
    if last_reopen is not None:
        q = q.where(BillingChangeRequestEvent.created_at > last_reopen)
    return {a for a in db.scalars(q) if a is not None}


def _clean_comment(comment: str | None, *, required: bool) -> str | None:
    text = (comment or "").strip()
    if required and not text:
        raise CommentRequiredError("El comentario es obligatorio y no puede estar vacío.")
    return text or None


def _require_approver(db: Session, actor: User, request_id: uuid.UUID, action: str) -> BillingPolicy:
    policy = get_policy(db)
    if not is_approver(actor, policy):
        # No existe tipo de evento para intentos denegados (CHECK de event_type): queda en el log, sin PII.
        log.warning("billing intento denegado: accion=%s solicitud=%s usuario=%s", action, request_id, actor.id)
        raise NotApproverError()
    return policy


def approve(db: Session, request_id: uuid.UUID, actor: User, comment: str | None = None, *, now: datetime | None = None) -> BillingChangeRequest:
    """Aprueba (o autoaprueba) una solicitud `pendiente`. Con doble aprobacion hacen falta aprobadores DISTINTOS."""
    text = _clean_comment(comment, required=False)
    when = _utc(now)
    req = _lock_request(db, request_id)
    if req.status != "pendiente":
        db.rollback()
        raise RequestStateConflictError(req.status, ("pendiente",))
    if req.expires_at is not None and req.expires_at <= when:  # AP-10: aprobar una vencida => expirada
        _expire_one(db, req, when)
        db.commit()
        raise RequestExpiredError()
    policy = _require_approver(db, actor, req.id, "approve")
    is_self = actor.id == req.requested_by_user_id
    if is_self and not policy.self_approval_enabled:  # AP-01 / AP-26: se evalua al aprobar
        log.warning("billing autoaprobacion denegada: solicitud=%s usuario=%s", req.id, actor.id)
        db.rollback()
        raise SelfApprovalNotAllowedError()
    if actor.id in _approver_ids(db, req.id):
        db.rollback()
        raise DuplicateApproverError()
    new_count = int(req.approvals_count) + 1
    final = new_count >= int(req.approvals_required)
    values: dict[str, Any] = {
        "approvals_count": new_count, "self_approved": bool(req.self_approved) or is_self, "updated_at": func.now()}
    if final:
        values.update(status="aprobada", approved_by_user_id=actor.id, decided_at=when)
    updated = db.execute(
        update(BillingChangeRequest)
        .where(BillingChangeRequest.id == req.id, BillingChangeRequest.status == "pendiente",
               BillingChangeRequest.approvals_count == req.approvals_count)  # AP-14: UPDATE condicional
        .values(**values).execution_options(synchronize_session=False)
    ).rowcount
    if updated != 1:
        db.rollback()
        raise RequestStateConflictError(_current_status(db, request_id), ("pendiente",))
    _event(db, req.id, "autoaprobada" if is_self else "aprobada", actor.id, {
        "approvals_count": new_count, "approvals_required": int(req.approvals_required), "final": final,
        "self_approved": is_self, "comment": text})
    db.commit()
    db.refresh(req)
    return req


def _current_status(db: Session, request_id: uuid.UUID) -> str:
    return str(db.scalar(select(BillingChangeRequest.status).where(BillingChangeRequest.id == request_id)) or "desconocido")


def reject(db: Session, request_id: uuid.UUID, actor: User, comment: str | None, *, now: datetime | None = None) -> BillingChangeRequest:
    """Rechaza una solicitud `pendiente`. Comentario obligatorio (AP-11; el CHECK de BD tambien lo exige)."""
    text = _clean_comment(comment, required=True)
    req = _lock_request(db, request_id)
    if req.status != "pendiente":
        db.rollback()
        raise RequestStateConflictError(req.status, ("pendiente",))
    _require_approver(db, actor, req.id, "reject")
    updated = db.execute(
        update(BillingChangeRequest)
        .where(BillingChangeRequest.id == req.id, BillingChangeRequest.status == "pendiente")
        .values(status="rechazada", decision_comment=text, decided_at=_utc(now), updated_at=func.now())
        .execution_options(synchronize_session=False)
    ).rowcount
    if updated != 1:
        db.rollback()
        raise RequestStateConflictError(_current_status(db, request_id), ("pendiente",))
    _event(db, req.id, "rechazada", actor.id, {"comment": text})
    db.commit()
    db.refresh(req)
    return req


def withdraw(db: Session, request_id: uuid.UUID, actor: User, comment: str | None = None, *, now: datetime | None = None) -> BillingChangeRequest:
    """Retira una solicitud `pendiente`: solo su solicitante o un admin (AP-33)."""
    text = _clean_comment(comment, required=False)
    req = _lock_request(db, request_id)
    # Propiedad ANTES que estado: quien no puede retirar no debe enterarse del estado de la solicitud (403 antes que 409).
    if actor.id != req.requested_by_user_id and not any(r.name == ADMIN_ROLE for r in actor.roles):
        db.rollback()
        raise NotAllowedError("Solo el solicitante o un administrador puede retirar la solicitud.")
    if req.status != "pendiente":
        db.rollback()
        raise RequestStateConflictError(req.status, ("pendiente",))
    updated = db.execute(
        update(BillingChangeRequest)
        .where(BillingChangeRequest.id == req.id, BillingChangeRequest.status == "pendiente")
        .values(status="retirada", decided_at=_utc(now), updated_at=func.now())
        .execution_options(synchronize_session=False)
    ).rowcount
    if updated != 1:
        db.rollback()
        raise RequestStateConflictError(_current_status(db, request_id), ("pendiente",))
    _event(db, req.id, "retirada", actor.id, {"comment": text})
    db.commit()
    db.refresh(req)
    return req


def reopen(db: Session, request_id: uuid.UUID, actor: User, comment: str | None, *, now: datetime | None = None) -> BillingChangeRequest:
    """`fallida` / `requiere_conciliacion` -> `aprobada`, explicito, con comentario obligatorio. Sin reintento automatico.

    Quien: SIEMPRE un aprobador segun la politica vigente (el permiso `billing_policy.manage` por si solo no basta).
    La suscripcion no debe estar bloqueada por cobros en conciliacion de OTRA solicitud. Se reinician las aprobaciones
    (`approvals_count = 0`) y se recalcula `approvals_required` con la politica vigente: si ahora exige 2, vuelve a
    `pendiente` (con nuevo vencimiento) para reunir aprobadores distintos; si exige 1, queda `aprobada` (la reapertura la
    hace un aprobador). Evento `reintentada` con `detail.action = "reabierta"` y el estado previo (el CHECK de BD no
    admite un tipo `reabierta`).
    """
    text = _clean_comment(comment, required=True)
    req = _lock_request(db, request_id)
    if req.status not in REOPENABLE_STATUSES:
        db.rollback()
        raise RequestStateConflictError(req.status, REOPENABLE_STATUSES)
    policy = _require_approver(db, actor, req.id, "reopen")
    if ba.is_subscription_blocked(db, req.platform, req.subscription_external_id, exclude_request=req.id):
        db.rollback()
        raise SubscriptionBlockedError("La suscripción tiene cobros en conciliación pendiente de otra solicitud.")
    previous_status = req.status
    previous_error = ba.reduce_stored_error(req.error_message)
    previous_count, previous_required = int(req.approvals_count), int(req.approvals_required)
    summary = (req.plan_preview or {}).get("summary") or {}
    variation = summary.get("variation_pct")
    required = required_approvals(policy, subscriptions=1, variation_pct=float(variation) if variation is not None else None)
    when = _utc(now)
    new_status = "aprobada" if required == 1 else "pendiente"
    values: dict[str, Any] = {
        "status": new_status, "error_message": None, "approvals_count": 0, "approvals_required": required,
        "decided_at": when if new_status == "aprobada" else None, "updated_at": func.now()}
    if new_status == "pendiente":
        values["expires_at"] = when + timedelta(days=int(policy.request_expiry_days))
    try:
        with db.begin_nested():  # el indice unico de "una abierta por suscripcion" puede rechazar el UPDATE
            updated = db.execute(
                update(BillingChangeRequest)
                .where(BillingChangeRequest.id == req.id, BillingChangeRequest.status == previous_status)
                .values(**values)
                .execution_options(synchronize_session=False)
            ).rowcount
    except IntegrityError:
        db.rollback()
        raise OpenRequestExistsError(None, None) from None
    if updated != 1:
        db.rollback()
        raise RequestStateConflictError(_current_status(db, request_id), REOPENABLE_STATUSES)
    _event(db, req.id, "reintentada", actor.id, {
        "action": "reabierta", "from_status": previous_status, "to_status": new_status, "comment": text,
        "previous_error": previous_error, "previous_approvals_count": previous_count,
        "previous_approvals_required": previous_required, "new_approvals_required": required})
    db.commit()
    db.refresh(req)
    return req


def _expire_one(db: Session, req: BillingChangeRequest, when: datetime) -> None:
    db.execute(update(BillingChangeRequest)
               .where(BillingChangeRequest.id == req.id, BillingChangeRequest.status == "pendiente")
               .values(status="expirada", decided_at=when, updated_at=func.now())
               .execution_options(synchronize_session=False))
    _event(db, req.id, "expirada", None, {"expires_at": req.expires_at.isoformat() if req.expires_at else None})


def expire_pending_requests(db: Session, now: datetime | None = None) -> list[uuid.UUID]:
    """Pasa a `expirada` las `pendiente` con `expires_at <= now` (limite INCLUSIVO). Idempotente.

    La invoca el job `billing_expire_requests` del scheduler (cada hora, minuto 10; ver `app/scheduler/engine.py`).
    Evento `expirada` con actor NULL (sistema).
    """
    when = _utc(now)
    rows = db.execute(
        update(BillingChangeRequest)
        .where(BillingChangeRequest.status == "pendiente", BillingChangeRequest.expires_at.is_not(None),
               BillingChangeRequest.expires_at <= when)
        .values(status="expirada", decided_at=when, updated_at=func.now())
        .returning(BillingChangeRequest.id, BillingChangeRequest.expires_at)
        .execution_options(synchronize_session=False)
    ).all()
    for rid, expires_at in rows:
        _event(db, rid, "expirada", None, {"expires_at": expires_at.isoformat() if expires_at else None})
    db.commit()
    return [r[0] for r in rows]


async def apply_request(
    db: Session, request_id: uuid.UUID, actor: User, *, accept_drift: bool = False, now: datetime | None = None
) -> ApplyResult:
    """Ejecuta una solicitud `aprobada` (delegado en billing_apply). El actor debe ser aprobador vigente."""
    req = db.get(BillingChangeRequest, request_id)
    if req is None:
        raise RequestNotFoundError(str(request_id))
    _require_approver(db, actor, request_id, "apply")
    return await ba.apply_change_request(db, request_id, actor_user_id=actor.id, now=now, accept_drift=accept_drift)


# ----------------------------- consulta -----------------------------


@dataclass
class RequestFilters:
    statuses: list[str] | None = None
    platform: str | None = None
    subscription_external_id: str | None = None
    request_type: str | None = None
    requested_by_user_id: uuid.UUID | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    limit: int = 50
    offset: int = 0


def list_requests(db: Session, f: RequestFilters) -> tuple[list[BillingChangeRequest], int]:
    q = select(BillingChangeRequest)
    if f.statuses:
        q = q.where(BillingChangeRequest.status.in_(f.statuses))
    if f.platform:
        q = q.where(BillingChangeRequest.platform == normalize_platform(f.platform))
    if f.subscription_external_id:
        q = q.where(BillingChangeRequest.subscription_external_id == f.subscription_external_id)
    if f.request_type:
        q = q.where(BillingChangeRequest.request_type == f.request_type)
    if f.requested_by_user_id:
        q = q.where(BillingChangeRequest.requested_by_user_id == f.requested_by_user_id)
    if f.created_from:
        q = q.where(BillingChangeRequest.created_at >= f.created_from)
    if f.created_to:
        q = q.where(BillingChangeRequest.created_at <= f.created_to)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(BillingChangeRequest.created_at.desc(), BillingChangeRequest.id)
                      .limit(f.limit).offset(f.offset)).all()
    return list(rows), total


def get_request(db: Session, request_id: uuid.UUID) -> BillingChangeRequest:
    req = db.get(BillingChangeRequest, request_id)
    if req is None:
        raise RequestNotFoundError(str(request_id))
    return req


def get_events(db: Session, request_id: uuid.UUID) -> list[BillingChangeRequestEvent]:
    return list(db.scalars(select(BillingChangeRequestEvent).where(BillingChangeRequestEvent.request_id == request_id)
                           .order_by(BillingChangeRequestEvent.created_at, BillingChangeRequestEvent.id)))


def usernames(db: Session, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    return {uid: name for uid, name in db.execute(select(User.id, User.username).where(User.id.in_(wanted)))}


def list_requesters(db: Session) -> list[tuple[uuid.UUID, str]]:
    """Solicitantes distintos (id, username) que figuran en billing_change_requests; sin otros datos del usuario."""
    stmt = (
        select(User.id, User.username)
        .where(User.id.in_(select(BillingChangeRequest.requested_by_user_id)))
        .order_by(User.username, User.id)
    )
    return [(uid, name) for uid, name in db.execute(stmt)]


__all__ = [
    "ADMIN_ROLE",
    "PERM_APPROVE",
    "PERM_POLICY",
    "PERM_REQUEST",
    "PERM_VIEW",
    "BillingRequestError",
    "CommentRequiredError",
    "DuplicateApproverError",
    "InvalidRequestFieldsError",
    "InvalidRequestStateError",
    "NoChangesError",
    "NotAllowedError",
    "NotApproverError",
    "OpenRequestExistsError",
    "PlanInvalidError",
    "PolicyValidationError",
    "PreparedRequest",
    "RequestExpiredError",
    "RequestFilters",
    "RequestNotFoundError",
    "RequestParams",
    "RequestStateConflictError",
    "SelfApprovalNotAllowedError",
    "SubscriptionBlockedError",
    "SubscriptionNotActiveError",
    "SubscriptionUnknownError",
    "apply_request",
    "approve",
    "create_request",
    "effective_approver_ids",
    "expire_pending_requests",
    "find_open_request",
    "get_events",
    "get_policy",
    "get_request",
    "is_approver",
    "list_policy_audit",
    "list_requesters",
    "list_requests",
    "normalize_platform",
    "policy_effective_approvers",
    "policy_values",
    "prepare_request",
    "reject",
    "reopen",
    "required_approvals",
    "update_policy",
    "usernames",
    "withdraw",
]
