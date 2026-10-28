# ruff: noqa: F811  (fixtures importadas de billing_requests_support: db_session/env)
"""Paso 6a: chequeo diario de renovacion (solo lectura), jobs del scheduler y endpoint de tareas. Sin red.

Escenarios del doc docs/designs/facturacion-gestionada-escenarios.md: JB-19/20, JB-25..JB-36, AP-10, AP-34.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from billing_requests_support import (  # noqa: F401 - fixtures autouse/importadas
    CALLS,
    NOW,
    SUB,
    client_for,
    db_session,
    env,
    make_role,
    make_user,
    roles_kit,
    seed_sub,
    set_policy,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.main import app
from app.models.billing import BillingChangeRequest, BillingRenewalTask, VpCalendarMark
from app.models.crm import Subscription
from app.models.sync_run import SyncRun
from app.scheduler import engine as sched_engine
from app.scheduler.jobs import billing_jobs
from app.services import billing_renewal as rn
from app.services import billing_requests as br

ROOT = Path(__file__).resolve().parent.parent
TODAY = NOW.date()
BASE = "/api/v1/billing"


# ----------------------------- helpers -----------------------------


def add_sub(db, sub_id, status="ACTIVA"):
    db.add(Subscription(source="virtualpos1", external_id=sub_id, plan_external_id="plan-1", status=status))
    db.commit()


def mark(db, days_ahead, sub=SUB, amount=12000, active=True, platform="virtualpos1"):
    m = VpCalendarMark(platform=platform, subscription_external_id=sub, last_scheduled_month="2027-01",
                       last_scheduled_date=TODAY + timedelta(days=days_ahead), scheduled_amount=amount,
                       charge_day=5, is_active=active)
    db.add(m)
    db.commit()
    return m


def fresh_sync(db, platform="virtualpos1", ago=timedelta(hours=1), status="completed"):
    when = NOW - ago
    db.add(SyncRun(source=platform, status=status, started_at=when, finished_at=when))
    db.commit()


def tasks(db, sub=SUB):
    db.expire_all()
    return list(db.scalars(select(BillingRenewalTask).where(BillingRenewalTask.subscription_external_id == sub)
                           .order_by(BillingRenewalTask.created_at, BillingRenewalTask.id)))


def check(db, now=NOW):
    return rn.run_renewal_check(db, now)


def make_req(db, user, status="pendiente", sub=SUB, request_type="renew_calendar"):
    r = BillingChangeRequest(request_type=request_type, platform="virtualpos1", subscription_external_id=sub, status=status,
                             requested_by_user_id=user.id, new_amount=Decimal(12000), rules_snapshot={})
    db.add(r)
    db.commit()
    return r


@pytest.fixture
def world(db_session):
    seed_sub(db_session)
    fresh_sync(db_session)
    return db_session


# ----------------------------- umbral, dedupe, actualizacion -----------------------------


def test_threshold_boundary_is_inclusive(world):
    """JB-26: a exactamente N=60 dias abre la tarea; a 61 no. JB-25: lleva suscripcion, monto y fecha limite."""
    add_sub(world, "sub-61")
    mark(world, 60)
    mark(world, 61, sub="sub-61")
    res = check(world)
    assert res.examined == 2 and res.opened == 1 and res.errors == 0
    [t] = tasks(world)
    assert t.status == "abierta" and t.days_remaining == 60 and t.due_date == TODAY + timedelta(days=60)
    assert t.scheduled_amount == Decimal(12000) and t.last_scheduled_date == TODAY + timedelta(days=60)
    assert tasks(world, "sub-61") == []


def test_no_mark_never_generates_a_task(world):
    """JB-28: una suscripcion sin calendario modificado no genera tarea."""
    res = check(world)
    assert res.examined == 0 and res.opened == 0 and tasks(world) == []


def test_two_runs_do_not_duplicate_and_days_remaining_updates(world):
    """JB-27: segunda corrida no duplica; dias posteriores solo actualizan days_remaining."""
    mark(world, 30)
    assert check(world).opened == 1
    again = check(world)
    assert again.opened == 0 and again.updated == 0
    assert len(tasks(world)) == 1
    later = check(world, NOW + timedelta(days=3))
    assert later.opened == 0 and later.updated == 1
    [t] = tasks(world)
    assert t.days_remaining == 27 and t.status == "abierta"


def test_threshold_comes_from_policy_not_hardcoded(world):
    """JB-34: rige el N vigente de la politica: con 90 abre a 80 dias; con 30 no abre a 40."""
    add_sub(world, "sub-b")
    mark(world, 80)
    set_policy(world, renewal_threshold_days=90)
    assert check(world).opened == 1
    mark(world, 40, sub="sub-b")
    set_policy(world, renewal_threshold_days=30)
    res = check(world)
    assert res.opened == 0 and tasks(world, "sub-b") == []
    assert tasks(world)[0].status == "abierta"  # la ya abierta no se cierra al bajar N


# ----------------------------- vencida y prioridad -----------------------------


def test_overdue_is_high_priority_and_born_overdue_after_downtime(world):
    """JB-31, JB-33: si ya paso el fin del horizonte la tarea nace `vencida` con prioridad alta."""
    mark(world, -2)
    res = check(world)
    assert res.opened == 1 and res.overdue == 1
    [t] = tasks(world)
    assert t.status == "vencida" and t.priority == "alta" and t.days_remaining == -2


def test_open_task_turns_overdue_over_time_and_priority_rises_under_15_days(world):
    """JB-27 (prioridad al faltar menos de 15 dias), JB-31 (abierta -> vencida con la misma tarea)."""
    add_sub(world, "sub-n")
    mark(world, 1)
    mark(world, 30, sub="sub-n")
    check(world)
    assert tasks(world, "sub-n")[0].priority == "normal"
    [t] = tasks(world)
    assert t.priority == "alta" and t.status == "abierta"
    task_id = t.id
    res = check(world, NOW + timedelta(days=2))
    assert res.overdue == 1 and res.opened == 0
    [t] = tasks(world)
    assert t.id == task_id and t.status == "vencida" and t.priority == "alta" and t.days_remaining == -1
    assert tasks(world, "sub-n")[0].priority == "normal"
    check(world, NOW + timedelta(days=20))  # 30 - 20 = 10 dias
    assert tasks(world, "sub-n")[0].priority == "alta"


# ----------------------------- cierres -----------------------------


@pytest.mark.parametrize("status", ["CANCELADA", "FINALIZADA", "SUSCRIPCION_FALLIDA"])
def test_task_closed_no_aplica_when_subscription_not_active(world, status):
    """JB-35: la suscripcion deja de estar ACTIVA -> la abierta se cierra `no_aplica`; no se vuelve a abrir."""
    mark(world, 20)
    check(world)
    world.execute(text("update subscriptions set status = :s where external_id = :e"), {"s": status, "e": SUB})
    world.commit()
    res = check(world)
    assert res.not_applicable == 1 and res.opened == 0
    [t] = tasks(world)
    assert t.status == "no_aplica" and t.closed_at is not None and status in t.close_reason
    again = check(world)
    assert again.not_applicable == 0 and again.opened == 0 and len(tasks(world)) == 1


def test_inactive_subscription_without_task_creates_nothing(world):
    """JB-35: no genera tarea para una suscripcion cancelada."""
    world.execute(text("update subscriptions set status = 'CANCELADA'"))
    world.commit()
    mark(world, 10)
    res = check(world)
    assert res.opened == 0 and tasks(world) == []


def test_task_closed_when_renewal_executed_links_request(world):
    """AP-34, JB-30: la renovacion se ejecuta y extiende el calendario -> tarea `cerrada` con request_id enlazado."""
    user = make_user(world, roles_kit(world)["solicitante"])
    m = mark(world, 20)
    pending = make_req(world, user, "pendiente")
    check(world)
    [t] = tasks(world)
    assert t.request_id == pending.id  # AP-34: enlazada a la solicitud de renovacion abierta
    pending.status = "ejecutada"
    m.last_scheduled_date = TODAY + timedelta(days=385)
    m.origin_request_id = pending.id
    world.commit()
    res = check(world)
    assert res.closed == 1 and res.opened == 0
    [t] = tasks(world)
    assert t.status == "cerrada" and t.request_id == pending.id and t.closed_at is not None and t.close_reason


def test_request_link_dropped_when_request_closed_without_execution(world):
    """AP-34: si la solicitud enlazada se rechaza, la tarea sigue abierta y sin enlace."""
    user = make_user(world, roles_kit(world)["solicitante"])
    mark(world, 20)
    req = make_req(world, user, "pendiente")
    check(world)
    req.status = "retirada"
    world.commit()
    check(world)
    [t] = tasks(world)
    assert t.status == "abierta" and t.request_id is None


def test_deactivated_mark_closes_open_task(world):
    """JB-28/JB-35: la marca se desactiva -> la tarea abierta se cierra `no_aplica`."""
    m = mark(world, 20)
    check(world)
    m.is_active = False
    world.commit()
    res = check(world)
    assert res.not_applicable == 1
    assert tasks(world)[0].status == "no_aplica"


# ----------------------------- datos desactualizados -----------------------------


def test_data_stale_by_age_missing_and_failed(db_session):
    """JB-36: >48 h, sin sync o ultima corrida fallida -> `data_stale`; con sync fresca se limpia."""
    seed_sub(db_session)
    mark(db_session, 20)
    res = check(db_session)  # sin ningun sync
    assert res.opened == 1 and res.stale == 1 and tasks(db_session)[0].data_stale is True
    fresh_sync(db_session, ago=timedelta(hours=49))
    assert check(db_session).stale == 1 and tasks(db_session)[0].data_stale is True
    fresh_sync(db_session, ago=timedelta(hours=47))
    res = check(db_session)
    assert res.stale == 0 and res.updated == 1 and tasks(db_session)[0].data_stale is False
    fresh_sync(db_session, ago=timedelta(minutes=5), status="failed")
    assert check(db_session).stale == 1 and tasks(db_session)[0].data_stale is True


# ----------------------------- hora de Chile -----------------------------


def test_today_is_computed_in_chile_time_across_utc_midnight(world):
    """Las 22:30 del 28/oct en Chile ya son 29/oct en UTC: los dias restantes se cuentan desde el 28 (Chile)."""
    now_utc = datetime(2026, 10, 29, 1, 30, tzinfo=UTC)
    assert now_utc.astimezone(NOW.tzinfo).date() == TODAY  # sanity: sigue siendo 28 en Chile
    mark(world, 60)
    check(world, now_utc)
    [t] = tasks(world)
    assert t.days_remaining == 60  # con fecha UTC serian 59


# ----------------------------- robustez -----------------------------


def test_bad_record_does_not_break_the_batch(world, monkeypatch):
    """Un registro malo se aisla (SAVEPOINT): el resto del lote se procesa y se cuenta el error."""
    from app.services import billing_apply as ba

    add_sub(world, "sub-bad")
    add_sub(world, "sub-ok")
    mark(world, 10, sub="sub-bad")
    mark(world, 10, sub="sub-ok")
    real = ba._subscription_state

    def flaky(db, platform, sub):
        if sub == "sub-bad":
            raise RuntimeError("boom")
        return real(db, platform, sub)

    monkeypatch.setattr(ba, "_subscription_state", flaky)
    res = check(world)
    assert res.errors == 1 and res.opened == 1 and res.examined == 2
    assert tasks(world, "sub-bad") == [] and len(tasks(world, "sub-ok")) == 1


# ----------------------------- CERO ESCRITURAS AL PROVEEDOR (JB-19, JB-29) -----------------------------


@pytest.mark.parametrize("writes", [False, True])
def test_zero_provider_calls_with_writes_flag_on_or_off(world, monkeypatch, writes):
    """JB-19/JB-29: el cliente de VirtualPOS nunca se instancia ni se llama; no hay write_runs; funciona con banderas apagadas."""
    from app.integrations.virtualpos import client as vp_client
    from app.services import write_virtualpos as wv

    def boom(*_a, **_k):
        raise AssertionError("el chequeo de renovacion NO debe tocar el cliente de VirtualPOS")

    monkeypatch.setattr(settings, "virtualpos_writes_enabled", writes)
    monkeypatch.setattr(settings, "virtualpos_allow_charge_on_fixed_plan", writes)
    monkeypatch.setattr(wv, "VirtualPOSClient", boom)
    monkeypatch.setattr(vp_client.VirtualPOSClient, "__init__", boom)
    for name in ("create_charge", "delete_charge", "delete_subscription_charges", "list_charges", "get_charge", "retry_charge"):
        monkeypatch.setattr(vp_client.VirtualPOSClient, name, boom, raising=False)
    before = world.scalar(text("select count(*) from write_runs"))
    for i in range(30):
        sub = f"sub-w{i}"
        add_sub(world, sub)
        mark(world, 10 + i, sub=sub)
    res = check(world)
    assert res.opened == 30 and res.errors == 0
    assert world.scalar(text("select count(*) from write_runs")) == before
    assert CALLS == []


def test_renewal_module_does_not_import_provider_client():
    text_ = (ROOT / "app/services/billing_renewal.py").read_text(encoding="utf-8")
    assert "VirtualPOSClient" not in text_ and "write_virtualpos" not in text_ and "integrations" not in text_.split('"""')[2]


