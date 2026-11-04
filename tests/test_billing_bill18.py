"""BILL-18 (tanda 1b, DEC-30 opcion A y DEC-29): ventana de 31 dias con reemplazo de mes atrasado fechado MANANA (hora
de Chile) y atribuido a su mes de origen por el `internal_code` `{sub}-{YYYYMM}-{monto}`; meses sin cobro previo.

Solo con fakes: `VirtualPOSClient` se reemplaza por `FakeVP` (estado en memoria). Ninguna llamada de red.
Escenarios: GB-JB-03..09, GB-JB-22, GB-RA-05, GB-RA-27, GB-CS-03, GB-CO-12 (docs/designs/facturacion-gestionada-escenarios.md).
"""

import asyncio
import uuid
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.models.auth import User
from app.models.billing import BillingChangeRequest, VpCalendarMark, VpManagedCharge
from app.models.crm import Plan, Subscription
from app.models.vp import VpCharge
from app.services import billing_apply as ba
from app.services import billing_consistency as bc
from app.services import billing_plan as bp
from app.services import write_virtualpos as wv
from app.services.billing_plan import (
    PlanCharge,
    PlanInput,
    build_amount_change_plan,
    plan_to_preview_json,
)
from app.services.rejected_month import CHILE_TZ

SUB = "sub-b18"
CALLS: list[tuple] = []
STATE: dict = {}
# 2026-11-01 01:30 UTC = 2026-10-31 22:30 en Chile (UTC-3): hoy sigue siendo el 31 de octubre.
NOW_UTC = datetime(2026, 11, 1, 1, 30, tzinfo=UTC)
TODAY_CL = date(2026, 10, 31)


# ----------------------------- plan puro -----------------------------


def _inp(charges=(), **kw) -> PlanInput:
    base = {"request_type": "change_amount", "subscription_external_id": SUB, "platform": "virtualpos1",
            "new_amount": 12000, "charges": tuple(charges), "charge_day": 15, "effective_month": "2026-10",
            "horizon_months": 2, "today": TODAY_CL}
    base.update(kw)
    return PlanInput(**base)


def _pc(cid, d, amount=9900, status="pendiente", code=None, crm=False) -> PlanCharge:
    return PlanCharge(cid, status, d, amount, internal_code=code, is_crm=crm)


def test_code_month_parses_only_regular_codes_of_the_subscription() -> None:
    assert bp.code_month(f"{SUB}-202610-12000", SUB) == "2026-10"
    assert bp.code_month(f"{SUB}-202612-12000-d05", SUB) == "2026-12"  # cambio de fecha
    assert bp.code_month(f"{SUB}-T42-20261101-5000", SUB) is None  # puntual por tarea
    assert bp.code_month(f"{SUB}-20261101-5000-oneoff", SUB) is None
    assert bp.code_month("otra-sub-202610-12000", SUB) is None
    assert bp.code_month(f"{SUB}-202613-12000", SUB) is None  # mes invalido
    assert bp.code_month(None, SUB) is None
    # sin codigo del CRM manda la fecha
    assert bp.charge_month(_pc("a", date(2026, 11, 1)), SUB) == "2026-11"
    assert bp.charge_month(_pc("a", date(2026, 11, 1), code=f"{SUB}-202610-12000"), SUB) == "2026-10"


def test_overdue_month_without_charge_is_replaced_tomorrow_with_origin_code() -> None:
    """JB-03 / DEC-30: octubre atrasado sin cobro pagado/procesando/rechazado -> manana (1-nov) con codigo de octubre."""
    ch = [_pc("a10", date(2026, 10, 15)), _pc("a11", date(2026, 11, 15))]
    r = build_amount_change_plan(_inp(ch))
    assert not r.manual_review and not r.errors
    assert [(a.month, a.charge_date, a.internal_code) for a in r.create] == [
        ("2026-10", date(2026, 11, 1), f"{SUB}-202610-12000"), ("2026-11", date(2026, 11, 15), f"{SUB}-202611-12000")]
    assert [a.charge_id for a in r.cancel] == ["a10", "a11"]
    assert all(set(a.depends_on) == {a.internal_code for a in r.create} for a in r.cancel)  # crear y despues cancelar


