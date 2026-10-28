# ruff: noqa: F811,F401  (fixtures importadas de billing_requests_support)
"""Tanda 2 (revision de la opcion A): API, politica, scheduler y KPIs. SOLO con fakes (ninguna llamada de red).

Cada test se escribio primero contra el codigo anterior (en rojo) y luego se arreglo el defecto.
Numeracion = puntos 1-11 del encargo de la tanda 2.
"""

import asyncio
import inspect
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from billing_requests_support import (
    CALLS,
    NOW,
    STATE,
    SUB,
    FakeVP,
    api_error,
    client_for,
    db_session,
    env,
    make_role,
    make_user,
    names,
    roles_kit,
    seed_crm_calendar,
    seed_sub,
    set_policy,
)
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from test_billing_renewal import add_sub, mark
from test_billing_requests_api import BASE, BODY, World

from app.api.v1.routes import billing_changes as bc
from app.api.v1.routes import scheduler as sched_routes
from app.api.v1.routes import staging, sync_runs
from app.models.auth import Role
from app.models.billing import (
    BillingChangeRequest,
    BillingChangeRequestEvent,
    BillingRenewalTask,
    VpCalendarMark,
    VpManagedCharge,
)
from app.models.crm import Subscription
from app.models.sync_run import SyncRun
from app.scheduler import engine as sched_engine
from app.scheduler.jobs import billing_jobs
from app.services import billing_apply as ba
from app.services import billing_renewal as rn
from app.services import billing_requests as br
from app.services import write_virtualpos as wv
from app.services.billing_plan import (
    PlanCharge,
    PlanInput,
    build_plan,
    plan_to_preview_json,
)

LEAK = "juan.perez@example.com 12.345.678-5 https://api.vp.test/subscriptions/9988776655/charges/abc123"


@pytest.fixture
def w(db_session):
    return World(db_session)


def _svc_world(db):
    kit = roles_kit(db)
    a1, a2 = make_user(db, kit["admin"]), make_user(db, kit["admin"])
    requester = make_user(db, kit["solicitante"])
    seed_sub(db)
    return kit, a1, a2, requester


def _params(**over) -> br.RequestParams:
    values = dict(request_type="change_amount", platform="virtualpos1", subscription_external_id=SUB,
                  new_amount=12000, horizon_start_month="2026-11")
    values.update(over)
    return br.RequestParams(**values)


def _create(db, user, **over):
    return asyncio.run(br.create_request(db, user, _params(**over), now=NOW))


def _session_factory(db):
    return lambda: Session(bind=db.get_bind(), join_transaction_mode="create_savepoint")


# ----------------------------- 1. previous_charge_day -----------------------------


def test_1_create_stores_the_effective_charge_day(db_session):
    """La solicitud guarda el dia vigente (modal sin puntuales ni reemplazos) para que no cambie al aplicar."""
    _k, a1, _a2, _r = _svc_world(db_session)
    req = _create(db_session, a1)
    assert req.previous_charge_day == 5  # los automaticos de VP caen el dia 5


def test_1_active_mark_wins_over_modal_day(db_session):
    _k, a1, _a2, _r = _svc_world(db_session)
    db_session.add(VpCalendarMark(platform="virtualpos1", subscription_external_id=SUB, last_scheduled_month="2027-10",
                                  last_scheduled_date=date(2027, 10, 15), scheduled_amount=9900, charge_day=15, is_active=True))
    db_session.commit()
    assert _create(db_session, a1).previous_charge_day == 15


def test_1_change_date_also_records_the_previous_day(db_session):
    _k, a1, _a2, _r = _svc_world(db_session)
    req = _create(db_session, a1, request_type="change_date", new_amount=None, new_charge_day=10)
    assert req.new_charge_day == 10 and req.previous_charge_day == 5


def test_1_api_exposes_previous_charge_day(w):
    assert w.create("admin1")["previous_charge_day"] == 5


# ----------------------------- 2. mapeo de errores tipados -----------------------------


def _boom(exc):
    async def _raise(*_a, **_k):
        raise exc
    return _raise


def test_2_listing_error_is_502_on_preview_and_create(w, monkeypatch):
    monkeypatch.setattr(ba, "_fetch_charges", _boom(wv.ProviderListingError("pagina inesperada " + LEAK)))
    for path in ("/changes/preview", "/changes"):
        r = w.post("requester", path, BODY)
        assert r.status_code == 502, path
        assert r.json()["detail"]["code"] == "provider_listing_incomplete"
        assert "example.com" not in r.text and "9988776655" not in r.text