# ----------------------------- scheduler -----------------------------


def test_jobs_registered_with_expected_schedule():
    """El chequeo corre a las 03:00 (despues del sync de las 02:00, antes del reintento de las 04:00); expiracion cada hora."""
    sched = AsyncIOScheduler(timezone="America/Santiago")
    sched_engine.register_jobs(sched)
    jobs = {j.id: j for j in sched.get_jobs()}
    assert {"sync_all_channels", "retry_failed_channels", "billing_renewal_check", "billing_expire_requests"} <= set(jobs)
    renewal = str(jobs["billing_renewal_check"].trigger)
    assert "hour='3'" in renewal and "minute='0'" in renewal
    assert "minute='10'" in str(jobs["billing_expire_requests"].trigger)
    assert str(jobs["billing_renewal_check"].trigger.timezone) == "America/Santiago"
    sched_engine.register_jobs(sched)  # idempotente
    assert len(sched.get_jobs()) == 4


@pytest.mark.parametrize(("env_mode", "flag", "starts"), [("sandbox", False, False), ("sandbox", True, True), ("production", False, True)])
def test_scheduler_respects_sandbox_switch(monkeypatch, env_mode, flag, starts):
    """El scheduler (y por tanto estos jobs) sigue apagado en sandbox salvo SANDBOX_SCHEDULER_ENABLED."""
    import app.main as main_module

    monkeypatch.setattr(settings, "app_env", env_mode)
    monkeypatch.setattr(settings, "sandbox_scheduler_enabled", flag)
    assert main_module.scheduler_should_start() is starts