def test_window_boundary_31_inclusive_32_manual_review_across_months() -> None:
    """JB-05 / JB-06 con el reemplazo cayendo en otro mes: 31 dias -> manana; 32 dias -> revision manual."""
    today = date(2026, 11, 15)
    r31 = build_amount_change_plan(_inp(today=today, horizon_months=1))  # 15-oct: 31 dias
    assert [(a.month, a.charge_date) for a in r31.create] == [("2026-10", date(2026, 11, 16))]
    r32 = build_amount_change_plan(_inp(today=today, horizon_months=1, charge_day=14))  # 14-oct: 32 dias
    assert not r32.create and [(m.month, m.days_overdue, m.reason) for m in r32.manual_review] == [
        ("2026-10", 32, "older_than_window")]


def test_month_already_covered_is_not_replaced() -> None:
    """JB-07: el mes atrasado tiene un rechazado -> cubierto, no se crea."""
    r = build_amount_change_plan(_inp([_pc("r10", date(2026, 10, 15), status="rechazado")], horizon_months=1))
    assert not r.create and [c.reason for c in r.covered] == ["rechazado"]


def test_tomorrow_uses_chile_time_not_utc(monkeypatch) -> None:
    """JB-22: a las 22:30 de Chile (01:30 UTC del dia siguiente) manana es el 1-nov, no el 2-nov."""
    monkeypatch.setattr(bp, "now_chile", lambda: NOW_UTC.astimezone(CHILE_TZ))
    r = build_amount_change_plan(_inp(today=None, horizon_months=1))
    assert [(a.month, a.charge_date) for a in r.create] == [("2026-10", date(2026, 11, 1))]


def test_replacement_never_falls_on_the_regular_date_of_the_next_month() -> None:
    """JB-09: dia 1; octubre atrasado y noviembre se cobra el 1-nov -> el reemplazo de octubre se corre al 2-nov."""
    r = build_amount_change_plan(_inp(charge_day=1))
    assert [(a.month, a.charge_date) for a in r.create] == [("2026-10", date(2026, 11, 2)), ("2026-11", date(2026, 11, 1))]


def test_idempotent_after_apply_and_no_double_pending_in_next_month() -> None:
    """Reinyectar el resultado: el reemplazo de octubre (fechado en noviembre) cubre octubre; noviembre sigue con uno."""
    ch = [_pc("a10", date(2026, 10, 15)), _pc("a11", date(2026, 11, 15))]
    r = build_amount_change_plan(_inp(ch))
    applied = [_pc("a10", date(2026, 10, 15), status="cancelado"), _pc("a11", date(2026, 11, 15), status="cancelado")]
    applied += [_pc(f"n{i}", a.charge_date, a.amount, code=a.internal_code, crm=True) for i, a in enumerate(r.create)]
    again = build_amount_change_plan(_inp(applied))
    assert again.noop and again.unchanged == ("2026-10", "2026-11")
    assert not any(w.code == "multiple_pending" for w in again.warnings)
    # un pendiente con el codigo de octubre que el CRM no registro (POST con timeout) tambien cubre octubre (CO-12)
    orphan = [_pc("a11", date(2026, 11, 15)), _pc("x", date(2026, 11, 1), 12000, code=f"{SUB}-202610-12000")]
    o = build_amount_change_plan(_inp(orphan))
    assert [a.month for a in o.create] == ["2026-11"] and "2026-10" not in {a.month for a in o.cancel}


