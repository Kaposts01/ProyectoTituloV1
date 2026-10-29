# ruff: noqa: F811  (fixtures importadas de cancellation_support: db_session/_env)
"""MGT-08/09/10 + TCH: ejecutores de baja multicanal con proveedores FALSOS (ninguna llamada de red ni escritura real).

Cubre dry-run, exito, fallo a mitad con requires_reconciliation y reintento desde el paso fallido (reopen), idempotencia,
D30 (Toku con invoices in_progress), Payku irreversible, TCH en tramite, bloqueo por lock, banderas apagadas y barredor.
"""

import asyncio
from types import SimpleNamespace
from typing import ClassVar

import pytest
import test_virtualpos_cancel_subscription as vpc
from cancellation_support import (
    NOW,
    approved_request,
    db_session,  # noqa: F401 - fixture
    make_roles,
    make_user,
    seed_payku,
    seed_tch,
    seed_toku,
    seed_vp,
)
from sqlalchemy import select

from app.core.config import settings
from app.models.cancellation import SubscriptionCancellationRequest
from app.models.crm import Subscription
from app.models.tch import TchSubscription
from app.models.write_run import WriteRun
from app.services import billing_apply as ba
from app.services import cancellation_apply as ca
from app.services import cancellation_requests as cr
from app.services import write_payku as wp
from app.services import write_toku as wt
from app.services.subscription_refresh import RefreshError

_env = vpc._env
SUB = vpc.SUB


def _apply(db, req, user, **kw):
    return asyncio.run(ca.apply_cancellation_request(db, req.id, actor_user_id=user.id, now=NOW, **kw))


def _jefa(db):
    return make_user(db, make_roles(db)["jefatura"])


def _step_status(req):
    return {s["step"]: (s["status"], s.get("code")) for s in req.steps}


def _event_types(db, req):
    return [e.event_type for e in cr.get_events(db, req.id)]


def _reload(db, req):
    db.expire_all()
    return db.get(SubscriptionCancellationRequest, req.id)


def _runs(db, operation):
    return list(db.scalars(select(WriteRun).where(WriteRun.operation == operation)))


# ============================== VirtualPOS ==============================


def _vp_request(db):
    seed_vp(db, SUB, pending=2)
    jefa = _jefa(db)
    return approved_request(db, jefa, "virtualpos1", SUB), jefa


def test_vp_dry_run_changes_nothing_and_calls_no_provider_write(db_session) -> None:
    req, jefa = _vp_request(db_session)
    res = _apply(db_session, req, jefa, dry_run=True)
    assert res.status == "dry_run" and res.dry_run is True
    assert res.plan["steps_to_run"] == ["stop_subscription", "cancel_pending_charges", "payment_method"]
    assert res.plan["blockers"] == [] and res.plan["irreversible"] is True
    assert _reload(db_session, req).status == "approved"
    assert not [c for c in vpc.CALLS if c[0] in ("cancel_subscription", "delete_charge", "delete_plural")]
    assert _runs(db_session, "apply_cancellation_request") == []


def test_vp_success_runs_steps_in_order_with_audit(db_session) -> None:
    req, jefa = _vp_request(db_session)
    res = _apply(db_session, req, jefa)
    assert res.status == "completed" and not res.already_applied
    req = _reload(db_session, req)
    assert req.status == "completed" and req.executed_at is not None and req.requires_reconciliation is False
    assert _step_status(req) == {
        "stop_subscription": ("done", None), "cancel_pending_charges": ("done", None),
        "payment_method": ("manual", "VP_NO_PAYMENT_METHOD_API"),
    }
    assert [c for c in vpc.CALLS if c[0] == "cancel_subscription"] == [("cancel_subscription", SUB)]
    vpc._no_plural()
    types = _event_types(db_session, req)
    assert types == ["created", "self_approved", "applying", "step_completed", "step_completed", "step_manual", "completed"]
    run = _runs(db_session, "apply_cancellation_request")[0]
    assert run.status == "completed" and run.requested_by_user_id == jefa.id
    assert run.request_payload["cancellation_request_id"] == str(req.id) and req.write_run_id == run.id
    assert db_session.scalar(select(Subscription.status).where(Subscription.external_id == SUB)) == "CANCELADA"


