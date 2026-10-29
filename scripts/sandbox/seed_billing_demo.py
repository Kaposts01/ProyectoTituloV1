"""Siembra SINTETICA e idempotente de datos de la opcion A (cambios de cobro VirtualPOS) en el SANDBOX.

Uso (desde la raiz del repo, con el venv del proyecto):

    $env:APP_ENV='sandbox'
    .venv\\Scripts\\python.exe scripts\\sandbox\\seed_billing_demo.py

Que siembra (todo marcado con el prefijo ``DEMO-``; ningun dato personal ni suscripcion real):
- Suscripciones ficticias ``DEMO-SUB-001``... (plataforma virtualpos1), montos y fechas ficticios, relativos a "hoy" (Chile).
- Solicitudes (``billing_change_requests``) en TODOS los estados (pendiente [una con vencimiento proximo y otra con doble
  aprobacion a medias], aprobada, ejecutada, fallida, requiere_conciliacion, rechazada, retirada, expirada, no_ejecutable)
  y de los 4 tipos, cada una con su ``plan_preview`` calculado con ``billing_plan.build_plan`` sobre cobros SINTETICOS
  (incluye ``manual_review`` por ``replacement_outside_month``, ``kept_due_today`` y warnings) y su linea de tiempo
  coherente de eventos (``billing_change_request_events``), con los mismos tipos y detalles que escribe el servicio.
- Cobros gestionados (``vp_managed_charges``) de las solicitudes ejecutadas / en conciliacion.
- Marcas de calendario (``vp_calendar_marks``) y tareas de renovacion (``billing_renewal_tasks``): abierta de prioridad
  alta, abierta normal, vencida, cerrada, abierta con ``data_stale`` y una ``no_aplica``.
- Dos filas de auditoria de politica (``billing_policy_audit``, motivo con prefijo ``DEMO-``) y, si falta, la fila de
  politica (``billing_policy``) con los valores por defecto.
- Solicitante / actor: el usuario ACTIVO con rol ``admin`` que ya existe en la base sandbox (no crea usuarios ni claves).

Seguridad (falla cerrado):
- Fija ``APP_ENV=sandbox`` ANTES de importar ``app.*`` (la configuracion se lee al importar) y aborta si la base conectada
  no contiene ``sandbox`` o ``qa`` en su nombre, si se llama ``crm`` o si ``current_database()`` no lo confirma.
- No ejecuta Alembic, no llama a proveedores y no escribe fuera de las tablas de billing indicadas.

Idempotencia: una solicitud/marca/tarea/cobro/auditoria se omite si ya existe (por ``subscription_external_id``,
``charge_id`` o ``reason`` con prefijo ``DEMO-``). Informa filas creadas y omitidas por tabla.

LIMPIEZA: NO esta implementada. ``billing_change_request_events`` y ``billing_policy_audit`` son inmutables (trigger de BD
impide UPDATE/DELETE fila por fila), y las solicitudes tienen eventos que las referencian. En el sandbox la unica forma de
limpiar es un TRUNCATE manual y explicito de esas tablas (p. ej. ``TRUNCATE billing_change_request_events,
billing_policy_audit, vp_managed_charges, billing_renewal_tasks, vp_calendar_marks, billing_change_requests``), SOLO en la
base sandbox y por decision del usuario. Nunca en ``crm``.
"""

from __future__ import annotations

import calendar
import os
import sys
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

# 1) Entorno: ANTES de importar cualquier modulo `app.*` (la configuracion lee APP_ENV al importarse).
os.environ["APP_ENV"] = "sandbox"
ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)  # el .env se resuelve relativo al directorio actual
sys.path.insert(0, str(ROOT))

from sqlalchemy import select, text  # noqa: E402

import app.models.write_run  # noqa: E402,F401  (registra la tabla destino de la FK write_run_id)
from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.models.auth import Role, User  # noqa: E402
from app.models.billing import (  # noqa: E402
    BillingChangeRequest,
    BillingChangeRequestEvent,
    BillingPolicy,
    BillingPolicyAudit,
    BillingRenewalTask,
    VpCalendarMark,
    VpManagedCharge,
)
from app.services.billing_plan import (  # noqa: E402
    PlanCharge,
    PlanInput,
    build_plan,
    month_date,
    plan_to_preview_json,
)
from app.services.rejected_month import now_chile  # noqa: E402