def test_dec29_month_only_cancelled_goes_to_review_and_month_without_charge_warns() -> None:
    only_cancelled = [_pc("c10", date(2026, 10, 15), status="cancelado"), _pc("a11", date(2026, 11, 15))]
    r = build_amount_change_plan(_inp(only_cancelled))
    assert [(m.month, m.reason) for m in r.manual_review] == [("2026-10", "only_cancelled_charges")]
    assert [a.month for a in r.create] == ["2026-11"]
    empty = build_amount_change_plan(_inp([_pc("a11", date(2026, 11, 15))]))
    assert [a.month for a in empty.create] == ["2026-10", "2026-11"]
    assert [(w.code, w.month) for w in empty.warnings] == [("month_without_charge", "2026-10")]
    # un cobro del CRM cancelado (compensacion) no cuenta como "solo cancelados": se crea igual
    crm_cancelled = [_pc("n0", date(2026, 11, 1), 12000, status="cancelado", code=f"{SUB}-202610-12000", crm=True)]
    c = build_amount_change_plan(_inp(crm_cancelled, horizon_months=1))
    assert [a.month for a in c.create] == ["2026-10"] and not c.manual_review
    preview = plan_to_preview_json(r)
    assert preview["manual_review"][0]["reason"] == "only_cancelled_charges"


# ----------------------------- aplicacion con FakeVP -----------------------------


class FakeVP:
    def __init__(self, platform: str = "virtualpos1") -> None:
        self.platform = platform

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def list_charges(self, subscription_id, page=1, limit=100, status=None):
        CALLS.append(("list_charges", status))
        rows = [dict(c) for c in STATE["charges"] if status is None or c["status"] == status]
        return {"charges": rows, "pagination": {"pages": 1, "page": 1}}

    async def delete_subscription_charges(self, subscription_id):  # nunca debe usarse (CO-16)
        CALLS.append(("delete_plural", subscription_id))
        raise AssertionError("DELETE plural prohibido")

    async def delete_charge(self, charge_id):
        CALLS.append(("delete_charge", charge_id))
        next(c for c in STATE["charges"] if c["id"] == charge_id)["status"] = "cancelado"
        return {}

    async def create_charge(self, data):
        STATE["n"] += 1
        CALLS.append(("create_charge", data["internal_code"], data["charge_date"]))
        charge = {"id": f"new-{STATE['n']}", "charge_date": data["charge_date"], "amount": data["amount"],
                  "status": "pendiente", "internal_code": data["internal_code"]}
        STATE["charges"].append(charge)
        return {**charge, "suscription_id": data["suscription_id"]}

    async def get_charge(self, charge_id):
        return dict(next(c for c in STATE["charges"] if c["id"] == charge_id))


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    CALLS.clear()
    STATE.clear()
    STATE.update(n=0, charges=[
        {"id": "paid-09", "charge_date": "2026-09-15", "amount": 9900, "status": "pagado"},
        {"id": "auto-10", "charge_date": "2026-10-15", "amount": 9900, "status": "pendiente"},  # vencido, sin cobrar
        {"id": "auto-11", "charge_date": "2026-11-15", "amount": 9900, "status": "pendiente"},
        {"id": "auto-12", "charge_date": "2026-12-15", "amount": 9900, "status": "pendiente"},
    ])
    monkeypatch.setattr(settings, "virtualpos_writes_enabled", True)
    monkeypatch.setattr(settings, "virtualpos_allow_charge_on_fixed_plan", True)
    monkeypatch.setattr(wv, "VirtualPOSClient", FakeVP)


@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _setup(db):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}", password_hash="x")
    db.add(user)
    db.add(Subscription(source="virtualpos1", external_id=SUB, plan_external_id="plan-b18", status="ACTIVA"))
    db.add(Plan(source="virtualpos1", external_id="plan-b18", plan_type="MONTO_FIJO"))
    db.flush()
    req = BillingChangeRequest(
        request_type="change_amount", platform="virtualpos1", subscription_external_id=SUB,
        requested_by_user_id=user.id, status="aprobada", new_amount=12000, previous_amount=9900,
        previous_charge_day=15, horizon_months=2, horizon_start_month="2026-10",
        rules_snapshot={"self_approval_enabled": True}, plan_preview={},
    )
    db.add(req)
    db.flush()
    req.plan_preview = plan_to_preview_json(asyncio.run(ba.preview_change(db, req, now=NOW_UTC)))
    db.commit()
    CALLS.clear()
    return user, req


def _apply(db, req, user):
    return asyncio.run(ba.apply_change_request(db, req.id, actor_user_id=user.id, now=NOW_UTC))


