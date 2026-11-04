# ruff: noqa: F811  (fixtures importadas de billing_requests_support: db_session/env)
"""BILL-10: controles de consistencia GB-CS-02..14 (solo lectura), cola de reconciliacion (GB-CS-09), bloqueo por doble
pendiente (GB-CS-03) y job apagado por defecto. Sin red: solo tablas locales (FakeVP no se llama).
"""

import asyncio
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from billing_requests_support import (  # noqa: F401 - fixtures autouse/importadas
    CALLS,
    NOW,
    SUB,
    client_for,
    db_session,
    env,
    make_user,
    roles_kit,
    seed_sub,
)
from sqlalchemy import func, select

from app.core.config import settings
from app.models.billing import (
    BillingChangeRequest,
    BillingChangeRequestEvent,
    VpCalendarMark,
    VpManagedCharge,
)
from app.models.vp import VpCharge, VpPayment
from app.models.write_run import WriteRun
from app.scheduler import engine as sched_engine
from app.scheduler.jobs import billing_jobs
from app.services import billing_consistency as bc
from app.services import billing_requests as br

BASE = "/api/v1/billing"
TODAY = NOW.date()  # 2026-10-28


def charge(db, cid, day, amount=12000, status="pendiente", sub=SUB):
    db.add(VpCharge(platform="virtualpos1", external_id=cid, subscription_external_id=sub, amount=str(amount),
                    status=status, charge_date=day))


def request(db, user, status="ejecutada", request_type="change_amount", approved=True, sub=SUB):
    r = BillingChangeRequest(request_type=request_type, platform="virtualpos1", subscription_external_id=sub, status=status,
                             requested_by_user_id=user.id, new_amount=Decimal(12000), rules_snapshot={},
                             new_charge_date=date(2026, 11, 20) if request_type == "one_off_charge" else None)
    db.add(r)
    db.flush()
    if approved:
        db.add(BillingChangeRequestEvent(request_id=r.id, event_type="aprobada", actor_user_id=user.id, detail={}))
    return r


def managed(db, cid, month, req, status="creado", amount=12000, code=None, created_ago=timedelta(hours=1)):
    m = VpManagedCharge(platform="virtualpos1", charge_id=cid, subscription_external_id=SUB,
                        internal_code=code or f"{SUB}-{month.replace('-', '')}05-{amount}", month=month,
                        charge_date=date.fromisoformat(f"{month}-05"), amount=amount,
                        request_id=req.id if req is not None else None, status=status)
    m.created_at = NOW.astimezone(UTC) - created_ago
    db.add(m)
    return m


def mark(db, last_month="2026-12", amount=12000, last_date=date(2026, 12, 5)):
    db.add(VpCalendarMark(platform="virtualpos1", subscription_external_id=SUB, last_scheduled_month=last_month,
                          last_scheduled_date=last_date, scheduled_amount=amount, charge_day=5, is_active=True))


@pytest.fixture
def world(db_session):
    kit = roles_kit(db_session)
    admin = make_user(db_session, kit["admin"])
    seed_sub(db_session)
    return db_session, admin


def clean_calendar(db, admin):
    """Calendario sano: marca hasta 2026-12, manuales del CRM (nov y dic) aprobados y sincronizados, octubre pagado."""
    req = request(db, admin)
    mark(db)
    for cid, month in (("m-11", "2026-11"), ("m-12", "2026-12")):
        managed(db, cid, month, req)
        charge(db, cid, f"{month}-05")
    charge(db, "paid-10", "2026-10-05", status="pagado")
    db.add(VpPayment(platform="virtualpos1", external_id="pay-10", charge_external_id="paid-10", amount="12000",
                     status="pagado"))
    db.commit()
    return req


def codes(report):
    return sorted(f.code for f in report.findings)


# ----------------------------- controles -----------------------------


def test_clean_calendar_has_no_findings_and_writes_nothing(world):
    db, admin = world
    clean_calendar(db, admin)
    before = [db.scalar(select(func.count()).select_from(m)) for m in (VpManagedCharge, BillingChangeRequestEvent, WriteRun)]
    report = bc.run_consistency_checks(db, NOW)
    assert report.ok, codes(report)
    assert report.subscriptions_checked == 1
    after = [db.scalar(select(func.count()).select_from(m)) for m in (VpManagedCharge, BillingChangeRequestEvent, WriteRun)]
    assert before == after and CALLS == []  # solo lectura y sin proveedor