PREFIX = "DEMO-"
PLATFORM = "virtualpos1"
HORIZON = 12
EXPIRY_DAYS = 7
SPEC_TO_PLAN_TYPE = {"one_off_charge": "one_off"}

POLICY_DEFAULTS: dict[str, Any] = {
    "approver_roles": ["admin"],
    "approver_user_ids": [],
    "self_approval_enabled": True,
    "dual_approval_enabled": False,
    "dual_threshold_subscriptions": 20,
    "dual_threshold_variation_pct": 50.0,
    "renewal_threshold_days": 60,
    "request_expiry_days": EXPIRY_DAYS,
    "horizon_months": HORIZON,
    "window_days": 31,
}


# ----------------------------- guardas -----------------------------


def fail(msg: str) -> None:
    print(f"ABORTADO: {msg}", file=sys.stderr)
    raise SystemExit(2)


def guard_sandbox() -> str:
    """Aborta salvo que la base conectada sea claramente sandbox/qa. Devuelve el nombre de la base."""
    if settings.env_mode not in ("sandbox", "qa"):
        fail(f"APP_ENV efectivo es {settings.env_mode!r}; se exige sandbox o qa.")
    name = (engine.url.database or "").lower()
    if name == "crm" or not ("sandbox" in name or "qa" in name):
        fail("la base configurada no contiene 'sandbox' o 'qa' en su nombre (o es 'crm'). No se escribe nada.")
    with engine.connect() as conn:
        live = (conn.execute(text("SELECT current_database()")).scalar() or "").lower()
    if live != name or live == "crm" or not ("sandbox" in live or "qa" in live):
        fail("current_database() no coincide con una base sandbox/qa. No se escribe nada.")
    return live


# ----------------------------- calendario sintetico -----------------------------

NOW = datetime.now(UTC)
TODAY = now_chile().date()
CUR = (TODAY.year, TODAY.month)


def add_months(ym: tuple[int, int], n: int) -> tuple[int, int]:
    idx = ym[0] * 12 + (ym[1] - 1) + n
    return idx // 12, idx % 12 + 1


def fmt(ym: tuple[int, int]) -> str:
    return f"{ym[0]:04d}-{ym[1]:02d}"


def sub_id(n: int) -> str:
    return f"{PREFIX}SUB-{n:03d}"


def charges(
    n: int, day: int, amount: int, *, first: tuple[int, int], count: int, crm: bool = False,
    paid_through: date | None = None, extra: tuple[PlanCharge, ...] = (),
) -> tuple[PlanCharge, ...]:
    """Calendario mensual sintetico: cobros con fecha < `paid_through` (default hoy) quedan pagados, el resto pendientes."""
    limit = paid_through or TODAY
    out: list[PlanCharge] = []
    for i in range(count):
        ym = add_months(first, i)
        d = month_date(ym, day)
        tag = f"{ym[0]}{ym[1]:02d}"
        out.append(PlanCharge(
            charge_id=f"{PREFIX}CH-{n:03d}-{tag}", status="pagado" if d < limit else "pendiente", charge_date=d,
            amount=amount, internal_code=f"{sub_id(n)}-{tag}-{amount}" if crm else None, is_crm=crm,
        ))
    return (*out, *extra)


# ----------------------------- especificacion de escenarios -----------------------------


@dataclass
class Scenario:
    n: int
    request_type: str  # change_amount | change_date | renew_calendar | one_off_charge
    status: str
    kind: str  # pendiente | pendiente_dual | aprobada | ejecutada | fallida | conciliacion | no_ejecutable | rechazada | retirada | expirada
    plan_input: PlanInput
    new_amount: int | None
    previous_amount: int | None
    previous_day: int | None
    new_day: int | None = None
    new_date: date | None = None
    horizon_start_month: str | None = None
    created_ago: timedelta = timedelta(days=2)
    expires_in: timedelta | None = None  # None => created + 7 dias
    comment: str | None = None  # comentario del solicitante
    decision_comment: str | None = None
    error_label: str | None = None
    snapshot: dict[str, Any] = field(default_factory=dict)
    mark: bool = False  # sembrar marca de calendario (solicitud que dejo calendario CRM)
    managed: bool = False  # sembrar cobros gestionados con los 'create' del plan
    extras: dict[str, Any] = field(default_factory=dict)


