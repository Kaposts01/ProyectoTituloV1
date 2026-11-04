# ruff: noqa: F811  (fixtures importadas: db_session/env)
"""MGT-12 (d106): cambio de monto de Toku por la bandeja de cambios de cobro y sus aprobadores.

Cliente de Toku FALSO (el host de Toku es compartido con produccion: ninguna llamada de red). Solo ids sinteticos
`TEST-`. Cubre la vista previa, la creacion con autoaprobacion, la ejecucion (suscripcion -> cuotas impagas sin las
`in_progress` -> verificacion), la bandera apagada, la compensacion, la conciliacion, la validacion, RBAC y la guarda
dura de escritura fuera de produccion.
"""

import asyncio
from types import SimpleNamespace
from typing import ClassVar

import pytest
from billing_requests_support import (  # noqa: F401 - env (autouse): JWT secret y banderas
    client_for,
    env,
    make_role,
    make_user,
)
from cancellation_support import db_session  # noqa: F401 - fixture
from sqlalchemy import select

from app.core.config import settings
from app.integrations.toku import write_guard as wg
from app.models.billing import BillingChangeRequest
from app.models.crm import Subscription
from app.models.toku_channel import TokuInvoice
from app.models.write_run import WriteRun
from app.services import billing_requests as br
from app.services import toku_amount_apply as ta
from app.services import write_toku as wt
from app.services.billing_apply import ApplyFailedError
from app.services.rbac import PERMISSIONS, executive_permission_codes
from app.services.write_virtualpos import ReconciliationRequiredError

SUB = "TEST-sub-amount-1"
BASE = "/api/v1/billing/changes"


class FakeTokuAmount:
    calls: ClassVar[list[tuple]] = []
    state: ClassVar[dict] = {}

    def __init__(self, *_: object, **__: object) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def precheck_writes(self, operations):
        FakeTokuAmount.calls.append(("precheck", len(operations)))

    async def get_subscription(self, subscription_id):
        FakeTokuAmount.calls.append(("get", subscription_id))
        amount = FakeTokuAmount.state["amount"]
        if FakeTokuAmount.state.get("ignore_update"):
            amount = FakeTokuAmount.state["original"]
        return {"subscription": {"id": subscription_id, "status": "ACTIVE", "amount": amount}}

    async def list_subscription_invoices(self, subscription_id, general_statuses=None, page_size=100):
        FakeTokuAmount.calls.append(("list", subscription_id))
        return {"invoices": [dict(i) for i in FakeTokuAmount.state["invoices"]]}

    async def update_subscription(self, subscription_id, data):
        FakeTokuAmount.calls.append(("put_sub", data["amount"]))
        if FakeTokuAmount.state.get("sub_fail") and data["amount"] != FakeTokuAmount.state["original"]:
            raise RuntimeError("texto-libre-del-proveedor")
        if FakeTokuAmount.state.get("compensation_fail") and data["amount"] == FakeTokuAmount.state["original"]:
            raise RuntimeError("compensacion-falla")
        FakeTokuAmount.state["amount"] = data["amount"]
        return {}

    async def update_invoice(self, invoice_id, data):
        FakeTokuAmount.calls.append(("put_inv", invoice_id, data["amount"]))
        if invoice_id in FakeTokuAmount.state.get("inv_fail", set()):
            raise RuntimeError("texto-libre-del-proveedor")
        for inv in FakeTokuAmount.state["invoices"]:
            if inv["id"] == invoice_id:
                inv["amount"] = data["amount"]
        return {}


@pytest.fixture
def toku(monkeypatch):
    FakeTokuAmount.calls = []
    FakeTokuAmount.state = {
        "amount": 9900, "original": 9900,
        "invoices": [{"id": "TEST-in-1", "amount": 9900, "in_progress": False},
                     {"id": "TEST-in-2", "amount": 9900, "in_progress": False},
                     {"id": "TEST-in-busy", "amount": 9900, "in_progress": True}],
    }
    monkeypatch.setattr(settings, "toku_writes_enabled", True)
    monkeypatch.setattr(wt, "TokuClient", FakeTokuAmount)
    yield FakeTokuAmount


def _seed(db, sub=SUB, status="ACTIVE", amount="9900"):
    db.add(Subscription(source="toku", external_id=sub, status=status, amount=amount, raw_payload={"id": sub}))
    for i, in_progress in ((1, False), (2, False), ("busy", True)):
        db.add(TokuInvoice(external_id=f"TEST-in-{i}", subscription_id=sub, status="unpaid",
                           raw_payload={"general_status": "unpaid", "in_progress": in_progress}))
    db.commit()


def _admin(db):
    return make_user(db, make_role(db, "admin", set(PERMISSIONS)))


def _params(**over):
    values = {"request_type": "change_amount", "platform": "toku", "subscription_external_id": SUB,
              "new_amount": 12900, "requester_comment": "Socio sube su aporte"}
    values.update(over)
    return br.RequestParams(**values)