def test_2_listing_error_is_502_on_apply_and_leaves_the_request_approved(w, monkeypatch):
    rid = w.create("admin1")["id"]
    monkeypatch.setattr(ba, "_fetch_charges", _boom(wv.ProviderListingError("pagina inesperada " + LEAK)))
    r = w.post("admin1", f"/changes/{rid}/apply", {})
    assert r.status_code == 502 and r.json()["detail"]["code"] == "provider_listing_incomplete"
    assert w.get("admin1", f"/changes/{rid}").json()["status"] == "aprobada"


def test_2_unparseable_charges_is_422_with_only_count_and_states(w):
    STATE["charges"].append({"id": "bad-secret-id-777", "charge_date": "2026-12-05", "amount": "abc-424242", "status": "pendiente"})
    for path in ("/changes/preview", "/changes"):
        r = w.post("requester", path, BODY)
        assert r.status_code == 422, path
        d = r.json()["detail"]
        assert d["code"] == "unparseable_charges" and d["count"] == 1 and d["by_status"] == {"pendiente": 1}
        assert "bad-secret-id-777" not in r.text and "424242" not in r.text


def test_2_apply_unparseable_is_422(w, monkeypatch):
    rid = w.create("admin1")["id"]
    STATE["charges"].append({"id": "bad-1", "charge_date": "x", "amount": 5, "status": "pendiente"})
    r = w.post("admin1", f"/changes/{rid}/apply", {})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unparseable_charges"


@pytest.mark.parametrize(("exc", "code"), [
    (ba.SubscriptionBusyError("ocupada"), "subscription_busy"),
    (ba.SubscriptionBlockedError("bloqueada"), "subscription_blocked"),
])
def test_2_busy_and_blocked_are_409(w, monkeypatch, exc, code):
    rid = w.create("admin1")["id"]
    monkeypatch.setattr(bc.svc, "apply_request", _boom(exc))
    r = w.post("admin1", f"/changes/{rid}/apply", {})
    assert r.status_code == 409 and r.json()["detail"]["code"] == code


def _instances():
    out = []
    for cls in {c for _n, c in inspect.getmembers(ba, inspect.isclass) if issubclass(c, ba.BillingApplyError)}:
        if cls is ba.UnparseableChargesError:
            out.append(cls(1, {"pendiente": 1}))
        elif cls is ba.PlanDriftError:
            out.append(cls({}, {}))
        elif cls is ba.ApplyFailedError:
            out.append(cls(uuid.uuid4(), None, []))
        elif cls is ba.InvalidRequestStateError:
            out.append(cls("x"))
        else:
            out.append(cls("x"))
    for cls in (wv.WriteDisabledError, wv.FixedPlanChargeBlockedError, wv.ProviderListingError, wv.ReconciliationRequiredError,
                wv.PluralCancelForbiddenError, wv.BillingFlowConflictError, wv.ChargeNotFoundError):
        out.append(cls("x"))
    return out


@pytest.mark.parametrize("exc", _instances(), ids=lambda e: type(e).__name__)
def test_2_no_typed_error_falls_through_to_500(exc):
    """Toda excepcion publica de billing_apply / write_virtualpos alcanzable desde las rutas se traduce a HTTPException."""
    with pytest.raises(HTTPException) as info:
        bc._http(exc)
    assert info.value.status_code in (403, 404, 409, 422, 502, 503)
    assert isinstance(exc, bc._HANDLED)


# ----------------------------- 3. politica: aprobadores efectivos -----------------------------


def _put(db, actor, **patch):
    return br.update_policy(db, actor, patch)


def _code(db, actor, **patch):
    with pytest.raises(br.PolicyValidationError) as info:
        _put(db, actor, **patch)
    db.rollback()
    return info.value.policy_code


def test_3_role_without_approve_permission_is_not_an_effective_approver(db_session):
    _k, a1, _a2, _r = _svc_world(db_session)
    assert _code(db_session, a1, approver_roles=["solicitante-t"]) == "no_approvers"


def test_3_user_without_approve_permission_is_not_effective(db_session):
    _k, a1, _a2, requester = _svc_world(db_session)
    assert _code(db_session, a1, approver_roles=[], approver_user_ids=[str(requester.id)]) == "no_approvers"