def _session_factory(db):
    return lambda: Session(bind=db.get_bind(), join_transaction_mode="create_savepoint")


def test_renewal_job_runs_and_records_a_sync_run(world, monkeypatch):
    """El job registra su corrida en sync_runs (lectura) y crea la tarea; no toca etl_runs."""
    monkeypatch.setattr(billing_jobs, "SessionLocal", _session_factory(world))
    mark(world, 30)
    etl_before = world.scalar(text("select count(*) from etl_runs"))
    asyncio.run(billing_jobs.billing_renewal_check())
    assert len(tasks(world)) == 1
    run = world.scalar(select(SyncRun).where(SyncRun.source == "billing_renewal_check"))
    assert run is not None and run.status == "completed" and run.records_processed == 1 and run.finished_at is not None
    assert world.scalar(text("select count(*) from etl_runs")) == etl_before


def test_expire_job_expires_pending_requests(world, monkeypatch):
    """AP-10: el job expira las pendientes vencidas (evento `expirada` del sistema) y deja registro de la corrida."""
    monkeypatch.setattr(billing_jobs, "SessionLocal", _session_factory(world))
    requester = make_user(world, roles_kit(world)["solicitante"])
    req = asyncio.run(br.create_request(world, requester, br.RequestParams(
        request_type="change_amount", platform="virtualpos1", subscription_external_id=SUB, new_amount=12000,
        horizon_start_month="2026-11"), now=NOW))
    assert req.status == "pendiente"
    req.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    world.commit()
    asyncio.run(billing_jobs.billing_expire_requests())
    world.expire_all()
    assert world.get(BillingChangeRequest, req.id).status == "expirada"
    assert [e.event_type for e in br.get_events(world, req.id)][-1] == "expirada"
    run = world.scalar(select(SyncRun).where(SyncRun.source == "billing_expire_requests"))
    assert run is not None and run.status == "completed" and run.records_processed == 1
    n = world.scalar(select(func.count()).select_from(SyncRun).where(SyncRun.source == "billing_expire_requests"))
    asyncio.run(billing_jobs.billing_expire_requests())  # sin nada que expirar: idempotente y sin fila nueva
    assert world.scalar(select(func.count()).select_from(SyncRun).where(SyncRun.source == "billing_expire_requests")) == n


