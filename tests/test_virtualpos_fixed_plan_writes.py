import asyncio
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db
from app.core.config import settings
from app.core.security import ACCESS_COOKIE, create_access_token, get_current_user
from app.db.session import engine
from app.main import app
from app.models.crm import Charge, Plan, Subscription
from app.models.write_run import WriteRun
from app.services import write_virtualpos as svc

SUB = "sub-fixed-1"
CALLS: list[tuple] = []
STATE: dict = {}


def _http_error(code: str) -> httpx.HTTPStatusError:
    request = httpx.Request("DELETE", "https://vp.test/x")
    response = httpx.Response(400, json={"status": "ERROR", "code": code}, request=request)
    return httpx.HTTPStatusError("bad request", request=request, response=response)


class FakeVP:
    def __init__(self, platform: str = "virtualpos1") -> None:
        self.platform = platform

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def list_charges(self, subscription_id, page=1, limit=100, status=None):
        CALLS.append(("list_charges", subscription_id, status))
        return {"charges": STATE["charges"], "pagination": {"pages": 1, "page": 1}}

    async def delete_subscription_charges(self, subscription_id):
        CALLS.append(("delete_plural", subscription_id))
        if STATE.get("plural_error"):
            raise _http_error(STATE["plural_error"])
        pend = [c for c in STATE["charges"] if c["status"] == "pendiente"]
        return {"cancel_charges": [{**c, "status": "cancelado"} for c in pend]}

    async def delete_charge(self, charge_id):
        CALLS.append(("delete_charge", charge_id))
        if STATE.get("single_error"):
            raise _http_error(STATE["single_error"])
        return {}

    async def create_charge(self, data):
        CALLS.append(("create_charge", data["suscription_id"]))
        if STATE.get("create_error"):
            raise _http_error(STATE["create_error"])
        return {"id": "cid_new", "suscription_id": data["suscription_id"], "amount": data["amount"],
                "charge_date": data["charge_date"], "status": "pendiente"}

    async def get_charge(self, charge_id):
        return {"id": charge_id, "status": "pendiente"}


def _charges():
    return [
        {"id": "c-pend-1", "charge_date": "2026-11-05", "amount": 9900, "status": "pendiente"},
        {"id": "c-pend-2", "charge_date": "2026-12-05", "amount": 9900, "status": "pendiente"},
        {"id": "c-proc", "charge_date": "2026-11-06", "amount": 9900, "status": "procesando"},
        {"id": "c-paid", "charge_date": "2026-10-05", "amount": 9900, "status": "pagado"},
        {"id": "c-rej", "charge_date": "2026-09-05", "amount": 9900, "status": "rechazado"},
    ]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    CALLS.clear()
    STATE.clear()
    STATE["charges"] = _charges()
    monkeypatch.setattr(settings, "virtualpos_writes_enabled", True)
    monkeypatch.setattr(settings, "virtualpos_allow_charge_on_fixed_plan", False)
    monkeypatch.setattr(svc, "VirtualPOSClient", FakeVP)


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


def _seed(db, plan_type: str | None = "MONTO_FIJO") -> None:
    db.add(Subscription(source="virtualpos1", external_id=SUB, plan_external_id="plan-1"))
    if plan_type is not None:
        db.add(Plan(source="virtualpos1", external_id="plan-1", plan_type=plan_type))
    for cid in ("c-pend-1", "c-pend-2"):
        db.add(Charge(source="virtualpos1", external_id=cid, subscription_external_id=SUB, status="pendiente",
                      raw_payload={"id": cid, "status": "pendiente"}))
    db.flush()


def _runs(db, operation):
    return list(db.scalars(select(WriteRun).where(WriteRun.operation == operation, WriteRun.external_id == SUB)))


def _deletes():
    return [c for c in CALLS if c[0].startswith("delete")]


def test_cancel_future_only_pending_and_traced(db_session) -> None:
    _seed(db_session)
    result = asyncio.run(svc.cancel_future_charges(db_session, SUB))
    assert [c["id"] for c in result["cancelled"]] == ["c-pend-1", "c-pend-2"]
    assert _deletes() == [("delete_plural", SUB)]
    run = _runs(db_session, "cancel_future_charges")[0]
    assert run.status == "completed"
    assert run.response_payload["cancelled_charge_ids"] == ["c-pend-1", "c-pend-2"]
    local = db_session.scalar(select(Charge).where(Charge.external_id == "c-pend-1"))
    assert local.status == "cancelado"