def test_3_role_with_approve_or_user_with_approve_counts(db_session):
    kit, a1, _a2, _r = _svc_world(db_session)
    approver = make_user(db_session, kit["aprobador"])
    db_session.commit()
    assert _put(db_session, a1, approver_roles=["aprobador-t"]).approver_roles == ["aprobador-t"]
    assert _put(db_session, a1, approver_roles=["solicitante-t"], approver_user_ids=[str(approver.id)]).approver_user_ids


def test_3_dual_requires_enough_effective_approvers(db_session):
    _kit, a1, _a2, _r = _svc_world(db_session)
    role = make_role(db_session, f"ap-{uuid.uuid4().hex[:8]}", {"virtualpos.billing_changes.approve"})  # rol propio: la BD
    users = [make_user(db_session, role) for _ in range(2)]                                              # puede traer admins
    db_session.commit()
    # un solo aprobador efectivo: la doble aprobacion no se puede cumplir
    _put(db_session, a1, approver_roles=[], approver_user_ids=[str(users[0].id)])
    assert _code(db_session, a1, dual_approval_enabled=True) == "dual_insufficient_approvers"
    # autoaprobacion ENCENDIDA: bastan 2 efectivos
    _put(db_session, a1, approver_roles=[role.name], approver_user_ids=[])
    assert _put(db_session, a1, dual_approval_enabled=True).dual_approval_enabled is True
    # autoaprobacion APAGADA: hacen falta 3 (el solicitante puede ser uno de los efectivos)
    assert _code(db_session, a1, self_approval_enabled=False) == "dual_insufficient_approvers"
    make_user(db_session, role)
    db_session.commit()
    assert _put(db_session, a1, self_approval_enabled=False).self_approval_enabled is False


def test_3_dual_off_keeps_ap24_only(db_session):
    _k, a1, _a2, _r = _svc_world(db_session)
    assert _put(db_session, a1, self_approval_enabled=False).self_approval_enabled is False  # a2 es otro aprobador


def test_3_api_policy_code_is_explicit(w):
    r = w.put("admin1", "/policy", {"approver_roles": ["solicitante-t"]})
    assert r.status_code == 422 and r.json()["detail"]["policy_code"] == "no_approvers"


def _admin_world(db):
    kit = roles_kit(db)
    boss = make_user(db, kit["admin"])
    only = make_user(db, kit["aprobador"])
    db.commit()
    set_policy(db, approver_roles=["aprobador-t"], approver_user_ids=[])
    return kit, boss, only


def test_3_admin_cannot_deactivate_last_effective_approver(db_session):
    _kit, boss, only = _admin_world(db_session)
    client, h = client_for(db_session, boss)
    r = client.put(f"/api/v1/admin/users/{only.id}", json={"is_active": False}, headers=h)
    assert r.status_code == 409 and "aprobador" in r.json()["detail"].lower()
    db_session.expire_all()
    assert only.is_active is True


def test_3_admin_cannot_remove_the_approver_role_from_last_approver(db_session):
    kit, boss, only = _admin_world(db_session)
    client, h = client_for(db_session, boss)
    r = client.put(f"/api/v1/admin/users/{only.id}", json={"role_ids": [str(kit["solicitante"].id)]}, headers=h)
    assert r.status_code == 409
    db_session.expire_all()
    assert [x.name for x in only.roles] == ["aprobador-t"]


def test_3_admin_can_deactivate_when_another_approver_remains(db_session):
    kit, boss, only = _admin_world(db_session)
    make_user(db_session, kit["aprobador"])
    db_session.commit()
    client, h = client_for(db_session, boss)
    assert client.put(f"/api/v1/admin/users/{only.id}", json={"is_active": False}, headers=h).status_code == 200