def test_amount_mismatch_double_pending_and_unregistered(world):
    """CS-02 (monto distinto), CS-03 (dos pendientes, bloquea, D-3) y CS-06 (cargo ajeno en mes gestionado)."""
    db, admin = world
    clean_calendar(db, admin)
    charge(db, "panel-11", "2026-11-01", amount=9900)  # creado desde el panel de VP en un mes gestionado
    db.commit()
    report = bc.run_consistency_checks(db, NOW)
    got = {(f.scenario, f.code, f.month) for f in report.findings}
    assert ("GB-CS-02", "amount_mismatch", "2026-11") in got
    assert ("GB-CS-03", "double_pending", "2026-11") in got
    assert ("GB-CS-06", "unregistered_charge", "2026-11") in got
    double = next(f for f in report.findings if f.code == "double_pending")
    assert double.blocks and double.severity == "P0" and double.detail["count"] == 2
    assert double.detail["imminent"] is False
    assert (("virtualpos1", SUB)) in bc.blocked_subscriptions(report)


def test_one_off_charge_coexists_without_double_pending(world):
    """CO-01: el puntual del CRM convive con el pendiente del mes; no es doble pendiente ni desfase."""
    db, admin = world
    clean_calendar(db, admin)
    one_off = request(db, admin, request_type="one_off_charge")
    managed(db, "oneoff-1", "2026-11", one_off, amount=5000, code=f"{SUB}-20261120-5000-oneoff")
    charge(db, "oneoff-1", "2026-11-20", amount=5000)
    db.commit()
    assert bc.run_consistency_checks(db, NOW).ok
    assert not bc.has_double_pending(db, "virtualpos1", SUB, TODAY)


def test_missing_month_overdue_and_cancelled_externally(world):
    """CS-04 (mes sin cobro, pendiente vencido) y CS-07 (manual cancelado en el panel). No se repone nada."""
    db, admin = world
    req = clean_calendar(db, admin)
    db.get(VpCharge, db.scalar(select(VpCharge.id).where(VpCharge.external_id == "m-12"))).status = "cancelado"
    managed(db, "m-10", "2026-10", req)
    charge(db, "m-10", "2026-10-20")  # pendiente ya vencido (hoy es 28)
    db.commit()
    got = {(f.code, f.month) for f in bc.run_consistency_checks(db, NOW).findings}
    assert ("missing_month", "2026-12") in got
    assert ("managed_cancelled_externally", "2026-12") in got
    assert ("overdue_pending", "2026-10") in got


def test_duplicates_not_synced_and_not_active(world):
    """CS-05 (cobro del CRM sin sincronizar; los duplicados los impide el UNIQUE del esquema) y CS-08 (suscripcion cancelada con gestion abierta)."""
    db, admin = world
    req = clean_calendar(db, admin)
    managed(db, "m-old", "2027-01", req, created_ago=timedelta(hours=72))
    from app.models.crm import Subscription
    db.scalar(select(Subscription).where(Subscription.external_id == SUB)).status = "CANCELADA"
    db.commit()
    report = bc.run_consistency_checks(db, NOW)
    got = {f.code for f in report.findings}
    assert {"managed_not_synced", "subscription_not_active"} <= got
    inactive = next(f for f in report.findings if f.code == "subscription_not_active")
    assert inactive.detail["active_mark"] is True and inactive.detail["status"] == "cancelada"


def test_payment_mismatch_double_paid_and_reverted_amount(world):
    """CS-10 (pago con otro monto), CS-11 (dos pagados en un mes) y CS-14 (volvio al monto antiguo tras el horizonte)."""
    db, admin = world
    req = request(db, admin)
    mark(db, last_month="2026-08", last_date=date(2026, 8, 5))
    managed(db, "m-08", "2026-08", req, status="cancelado")
    charge(db, "paid-a", "2026-09-05", amount=9900, status="pagado")
    charge(db, "paid-b", "2026-09-20", amount=9900, status="pagado")
    db.add(VpPayment(platform="virtualpos1", external_id="pay-a", charge_external_id="paid-a", amount="9000"))
    db.commit()
    got = {(f.scenario, f.code) for f in bc.run_consistency_checks(db, NOW).findings}
    assert {("GB-CS-10", "payment_amount_mismatch"), ("GB-CS-11", "double_paid"),
            ("GB-CS-14", "reverted_to_old_amount")} <= got