def test_cancel_future_no_pending_is_noop_without_delete(db_session) -> None:
    STATE["charges"] = [c for c in _charges() if c["status"] != "pendiente"]
    result = asyncio.run(svc.cancel_future_charges(db_session, SUB))
    assert result["noop"] is True
    assert _deletes() == []
    assert _runs(db_session, "cancel_future_charges")[0].status == "completed"


def test_cancel_future_e079_is_noop_not_error(db_session) -> None:
    STATE["plural_error"] = "E-079"
    result = asyncio.run(svc.cancel_future_charges(db_session, SUB))
    assert result["noop"] is True and result["cancelled"] == []
    assert _runs(db_session, "cancel_future_charges")[0].status == "completed"


def test_cancel_future_other_error_marks_failed(db_session) -> None:
    STATE["plural_error"] = "E-050"
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(svc.cancel_future_charges(db_session, SUB))
    assert _runs(db_session, "cancel_future_charges")[0].status == "failed"


def test_cancel_selected_e059_is_skipped(db_session) -> None:
    STATE["single_error"] = "E-059"
    result = asyncio.run(svc.cancel_future_charges(db_session, SUB, charge_ids=["c-pend-1", "c-proc"]))
    assert result["cancelled"] == []
    assert {s["id"]: s["reason"] for s in result["skipped"]} == {"c-pend-1": "E-059", "c-proc": "no_pendiente"}
    assert ("delete_charge", "c-proc") not in CALLS


def test_cancel_future_dry_run_does_not_write(db_session) -> None:
    result = asyncio.run(svc.cancel_future_charges(db_session, SUB, dry_run=True))
    assert [c["id"] for c in result["would_cancel"]] == ["c-pend-1", "c-pend-2"]
    assert _deletes() == []
    assert _runs(db_session, "cancel_future_charges") == []


def test_cancel_future_blocked_when_writes_disabled(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "virtualpos_writes_enabled", False)
    with pytest.raises(svc.WriteDisabledError):
        asyncio.run(svc.cancel_future_charges(db_session, SUB))
    assert CALLS == []


def test_reassign_creates_first_then_cancels_matching_period(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "virtualpos_allow_charge_on_fixed_plan", True)
    _seed(db_session)
    result = asyncio.run(
        svc.reassign_subscription_amount(db_session, SUB, 12000, "2026-11-05", dry_run=False)
    )
    names = [c[0] for c in CALLS]
    assert names.index("create_charge") < names.index("delete_charge")
    assert _deletes() == [("delete_charge", "c-pend-1")]  # solo el pendiente de noviembre
    assert result["created_charge_id"] == "cid_new"
    run = _runs(db_session, "reassign_subscription_amount")[0]
    assert run.status == "completed"
    assert run.response_payload["cancelled_charge_ids"] == ["c-pend-1"]


def test_reassign_post_failure_cancels_nothing(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "virtualpos_allow_charge_on_fixed_plan", True)
    STATE["create_error"] = "E-113"
    _seed(db_session)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(svc.reassign_subscription_amount(db_session, SUB, 12000, "2026-11-05", dry_run=False))
    assert _deletes() == []
    run = _runs(db_session, "reassign_subscription_amount")[0]
    assert run.status == "failed"
    assert "E-113" in run.error_message and "no se canceló ningún cargo" in run.error_message


def test_reassign_dry_run_does_not_write(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "virtualpos_allow_charge_on_fixed_plan", True)
    result = asyncio.run(svc.reassign_subscription_amount(db_session, SUB, 12000, "2026-11-05"))
    assert result["dry_run"] is True
    assert [c["id"] for c in result["would_cancel"]] == ["c-pend-1"]
    assert result["would_create"]["amount"] == 12000
    assert {c[0] for c in CALLS} == {"list_charges"}
    assert _runs(db_session, "reassign_subscription_amount") == []