def test_apply_replaces_overdue_month_tomorrow_chile_and_verifies_by_internal_code(db) -> None:
    user, req = _setup(db)
    res = _apply(db, req, user)
    assert res.status == "ejecutada" and not res.manual_review_months
    creates = [c for c in CALLS if c[0] == "create_charge"]
    assert creates == [("create_charge", f"{SUB}-202610-12000", "2026-11-01"),
                       ("create_charge", f"{SUB}-202611-12000", "2026-11-15")]
    # orden seguro: todos los create antes del primer DELETE; nunca el DELETE plural
    names = [c[0] for c in CALLS]
    assert max(i for i, n in enumerate(names) if n == "create_charge") < min(i for i, n in enumerate(names) if n == "delete_charge")
    assert "delete_plural" not in names
    assert sorted(c[1] for c in CALLS if c[0] == "delete_charge") == ["auto-10", "auto-11"]
    managed = {m.charge_id: (m.month, m.charge_date) for m in db.scalars(select(VpManagedCharge).where(
        VpManagedCharge.subscription_external_id == SUB))}
    assert managed == {"new-1": ("2026-10", date(2026, 11, 1)), "new-2": ("2026-11", date(2026, 11, 15))}
    mark = db.scalar(select(VpCalendarMark).where(VpCalendarMark.subscription_external_id == SUB))
    assert mark.last_scheduled_month == "2026-11" and mark.charge_day == 15


def test_apply_is_idempotent_and_replan_is_noop(db) -> None:
    user, req = _setup(db)
    assert _apply(db, req, user).status == "ejecutada"
    CALLS.clear()
    again = _apply(db, req, user)
    assert again.already_applied and not CALLS
    replan = asyncio.run(ba.preview_change(db, PlanInput(
        request_type="change_amount", subscription_external_id=SUB, platform="virtualpos1", new_amount=12000,
        charge_day=15, effective_month="2026-10", horizon_months=2), now=NOW_UTC))
    assert replan.noop and replan.unchanged == ("2026-10", "2026-11")
    assert not [c for c in CALLS if c[0] in ("create_charge", "delete_charge")]


def test_consistency_does_not_flag_double_pending_for_attributed_replacement(db) -> None:
    """CS-03: tras sincronizar, noviembre tiene el reemplazo de octubre (1-nov) y su propio cobro (15-nov): no es doble
    pendiente porque el reemplazo cuenta para octubre (`vp_managed_charges.month`)."""
    user, req = _setup(db)
    assert _apply(db, req, user).status == "ejecutada"
    for c in STATE["charges"]:
        db.add(VpCharge(platform="virtualpos1", external_id=c["id"], subscription_external_id=SUB, amount=str(c["amount"]),
                        status=c["status"], charge_date=date.fromisoformat(c["charge_date"])))
    db.commit()
    today = TODAY_CL
    assert bc.has_double_pending(db, "virtualpos1", SUB, today) is False
    report = bc.run_consistency_checks(db, now=datetime(2026, 10, 31, 12, 0, tzinfo=ZoneInfo("America/Santiago")))
    mine = [f for f in report.findings if f.subscription_external_id == SUB]
    assert not [f for f in mine if f.code in ("double_pending", "missing_month", "unregistered_charge")]


def test_apply_respects_subscription_lock_ra27(db) -> None:
    """RA-27 / RA-13: con el lock de la suscripcion tomado (p. ej. un retry_charge) el cambio no escribe nada."""
    user, req = _setup(db)
    with ba.subscription_lock(db, "virtualpos1", SUB):
        with pytest.raises(ba.SubscriptionBusyError):
            _apply(db, req, user)
    assert not [c for c in CALLS if c[0] in ("create_charge", "delete_charge")]
    db.refresh(req)
    assert req.status == "aprobada"


def test_apply_blocked_when_writes_disabled(db, monkeypatch) -> None:
    """JB-19: sin la bandera de escritura no se llama al proveedor y la solicitud sigue aprobada."""
    user, req = _setup(db)
    monkeypatch.setattr(settings, "virtualpos_writes_enabled", False)
    with pytest.raises(wv.WriteDisabledError):
        _apply(db, req, user)
    assert not CALLS
