"""Fase 3b: aplicacion de cambios de cobro aprobados (app/services/billing_apply.py), SOLO con fakes.

Ninguna llamada de red: `VirtualPOSClient` se reemplaza por `FakeVP` (estado en memoria con CALLS/STATE).
Escenarios del doc docs/designs/facturacion-gestionada-escenarios.md cubiertos por cada test en su docstring.
"""

import asyncio
import uuid
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db
from app.core.config import settings
from app.core.security import ACCESS_COOKIE, create_access_token, get_current_user
from app.db.session import engine
from app.integrations.virtualpos.client import VirtualPOSAPIError
from app.main import app
from app.models.auth import User
from app.models.billing import (
    BillingChangeRequest,
    BillingChangeRequestEvent,
    VpCalendarMark,
    VpManagedCharge,
)
from app.models.crm import Plan, Subscription
from app.models.write_run import WriteRun
from app.services import billing_apply as ba
from app.services import write_virtualpos as wv
from app.services.billing_plan import PlanInput, plan_to_preview_json

SUB = "sub-bill-1"
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=ZoneInfo("America/Santiago"))
CALLS: list[tuple] = []
STATE: dict = {}
HORIZON = [f"2026-{m:02d}" for m in (11, 12)] + [f"2027-{m:02d}" for m in range(1, 11)]


def _api_error(code: str) -> VirtualPOSAPIError:
    return VirtualPOSAPIError(code, "nok", 400, 200)