def build_scenarios() -> list[Scenario]:
    prev = add_months(CUR, -1)
    first = add_months(CUR, -4)
    sc: list[Scenario] = []

    def pi(n: int, rtype: str, amount: int, chs: tuple[PlanCharge, ...], **kw: Any) -> PlanInput:
        return PlanInput(
            request_type=SPEC_TO_PLAN_TYPE.get(rtype, rtype), subscription_external_id=sub_id(n), platform=PLATFORM,
            new_amount=amount, charges=chs, horizon_months=HORIZON, window_days=31, today=TODAY, **kw,
        )

    # 001 pendiente con vencimiento proximo (menos de 24 h)
    sc.append(Scenario(
        1, "change_amount", "pendiente", "pendiente", pi(1, "change_amount", 12000, charges(1, 10, 10000, first=first, count=18)),
        12000, 10000, 10, horizon_start_month=fmt(CUR), created_ago=timedelta(days=6, hours=4),
        expires_in=timedelta(hours=20), comment="Ajuste de cuota solicitado por el socio (ejemplo ficticio).",
    ))
    # 002 pendiente con doble aprobacion a medias (variacion > umbral)
    sc.append(Scenario(
        2, "change_amount", "pendiente", "pendiente_dual", pi(2, "change_amount", 18000, charges(2, 15, 10000, first=first, count=18)),
        18000, 10000, 15, horizon_start_month=fmt(CUR), created_ago=timedelta(days=2),
        snapshot={"dual_approval_enabled": True}, comment="Aumento grande: requiere segunda aprobacion (ejemplo ficticio).",
    ))
    # 003 aprobada: cambio de fecha con pendiente fechado HOY (kept_due_today) y mes con dos pendientes (warnings)
    new_day = 15 if TODAY.day != 15 else 20
    dup_ym = add_months(CUR, 2)
    dup = PlanCharge(
        charge_id=f"{PREFIX}CH-003-DUP", status="pendiente", charge_date=month_date(dup_ym, 5), amount=10000,
    )
    sc.append(Scenario(
        3, "change_date", "aprobada", "aprobada",
        pi(3, "change_date", 10000, charges(3, TODAY.day, 10000, first=first, count=18, extra=(dup,)),
           new_charge_day=new_day, charge_day=TODAY.day),
        10000, 10000, TODAY.day, new_day=new_day, horizon_start_month=fmt(CUR), created_ago=timedelta(hours=3),
        comment="Cambio de dia de cobro (ejemplo ficticio).",
    ))
    # 004 renovacion ejecutada (calendario del CRM extendido)
    renew_first = add_months(CUR, -3)
    sc.append(Scenario(
        4, "renew_calendar", "ejecutada", "ejecutada",
        pi(4, "renew_calendar", 15000, charges(4, 5, 15000, first=renew_first, count=5, crm=True), charge_day=5),
        15000, None, 5, created_ago=timedelta(days=5), mark=True, managed=True,
    ))
    # 005 fallida: error del proveedor (etiqueta tecnica corta)
    sc.append(Scenario(
        5, "change_amount", "fallida", "fallida", pi(5, "change_amount", 9500, charges(5, 12, 8000, first=first, count=18)),
        9500, 8000, 12, horizon_start_month=fmt(CUR), created_ago=timedelta(days=3), error_label="VirtualPOSAPIError E-113",
    ))
    # 006 cobro puntual con conciliacion pendiente
    sc.append(Scenario(
        6, "one_off_charge", "requiere_conciliacion", "conciliacion",
        pi(6, "one_off_charge", 5000, charges(6, 10, 10000, first=first, count=18), one_off_date=TODAY + timedelta(days=10)),
        5000, None, None, new_date=TODAY + timedelta(days=10), created_ago=timedelta(days=1),
        error_label="ReadTimeout", managed=True, comment="Cobro unico por actividad (ejemplo ficticio).",
    ))
    # 007 rechazada con comentario
    sc.append(Scenario(
        7, "change_amount", "rechazada", "rechazada", pi(7, "change_amount", 30000, charges(7, 20, 12000, first=first, count=18)),
        30000, 12000, 20, horizon_start_month=fmt(CUR), created_ago=timedelta(days=4),
        snapshot={"self_approval_enabled": False}, decision_comment="Monto fuera de lo acordado con el socio; verificar y volver a solicitar.",
    ))
    # 008 retirada
    sc.append(Scenario(
        8, "change_date", "retirada", "retirada", pi(8, "change_date", 8000, charges(8, 12, 8000, first=first, count=18), new_charge_day=3, charge_day=12),
        8000, 8000, 12, new_day=3, horizon_start_month=fmt(CUR), created_ago=timedelta(days=2, hours=5),
        decision_comment="Solicitud retirada por el solicitante: el socio desistio.",
    ))
    # 009 expirada (sin decision a tiempo)
    sc.append(Scenario(
        9, "change_amount", "expirada", "expirada", pi(9, "change_amount", 11000, charges(9, 8, 9000, first=first, count=18)),
        11000, 9000, 8, horizon_start_month=fmt(CUR), created_ago=timedelta(days=12), expires_in=timedelta(days=-5),
    ))
    # 010 no ejecutable (el plan de la suscripcion cambio tras aprobar)
    sc.append(Scenario(
        10, "change_amount", "no_ejecutable", "no_ejecutable", pi(10, "change_amount", 20000, charges(10, 18, 25000, first=first, count=18)),
        20000, 25000, 18, horizon_start_month=fmt(CUR), created_ago=timedelta(days=6), error_label="plan_changed",
    ))
    # 011 ejecutada con manual_review por replacement_outside_month (mes anterior vencido <= ventana, reemplazo cae fuera del mes)
    day11 = calendar.monthrange(*prev)[1]
    sc.append(Scenario(
        11, "change_amount", "ejecutada", "ejecutada",
        pi(11, "change_amount", 14000, charges(11, day11, 10000, first=first, count=18, paid_through=date(prev[0], prev[1], 1)),
           effective_month=fmt(prev)),
        14000, 10000, day11, horizon_start_month=fmt(prev), created_ago=timedelta(days=1, hours=2), mark=True, managed=True,
        comment="Ajuste con un mes vencido que requiere revision manual (ejemplo ficticio).",
    ))
    return sc