def test_vp_apply_is_idempotent(db_session) -> None:
    req, jefa = _vp_request(db_session)
    _apply(db_session, req, jefa)
    calls_after_first = len(vpc.CALLS)
    again = _apply(db_session, req, jefa)
    assert again.already_applied is True and again.status == "completed"
    assert len(vpc.CALLS) == calls_after_first  # sin ninguna llamada nueva al proveedor


def test_vp_failure_mid_flow_requires_reconciliation_then_resumes_from_failed_step(db_session) -> None:
    req, jefa = _vp_request(db_session)
    vpc.STATE["stay_pending"] = {"c-p1"}  # el proveedor deja un cobro pendiente tras la baja
    vpc.STATE["delete_fail"] = {"c-p1"}  # y no se deja cancelar individualmente
    with pytest.raises(ca.ReconciliationRequiredError) as exc:
        _apply(db_session, req, jefa)
    assert (exc.value.step, exc.value.step_code) == ("cancel_pending_charges", "PENDING_CHARGES_REMAIN")
    req = _reload(db_session, req)
    assert req.status == "requires_reconciliation" and req.requires_reconciliation is True
    assert _step_status(req)["stop_subscription"] == ("done", None)  # la baja hecha NO se revierte
    assert _step_status(req)["cancel_pending_charges"] == ("failed", "PENDING_CHARGES_REMAIN")
    assert "payment_method" not in _step_status(req)  # parada en el primer fallo
    assert _runs(db_session, "apply_cancellation_request")[0].status == "reconciliation_required"
    assert _event_types(db_session, req)[-1] == "requires_reconciliation"
    vpc._no_plural()

    # un aprobador reabre y reintenta: reanuda desde el paso fallido, sin repetir la baja
    vpc.STATE["delete_fail"].clear()
    cancels_before = len([c for c in vpc.CALLS if c[0] == "cancel_subscription"])
    cr.reopen(db_session, req.id, jefa, "Se destraba el cobro", now=NOW)
    res = _apply(db_session, req, jefa)
    assert res.status == "completed"
    assert len([c for c in vpc.CALLS if c[0] == "cancel_subscription"]) == cancels_before  # no repite el DELETE
    req = _reload(db_session, req)
    assert req.status == "completed" and req.requires_reconciliation is False
    assert _step_status(req)["cancel_pending_charges"] == ("done", None)
    vpc._no_plural()


def test_vp_processing_charge_is_not_cancelled_and_needs_reconciliation(db_session) -> None:
    req, jefa = _vp_request(db_session)
    vpc.STATE["charges"].append({"id": "c-proc", "charge_date": "2026-11-05", "amount": 9900, "status": "procesando"})
    with pytest.raises(ca.ReconciliationRequiredError) as exc:
        _apply(db_session, req, jefa)
    assert exc.value.step_code == "PROCESSING_CHARGES"
    assert not [c for c in vpc.CALLS if c == ("delete_charge", "c-proc")]


def test_vp_first_step_failure_leaves_failed_without_effects_and_can_retry(db_session) -> None:
    req, jefa = _vp_request(db_session)
    vpc.STATE["cancel_error"] = True
    with pytest.raises(ca.ApplyFailedError) as exc:
        _apply(db_session, req, jefa)
    assert (exc.value.step, exc.value.step_code) == ("stop_subscription", "PROVIDER_ERROR")
    req = _reload(db_session, req)
    assert req.status == "failed" and req.requires_reconciliation is False
    assert req.steps[0]["error"].startswith("VirtualPOSAPIError")  # etiqueta segura, sin texto libre
    assert _runs(db_session, "apply_cancellation_request")[0].status == "failed"
    vpc.STATE["cancel_error"] = False
    cr.reopen(db_session, req.id, jefa, "Reintento", now=NOW)
    assert _apply(db_session, req, jefa).status == "completed"


def test_vp_subscription_already_cancelled_is_not_executable(db_session) -> None:
    req, jefa = _vp_request(db_session)
    sub = db_session.scalar(select(Subscription).where(Subscription.external_id == SUB))
    sub.status = "CANCELADA"  # alguien la dio de baja directamente despues de aprobar
    db_session.commit()
    res = _apply(db_session, req, jefa)
    assert res.status == "not_executable" and res.reason == "subscription_not_active"
    assert _reload(db_session, req).status == "not_executable"
    assert not [c for c in vpc.CALLS if c[0] == "cancel_subscription"]