def _create(db, user, **over):
    return asyncio.run(br.create_request(db, user, _params(**over)))


def _apply(db, req, user):
    return asyncio.run(br.apply_request(db, req.id, user))


def _reload(db, req):
    db.expire_all()
    return db.get(BillingChangeRequest, req.id)


def _events(db, req):
    return [e.event_type for e in br.get_events(db, req.id)]


# ----------------------------- vista previa y creacion -----------------------------


def test_preview_uses_local_data_and_skips_in_progress_invoices(db_session, toku) -> None:
    _seed(db_session)
    prepared = asyncio.run(br.prepare_request(db_session, _params()))
    summary = prepared.preview["summary"]
    assert (summary["previous_amount"], summary["new_amount"], summary["variation_pct"]) == (9900, 12900, 30.3)
    assert prepared.preview["toku"]["invoices_to_update"] == 2
    assert prepared.preview["toku"]["invoices_in_progress_skipped"] == 1
    assert prepared.preview["warnings"] == [{"code": "TOKU_INVOICES_IN_PROGRESS_SKIPPED", "count": 1}]
    assert toku.calls == []  # la vista previa no llama al proveedor


def test_admin_creates_and_self_approves_through_the_same_inbox(db_session, toku) -> None:
    _seed(db_session)
    req = _create(db_session, _admin(db_session))
    assert req.platform == "toku" and req.status == "aprobada" and req.self_approved is True
    assert req.previous_amount == 9900 and req.new_amount == 12900
    assert _events(db_session, req) == ["creada", "autoaprobada"]


@pytest.mark.parametrize(("over", "error"), [
    ({"request_type": "change_date", "new_amount": None, "new_charge_day": 5}, br.InvalidRequestFieldsError),
    ({"new_amount": 9900}, br.NoChangesError),
    ({"subscription_external_id": "TEST-no-existe"}, br.SubscriptionUnknownError),
])
def test_validation(db_session, toku, over, error) -> None:
    _seed(db_session)
    with pytest.raises(error):
        _create(db_session, _admin(db_session), **over)


def test_paused_subscription_is_rejected(db_session, toku) -> None:
    _seed(db_session, status="PAUSED")
    with pytest.raises(br.SubscriptionNotActiveError):
        _create(db_session, _admin(db_session))


# ----------------------------- ejecucion -----------------------------


def test_apply_updates_subscription_then_unpaid_invoices_and_verifies(db_session, toku) -> None:
    _seed(db_session)
    admin = _admin(db_session)
    req = _create(db_session, admin)
    res = _apply(db_session, req, admin)
    assert res.status == "ejecutada" and res.toku["invoices_updated"] == ["TEST-in-1", "TEST-in-2"]
    assert res.toku["skipped_in_progress"] == ["TEST-in-busy"]
    assert toku.calls == [("get", SUB), ("list", SUB), ("precheck", 3), ("put_sub", 12900),
                          ("put_inv", "TEST-in-1", 12900), ("put_inv", "TEST-in-2", 12900), ("get", SUB)]
    req = _reload(db_session, req)
    assert req.status == "ejecutada" and req.executed_at is not None and req.error_message is None
    assert _events(db_session, req)[-2:] == ["aplicando", "aplicada"]
    run = db_session.get(WriteRun, req.write_run_id)
    assert run.operation == "change_subscription_amount" and run.status == "completed"
    assert run.request_id == req.id and run.requested_by_user_id == admin.id
    sub = db_session.scalar(select(Subscription).where(Subscription.source == "toku", Subscription.external_id == SUB))
    assert sub.amount == "12900"
    again = _apply(db_session, req, admin)
    assert again.already_applied is True and len(toku.calls) == 7  # idempotente: sin llamadas nuevas


def test_writes_flag_off_blocks_before_changing_state(db_session, toku, monkeypatch) -> None:
    _seed(db_session)
    admin = _admin(db_session)
    req = _create(db_session, admin)
    monkeypatch.setattr(settings, "toku_writes_enabled", False)
    with pytest.raises(ta.TokuWritesDisabledError):
        _apply(db_session, req, admin)
    assert _reload(db_session, req).status == "aprobada" and toku.calls == []


def test_invoice_failure_is_compensated_and_request_fails(db_session, toku) -> None:
    _seed(db_session)
    admin = _admin(db_session)
    req = _create(db_session, admin)
    toku.state["inv_fail"] = {"TEST-in-2"}
    with pytest.raises(ApplyFailedError):
        _apply(db_session, req, admin)
    # compensacion: la cuota ya actualizada y la suscripcion vuelven al monto anterior
    assert ("put_inv", "TEST-in-1", 9900) in toku.calls and toku.calls[-1] == ("put_sub", 9900)
    assert toku.state["amount"] == 9900
    req = _reload(db_session, req)
    assert req.status == "fallida" and req.error_message == "INVOICE_UPDATE_FAILED"
    run = db_session.get(WriteRun, req.write_run_id)
    assert run.status == "failed" and run.response_payload["compensated"] is True
    assert "texto-libre" not in (run.error_message or "")