def test_3_role_edit_cannot_strip_approve_or_rename_the_last_approver_role(db_session):
    kit, boss, _only = _admin_world(db_session)
    client, h = client_for(db_session, boss)
    role = kit["aprobador"]
    no_approve = {"name": "aprobador-t", "description": None, "permission_codes": ["virtualpos.billing_changes.view"]}
    assert client.put(f"/api/v1/admin/roles/{role.id}", json=no_approve, headers=h).status_code == 409
    renamed = {"name": "aprobador-renamed", "description": None,
               "permission_codes": ["virtualpos.billing_changes.approve", "virtualpos.billing_changes.view"]}
    assert client.put(f"/api/v1/admin/roles/{role.id}", json=renamed, headers=h).status_code == 409
    db_session.expire_all()
    assert role.name == "aprobador-t" and {p.code for p in role.permissions} == {
        "virtualpos.billing_changes.approve", "virtualpos.billing_changes.view"}
    harmless = {"name": "aprobador-t", "description": "x",
                "permission_codes": ["virtualpos.billing_changes.approve", "virtualpos.billing_changes.view"]}
    assert client.put(f"/api/v1/admin/roles/{role.id}", json=harmless, headers=h).status_code == 200


# ----------------------------- 4. reabrir -----------------------------


def _failed(w, status="fallida", error=None):
    rid = w.create("admin1")["id"]
    req = w.db.get(BillingChangeRequest, uuid.UUID(rid))
    req.status, req.error_message = status, error
    w.db.commit()
    return rid


def test_4_policy_manage_without_being_a_policy_approver_cannot_reopen(w):
    rid = _failed(w)
    r = w.post("manager", f"/changes/{rid}/reopen", {"comment": "x"})
    assert r.status_code == 403
    assert w.get("admin1", f"/changes/{rid}").json()["status"] == "fallida"


def test_4_manager_listed_as_approver_with_approve_permission_can_reopen(w):
    rid = _failed(w)
    both = make_user(w.db, make_role(w.db, "ambos-t", {"virtualpos.billing_changes.approve", "virtualpos.billing_policy.manage"}))
    w.db.commit()
    set_policy(w.db, approver_user_ids=[str(both.id)])
    client, h = client_for(w.db, both)
    assert client.post(f"{BASE}/changes/{rid}/reopen", json={"comment": "ok"}, headers=h).status_code == 200