def test_vp_open_billing_request_applying_blocks_the_cancellation(db_session) -> None:
    from app.models.billing import BillingChangeRequest

    req, jefa = _vp_request(db_session)
    db_session.add(BillingChangeRequest(
        request_type="change_amount", platform="virtualpos1", subscription_external_id=SUB,
        requested_by_user_id=jefa.id, status="aplicando", new_amount=12000, rules_snapshot={}, plan_preview={}))
    db_session.commit()
    with pytest.raises(ca.ApplyFailedError) as exc:
        _apply(db_session, req, jefa)
    assert exc.value.step_code == "BILLING_FLOW_CONFLICT"
    assert not [c for c in vpc.CALLS if c[0] == "cancel_subscription"]


def test_vp_open_pending_billing_request_is_closed_not_executable(db_session) -> None:
    from app.models.billing import BillingChangeRequest

    req, jefa = _vp_request(db_session)
    bcr = BillingChangeRequest(
        request_type="change_amount", platform="virtualpos1", subscription_external_id=SUB,
        requested_by_user_id=jefa.id, status="pendiente", new_amount=12000, rules_snapshot={}, plan_preview={})
    db_session.add(bcr)
    db_session.commit()
    _apply(db_session, req, jefa)
    db_session.expire_all()
    assert db_session.get(BillingChangeRequest, bcr.id).status == "no_ejecutable"  # reutiliza MGT-03


def test_writes_disabled_raises_before_any_state_change(db_session, monkeypatch) -> None:
    req, jefa = _vp_request(db_session)
    monkeypatch.setattr(settings, "virtualpos_writes_enabled", False)
    with pytest.raises(ca.WritesDisabledError):
        _apply(db_session, req, jefa)
    assert _reload(db_session, req).status == "approved"
    assert _runs(db_session, "apply_cancellation_request") == []


def test_busy_lock_rejects_concurrent_apply(db_session) -> None:
    req, jefa = _vp_request(db_session)
    with ba.subscription_lock(db_session, "virtualpos1", SUB), pytest.raises(ca.SubscriptionBusyError):
        _apply(db_session, req, jefa)
    assert _reload(db_session, req).status == "approved"
    assert not [c for c in vpc.CALLS if c[0] == "cancel_subscription"]


def test_only_approved_requests_can_be_applied(db_session) -> None:
    seed_vp(db_session, SUB)
    roles = make_roles(db_session)
    solicitante = make_user(db_session, roles["solicitante"])
    req = approved_request(db_session, solicitante, "virtualpos1", SUB)  # pendiente: nadie la aprobo
    assert req.status == "pending"
    with pytest.raises(ca.InvalidRequestStateError):
        _apply(db_session, req, solicitante)


# ============================== Toku ==============================


class FakeToku:
    calls: ClassVar[list[tuple]] = []
    invoices: ClassVar[list[dict]] = []
    void_fail: ClassVar[set[str]] = set()

    def __init__(self, *_: object, **__: object) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def precheck_writes(self, operations):
        return None

    async def list_subscription_invoices(self, subscription_id, general_statuses=None, page_size=100):
        FakeToku.calls.append(("list", subscription_id))
        return {"invoices": [dict(i) for i in FakeToku.invoices]}

    async def void_invoice(self, invoice_id, data):
        FakeToku.calls.append(("void", invoice_id))
        if invoice_id in FakeToku.void_fail:
            raise RuntimeError("texto-libre-del-proveedor")
        FakeToku.invoices = [i for i in FakeToku.invoices if i["id"] != invoice_id]
        return {}

    async def change_subscription_status(self, subscription_id, data):
        FakeToku.calls.append(("status", data["status"]))
        return {}

    async def update_subscription(self, subscription_id, data):
        FakeToku.calls.append(("update", data))
        return {}

    async def get_subscription(self, subscription_id):
        return {"id": subscription_id, "status": "PAUSED"}

    async def delete_subscription(self, subscription_id):
        FakeToku.calls.append(("delete", subscription_id))
        raise AssertionError("La baja de Toku NUNCA usa DELETE (D12)")