def _scheduler_with_jobs():
    sched = AsyncIOScheduler(timezone="America/Santiago")
    sched_engine.register_jobs(sched)
    return sched


def test_jobs_listed_and_manually_runnable(world, monkeypatch):
    """/scheduler/jobs lista los dos jobs nuevos y /jobs/{id}/run los dispara (permiso sync.run), sin tocar canales."""
    from app.api.v1.routes import scheduler as sched_routes

    sched = _scheduler_with_jobs()
    monkeypatch.setattr(sched_routes, "get_scheduler", lambda: sched)
    ran: list = []

    async def fake_renewal(run_id=None):
        ran.append(("renewal", run_id))

    monkeypatch.setattr(sched_routes, "billing_renewal_check", fake_renewal)
    role = make_role(world, "sched-t", {"sync.run", "sync_runs.view"})
    client, headers = client_for(world, make_user(world, role))
    jobs = {j["id"]: j for j in client.get("/api/v1/scheduler/jobs").json()}
    assert jobs["billing_renewal_check"]["cron"].split()[:2] == ["0", "3"] and jobs["billing_renewal_check"]["status"] == "scheduled"
    assert "billing_expire_requests" in jobs and jobs["retry_failed_channels"]["cron"].split()[:2] == ["0", "4"]
    r = client.post("/api/v1/scheduler/jobs/billing_renewal_check/run", json={}, headers=headers)
    assert r.status_code == 202 and r.json()["skipped_channels"] == []
    assert ran == [("renewal", r.json()["run_id"])]
    assert client.post("/api/v1/scheduler/jobs/billing_renewal_check/run", json={"channels": ["toku"]}, headers=headers).status_code == 422
    noperm = make_user(world, make_role(world, "viewer-t", {"sync_runs.view"}))
    c2, h2 = client_for(world, noperm)
    assert c2.post("/api/v1/scheduler/jobs/billing_renewal_check/run", json={}, headers=h2).status_code == 403