# ----------------------------- construccion de filas -----------------------------


@dataclass
class Stats:
    created: Counter = field(default_factory=Counter)
    skipped: Counter = field(default_factory=Counter)

    def add(self, table: str, ok: bool) -> None:
        (self.created if ok else self.skipped)[table] += 1


def event(req_id: uuid.UUID, kind: str, actor: uuid.UUID | None, at: datetime, detail: dict[str, Any]) -> BillingChangeRequestEvent:
    return BillingChangeRequestEvent(request_id=req_id, event_type=kind, actor_user_id=actor, detail=detail, created_at=at)


def build_events(s: Scenario, req_id: uuid.UUID, admin: uuid.UUID, created: datetime, preview: dict[str, Any],
                 expires_at: datetime, approvals_required: int) -> tuple[list[BillingChangeRequestEvent], datetime | None]:
    """Eventos como los escribe el servicio (billing_requests / billing_apply). Devuelve (eventos, instante de la aplicacion)."""
    summary = preview.get("summary") or {}
    keys = ("creates", "cancels", "covered_months", "manual_review_months", "variation_pct")
    evs = [event(req_id, "creada", admin, created, {
        "request_type": s.request_type, "approvals_required": approvals_required, "summary": {k: summary.get(k) for k in keys}})]
    t_auto = created + timedelta(seconds=1)
    t_decide = created + timedelta(minutes=2)

    def auto(final: bool) -> BillingChangeRequestEvent:
        return event(req_id, "autoaprobada", admin, t_auto, {
            "self_approved": True, "approvals_count": 1, "approvals_required": approvals_required, "final": final})

    k = s.kind
    applied_at: datetime | None = None
    created_ids = [f"{PREFIX}MC-{s.n:03d}-{a['month'].replace('-', '')}" for a in preview.get("create", [])]
    if k == "pendiente_dual":
        evs.append(auto(False))
    elif k in ("aprobada", "ejecutada", "fallida", "conciliacion", "no_ejecutable"):
        evs.append(auto(True))
        t_apply = t_decide + timedelta(minutes=5)
        if k in ("ejecutada", "fallida", "conciliacion"):
            evs.append(event(req_id, "aplicando", admin, t_apply, {"write_run_id": None, "drift_accepted": None}))
        if k == "ejecutada":
            applied_at = t_apply + timedelta(seconds=40)
            evs.append(event(req_id, "aplicada", admin, applied_at, {
                "created": created_ids, "cancelled": [a.get("charge_id") for a in preview.get("cancel", [])],
                "covered_late_months": [], "manual_review_months": [m["month"] for m in preview.get("manual_review", [])],
                "calendar_mark": {"last_scheduled_month": preview["summary"]["horizon_end"], "charge_day": s.previous_day,
                                  "amount": s.new_amount},
                "write_run_id": None}))
        elif k == "fallida":
            evs.append(event(req_id, "fallida", admin, t_apply + timedelta(seconds=12), {
                "failed_create_index": 3, "failed_internal_code": (preview["create"][3]["internal_code"] if len(preview["create"]) > 3 else None),
                "error": s.error_label, "compensated": created_ids[:3], "not_compensated": []}))
        elif k == "conciliacion":
            evs.append(event(req_id, "requiere_conciliacion", admin, t_apply + timedelta(seconds=30), {
                "error": s.error_label, "created": created_ids, "phase": "create"}))
        elif k == "no_ejecutable":
            evs.append(event(req_id, "no_ejecutable", admin, t_apply, {
                "reason": "plan_changed", "expected": f"{PREFIX}PLAN-{s.n:03d}", "current": f"{PREFIX}PLAN-{s.n:03d}-B"}))
    elif k == "rechazada":
        evs.append(event(req_id, "rechazada", admin, t_decide, {"comment": s.decision_comment}))
    elif k == "retirada":
        evs.append(event(req_id, "retirada", admin, t_decide + timedelta(hours=1), {"comment": s.decision_comment}))
    elif k == "expirada":
        evs.append(event(req_id, "expirada", None, expires_at, {"expires_at": expires_at.isoformat()}))
    return evs, applied_at