REFRESH = SimpleNamespace(pending=0, processing=0, error=None, calls=[])


async def _fake_refresh(db, source, external_id, *, run_id=None):
    REFRESH.calls.append((source, external_id))
    if REFRESH.error:
        raise RefreshError(REFRESH.error)
    return SimpleNamespace(pending_charges=REFRESH.pending, processing_charges=REFRESH.processing,
                           pending_charge_ids=[], processing_charge_ids=[])


@pytest.fixture
def providers(monkeypatch):
    FakeToku.calls = []
    FakeToku.invoices = []
    FakeToku.void_fail = set()
    REFRESH.pending, REFRESH.processing, REFRESH.error, REFRESH.calls = 0, 0, None, []
    FakePayku.calls = []
    FakePayku.delete_fail = False
    monkeypatch.setattr(settings, "toku_writes_enabled", True)
    monkeypatch.setattr(settings, "payku_writes_enabled", True)
    monkeypatch.setattr(wt, "TokuClient", FakeToku)
    monkeypatch.setattr(wp, "PaykuClient", FakePayku)
    monkeypatch.setattr(ca, "refresh_subscription", _fake_refresh)


def _toku_request(db, **over):
    seed_toku(db, "sub_tk1", unpaid=2)
    FakeToku.invoices = [{"id": "in_a", "in_progress": False}, {"id": "in_b", "in_progress": False}]
    jefa = _jefa(db)
    return approved_request(db, jefa, "toku", "sub_tk1", **over), jefa


def test_toku_success_pauses_voids_and_never_deletes(db_session, providers) -> None:
    req, jefa = _toku_request(db_session)
    res = _apply(db_session, req, jefa)
    assert res.status == "completed"
    assert FakeToku.calls == [("list", "sub_tk1"), ("status", "PAUSED"), ("list", "sub_tk1"), ("void", "in_a"), ("void", "in_b")]
    assert not [c for c in FakeToku.calls if c[0] == "delete"]
    req = _reload(db_session, req)
    assert _step_status(req) == {
        "stop_subscription": ("done", None), "cancel_pending_charges": ("done", None),
        "payment_method": ("manual", "TOKU_PAYMENT_METHOD_DECISION_PENDING"),
    }
    assert req.steps[0]["mode"] == "paused" and req.steps[1]["voided"] == 2
    assert REFRESH.calls == [("toku", "sub_tk1")]  # cada paso verificado releyendo el proveedor
    assert db_session.scalar(select(Subscription.status).where(Subscription.external_id == "sub_tk1")) == "PAUSED"


def test_toku_end_date_mode_sets_end_date_instead_of_pausing(db_session, providers) -> None:
    from datetime import date

    req, jefa = _toku_request(db_session, toku_stop_mode="end_date", toku_end_date=date(2026, 12, 31))
    assert _apply(db_session, req, jefa).status == "completed"
    assert ("update", {"end_date": "2026-12-31"}) in FakeToku.calls
    assert not [c for c in FakeToku.calls if c[0] in ("status", "delete")]
    assert _reload(db_session, req).steps[0]["mode"] == "end_date"


def test_toku_in_progress_invoice_denies_the_cancellation_d30(db_session, providers) -> None:
    req, jefa = _toku_request(db_session)
    FakeToku.invoices.append({"id": "in_busy", "in_progress": True})
    with pytest.raises(ca.BlockedError) as exc:
        _apply(db_session, req, jefa)
    assert exc.value.code == "INVOICE_IN_PROGRESS"
    # nada se toco: ni pausa, ni void, ni DELETE; la solicitud sigue aprobada
    assert not [c for c in FakeToku.calls if c[0] in ("status", "update", "void", "delete")]
    assert _reload(db_session, req).status == "approved"
    assert _runs(db_session, "apply_cancellation_request") == []


def test_toku_dry_run_reports_in_progress_blocker_and_invoices_to_void(db_session, providers) -> None:
    req, jefa = _toku_request(db_session)
    res = _apply(db_session, req, jefa, dry_run=True)
    assert res.plan["invoices_to_void"] == 2 and res.plan["blockers"] == []
    FakeToku.invoices.append({"id": "in_busy", "in_progress": True})
    res = _apply(db_session, req, jefa, dry_run=True)
    assert "INVOICE_IN_PROGRESS" in res.plan["blockers"]
    assert not [c for c in FakeToku.calls if c[0] in ("status", "update", "void", "delete")]