# ----------------------------- endpoint -----------------------------


def _task(db, sub, *, status="abierta", priority="normal", due=10, platform="virtualpos1", stale=False):
    t = BillingRenewalTask(platform=platform, subscription_external_id=sub, status=status, priority=priority,
                           last_scheduled_date=TODAY + timedelta(days=due), scheduled_amount=Decimal(9900),
                           due_date=TODAY + timedelta(days=due), days_remaining=due, data_stale=stale)
    db.add(t)
    db.commit()
    return t


def test_endpoint_permissions(db_session):
    """401 sin sesion; 403 sin `billing_changes.view`; 200 con el permiso (ejecutivo/soporte/solicitante)."""
    kit = roles_kit(db_session)
    _task(db_session, "s1")
    assert TestClient(app).get(f"{BASE}/renewal-tasks").status_code == 401
    nobody = make_user(db_session, make_role(db_session, "noview-t", {"sync.run"}))
    assert client_for(db_session, nobody)[0].get(f"{BASE}/renewal-tasks").status_code == 403
    for key in ("ejecutivo", "soporte", "solicitante"):
        client, _ = client_for(db_session, make_user(db_session, kit[key]))
        r = client.get(f"{BASE}/renewal-tasks")
        assert r.status_code == 200 and r.json()["total"] == 1, key