@pytest.mark.parametrize("plan_type", ["MONTO_FIJO", None])
def test_flag_off_blocks_fixed_or_unknown_plan_without_provider_call(db_session, plan_type) -> None:
    _seed(db_session, plan_type=plan_type)
    with pytest.raises(svc.FixedPlanChargeBlockedError):
        asyncio.run(svc.create_charge(db_session, SUB, {"charge_date": "2026-11-05", "amount": 1}))
    with pytest.raises(svc.FixedPlanChargeBlockedError):
        asyncio.run(svc.reassign_subscription_amount(db_session, SUB, 1, "2026-11-05"))
    assert CALLS == []


def test_flag_off_allows_variable_plan(db_session) -> None:
    _seed(db_session, plan_type="MONTO_VARIABLE")
    charge = asyncio.run(svc.create_charge(db_session, SUB, {"charge_date": "2026-11-05", "amount": 1}))
    assert charge.external_id == "cid_new"


def test_flag_on_keeps_current_behavior_for_fixed_plan(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "virtualpos_allow_charge_on_fixed_plan", True)
    _seed(db_session)
    charge = asyncio.run(svc.create_charge(db_session, SUB, {"charge_date": "2026-11-05", "amount": 1}))
    assert charge.external_id == "cid_new"


# -- Rutas --------------------------------------------------------------------

def _route_client(monkeypatch, db_session, perms: list[str]) -> tuple[TestClient, str]:
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    user = SimpleNamespace(
        id=uuid.uuid4(), is_active=True,
        roles=[SimpleNamespace(name="r", permissions=[SimpleNamespace(code=p) for p in perms])],
    )
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


BASE = f"/api/v1/writes/virtualpos/subscriptions/{SUB}"
BODY = {"new_amount": 12000, "effective_date": "2026-11-05"}


def test_routes_permissions_and_csrf(monkeypatch, db_session, _cleanup) -> None:
    client, csrf = _route_client(monkeypatch, db_session, ["virtualpos.charges.create"])
    h = {"X-CSRF-Token": csrf}
    assert client.delete(f"{BASE}/charges", headers=h).status_code == 403  # falta cancel
    assert client.post(f"{BASE}/reassign-amount", json=BODY, headers=h).status_code == 403  # falta cancel
    client, csrf = _route_client(monkeypatch, db_session, ["virtualpos.charges.cancel"])
    assert client.post(f"{BASE}/reassign-amount", json=BODY, headers={"X-CSRF-Token": csrf}).status_code == 403
    assert client.delete(f"{BASE}/charges").status_code == 403  # sin CSRF
    assert CALLS == []


def test_route_cancel_defaults_to_dry_run(monkeypatch, db_session, _cleanup) -> None:
    client, csrf = _route_client(monkeypatch, db_session, ["virtualpos.charges.cancel"])
    r = client.delete(f"{BASE}/charges", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and r.json()["dry_run"] is True
    assert len(r.json()["would_cancel"]) == 2
    assert _deletes() == []
    r = client.delete(f"{BASE}/charges?dry_run=false", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and len(r.json()["cancelled"]) == 2
    assert _deletes() == [("delete_plural", SUB)]


def test_route_cancel_writes_disabled_403(monkeypatch, db_session, _cleanup) -> None:
    monkeypatch.setattr(settings, "virtualpos_writes_enabled", False)
    client, csrf = _route_client(monkeypatch, db_session, ["virtualpos.charges.cancel"])
    r = client.delete(f"{BASE}/charges?dry_run=false", headers={"X-CSRF-Token": csrf})
    assert r.status_code == 403
    assert CALLS == []


def test_route_reassign_and_create_422_when_flag_off(monkeypatch, db_session, _cleanup) -> None:
    _seed(db_session)
    client, csrf = _route_client(
        monkeypatch, db_session, ["virtualpos.charges.create", "virtualpos.charges.cancel"]
    )
    h = {"X-CSRF-Token": csrf}
    r = client.post(f"{BASE}/reassign-amount?dry_run=false", json=BODY, headers=h)
    assert r.status_code == 422 and "monto fijo" in r.json()["detail"]
    r = client.post(f"{BASE}/charges", json={"charge_date": "2026-11-05", "amount": 5}, headers=h)
    assert r.status_code == 422 and "monto fijo" in r.json()["detail"]
    assert CALLS == []