def test_failed_compensation_requires_reconciliation(db_session, toku) -> None:
    _seed(db_session)
    admin = _admin(db_session)
    req = _create(db_session, admin)
    toku.state["inv_fail"] = {"TEST-in-2"}
    toku.state["compensation_fail"] = True
    with pytest.raises(ReconciliationRequiredError):
        _apply(db_session, req, admin)
    req = _reload(db_session, req)
    assert req.status == "requiere_conciliacion" and _events(db_session, req)[-1] == "requiere_conciliacion"
    assert db_session.get(WriteRun, req.write_run_id).status == "reconciliation_required"
    # un aprobador reabre y reintenta: vuelve a quedar aprobada (flujo comun de la bandeja)
    toku.state.pop("inv_fail")
    toku.state.pop("compensation_fail")
    br.reopen(db_session, req.id, admin, "Se revisaron los montos en Toku")
    assert _apply(db_session, req, admin).status == "ejecutada"


def test_verification_mismatch_requires_reconciliation(db_session, toku) -> None:
    _seed(db_session)
    admin = _admin(db_session)
    req = _create(db_session, admin)
    toku.state["ignore_update"] = True  # el proveedor no refleja el monto nuevo al releer
    with pytest.raises(ReconciliationRequiredError):
        _apply(db_session, req, admin)
    assert _reload(db_session, req).error_message == "VERIFY_FAILED"


def test_subscription_update_failure_has_no_effect(db_session, toku) -> None:
    _seed(db_session)
    admin = _admin(db_session)
    req = _create(db_session, admin)
    toku.state["sub_fail"] = True
    with pytest.raises(ApplyFailedError):
        _apply(db_session, req, admin)
    assert not [c for c in toku.calls if c[0] == "put_inv"]
    assert _reload(db_session, req).status == "fallida"


# ----------------------------- API y RBAC -----------------------------


def test_api_create_and_apply_and_rbac(db_session, toku) -> None:
    _seed(db_session)
    admin = _admin(db_session)
    client, h = client_for(db_session, admin)
    body = {"request_type": "change_amount", "platform": "toku", "subscription_external_id": SUB, "new_amount": 12900}
    r = client.post(BASE, json=body, headers=h)
    assert r.status_code == 201, r.text
    req_id = r.json()["id"]
    assert r.json()["platform"] == "toku" and r.json()["plan_preview"]["toku"]["invoices_to_update"] == 2
    listed = client.get(BASE, params={"platform": "toku"}).json()
    assert [i["id"] for i in listed["items"]] == [req_id]
    r = client.post(f"{BASE}/{req_id}/apply", json={}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ejecutada" and r.json()["toku"]["skipped_in_progress"] == ["TEST-in-busy"]

    reader = make_user(db_session, make_role(db_session, "ejecutivo", executive_permission_codes()))
    rclient, rh = client_for(db_session, reader)
    assert rclient.post(BASE, json=body, headers=rh).status_code == 403
    assert rclient.post(f"{BASE}/{req_id}/apply", json={}, headers=rh).status_code == 403


def test_api_flag_off_returns_403_with_toku_channel(db_session, toku, monkeypatch) -> None:
    _seed(db_session)
    admin = _admin(db_session)
    req = _create(db_session, admin)
    monkeypatch.setattr(settings, "toku_writes_enabled", False)
    client, h = client_for(db_session, admin)
    r = client.post(f"{BASE}/{req.id}/apply", json={}, headers=h)
    assert r.status_code == 403 and r.json()["detail"] == {
        "code": "writes_disabled", "message": "Las escrituras a Toku están deshabilitadas.", "channel": "toku"}


# ----------------------------- guarda dura fuera de produccion -----------------------------


def _guard_settings():
    return SimpleNamespace(toku_writes_enabled=True, toku_base_url=f"https://{wg.TOKU_HOST}/v1")


def test_sandbox_guard_only_allows_test_ids_for_the_amount_change() -> None:
    state = wg.WriteGuardState(env={wg.ENV_ARMED: "1"})
    ops_real = [("PUT", "/subscriptions/sub_real123", {"amount": 12900})]
    with pytest.raises(wg.TokuWriteBlockedError) as exc:
        wg.check_sandbox_writes_allowed(ops_real, _guard_settings(), state)
    assert exc.value.code == "ID_NOT_ALLOWED"
    ops_test = [("PUT", f"/subscriptions/{SUB}", {"amount": 12900}), ("PUT", "/invoices/TEST-in-1", {"amount": 12900})]
    wg.check_sandbox_writes_allowed(ops_test, _guard_settings(), state)  # no lanza
    with pytest.raises(wg.TokuWriteBlockedError) as exc:
        wg.check_sandbox_writes_allowed(ops_test, _guard_settings(), wg.WriteGuardState(env={}))
    assert exc.value.code == "NOT_ARMED"