def test_endpoint_fields_order_filters_and_pagination(db_session):
    """Orden: prioridad alta primero y luego due_date; filtros estado/prioridad/plataforma/suscripcion; paginacion; sin PII."""
    kit = roles_kit(db_session)
    _task(db_session, "a-normal-5", due=5)
    _task(db_session, "b-alta-20", priority="alta", due=20)
    _task(db_session, "c-alta-3", priority="alta", due=3, stale=True)
    _task(db_session, "d-vencida", status="vencida", priority="alta", due=-4)
    _task(db_session, "e-cerrada", status="cerrada", due=1)
    _task(db_session, "f-vp2", due=7, platform="virtualpos2")
    client, _ = client_for(db_session, make_user(db_session, kit["ejecutivo"]))

    body = client.get(f"{BASE}/renewal-tasks").json()
    assert body["total"] == 6 and body["limit"] == 50 and body["offset"] == 0
    order = [i["subscription_external_id"] for i in body["items"]]
    assert order == ["d-vencida", "c-alta-3", "b-alta-20", "e-cerrada", "a-normal-5", "f-vp2"]
    item = body["items"][1]
    assert set(item) == {"id", "platform", "subscription_external_id", "status", "priority", "last_scheduled_date",
                         "scheduled_amount", "due_date", "days_remaining", "data_stale", "request_id", "close_reason"}
    assert item["data_stale"] is True and item["scheduled_amount"] == 9900 and item["request_id"] is None

    def ids(qs):
        return [i["subscription_external_id"] for i in client.get(f"{BASE}/renewal-tasks?{qs}").json()["items"]]

    assert ids("status=vencida") == ["d-vencida"]
    assert ids("status=abierta&status=cerrada") and "d-vencida" not in ids("status=abierta&status=cerrada")
    assert ids("priority=alta") == ["d-vencida", "c-alta-3", "b-alta-20"]
    assert ids("platform=virtualpos2") == ["f-vp2"]
    assert ids("subscription_id=a-normal-5") == ["a-normal-5"]
    page = client.get(f"{BASE}/renewal-tasks?limit=2&offset=2").json()
    assert page["total"] == 6 and [i["subscription_external_id"] for i in page["items"]] == ["b-alta-20", "e-cerrada"]
    assert client.get(f"{BASE}/renewal-tasks?limit=0").status_code == 422
    assert client.get(f"{BASE}/renewal-tasks?status=inventado").status_code == 422
    assert client.get(f"{BASE}/renewal-tasks?platform=toku").status_code == 422


def test_endpoint_does_not_expose_member_pii(db_session):
    """Sin PII del socio: la respuesta no incluye nombre, RUT, correo ni telefono (solo ids de suscripcion)."""
    kit = roles_kit(db_session)
    _task(db_session, "s-pii")
    client, _ = client_for(db_session, make_user(db_session, kit["soporte"]))
    raw = client.get(f"{BASE}/renewal-tasks").text.lower()
    for word in ("rut", "email", "correo", "phone", "telefono", "nombre", "name", "social"):
        assert word not in raw, word


def test_openapi_lists_renewal_tasks_route():
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert set(paths["/api/v1/billing/renewal-tasks"]) == {"get"}