def test_toku_void_failure_mid_flow_reconciles_and_resume_does_not_repause(db_session, providers) -> None:
    req, jefa = _toku_request(db_session)
    FakeToku.void_fail = {"in_b"}
    with pytest.raises(ca.ReconciliationRequiredError) as exc:
        _apply(db_session, req, jefa)
    assert (exc.value.step, exc.value.step_code) == ("cancel_pending_charges", "INVOICE_VOID_FAILED")
    req = _reload(db_session, req)
    assert req.status == "requires_reconciliation" and req.requires_reconciliation is True
    assert _step_status(req)["stop_subscription"] == ("done", None)
    assert req.steps[1]["voided"] == 1 and "texto-libre" not in str(req.steps)
    assert ("void", "in_b") in FakeToku.calls and not [c for c in FakeToku.calls if c[0] == "delete"]

    FakeToku.void_fail = set()
    FakeToku.calls.clear()
    cr.reopen(db_session, req.id, jefa, "Reintento tras revisar", now=NOW)
    assert _apply(db_session, req, jefa).status == "completed"
    assert ("status", "PAUSED") not in FakeToku.calls  # no repite la pausa
    assert [c for c in FakeToku.calls if c[0] == "void"] == [("void", "in_b")]


def test_toku_remaining_pending_after_voiding_needs_reconciliation(db_session, providers) -> None:
    req, jefa = _toku_request(db_session)
    REFRESH.pending = 1
    with pytest.raises(ca.ReconciliationRequiredError) as exc:
        _apply(db_session, req, jefa)
    assert exc.value.step_code == "PENDING_CHARGES_REMAIN"


def test_toku_refresh_failure_is_fail_closed(db_session, providers) -> None:
    req, jefa = _toku_request(db_session)
    REFRESH.error = "PROVIDER_READ_FAILED"
    with pytest.raises(ca.ReconciliationRequiredError) as exc:
        _apply(db_session, req, jefa)
    assert exc.value.step_code == "REFRESH_FAILED"


# ============================== Payku ==============================


class FakePayku:
    calls: ClassVar[list[tuple]] = []
    delete_fail = False

    def __init__(self, *_: object, **__: object) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def delete_subscription(self, subscription_id):
        FakePayku.calls.append(("delete_subscription", subscription_id))
        if FakePayku.delete_fail:
            raise RuntimeError("texto-libre-del-proveedor")
        return {}

    async def delete_subscription_card(self, data):  # Q-09 sin validar: no debe llamarse jamas
        FakePayku.calls.append(("delete_card", data))
        raise AssertionError("La baja de Payku NO elimina tarjetas (Q-09)")


def _payku_request(db):
    seed_payku(db, "sus_pk1", pending=0)
    jefa = _jefa(db)
    return approved_request(db, jefa, "payku", "sus_pk1", confirm_irreversible=True), jefa


def test_payku_success_deletes_once_verifies_and_registers_manual_card_task(db_session, providers) -> None:
    req, jefa = _payku_request(db_session)
    assert _apply(db_session, req, jefa).status == "completed"
    assert FakePayku.calls == [("delete_subscription", "sus_pk1")]
    req = _reload(db_session, req)
    assert _step_status(req) == {
        "stop_subscription": ("done", None), "cancel_pending_charges": ("done", None),
        "payment_method": ("manual", "PAYKU_CARD_DELETE_Q09_UNVALIDATED"),
    }
    assert req.options["confirm_irreversible"] is True
    assert REFRESH.calls == [("payku", "sus_pk1")]
    assert db_session.scalar(select(Subscription.status).where(Subscription.external_id == "sus_pk1")) == "cancelled"


def test_payku_pending_transactions_remaining_reconcile_and_resume_without_second_delete(db_session, providers) -> None:
    req, jefa = _payku_request(db_session)
    REFRESH.pending = 1
    with pytest.raises(ca.ReconciliationRequiredError) as exc:
        _apply(db_session, req, jefa)
    assert exc.value.step_code == "PENDING_CHARGES_REMAIN"
    assert _step_status(_reload(db_session, req))["stop_subscription"] == ("done", None)
    REFRESH.pending = 0
    cr.reopen(db_session, req.id, jefa, "Las cuotas se cerraron en Payku", now=NOW)
    assert _apply(db_session, req, jefa).status == "completed"
    assert [c for c in FakePayku.calls if c[0] == "delete_subscription"] == [("delete_subscription", "sus_pk1")]