def test_managed_charge_without_approved_request(world):
    """CS-14: todo cobro del CRM debe tener una solicitud aprobada (evento aprobada/autoaprobada)."""
    db, admin = world
    clean_calendar(db, admin)
    unapproved = request(db, admin, approved=False)
    managed(db, "m-x", "2026-11", unapproved, status="cancelado")
    managed(db, "m-y", "2026-11", None, status="cancelado")
    db.commit()
    rows = [f for f in bc.run_consistency_checks(db, NOW).findings if f.code == "managed_without_approval"]
    assert sorted(f.detail["charge_id"] for f in rows) == ["m-x", "m-y"] and all(f.severity == "P0" for f in rows)


# ----------------------------- cola de reconciliacion (CS-09) -----------------------------


def test_queue_lists_requests_charges_and_runs_and_flags_stale(world):
    db, admin = world
    req = clean_calendar(db, admin)
    stuck = request(db, admin, status="requiere_conciliacion", sub="otra-sub")
    stuck.updated_at = NOW.astimezone(UTC) - timedelta(hours=30)
    rec = managed(db, "m-rec", "2027-01", req, status="requiere_conciliacion")
    db.add(WriteRun(source="virtualpos1", resource_type="charge", external_id=SUB, operation="cancel_charge",
                    status="reconciliation_required", request_payload={}, request_id=req.id))
    db.commit()
    db.execute(BillingChangeRequest.__table__.update().where(BillingChangeRequest.id == stuck.id)
               .values(updated_at=NOW.astimezone(UTC) - timedelta(hours=30)))
    db.commit()
    items = bc.reconciliation_queue(db, NOW)
    kinds = {(i.kind, i.id) for i in items}
    assert ("request", str(stuck.id)) in kinds and ("managed_charge", str(rec.id)) in kinds
    assert any(i.kind == "write_run" for i in items)
    assert next(i for i in items if i.kind == "request").stale is True
    report = bc.run_consistency_checks(db, NOW)
    assert any(f.code == "reconciliation_required" and f.blocks for f in report.findings)


def test_resolve_managed_charge_is_traced_and_unblocks(world):
    db, admin = world
    req = clean_calendar(db, admin)
    req.status = "requiere_conciliacion"
    rec = managed(db, "m-rec", "2027-01", req, status="requiere_conciliacion")
    db.commit()
    from app.services import billing_apply as ba
    assert ba.is_subscription_blocked(db, "virtualpos1", SUB)
    with pytest.raises(br.CommentRequiredError):
        br.resolve_managed_charge(db, rec.id, admin, "cancelado", "  ")
    row = br.resolve_managed_charge(db, rec.id, admin, "cancelado", "verificado en el panel", now=NOW)
    assert row.status == "cancelado" and row.cancelled_at is not None
    assert not ba.is_subscription_blocked(db, "virtualpos1", SUB)
    ev = db.scalars(select(BillingChangeRequestEvent).where(BillingChangeRequestEvent.request_id == req.id)
                    .order_by(BillingChangeRequestEvent.created_at.desc())).first()
    assert ev.event_type == "requiere_conciliacion" and ev.detail["action"] == "conciliada"
    assert ev.actor_user_id == admin.id and ev.detail["comment"] == "verificado en el panel"
    with pytest.raises(br.ManagedChargeStateError):  # ya resuelto
        br.resolve_managed_charge(db, rec.id, admin, "vigente", "otra vez")
    assert CALLS == []


def test_resolve_refused_while_request_is_being_decided(world):
    db, admin = world
    req = clean_calendar(db, admin)
    req.status = "pendiente"
    rec = managed(db, "m-rec", "2027-01", req, status="requiere_conciliacion")
    db.commit()
    with pytest.raises(br.ManagedChargeStateError):
        br.resolve_managed_charge(db, rec.id, admin, "vigente", "x")
    db.refresh(rec)
    assert rec.status == "requiere_conciliacion"


