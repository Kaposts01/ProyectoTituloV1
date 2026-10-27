"""Idempotencia de create_charge por internal_code (lado nuestro): VP no la impone. Todo offline, cliente falso."""

import asyncio
import json

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.integrations.virtualpos.client import VirtualPOSAPIError, VirtualPOSClient
from app.models.crm import Charge, Plan, Subscription
from app.models.write_run import WriteRun
from app.services import write_virtualpos as svc

SUB = "sub-idem-1"
CODE = "COD-1"


class FakeVP:
    """Proveedor con estado: POST /v3/charge crea, el listado devuelve lo creado (con internal_code)."""

    def __init__(self, existing: list[dict] | None = None) -> None:
        self.charges: list[dict] = list(existing or [])
        self.requests: list[tuple[str, str]] = []
        self.fail_list = False
        self.timeout_first_post = False  # el cargo se crea pero la respuesta se pierde
        self._n = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        ok = lambda body: httpx.Response(200, json=body, request=request)  # noqa: E731
        if request.method == "GET" and request.url.path == f"/v3/suscription/{SUB}/charges":
            if self.fail_list:
                return ok({"status": "NOK", "code": 500, "error": {"error_code": "E-999", "message": "boom"}})
            return ok({"status": "OK", "pagination": {"page": 1, "pages": 1}, "charges": self.charges})
        if request.method == "POST" and request.url.path == "/v3/charge":
            body = json.loads(request.content)
            self._n += 1
            charge = {"id": f"new-{self._n}", "amount": body["amount"], "charge_date": body["charge_date"],
                      "internal_code": body.get("internal_code"), "status": "pendiente"}
            self.charges.append(charge)
            if self.timeout_first_post:
                self.timeout_first_post = False
                raise httpx.ReadTimeout("timeout", request=request)
            return ok({"status": "OK", "charge": charge})
        if request.method == "DELETE" and request.url.path.startswith("/v3/charge/"):
            cid = request.url.path.rsplit("/", 1)[1]
            for c in self.charges:
                if c["id"] == cid:
                    c["status"] = "cancelado"
            return ok({"status": "OK"})
        return httpx.Response(404, json={"status": "NOK"}, request=request)

    def client(self, *_a: object, **_k: object) -> VirtualPOSClient:
        real = VirtualPOSClient.__new__(VirtualPOSClient)
        real._client = httpx.AsyncClient(base_url="https://vp.test", transport=httpx.MockTransport(self.handler))
        return real

    def posts(self) -> int:
        return sum(1 for m, p in self.requests if (m, p) == ("POST", "/v3/charge"))


def _existing(status: str, cid: str = "old-1", code: str = CODE) -> dict:
    return {"id": cid, "amount": 5000, "charge_date": "2099-01-05", "internal_code": code, "status": status}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "virtualpos_writes_enabled", True)
    monkeypatch.setattr(settings, "virtualpos_allow_charge_on_fixed_plan", False)


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


def _setup(monkeypatch, db, fake: FakeVP) -> FakeVP:
    monkeypatch.setattr(svc, "VirtualPOSClient", fake.client)
    db.add(Subscription(source="virtualpos1", external_id=SUB, plan_external_id="plan-idem"))
    db.add(Plan(source="virtualpos1", external_id="plan-idem", plan_type="MONTO_VARIABLE"))
    db.flush()
    return fake


def _create(db, code: str | None = CODE):
    data = {"charge_date": "2099-01-05", "amount": 5000}
    if code:
        data["internal_code"] = code
    return asyncio.run(svc.create_charge(db, SUB, data))


def _runs(db):
    return list(db.scalars(select(WriteRun).where(WriteRun.operation == "create_charge")))


def test_adopta_pendiente_con_mismo_codigo_sin_post(monkeypatch, db_session) -> None:
    fake = _setup(monkeypatch, db_session, FakeVP([_existing("pendiente")]))
    charge = _create(db_session)
    assert fake.posts() == 0
    assert charge.external_id == "old-1" and charge.status == "pendiente" and charge.subscription_external_id == SUB
    run = _runs(db_session)[0]
    assert run.status == "completed" and run.response_payload == {"adopted": True, "charge_id": "old-1"}


def test_crea_si_solo_hay_cancelado_con_ese_codigo(monkeypatch, db_session) -> None:
    fake = _setup(monkeypatch, db_session, FakeVP([_existing("cancelado")]))
    charge = _create(db_session)
    assert fake.posts() == 1 and charge.external_id == "new-1"
    assert _runs(db_session)[0].status == "completed"


def test_crea_si_no_existe(monkeypatch, db_session) -> None:
    fake = _setup(monkeypatch, db_session, FakeVP([_existing("pendiente", code="OTRO")]))
    charge = _create(db_session)
    assert fake.posts() == 1 and charge.external_id == "new-1"


def test_sin_internal_code_no_consulta_listado(monkeypatch, db_session) -> None:
    fake = _setup(monkeypatch, db_session, FakeVP())
    _create(db_session, code=None)
    assert fake.posts() == 1 and not any(m == "GET" for m, _ in fake.requests)


def test_timeout_en_post_y_reintento_adopta(monkeypatch, db_session) -> None:
    fake = _setup(monkeypatch, db_session, FakeVP())
    fake.timeout_first_post = True
    with pytest.raises(httpx.ReadTimeout):
        _create(db_session)
    assert fake.posts() == 1 and len(fake.charges) == 1
    charge = _create(db_session)  # reintento del llamador, mismo internal_code
    assert fake.posts() == 1 and len(fake.charges) == 1 and charge.external_id == "new-1"
    assert [r.status for r in sorted(_runs(db_session), key=lambda r: r.started_at)] == ["failed", "completed"]


def test_error_del_listado_impide_crear(monkeypatch, db_session) -> None:
    fake = _setup(monkeypatch, db_session, FakeVP())
    fake.fail_list = True
    with pytest.raises(VirtualPOSAPIError):
        _create(db_session)
    assert fake.posts() == 0 and fake.charges == []
    assert _runs(db_session)[0].status == "failed"
    assert db_session.scalar(select(Charge).where(Charge.subscription_external_id == SUB)) is None


def test_reassign_dos_veces_es_idempotente(monkeypatch, db_session) -> None:
    fake = _setup(monkeypatch, db_session, FakeVP([_existing("pendiente", "old-pend", code="otro")]))
    first = asyncio.run(svc.reassign_subscription_amount(db_session, SUB, 7000, "2099-01-05", dry_run=False))
    second = asyncio.run(svc.reassign_subscription_amount(db_session, SUB, 7000, "2099-01-05", dry_run=False))
    assert fake.posts() == 1
    assert first["created_charge_id"] == second["created_charge_id"] == "new-1"
    by_id = {c["id"]: c["status"] for c in fake.charges}
    assert by_id == {"old-pend": "cancelado", "new-1": "pendiente"}  # el adoptado/nuevo no se cancela
    assert [c["id"] for c in second["cancelled"]] == []