def test_4_blocked_subscription_cannot_be_reopened(w):
    rid = _failed(w)
    w.db.add(VpManagedCharge(platform="virtualpos1", charge_id="otro-1", subscription_external_id=SUB, internal_code="c",
                             month="2026-11", amount=1, request_id=None, status="requiere_conciliacion"))
    w.db.commit()
    r = w.post("admin1", f"/changes/{rid}/reopen", {"comment": "x"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "subscription_blocked"


def test_4_reopen_resets_approvals_and_records_the_previous_state(w):
    rid = _failed(w)
    req = w.db.get(BillingChangeRequest, uuid.UUID(rid))
    req.approvals_count, req.approvals_required = 2, 2
    w.db.commit()
    r = w.post("admin1", f"/changes/{rid}/reopen", {"comment": "reintento"})
    assert r.status_code == 200
    body = r.json()
    assert body["approvals_count"] == 0 and body["approvals_required"] == 1 and body["status"] == "aprobada"
    detail = body["events"][-1]["detail"]
    assert detail["action"] == "reabierta" and detail["from_status"] == "fallida"
    assert detail["previous_approvals_count"] == 2 and detail["previous_approvals_required"] == 2
    assert detail["new_approvals_required"] == 1


def test_4_comment_still_required(w):
    rid = _failed(w)
    assert w.post("admin1", f"/changes/{rid}/reopen", {}).status_code == 422
    assert w.post("admin1", f"/changes/{rid}/reopen", {"comment": "  "}).status_code == 422


# ----------------------------- 5. error_message sin texto libre -----------------------------


def _leaky_create(monkeypatch):
    async def _create(self, data):
        raise RuntimeError(f"fallo del proveedor para {LEAK}")
    monkeypatch.setattr(FakeVP, "create_charge", _create)


def _everything(w, rid) -> str:
    w.db.expire_all()
    req = w.db.get(BillingChangeRequest, uuid.UUID(rid))
    events = [e.detail for e in w.db.scalars(select(BillingChangeRequestEvent).where(BillingChangeRequestEvent.request_id == req.id))]
    return json.dumps({"error_message": req.error_message, "events": events}, default=str)


def test_5_apply_failure_stores_only_the_exception_type(w, monkeypatch):
    rid = w.create("admin1")["id"]
    _leaky_create(monkeypatch)
    r = w.post("admin1", f"/changes/{rid}/apply", {})
    assert r.status_code in (502, 503)
    stored = _everything(w, rid)
    for part in ("example.com", "12.345.678-5", "9988776655", "abc123", "https://"):
        assert part not in stored, part
        assert part not in r.text
    detail = w.get("admin1", f"/changes/{rid}")
    for part in ("example.com", "12.345.678-5", "9988776655", "abc123"):
        assert part not in detail.text
    assert detail.json()["error_message"] and len(detail.json()["error_message"]) < 80


def test_5_label_has_type_and_provider_code_only():
    assert ba.error_label(api_error("E-113")) == "VirtualPOSAPIError E-113"
    assert ba.error_label(RuntimeError(LEAK)) == "RuntimeError"


def test_5_legacy_free_text_is_reduced_on_reopen_and_in_responses(w):
    rid = _failed(w, error=f"Fallo {LEAK} (E-113)")
    detail = w.get("admin1", f"/changes/{rid}")
    assert "example.com" not in detail.text and "9988776655" not in detail.text
    r = w.post("admin1", f"/changes/{rid}/reopen", {"comment": "ok"})
    assert "example.com" not in r.text and "12.345.678-5" not in r.text and "9988776655" not in r.text
    assert "example.com" not in _everything(w, rid)
    assert r.json()["events"][-1]["detail"]["previous_error"]


# ----------------------------- 6. validaciones de entrada -----------------------------


def _check(**over):
    br._validate_params(_params(**over), NOW.date())


def _one_off(d):
    return dict(request_type="one_off_charge", new_amount=5000, new_charge_date=d, horizon_start_month=None)


def test_6_charge_date_bounds():
    today = NOW.date()
    _check(**_one_off(today + timedelta(days=1)))
    _check(**_one_off(date(today.year + 5, today.month, today.day)))
    for bad in (today, today - timedelta(days=1), date(today.year + 5, today.month, today.day) + timedelta(days=1), date(2999, 1, 1)):
        with pytest.raises(br.InvalidRequestFieldsError) as info:
            _check(**_one_off(bad))
        assert str(bad) not in str(info.value)


def test_6_horizon_start_month_bounds():
    for ok in ("2026-09", "2026-10", "2028-10"):
        _check(horizon_start_month=ok)
    for bad in ("2026-08", "2028-11", "0001-01", "9999-12", "2026-00", "2026-13"):
        with pytest.raises(br.InvalidRequestFieldsError) as info:
            _check(horizon_start_month=bad)
        assert bad not in str(info.value)


def test_6_api_rejects_without_echoing_values(w):
    for body, secret in (({"horizon_start_month": "0001-01"}, "0001-01"), ({"horizon_start_month": "zzz-secreto"}, "zzz-secreto"),
                         (_one_off("2999-01-01"), "2999-01-01"), (_one_off("fecha-secreta"), "fecha-secreta")):
        r = w.post("requester", "/changes/preview", {**BODY, **body, "subscription_external_id": SUB})
        assert r.status_code == 422, body
        assert secret not in r.text, body


# ----------------------------- 7. retirar: 403 antes que 409 -----------------------------


def test_7_withdraw_checks_ownership_before_revealing_state(w):
    rid = w.create("requester")["id"]
    req = w.db.get(BillingChangeRequest, uuid.UUID(rid))
    req.status = "aprobada"
    w.db.commit()
    r = w.post("stranger", f"/changes/{rid}/withdraw", {})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "forbidden"
    assert "current_status" not in r.json()["detail"]
    own = w.post("requester", f"/changes/{rid}/withdraw", {})
    assert own.status_code == 409 and own.json()["detail"]["current_status"] == "aprobada"


# ----------------------------- 8. scheduler y KPIs -----------------------------


def test_8a_kpi_and_listing_only_count_channel_sources(db_session):
    db_session.execute(SyncRun.__table__.delete())
    now = datetime.now(UTC)
    db_session.add_all([SyncRun(source="toku", status="completed", started_at=now, records_processed=1)]
                      + [SyncRun(source=s, status="failed", started_at=now)
                         for s in ("billing_renewal_check", "billing_expire_requests", "billing_sweep_applying")])
    db_session.flush()
    staging.invalidate_dashboard_cache()
    try:
        assert staging.general_dashboard(db=db_session)["sync_success_rate_pct"] == 100.0
    finally:
        staging.invalidate_dashboard_cache()  # el cache global no debe filtrar datos de esta transaccion a otros tests
    listed = {r["source"] for r in sync_runs.list_sync_runs(db=db_session)}
    assert listed == {"toku"}


def test_8a_every_billing_job_id_uses_the_excluded_prefix():
    from app.models.sync_run import BILLING_JOB_PREFIX

    assert billing_jobs.BILLING_JOB_IDS and all(j.startswith(BILLING_JOB_PREFIX) for j in billing_jobs.BILLING_JOB_IDS)
    assert billing_jobs.JOB_BILLING_SWEEP in billing_jobs.BILLING_JOB_IDS


@pytest.mark.parametrize(("examined", "errors", "status"), [(3, 0, "completed"), (3, 1, "partial"), (3, 3, "failed")])
def test_8b_renewal_run_status_reflects_errors(db_session, monkeypatch, examined, errors, status):
    monkeypatch.setattr(billing_jobs, "SessionLocal", _session_factory(db_session))
    monkeypatch.setattr(rn, "run_renewal_check", lambda db: rn.RenewalCheckResult(examined=examined, errors=errors, opened=1))
    asyncio.run(billing_jobs.billing_renewal_check())
    run = db_session.scalar(select(SyncRun).where(SyncRun.source == "billing_renewal_check"))
    assert run.status == status and len(run.status) <= 20
    assert (run.error_message or "").startswith("errores=") == bool(errors)


def test_8c_sweep_job_is_registered_every_15_minutes():
    sched = AsyncIOScheduler(timezone="America/Santiago")
    sched_engine.register_jobs(sched)
    jobs = {j.id: j for j in sched.get_jobs()}
    assert "minute='5,20,35,50'" in str(jobs["billing_sweep_applying"].trigger)
    assert "minute='10'" in str(jobs["billing_expire_requests"].trigger)
    sched_engine.register_jobs(sched)
    assert len(sched.get_jobs()) == 5


def _stuck_request(w, minutes=120):
    rid = w.create("admin1")["id"]
    w.db.execute(update(BillingChangeRequest).where(BillingChangeRequest.id == uuid.UUID(rid))
                 .values(status="aplicando", updated_at=datetime.now(UTC) - timedelta(minutes=minutes)))
    w.db.commit()
    return rid


def test_8c_sweep_job_moves_stuck_requests_and_logs_only_when_it_did_something(w, monkeypatch):
    monkeypatch.setattr(billing_jobs, "SessionLocal", _session_factory(w.db))
    asyncio.run(billing_jobs.billing_sweep_applying())  # nada que barrer, ejecucion programada: sin fila
    assert w.db.scalar(select(func.count()).select_from(SyncRun).where(SyncRun.source == "billing_sweep_applying")) == 0
    rid = _stuck_request(w)
    asyncio.run(billing_jobs.billing_sweep_applying())
    w.db.expire_all()
    assert w.db.get(BillingChangeRequest, uuid.UUID(rid)).status == "requiere_conciliacion"
    run = w.db.scalar(select(SyncRun).where(SyncRun.source == "billing_sweep_applying"))
    assert run.status == "completed" and run.records_processed == 1 and run.finished_at is not None
    # la bandeja la muestra como requiere_conciliacion
    listed = w.get("admin1", "/changes?status=requiere_conciliacion").json()["items"]
    assert [i["id"] for i in listed] == [rid]


def test_8c_sweep_job_manual_run_always_leaves_a_row(w, monkeypatch):
    monkeypatch.setattr(billing_jobs, "SessionLocal", _session_factory(w.db))
    run_id = str(uuid.uuid4())
    asyncio.run(billing_jobs.billing_sweep_applying(run_id))
    run = w.db.get(SyncRun, uuid.UUID(run_id))
    assert run is not None and run.status == "completed" and run.records_processed == 0


def _routes(w, monkeypatch, ran):
    sched = AsyncIOScheduler(timezone="America/Santiago")
    sched_engine.register_jobs(sched)
    monkeypatch.setattr(sched_routes, "get_scheduler", lambda: sched)

    def fake(label):
        async def _job(run_id=None):
            ran.append((label, run_id))  # no cierra la fila: simula un job en curso
        return _job

    monkeypatch.setattr(sched_routes, "billing_renewal_check", fake("renewal"))
    monkeypatch.setattr(sched_routes, "billing_expire_requests", fake("expire"))
    monkeypatch.setattr(sched_routes, "billing_sweep_applying", fake("sweep"))
    role = make_role(w.db, "sched-t2", {"sync.run", "sync_runs.view"})
    return client_for(w.db, make_user(w.db, role))


@pytest.mark.parametrize(("job", "label"), [("billing_renewal_check", "renewal"), ("billing_expire_requests", "expire"),
                                             ("billing_sweep_applying", "sweep")])
def test_8d_run_creates_the_running_row_before_launching_so_a_double_click_is_409(w, monkeypatch, job, label):
    ran: list = []
    client, h = _routes(w, monkeypatch, ran)
    first = client.post(f"/api/v1/scheduler/jobs/{job}/run", json={}, headers=h)
    assert first.status_code == 202
    row = w.db.get(SyncRun, uuid.UUID(first.json()["run_id"]))
    assert row is not None and row.status == "running" and row.source == job
    second = client.post(f"/api/v1/scheduler/jobs/{job}/run", json={}, headers=h)
    assert second.status_code == 409
    assert ran == [(label, first.json()["run_id"])]


def test_8d_checks_404_and_422(w, monkeypatch):
    client, h = _routes(w, monkeypatch, [])
    assert client.post("/api/v1/scheduler/jobs/no_existe/run", json={}, headers=h).status_code == 404
    assert client.post("/api/v1/scheduler/jobs/billing_sweep_applying/run", json={"channels": ["toku"]}, headers=h).status_code == 422


def test_8d_a_stale_running_row_does_not_block_forever(w, monkeypatch):
    client, h = _routes(w, monkeypatch, [])
    w.db.add(SyncRun(source="billing_renewal_check", status="running", started_at=datetime.now(UTC) - timedelta(hours=5)))
    w.db.commit()
    assert client.post("/api/v1/scheduler/jobs/billing_renewal_check/run", json={}, headers=h).status_code == 202


def test_8d_job_functions_adopt_the_row_created_by_the_endpoint(w, monkeypatch):
    monkeypatch.setattr(billing_jobs, "SessionLocal", _session_factory(w.db))
    run_id = uuid.uuid4()
    w.db.add(SyncRun(id=run_id, source="billing_expire_requests", status="running"))
    w.db.commit()
    asyncio.run(billing_jobs.billing_expire_requests(str(run_id)))
    w.db.expire_all()
    rows = list(w.db.scalars(select(SyncRun).where(SyncRun.source == "billing_expire_requests")))
    assert len(rows) == 1 and rows[0].id == run_id and rows[0].status == "completed"


def test_8e_expire_job_has_a_running_row_while_it_works(w, monkeypatch):
    monkeypatch.setattr(billing_jobs, "SessionLocal", _session_factory(w.db))
    seen: list[bool] = []

    def fake_expire(db):
        seen.append(w.db.scalar(select(SyncRun).where(SyncRun.source == "billing_expire_requests", SyncRun.status == "running")) is not None)
        return []

    monkeypatch.setattr(br, "expire_pending_requests", fake_expire)
    asyncio.run(billing_jobs.billing_expire_requests())
    assert seen == [True]
    # y sin nada que expirar (ejecucion programada) no deja filas de ruido
    assert w.db.scalar(select(func.count()).select_from(SyncRun).where(SyncRun.source == "billing_expire_requests")) == 0


# ----------------------------- 9. renovacion -----------------------------


@pytest.fixture
def rworld(db_session):
    seed_sub(db_session)
    db_session.add(SyncRun(source="virtualpos1", status="completed", started_at=NOW - timedelta(hours=1),
                           finished_at=NOW - timedelta(hours=1)))
    db_session.commit()
    return db_session


def _tasks(db, sub):
    db.expire_all()
    return list(db.scalars(select(BillingRenewalTask).where(BillingRenewalTask.subscription_external_id == sub)))


def test_9_unsynced_subscription_is_skipped_not_closed(rworld):
    mark(rworld, 20, sub="sub-nueva")  # la suscripcion aun no esta en vp_subscriptions ni en subscriptions
    result = rn.run_renewal_check(rworld, NOW)
    assert result.unsynced == 1 and result.not_applicable == 0 and result.opened == 0 and result.errors == 0
    assert _tasks(rworld, "sub-nueva") == []


def test_9_unsynced_subscription_keeps_its_open_task_marked_stale(rworld):
    add_sub(rworld, "sub-x")
    mark(rworld, 20, sub="sub-x")
    rn.run_renewal_check(rworld, NOW)
    assert _tasks(rworld, "sub-x")[0].status == "abierta"
    rworld.execute(Subscription.__table__.delete().where(Subscription.external_id == "sub-x"))
    rworld.commit()
    result = rn.run_renewal_check(rworld, NOW)
    task = _tasks(rworld, "sub-x")[0]
    assert task.status == "abierta" and task.data_stale is True and result.unsynced == 1 and result.not_applicable == 0


@pytest.mark.parametrize("status", ["ACTIVA", "activa", "Activa", "active", "ACTIVE", " activa "])
def test_9_active_status_is_compared_robustly(rworld, status):
    add_sub(rworld, "sub-s", status)
    mark(rworld, 20, sub="sub-s")
    assert rn.run_renewal_check(rworld, NOW).opened == 1


@pytest.mark.parametrize("status", ["CANCELADA", "cancelled", "inactive", None])
def test_9_non_active_status_still_closes_the_task(rworld, status):
    add_sub(rworld, "sub-n", "ACTIVA")
    mark(rworld, 20, sub="sub-n")
    rn.run_renewal_check(rworld, NOW)
    rworld.execute(update(Subscription).where(Subscription.external_id == "sub-n").values(status=status))
    rworld.commit()
    result = rn.run_renewal_check(rworld, NOW)
    assert result.not_applicable == 1 and _tasks(rworld, "sub-n")[0].status == "no_aplica"


# ----------------------------- 10. docstring -----------------------------


def test_10_expire_docstring_no_longer_says_unregistered():
    doc = inspect.getdoc(br.expire_pending_requests) or ""
    assert "NO esta registrada" not in doc and "billing_expire_requests" in doc


# ----------------------------- 11. mensajes del plan hacia el front -----------------------------


def _charge(cid, d, amount, status, code=None):
    return PlanCharge(charge_id=cid, status=status, charge_date=d, amount=amount, internal_code=code)


def test_11_unknown_status_message_has_no_provider_value():
    inp = PlanInput(request_type="change_amount", subscription_external_id="s", platform="virtualpos1", new_amount=1000,
                    charge_day=5, effective_month="2026-11", horizon_months=2, today=date(2026, 10, 28),
                    charges=(_charge("c1", date(2026, 11, 5), 900, "ZZ-SECRETO-99"), _charge("c2", date(2026, 12, 5), 900, "pendiente")))
    preview = plan_to_preview_json(build_plan(inp))
    issue = next(i for i in preview["warnings"] if i["code"] == "unknown_status")
    assert "ZZ-SECRETO" not in json.dumps(preview) and issue["month"] == "2026-11" and issue["message"]


def _preview_with_replacement_outside_month():
    inp = PlanInput(request_type="change_amount", subscription_external_id="s", platform="virtualpos1", new_amount=1000,
                    charge_day=30, effective_month="2026-10", horizon_months=2, today=date(2026, 10, 31),
                    charges=(_charge("c1", date(2026, 10, 30), 900, "pendiente"), _charge("c2", date(2026, 11, 30), 900, "pendiente"),
                             _charge("c3", date(2026, 11, 29), 900, "ZZ-RAW")))
    return build_plan(inp)


def test_11_manual_review_reason_is_a_stable_code_and_drift_tolerates_kept_due_today():
    plan = _preview_with_replacement_outside_month()
    preview = plan_to_preview_json(plan)
    assert [m["reason"] for m in preview["manual_review"]] == ["replacement_outside_month"]
    assert all(set(i) == {"code", "message", "month"} for i in preview["warnings"] + preview["errors"])
    old = {k: v for k, v in preview.items() if k != "kept_due_today"}  # una solicitud creada antes de la tanda 1
    new = {**preview, "kept_due_today": ["2026-10"]}
    assert ba.compute_drift(old, new, set()) is None and ba.compute_drift(new, old, set()) is None


def test_11_detail_api_exposes_the_stable_reasons(w):
    plan = _preview_with_replacement_outside_month()
    rid = w.create("requester")["id"]
    req = w.db.get(BillingChangeRequest, uuid.UUID(rid))
    req.plan_preview = {**plan_to_preview_json(plan), "kept_due_today": ["2026-10"]}
    w.db.commit()
    got = w.get("admin1", f"/changes/{rid}").json()["plan_preview"]
    assert got["manual_review"][0]["reason"] == "replacement_outside_month" and got["kept_due_today"] == ["2026-10"]
    assert "ZZ-RAW" not in json.dumps(got)