def test_double_pending_blocks_new_requests(world):
    """CS-03: con dos pendientes en un mes (datos locales) no se aceptan nuevas solicitudes."""
    db, admin = world
    charge(db, "a", "2026-11-05")
    charge(db, "b", "2026-11-06")
    db.commit()
    params = br.RequestParams(request_type="change_amount", platform="virtualpos1", subscription_external_id=SUB,
                              new_amount=15000, horizon_start_month="2026-11")
    with pytest.raises(br.DoublePendingBlockedError):
        asyncio.run(br.create_request(db, admin, params, now=NOW))


# ----------------------------- API y job -----------------------------


def test_api_consistency_queue_and_resolve(world):
    db, admin = world
    req = clean_calendar(db, admin)
    req.status = "requiere_conciliacion"
    rec = managed(db, "m-rec", "2027-01", req, status="requiere_conciliacion")
    db.commit()
    client, h = client_for(db, admin)
    body = client.get(f"{BASE}/consistency").json()
    assert body["subscriptions_checked"] == 1 and "reconciliation_required" in body["counts"]
    queue = client.get(f"{BASE}/reconciliation-queue").json()
    assert queue["total"] >= 2 and queue["stale"] == 0
    bad = client.post(f"{BASE}/reconciliation-queue/managed-charges/{rec.id}/resolve",
                      json={"resolution": "otra", "comment": "x"}, headers=h)
    assert bad.status_code == 422
    missing = client.post(f"{BASE}/reconciliation-queue/managed-charges/{uuid.uuid4()}/resolve",
                          json={"resolution": "vigente", "comment": "x"}, headers=h)
    assert missing.status_code == 404
    ok = client.post(f"{BASE}/reconciliation-queue/managed-charges/{rec.id}/resolve",
                     json={"resolution": "vigente", "comment": "sigue en VP"}, headers=h)
    assert ok.status_code == 200 and ok.json()["status"] == "creado"
    again = client.post(f"{BASE}/reconciliation-queue/managed-charges/{rec.id}/resolve",
                        json={"resolution": "vigente", "comment": "x"}, headers=h)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "managed_charge_not_in_reconciliation"


def test_api_resolve_requires_approver(world):
    db, _admin = world
    kit = roles_kit(db)
    viewer = make_user(db, kit["ejecutivo"])
    client, h = client_for(db, viewer)
    r = client.post(f"{BASE}/reconciliation-queue/managed-charges/{uuid.uuid4()}/resolve",
                    json={"resolution": "vigente", "comment": "x"}, headers=h)
    assert r.status_code == 403


def test_job_is_off_by_default_and_noop(monkeypatch):
    assert type(settings).model_fields["billing_consistency_check_enabled"].default is False
    monkeypatch.setattr(settings, "billing_consistency_check_enabled", False)
    monkeypatch.setattr(billing_jobs, "SessionLocal", lambda: pytest.fail("no debe abrir sesion"))
    asyncio.run(billing_jobs.billing_consistency_check())


def test_job_logs_findings_when_enabled(monkeypatch, caplog):
    report = bc.ConsistencyReport(generated_at=datetime.now(UTC), today=TODAY, subscriptions_checked=1,
                                  findings=[bc.Finding("GB-CS-03", "double_pending", "P0", "virtualpos1", SUB, "2026-11",
                                                       blocks=True)])
    monkeypatch.setattr(settings, "billing_consistency_check_enabled", True)
    monkeypatch.setattr(billing_jobs, "_consistency_sync", lambda: report)
    with caplog.at_level(logging.WARNING, logger=billing_jobs.__name__):
        asyncio.run(billing_jobs.billing_consistency_check())
    assert "double_pending" in caplog.text and SUB not in caplog.text


def test_job_runs_read_only_against_the_database(monkeypatch):
    monkeypatch.setattr(settings, "billing_consistency_check_enabled", True)
    report = billing_jobs._consistency_sync()
    assert isinstance(report, bc.ConsistencyReport)


def test_job_registered_at_0330():
    sched = AsyncIOScheduler(timezone="America/Santiago")
    sched_engine.register_jobs(sched)
    job = {j.id: j for j in sched.get_jobs()}[billing_jobs.JOB_BILLING_CONSISTENCY]
    assert "hour='3'" in str(job.trigger) and "minute='30'" in str(job.trigger)


def test_service_does_not_import_provider_clients():
    import inspect

    imports = [ln for ln in inspect.getsource(bc).splitlines() if ln.lstrip().startswith(("import ", "from "))]
    assert not any(x in ln for ln in imports for x in ("virtualpos", "billing_apply", "integrations"))