def build_request(s: Scenario, admin: uuid.UUID, preview: dict[str, Any], snapshot_base: dict[str, Any]) -> tuple[BillingChangeRequest, list[BillingChangeRequestEvent]]:
    req_id = uuid.uuid4()
    created = NOW - s.created_ago
    expires_at = NOW + s.expires_in if s.expires_in is not None else created + timedelta(days=EXPIRY_DAYS)
    approvals_required = 2 if s.kind == "pendiente_dual" else 1
    evs, applied_at = build_events(s, req_id, admin, created, preview, expires_at, approvals_required)

    approved = s.kind in ("aprobada", "ejecutada", "fallida", "conciliacion", "no_ejecutable")
    decided_at: datetime | None = None
    if approved:
        decided_at = created + timedelta(minutes=2)
    elif s.kind in ("rechazada", "retirada"):
        decided_at = evs[-1].created_at
    elif s.kind == "expirada":
        decided_at = expires_at
    count = 1 if (approved or s.kind == "pendiente_dual") else 0
    error = s.error_label if s.kind in ("fallida", "conciliacion", "no_ejecutable") else None
    req = BillingChangeRequest(
        id=req_id, request_type=s.request_type, platform=PLATFORM, subscription_external_id=sub_id(s.n), status=s.status,
        requested_by_user_id=admin, new_amount=Decimal(s.new_amount) if s.new_amount else None,
        previous_amount=Decimal(s.previous_amount) if s.previous_amount else None,
        new_charge_day=s.new_day, previous_charge_day=s.previous_day, new_charge_date=s.new_date, horizon_months=HORIZON,
        horizon_start_month=(preview["summary"]["horizon_start"] if s.request_type == "renew_calendar" else s.horizon_start_month),
        plan_preview=preview, rules_snapshot={**snapshot_base, **s.snapshot, "plan_external_id": f"{PREFIX}PLAN-{s.n:03d}", "task_ref": None},
        approvals_required=approvals_required, approvals_count=count, requester_comment=s.comment,
        approved_by_user_id=admin if approved else None, self_approved=bool(count), decided_at=decided_at,
        decision_comment=s.decision_comment if s.kind == "rechazada" else None, expires_at=expires_at, executed_at=applied_at,
        error_message=error, created_at=created, updated_at=evs[-1].created_at,
    )
    return req, evs