class FakeVP:
    def __init__(self, platform: str = "virtualpos1") -> None:
        self.platform = platform

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def _by_id(self, charge_id):
        return next(c for c in STATE["charges"] if c["id"] == charge_id)

    async def list_charges(self, subscription_id, page=1, limit=100, status=None):
        CALLS.append(("list_charges", status))
        if STATE.get("list_fail_after") is not None:
            STATE["list_fail_after"] -= 1
            if STATE["list_fail_after"] < 0:
                raise httpx.ReadTimeout("list timeout")
        rows = [c for c in STATE["charges"] if status is None or c["status"] == status]
        size = STATE.get("page_size", limit)
        pages = max(1, -(-len(rows) // size))
        return {"charges": [dict(c) for c in rows[(page - 1) * size: page * size]], "pagination": {"pages": pages, "page": page}}

    async def delete_subscription_charges(self, subscription_id):
        CALLS.append(("delete_plural", subscription_id))
        pend = [c for c in STATE["charges"] if c["status"] == "pendiente"]
        for c in pend:
            c["status"] = "cancelado"
        return {"cancel_charges": [dict(c) for c in pend]}

    async def delete_charge(self, charge_id):
        CALLS.append(("delete_charge", charge_id))
        fails = STATE.setdefault("delete_fail", {})
        if fails.get(charge_id, 0) > 0:
            fails[charge_id] -= 1
            raise httpx.ConnectError("boom")
        charge = self._by_id(charge_id)
        if charge_id in STATE.get("e059", set()):
            charge["status"] = "procesando"
            raise _api_error("E-059")
        if charge_id in STATE.get("e079", set()):
            charge["status"] = "cancelado"
            raise _api_error("E-079")
        if charge_id in STATE.get("timeout_applied", set()):
            STATE["timeout_applied"].discard(charge_id)
            charge["status"] = "cancelado"
            raise httpx.ReadTimeout("delete timeout")
        if charge_id in STATE.get("delete_noop", set()):
            return {}
        charge["status"] = "cancelado"
        return {}

    async def create_charge(self, data):
        STATE["n_create"] += 1
        n = STATE["n_create"]
        CALLS.append(("create_charge", data["internal_code"]))
        fail = STATE.get("create_fail") or {}
        kind = fail.get("kind") if fail.get("at") == n else None
        if kind == "nok":
            raise _api_error("E-113")
        if kind == "timeout":
            raise httpx.ReadTimeout("create timeout")
        charge = {"id": f"new-{n}", "charge_date": data["charge_date"], "amount": data["amount"],
                  "status": "pendiente", "internal_code": data["internal_code"]}
        STATE["charges"].append(charge)
        if kind == "timeout_created":
            raise httpx.ReadTimeout("create timeout")
        return {**charge, "suscription_id": data["suscription_id"]}

    async def get_charge(self, charge_id):
        return dict(self._by_id(charge_id))


def _autos():
    rows = [{"id": f"auto-{i:02d}", "charge_date": f"{m[:4]}-{m[5:]}-05", "amount": 9900, "status": "pendiente"}
            for i, m in enumerate(HORIZON, start=1)]
    rows += [{"id": "auto-13", "charge_date": "2027-11-05", "amount": 9900, "status": "pendiente"},
             {"id": "auto-14", "charge_date": "2027-12-05", "amount": 9900, "status": "pendiente"},
             {"id": "paid-0", "charge_date": "2026-10-05", "amount": 9900, "status": "pagado"}]
    return rows


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    CALLS.clear()
    STATE.clear()
    STATE.update(charges=_autos(), n_create=0)
    monkeypatch.setattr(settings, "virtualpos_writes_enabled", True)
    monkeypatch.setattr(settings, "virtualpos_allow_charge_on_fixed_plan", True)
    monkeypatch.setattr(wv, "VirtualPOSClient", FakeVP)  # billing_apply usa wv.VirtualPOSClient


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


# ----------------------------- helpers -----------------------------


def _seed_user_sub(db, sub_status="ACTIVA"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}", password_hash="x")
    db.add(user)
    db.add(Subscription(source="virtualpos1", external_id=SUB, plan_external_id="plan-1", status=sub_status))
    db.add(Plan(source="virtualpos1", external_id="plan-1", plan_type="MONTO_FIJO"))
    db.flush()
    return user


def _make_request(db, user, **over):
    values = dict(
        request_type="change_amount", platform="virtualpos1", subscription_external_id=SUB,
        requested_by_user_id=user.id, status="aprobada", new_amount=12000, previous_amount=9900,
        previous_charge_day=5, horizon_months=12, horizon_start_month="2026-11",
        rules_snapshot={"self_approval_enabled": True}, plan_preview={},
    )
    values.update(over)
    req = BillingChangeRequest(**values)
    db.add(req)
    db.flush()
    plan = asyncio.run(ba.preview_change(db, req, now=NOW))
    req.plan_preview = plan_to_preview_json(plan)
    db.commit()
    CALLS.clear()
    return req


def _apply(db, req, user, **kw):
    return asyncio.run(ba.apply_change_request(db, req.id, actor_user_id=user.id, now=NOW, **kw))


def _setup(db, **over):
    user = _seed_user_sub(db)
    return user, _make_request(db, user, **over)


def _names():
    return [c[0] for c in CALLS]


def _deleted():
    return [c[1] for c in CALLS if c[0] == "delete_charge"]


def _events(db, req):
    return [e.event_type for e in db.scalars(
        select(BillingChangeRequestEvent).where(BillingChangeRequestEvent.request_id == req.id)
        .order_by(BillingChangeRequestEvent.created_at, BillingChangeRequestEvent.id))]


def _pending_by_month():
    out: dict[str, list[dict]] = {}
    for c in STATE["charges"]:
        if c["status"] == "pendiente":
            out.setdefault(c["charge_date"][:7], []).append(c)
    return out


def _managed(db, req):
    return {m.charge_id: m for m in db.scalars(select(VpManagedCharge).where(VpManagedCharge.request_id == req.id))}


def _status(db, req):
    db.refresh(req)
    return req.status


# ----------------------------- camino feliz y orden -----------------------------


def test_happy_path_12_months_create_before_cancel_and_audit(db_session):
    """RA-01, CO-11, CO-14, RA-28, CS-05, AP-16: 12 POST, luego 12 DELETE individuales, verificacion y marca."""
    user, req = _setup(db_session)
    result = _apply(db_session, req, user)

    assert result.status == "ejecutada"
    names = _names()
    creates = [i for i, n in enumerate(names) if n == "create_charge"]
    deletes = [i for i, n in enumerate(names) if n == "delete_charge"]
    assert len(creates) == 12 and len(deletes) == 12
    assert max(creates) < min(deletes)  # nunca un DELETE antes de que todos los POST terminen
    assert "delete_plural" not in names
    assert set(_deleted()) == {f"auto-{i:02d}" for i in range(1, 13)}
    pend = _pending_by_month()
    assert all(len(pend[m]) == 1 and pend[m][0]["amount"] == 12000 for m in HORIZON)
    assert {c["id"] for c in pend["2027-11"] + pend["2027-12"]} == {"auto-13", "auto-14"}  # red de seguridad intacta

    assert _status(db_session, req) == "ejecutada" and req.executed_at is not None
    assert _events(db_session, req) == ["aplicando", "aplicada"]
    managed = _managed(db_session, req)
    assert len(managed) == 12 and {m.status for m in managed.values()} == {"creado"}
    assert {m.month for m in managed.values()} == set(HORIZON)

    mark = db_session.scalar(select(VpCalendarMark).where(VpCalendarMark.subscription_external_id == SUB))
    assert (mark.last_scheduled_month, int(mark.scheduled_amount), mark.charge_day) == ("2027-10", 12000, 5)
    assert mark.origin_request_id == req.id and mark.is_active

    runs = list(db_session.scalars(select(WriteRun).where(WriteRun.request_id == req.id)))
    assert {r.operation for r in runs} == {"apply_billing_change_request", "create_charge", "cancel_future_charges"}
    assert len(runs) == 1 + 12 + 12
    assert all(r.requested_by_user_id == user.id for r in runs)
    parent = db_session.get(WriteRun, req.write_run_id)
    assert parent.operation == "apply_billing_change_request" and parent.status == "completed"


def test_reapply_after_success_is_noop(db_session):
    """RA-14: reaplicar una solicitud ejecutada no escribe ni lee nada."""
    user, req = _setup(db_session)
    _apply(db_session, req, user)
    CALLS.clear()
    again = _apply(db_session, req, user)
    assert again.already_applied and again.status == "ejecutada"
    assert CALLS == []
    assert _events(db_session, req) == ["aplicando", "aplicada"]


def test_paginated_listing(db_session):
    """El listado se lee completo aunque el proveedor pagine."""
    STATE["page_size"] = 5
    user, req = _setup(db_session)
    assert _apply(db_session, req, user).status == "ejecutada"
    assert len(_deleted()) == 12


def test_change_date_uses_suffix_codes_and_updates_mark(db_session):
    """RA-16: cambio de dia 5 -> 20, mismo monto; codigos con sufijo -d20 (no adopta el cobro viejo)."""
    user, req = _setup(db_session, request_type="change_date", new_amount=9900, new_charge_day=20)
    result = _apply(db_session, req, user)
    assert result.status == "ejecutada"
    new = [c for c in STATE["charges"] if c["id"].startswith("new-")]
    assert len(new) == 12 and all(c["charge_date"].endswith("-20") and c["internal_code"].endswith("-d20") for c in new)
    mark = db_session.scalar(select(VpCalendarMark).where(VpCalendarMark.subscription_external_id == SUB))
    assert mark.charge_day == 20


def test_one_off_creates_single_charge_without_cancel_or_mark(db_session):
    """RA-29: un solo POST, sin cancelar ni marcar calendario modificado."""
    user, req = _setup(db_session, request_type="one_off_charge", new_amount=5000, previous_amount=None,
                       previous_charge_day=None, horizon_start_month=None, horizon_months=1,
                       new_charge_date=date(2026, 11, 20), rules_snapshot={"task_ref": "T9"})
    assert _apply(db_session, req, user).status == "ejecutada"
    assert [n for n in _names() if n in ("create_charge", "delete_charge")] == ["create_charge"]
    assert db_session.scalar(select(VpCalendarMark)) is None


# ----------------------------- compensacion -----------------------------


def test_create_k_fails_compensates_previous_and_cancels_nothing_old(db_session):
    """RA-07, CO-11: falla el POST 5 -> se cancelan los 4 nuevos; ningun automatico se toca; fallida."""
    STATE["create_fail"] = {"at": 5, "kind": "nok"}
    user, req = _setup(db_session)
    with pytest.raises(ba.ApplyFailedError) as ei:
        _apply(db_session, req, user)
    assert sorted(_deleted()) == ["new-1", "new-2", "new-3", "new-4"]
    assert not any(d.startswith("auto-") for d in _deleted())
    assert len(ei.value.compensated) == 4
    assert _status(db_session, req) == "fallida"
    assert _events(db_session, req) == ["aplicando", "fallida"]
    assert {m.status for m in _managed(db_session, req).values()} == {"compensado"}
    assert db_session.scalar(select(VpCalendarMark)) is None  # la marca no cambia si fallo
    assert all(len(v) == 1 and v[0]["id"].startswith(("auto", "paid")) for k, v in _pending_by_month().items() if k in HORIZON)
    assert db_session.get(WriteRun, req.write_run_id).status == "failed"
    assert "delete_plural" not in _names()


def test_create_timeout_orphan_is_found_and_compensated(db_session):
    """RA-08, RZ-31: el POST 3 dio timeout pero creo el cargo; se relee y el huerfano tambien se cancela."""
    STATE["create_fail"] = {"at": 3, "kind": "timeout_created"}
    user, req = _setup(db_session)
    with pytest.raises(ba.ApplyFailedError):
        _apply(db_session, req, user)
    assert sorted(_deleted()) == ["new-1", "new-2", "new-3"]
    assert [c for c in STATE["charges"] if c["id"].startswith("new-") and c["status"] == "pendiente"] == []
    assert _status(db_session, req) == "fallida"
    assert STATE["n_create"] == 3  # sin POST a ciegas despues del timeout


def test_failed_compensation_requires_reconciliation_and_blocks(db_session):
    """RA-09: falla el POST 3 y la compensacion tambien -> requiere_conciliacion y suscripcion bloqueada."""
    STATE["create_fail"] = {"at": 3, "kind": "nok"}
    STATE["delete_fail"] = {"new-1": 99, "new-2": 99}
    user, req = _setup(db_session)
    with pytest.raises(wv.ReconciliationRequiredError):
        _apply(db_session, req, user)
    assert _status(db_session, req) == "requiere_conciliacion"
    assert _events(db_session, req)[-1] == "requiere_conciliacion"
    assert {m.status for m in _managed(db_session, req).values()} == {"requiere_conciliacion"}
    assert not any(d.startswith("auto-") for d in _deleted())
    assert ba.is_subscription_blocked(db_session, "virtualpos1", SUB)
    assert db_session.get(WriteRun, req.write_run_id).status == "reconciliation_required"


def test_reapply_after_partial_failure_adopts_by_internal_code(db_session):
    """RA-14, RA-08: reaplicar tras un fallo parcial adopta los cobros existentes sin duplicar."""
    STATE["create_fail"] = {"at": 3, "kind": "nok"}
    STATE["delete_fail"] = {"new-1": 99, "new-2": 99}
    user, req = _setup(db_session)
    with pytest.raises(wv.ReconciliationRequiredError):
        _apply(db_session, req, user)
    STATE["create_fail"] = None
    STATE["delete_fail"] = {}
    req.status = "aprobada"  # el reintento autorizado (fase 4) devuelve la solicitud a `aprobada`
    db_session.commit()
    CALLS.clear()
    assert _apply(db_session, req, user).status == "ejecutada"
    assert STATE["n_create"] == 3 + 10  # los meses 1 y 2 se adoptaron (sin POST)
    live = [c["internal_code"] for c in STATE["charges"] if c.get("internal_code") and c["status"] != "cancelado"]
    assert len(live) == len(set(live)) == 12
    assert all(len(_pending_by_month()[m]) == 1 for m in HORIZON)
    assert {m.status for m in _managed(db_session, req).values() if m.charge_id in ("new-1", "new-2")} == {"creado"}


def test_delete_j_persistent_failure_keeps_created_and_reconciles(db_session):
    """RA-10: los 12 POST OK y el DELETE de un antiguo falla dos veces -> conciliacion; nunca se pierden los creados."""
    STATE["delete_fail"] = {"auto-07": 99}
    user, req = _setup(db_session)
    with pytest.raises(wv.ReconciliationRequiredError) as ei:
        _apply(db_session, req, user)
    assert "doble pendiente" in str(ei.value)
    assert not any(d.startswith("new-") for d in _deleted())
    assert _deleted().count("auto-07") == 2  # un reintento
    assert len([c for c in STATE["charges"] if c["id"].startswith("new-") and c["status"] == "pendiente"]) == 12
    assert _status(db_session, req) == "requiere_conciliacion"
    assert {m.status for m in _managed(db_session, req).values()} == {"requiere_conciliacion"}
    assert db_session.scalar(select(VpCalendarMark)) is None
    assert "auto-08" not in _deleted()  # se detiene en el primer fallo persistente


def test_delete_j_transient_failure_retries_once_and_succeeds(db_session):
    """RA-10: un fallo transitorio del DELETE se reintenta una vez."""
    STATE["delete_fail"] = {"auto-07": 1}
    user, req = _setup(db_session)
    assert _apply(db_session, req, user).status == "ejecutada"
    assert _deleted().count("auto-07") == 2


def test_delete_timeout_already_applied_is_not_blindly_retried(db_session):
    """RZ-31: timeout en un DELETE que si se aplico -> se relee, NO se repite el DELETE."""
    STATE["timeout_applied"] = {"auto-03"}
    user, req = _setup(db_session)
    assert _apply(db_session, req, user).status == "ejecutada"
    assert _deleted().count("auto-03") == 1


# ----------------------------- E-059 / E-079 / verificacion -----------------------------


def test_e059_skips_old_and_cancels_new_manual_of_that_month(db_session):
    """RA-11, RA-19, CO-06: el automatico pasa a procesando en medio del lote -> se omite y se cancela el manual nuevo."""
    STATE["e059"] = {"auto-04"}  # 2027-02
    user, req = _setup(db_session)
    result = _apply(db_session, req, user)
    assert result.status == "ejecutada" and result.covered_late_months == ["2027-02"]
    assert "new-4" in _deleted()
    feb = [c for c in STATE["charges"] if c["charge_date"].startswith("2027-02")]
    assert [(c["id"], c["status"]) for c in feb if c["status"] == "pendiente"] == []
    assert next(c for c in feb if c["id"] == "auto-04")["status"] == "procesando"
    assert _managed(db_session, req)["new-4"].status == "cancelado"
    assert _events(db_session, req) == ["aplicando", "aplicada"]


def test_e079_is_noop(db_session):
    """E-079 (nada pendiente) no es error."""
    STATE["e079"] = {"auto-05"}
    user, req = _setup(db_session)
    result = _apply(db_session, req, user)
    assert result.status == "ejecutada" and "auto-05" not in result.cancelled


def test_final_verification_detects_double_pending(db_session):
    """RA-01/CS-03: un DELETE 'exitoso' que no cancelo deja doble pendiente -> conciliacion y sin marca."""
    STATE["delete_noop"] = {"auto-06"}  # 2027-04
    user, req = _setup(db_session)
    with pytest.raises(wv.ReconciliationRequiredError) as ei:
        _apply(db_session, req, user)
    assert "2027-04" in str(ei.value)
    assert _status(db_session, req) == "requiere_conciliacion"
    assert db_session.scalar(select(VpCalendarMark)) is None


def test_foreign_manual_is_never_cancelled(db_session):
    """CO-14, hallazgo 2: un manual ajeno jamas se cancela (y el doble pendiente resultante exige conciliacion)."""
    STATE["charges"].append({"id": "ext-1", "charge_date": "2026-12-20", "amount": 5000, "status": "pendiente",
                             "internal_code": "EXT-1"})
    user, req = _setup(db_session)
    with pytest.raises(wv.ReconciliationRequiredError):
        _apply(db_session, req, user)
    assert "ext-1" not in _deleted()
    assert next(c for c in STATE["charges"] if c["id"] == "ext-1")["status"] == "pendiente"


# ----------------------------- drift, estado y lock -----------------------------


def test_drift_between_approved_plan_and_current_state(db_session):
    """AP-30, GB-AP-13: un mes paso a pagado tras la aprobacion -> no aplica; con confirmacion si."""
    user, req = _setup(db_session)
    next(c for c in STATE["charges"] if c["id"] == "auto-03")["status"] = "pagado"  # 2027-01
    with pytest.raises(ba.PlanDriftError) as ei:
        _apply(db_session, req, user)
    diff = ei.value.diff
    assert any(row[0] == "2027-01" for row in diff["create_removed"])
    assert any(row[1] == "auto-03" for row in diff["cancel_removed"])
    assert set(_names()) == {"list_charges"}  # sin escrituras
    assert _status(db_session, req) == "aprobada" and _events(db_session, req) == []

    result = _apply(db_session, req, user, accept_drift=True)
    assert result.status == "ejecutada" and result.drift_accepted is not None
    assert len(req.plan_preview["create"]) == 11
    assert "auto-03" not in _deleted()


def test_cancelled_subscription_is_not_executable_without_writes(db_session):
    """RA-22, JB-17: suscripcion cancelada tras la aprobacion -> no_ejecutable, cero llamadas."""
    user, req = _setup(db_session)
    sub = db_session.scalar(select(Subscription).where(Subscription.external_id == SUB))
    sub.status = "CANCELADA"
    db_session.commit()
    result = _apply(db_session, req, user)
    assert result.status == "no_ejecutable" and result.reason == "subscription_not_active"
    assert CALLS == []
    assert _status(db_session, req) == "no_ejecutable" and _events(db_session, req) == ["no_ejecutable"]


def test_plan_changed_is_not_executable(db_session):
    """AP-13: el plan de la suscripcion cambio desde la solicitud."""
    user, req = _setup(db_session, rules_snapshot={"plan_external_id": "plan-OLD"})
    result = _apply(db_session, req, user)
    assert result.status == "no_ejecutable" and result.reason == "plan_changed" and CALLS == []


def test_lock_busy_raises_and_leaves_request_untouched(db_session):
    """RA-13, RA-27: lock tomado por otra sesion -> SubscriptionBusyError (409); luego se libera."""
    user, req = _setup(db_session)
    other = engine.connect()
    other.begin()
    other.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": ba.lock_key("virtualpos1", SUB)})
    try:
        with pytest.raises(ba.SubscriptionBusyError):
            _apply(db_session, req, user)
        assert CALLS == [] and _status(db_session, req) == "aprobada"
    finally:
        other.rollback()
        other.close()
    assert _apply(db_session, req, user).status == "ejecutada"
    probe = engine.connect()
    try:
        probe.begin()
        assert probe.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": ba.lock_key("virtualpos1", SUB)}).scalar()
    finally:
        probe.rollback()
        probe.close()


def test_lock_key_is_stable_and_per_subscription():
    assert ba.lock_key("virtualpos1", "a") == ba.lock_key("virtualpos1", "a")
    assert ba.lock_key("virtualpos1", "a") != ba.lock_key("virtualpos2", "a")
    assert ba.lock_key("virtualpos1", "a") != ba.lock_key("virtualpos1", "b")


def test_atomic_transition_only_one_claim_wins(db_session):
    """AP-14: la transicion aprobada->aplicando es condicional; la segunda aplicacion no pasa."""
    user, req = _setup(db_session)
    assert ba._claim_request(db_session, req.id) is True
    assert ba._claim_request(db_session, req.id) is False
    db_session.commit()
    with pytest.raises(ba.InvalidRequestStateError):
        _apply(db_session, req, user)
    assert CALLS == []


def test_blocked_by_other_request_reconciliation(db_session):
    """RA-09: cobros en conciliacion de OTRA solicitud bloquean la suscripcion."""
    user, req = _setup(db_session)
    other = BillingChangeRequest(
        request_type="change_amount", platform="virtualpos1", subscription_external_id="otra", requested_by_user_id=user.id,
        status="fallida", new_amount=1, rules_snapshot={}, plan_preview={})
    db_session.add(other)
    db_session.flush()
    db_session.add(VpManagedCharge(platform="virtualpos1", charge_id="x-1", subscription_external_id=SUB, internal_code="c",
                                   month="2026-11", amount=1, request_id=other.id, status="requiere_conciliacion"))
    db_session.commit()
    with pytest.raises(ba.SubscriptionBlockedError):
        _apply(db_session, req, user)
    assert CALLS == []


# ----------------------------- banderas y dry-run -----------------------------


def test_writes_disabled_does_not_advance_state(monkeypatch, db_session):
    """JB-19: VIRTUALPOS_WRITES_ENABLED apagada -> WriteDisabledError y la solicitud sigue `aprobada`."""
    user, req = _setup(db_session)
    monkeypatch.setattr(settings, "virtualpos_writes_enabled", False)
    with pytest.raises(wv.WriteDisabledError):
        _apply(db_session, req, user)
    assert CALLS == [] and _status(db_session, req) == "aprobada" and _events(db_session, req) == []


def test_fixed_plan_flag_off_does_not_advance_state(monkeypatch, db_session):
    """RA-23: plan MONTO_FIJO con bandera apagada -> FixedPlanChargeBlockedError antes de cambiar de estado."""
    user, req = _setup(db_session)
    monkeypatch.setattr(settings, "virtualpos_allow_charge_on_fixed_plan", False)
    with pytest.raises(wv.FixedPlanChargeBlockedError):
        _apply(db_session, req, user)
    assert CALLS == [] and _status(db_session, req) == "aprobada"


def test_preview_change_is_read_only(db_session):
    """RA-24, AP-29: dry_run = solo lecturas; sin write_runs, eventos ni cambio de estado."""
    _user, req = _setup(db_session)
    runs_before = len(list(db_session.scalars(select(WriteRun))))
    plan = asyncio.run(ba.preview_change(db_session, req, now=NOW))
    assert len(plan.create) == 12 and len(plan.cancel) == 12
    plan2 = asyncio.run(ba.preview_change(db_session, PlanInput(
        request_type="change_amount", subscription_external_id=SUB, platform="virtualpos1", new_amount=12000,
        effective_month="2026-11", charge_day=5), now=NOW))
    assert len(plan2.create) == 12
    assert set(_names()) == {"list_charges"}
    assert len(list(db_session.scalars(select(WriteRun)))) == runs_before
    assert _status(db_session, req) == "aprobada" and _events(db_session, req) == []


# ----------------------------- DELETE plural prohibido (CO-16) -----------------------------


def _mark(db):
    db.add(VpCalendarMark(platform="virtualpos1", subscription_external_id=SUB, last_scheduled_month="2027-10",
                          last_scheduled_date=date(2027, 10, 5), scheduled_amount=12000, charge_day=5))
    db.flush()


def test_plural_cancel_forbidden_with_calendar_mark(db_session):
    """CO-16 / hallazgo 1: sin charge_ids y con marca -> PluralCancelForbiddenError, sin llamadas."""
    _seed_user_sub(db_session)
    _mark(db_session)
    with pytest.raises(wv.PluralCancelForbiddenError):
        asyncio.run(wv.cancel_future_charges(db_session, SUB))
    assert CALLS == []
    # dry_run (solo lectura) y charge_ids explicitos siguen permitidos
    assert asyncio.run(wv.cancel_future_charges(db_session, SUB, dry_run=True))["dry_run"] is True
    res = asyncio.run(wv.cancel_future_charges(db_session, SUB, charge_ids=["auto-01"]))
    assert [c["id"] for c in res["cancelled"]] == ["auto-01"]
    assert "delete_plural" not in _names()


def test_plural_cancel_allowed_without_mark_and_with_inactive_mark(db_session):
    """Sin marca activa el comportamiento actual no cambia."""
    _seed_user_sub(db_session)
    res = asyncio.run(wv.cancel_future_charges(db_session, SUB))
    assert ("delete_plural", SUB) in CALLS and res["cancelled"]
    CALLS.clear()
    for c in STATE["charges"]:
        c["status"] = "pendiente" if c["id"].startswith("auto") else c["status"]
    _mark(db_session)
    db_session.scalar(select(VpCalendarMark)).is_active = False
    db_session.flush()
    asyncio.run(wv.cancel_future_charges(db_session, SUB))
    assert ("delete_plural", SUB) in CALLS


def _route_client(monkeypatch, db_session, perms):
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    user = SimpleNamespace(id=uuid.uuid4(), is_active=True,
                           roles=[SimpleNamespace(name="r", permissions=[SimpleNamespace(code=p) for p in perms])])
    token, csrf = create_access_token(user)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    client.cookies.set(ACCESS_COOKIE, token)
    return client, csrf


@pytest.fixture
def _cleanup():
    yield
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


def test_route_plural_delete_409_with_mark_and_ok_without(monkeypatch, db_session, _cleanup):
    """CO-16 en la ruta DELETE /virtualpos/subscriptions/{id}/charges."""
    _seed_user_sub(db_session)
    client, csrf = _route_client(monkeypatch, db_session, ["virtualpos.charges.cancel"])
    h = {"X-CSRF-Token": csrf}
    url = f"/api/v1/writes/virtualpos/subscriptions/{SUB}/charges"
    r = client.delete(f"{url}?dry_run=false", headers=h)
    assert r.status_code == 200 and ("delete_plural", SUB) in CALLS  # sin marca: igual que hoy
    CALLS.clear()
    for c in STATE["charges"]:
        c["status"] = "pendiente" if c["id"].startswith("auto") else c["status"]
    _mark(db_session)
    r = client.delete(f"{url}?dry_run=false", headers=h)
    assert r.status_code == 409 and "charge_ids" in r.json()["detail"]
    assert "delete_plural" not in _names()
    assert client.delete(url, headers=h).status_code == 200  # dry_run por defecto: solo lectura