def test_payku_provider_failure_is_failed_not_reconciliation(db_session, providers) -> None:
    req, jefa = _payku_request(db_session)
    FakePayku.delete_fail = True
    with pytest.raises(ca.ApplyFailedError) as exc:
        _apply(db_session, req, jefa)
    assert (exc.value.step, exc.value.step_code) == ("stop_subscription", "PROVIDER_ERROR")
    req = _reload(db_session, req)
    assert req.status == "failed" and "texto-libre" not in str(req.steps) + str(req.error_message)
    assert not [c for c in FakePayku.calls if c[0] == "delete_card"]


def test_payku_confirmation_cannot_be_removed_from_the_request(db_session, providers) -> None:
    from sqlalchemy.exc import IntegrityError

    req, _jefa = _payku_request(db_session)
    req.options = {}  # defensa en profundidad: el CHECK de BD impide una solicitud Payku sin confirmacion
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
    assert FakePayku.calls == []


# ============================== TCH ==============================


def test_tch_apply_leaves_request_in_process_without_provider_and_closes_with_report(db_session, providers) -> None:
    ficha = seed_tch(db_session, 910100)
    jefa = _jefa(db_session)
    req = approved_request(db_session, jefa, "tch", ficha)
    res = _apply(db_session, req, jefa)
    assert res.status == "pending_external"
    req = _reload(db_session, req)
    assert req.status == "pending_external" and req.executed_at is None
    assert _step_status(req) == {"register_internal": ("done", None), "bank_mandate": ("manual", "TCH_BANK_MANDATE_OUTSIDE_CRM")}
    assert _runs(db_session, "apply_cancellation_request") == []  # TCH no tiene proveedor: sin write_run
    assert _apply(db_session, req, jefa).already_applied is True  # idempotente

    # mientras el Excel no traiga la ficha eliminada, sigue en tramite
    assert ca.close_tch_cancellations_from_report(db_session) == []
    assert _reload(db_session, req).status == "pending_external"
    # el siguiente Excel trae fecha_eliminacion
    ficha_row = db_session.scalar(select(TchSubscription).where(TchSubscription.file_number == 910100))
    ficha_row.deletion_date = "2026-11-03"
    db_session.commit()
    assert ca.close_tch_cancellations_from_report(db_session) == [req.id]
    assert ca.close_tch_cancellations_from_report(db_session) == []  # idempotente
    req = _reload(db_session, req)
    assert req.status == "completed" and req.executed_at is not None
    last = cr.get_events(db_session, req.id)[-1]
    assert last.event_type == "closed_by_report" and last.actor_user_id is None


def test_tch_open_request_blocks_a_second_one_until_closed(db_session, providers) -> None:
    ficha = seed_tch(db_session, 910101)
    jefa = _jefa(db_session)
    req = approved_request(db_session, jefa, "tch", ficha)
    _apply(db_session, req, jefa)
    with pytest.raises(cr.OpenRequestExistsError):
        approved_request(db_session, jefa, "tch", ficha)  # «en tramite» sigue ocupando el cupo


# ============================== barredor ==============================


def test_sweeper_moves_stuck_applying_to_reconciliation(db_session, providers) -> None:
    from datetime import timedelta

    req, _jefa_user = _vp_request(db_session)
    req.status = "applying"
    db_session.commit()
    from datetime import UTC, datetime

    assert ca.sweep_stuck_applying(db_session, now=datetime.now(UTC)) == []  # reciente: no esta atascada
    swept = ca.sweep_stuck_applying(db_session, older_than_minutes=30, now=NOW + timedelta(days=365))
    assert swept == [req.id]
    req = _reload(db_session, req)
    assert req.status == "requires_reconciliation" and req.requires_reconciliation is True
    assert req.error_message == "StuckApplying"
    last = cr.get_events(db_session, req.id)[-1]
    assert last.event_type == "requires_reconciliation" and last.actor_user_id is None