def main() -> int:
    dbname = guard_sandbox()
    print(f"Base conectada: {dbname} (APP_ENV={settings.env_mode}). Hoy (Chile): {TODAY.isoformat()}")
    stats = Stats()
    scenarios = build_scenarios()
    session = SessionLocal()
    try:
        admin = session.scalar(
            select(User).join(User.roles).where(Role.name == "admin", User.is_active.is_(True)).order_by(User.created_at).limit(1))
        if admin is None:
            fail("no hay un usuario activo con rol 'admin' en la base sandbox; no se crean usuarios.")
        admin_id = admin.id

        # Politica vigente (valores por defecto) si falta.
        policy = session.scalar(select(BillingPolicy).where(BillingPolicy.singleton.is_(True)))
        if policy is None:
            policy = BillingPolicy(singleton=True, approver_roles=["admin"], approver_user_ids=[])
            session.add(policy)
            session.flush()
            stats.add("billing_policy", True)
        else:
            stats.add("billing_policy", False)
        snapshot_base = {**POLICY_DEFAULTS}

        existing = {
            sid: rid for sid, rid in session.execute(
                select(BillingChangeRequest.subscription_external_id, BillingChangeRequest.id).where(
                    BillingChangeRequest.subscription_external_id.like(f"{PREFIX}%")))
        }
        request_ids: dict[int, uuid.UUID] = {}
        previews: dict[int, dict[str, Any]] = {}
        existing_charges = set(session.scalars(select(VpManagedCharge.charge_id).where(VpManagedCharge.charge_id.like(f"{PREFIX}%"))))

        for s in scenarios:
            plan = build_plan(s.plan_input)
            if not plan.ok:
                fail(f"el plan sintetico de {sub_id(s.n)} tiene errores: {[e.code for e in plan.errors]}")
            preview = plan_to_preview_json(plan)
            previews[s.n] = preview
            sid = sub_id(s.n)
            if sid in existing:
                request_ids[s.n] = existing[sid]
                stats.add("billing_change_requests", False)
                stats.add("billing_change_request_events", False)
                continue
            req, evs = build_request(s, admin_id, preview, snapshot_base)
            session.add(req)
            session.flush()
            session.add_all(evs)
            request_ids[s.n] = req.id
            stats.add("billing_change_requests", True)
            for _ in evs:
                stats.add("billing_change_request_events", True)
            if s.managed:  # cobros gestionados con los 'create' del plan
                for a in preview["create"]:
                    cid = f"{PREFIX}MC-{s.n:03d}-{a['month'].replace('-', '')}"
                    if cid in existing_charges:
                        stats.add("vp_managed_charges", False)
                        continue
                    session.add(VpManagedCharge(
                        platform=PLATFORM, charge_id=cid, subscription_external_id=sid, internal_code=a["internal_code"] or "",
                        month=a["month"], charge_date=date.fromisoformat(a["charge_date"]), amount=Decimal(a["amount"]),
                        request_id=req.id, status="requiere_conciliacion" if s.kind == "conciliacion" else "creado"))
                    stats.add("vp_managed_charges", True)

        # Marcas de calendario: las que dejaron las renovaciones/cambios ejecutados + las que alimentan las tareas.
        marks_existing = set(session.scalars(select(VpCalendarMark.subscription_external_id).where(
            VpCalendarMark.platform == PLATFORM, VpCalendarMark.subscription_external_id.like(f"{PREFIX}%"))))

        def add_mark(n: int, last: date, amount: int, day: int, *, origin: uuid.UUID | None = None, active: bool = True) -> None:
            if sub_id(n) in marks_existing:
                stats.add("vp_calendar_marks", False)
                return
            session.add(VpCalendarMark(
                platform=PLATFORM, subscription_external_id=sub_id(n), last_scheduled_month=fmt((last.year, last.month)),
                last_scheduled_date=last, scheduled_amount=Decimal(amount), charge_day=day, origin_request_id=origin, is_active=active))
            stats.add("vp_calendar_marks", True)

        for s in scenarios:
            if s.mark and s.kind == "ejecutada":
                last = max(date.fromisoformat(a["charge_date"]) for a in previews[s.n]["create"])
                origin = request_ids[s.n] if sub_id(s.n) not in existing else None
                add_mark(s.n, last, s.new_amount or 0, s.previous_day or last.day, origin=origin)

        # Tareas de renovacion (+ marca para cada una).
        task_existing = set(session.execute(select(BillingRenewalTask.subscription_external_id, BillingRenewalTask.status).where(
            BillingRenewalTask.subscription_external_id.like(f"{PREFIX}%"))).all())

        def add_task(n: int, status: str, last: date, amount: int, *, request_id: uuid.UUID | None = None, stale: bool = False,
                     reason: str | None = None, with_mark: bool = True, active_mark: bool = True) -> None:
            days = (last - TODAY).days
            if with_mark:
                add_mark(n, last, amount, last.day, active=active_mark)
            if (sub_id(n), status) in task_existing:
                stats.add("billing_renewal_tasks", False)
                return
            priority = "alta" if status == "vencida" or (status == "abierta" and days < 15) else "normal"
            closed = status in ("cerrada", "no_aplica")
            session.add(BillingRenewalTask(
                platform=PLATFORM, subscription_external_id=sub_id(n), status=status, priority=priority, last_scheduled_date=last,
                scheduled_amount=Decimal(amount), due_date=last, days_remaining=days, data_stale=stale, request_id=request_id,
                close_reason=reason, closed_at=NOW - timedelta(days=1) if closed else None))
            stats.add("billing_renewal_tasks", True)

        d4 = max(c.charge_date for c in scenarios[3].plan_input.charges)  # fin del calendario previo a la renovacion (004)
        add_task(4, "cerrada", d4, 15000, request_id=request_ids[4], with_mark=False,
                 reason="Renovación ejecutada: el calendario se extendió.")
        add_task(21, "abierta", TODAY + timedelta(days=8), 20000)  # prioridad alta (pocos dias)
        add_task(22, "abierta", TODAY + timedelta(days=40), 12000)  # normal
        add_task(23, "vencida", TODAY - timedelta(days=6), 18000)  # vencida => alta
        add_task(24, "abierta", TODAY + timedelta(days=25), 9000, stale=True)  # datos desactualizados
        add_task(25, "no_aplica", TODAY + timedelta(days=30), 7000, active_mark=False,
                 reason="La suscripción ya no está ACTIVA (estado: CANCELADA).")

        # Auditoria de politica (inmutable): 2 cambios historicos que terminan en los valores por defecto.
        audited = set(session.scalars(select(BillingPolicyAudit.reason).where(BillingPolicyAudit.reason.like(f"{PREFIX}%"))))
        v0 = {**POLICY_DEFAULTS, "renewal_threshold_days": 45, "request_expiry_days": 5}
        v1 = {**POLICY_DEFAULTS, "renewal_threshold_days": 45}
        v2 = {**POLICY_DEFAULTS}
        audits = [
            (f"{PREFIX}AUDIT-1: ampliar vigencia de solicitudes de 5 a 7 días (ejemplo)", v0, v1, NOW - timedelta(days=20)),
            (f"{PREFIX}AUDIT-2: avisar renovaciones con 60 días de anticipación (ejemplo)", v1, v2, NOW - timedelta(days=9)),
        ]
        for reason, before, after, at in audits:
            if reason in audited:
                stats.add("billing_policy_audit", False)
                continue
            session.add(BillingPolicyAudit(
                policy_id=policy.id, changed_by_user_id=admin_id, changed_at=at, before_values=before, after_values=after, reason=reason))
            stats.add("billing_policy_audit", True)

        session.commit()
    except SystemExit:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    # Comprobacion de las caracteristicas pedidas del plan (informativa).
    reasons = {m["reason"] for p in previews.values() for m in p["manual_review"]}
    has_kept = any(p["kept_due_today"] for p in previews.values())
    has_warn = any(p["warnings"] for p in previews.values())
    print(f"Caracteristicas de plan: manual_review={sorted(reasons)} kept_due_today={has_kept} warnings={has_warn}")
    if "replacement_outside_month" not in reasons or not has_kept or not has_warn:
        print("AVISO: alguna caracteristica esperada no se generó con la fecha de hoy; revisar los escenarios.")
    print(f"{'tabla':36}{'creadas':>9}{'omitidas':>10}")
    for table in ("billing_policy", "billing_change_requests", "billing_change_request_events", "vp_managed_charges",
                  "vp_calendar_marks", "billing_renewal_tasks", "billing_policy_audit"):
        print(f"{table:36}{stats.created[table]:>9}{stats.skipped[table]:>10}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
