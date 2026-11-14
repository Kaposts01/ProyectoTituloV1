"""d188: Payku devuelve muchos errores con HTTP 200 y `{"status": "failed", ...}`.

El cliente los convierte en `PaykuApiError`, salvo la pagina vacia de los listados ("there are no records"), que
sigue llegando tal cual y el sync la trata como coleccion vacia. Sin red: transporte httpx falso; BD de pruebas con
rollback para write_payku y subscription_refresh.
"""

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any, ClassVar

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes import writes as writes_routes
from app.core.config import Settings
from app.db.session import engine
from app.integrations.payku import client as payku_client
from app.integrations.payku.client import PaykuApiError, is_no_records_response
from app.models.crm import Client, Subscription
from app.models.payku_channel import PaykuSubscription
from app.models.write_run import WriteRun
from app.services import payku_sync, subscription_refresh, write_payku

NO_RECORDS = {"status": "failed", "type": "there are no records"}
NOT_FOUND = {"status": "failed", "type": "Not Found", "id": "is not valid"}
UNPROCESSABLE = {
    "status": "failed",
    "type": "Unprocessable Entity",
    "message_error": "email:is empty",
}
OK_CLIENT = {"id": "cl_1", "status": "active", "name": "TEST-socio", "email": "socio@example.test"}


def production(**kw: Any) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://u:p@localhost/crm",
        virtualpos_base_url="https://api.virtualpos.cl",
        virtualpos_api_key="prod-vk",
        virtualpos_secret_key="prod-vs",
        payku_base_url="https://app.payku.cl",
        payku_public_token="prod-pk-public",
        payku_private_token="prod-pk-private",
        app_env="production",
        **kw,
    )


class FakeHttp:
    """Sustituye httpx.AsyncClient. `routes[(METODO, ruta)] = (http_status, cuerpo)`; por defecto 200 + OK_CLIENT."""

    routes: ClassVar[dict[tuple[str, str], tuple[int, Any]]] = {}
    calls: ClassVar[list[tuple[str, str]]] = []

    def __init__(self, **_: object) -> None:
        pass

    async def aclose(self) -> None:
        return None

    async def _do(self, method: str, path: str, **_: object) -> httpx.Response:
        FakeHttp.calls.append((method, path))
        status, body = FakeHttp.routes.get((method, path), (200, OK_CLIENT))
        return httpx.Response(status, json=body, request=httpx.Request(method, "https://fake.invalid" + path))

    async def get(self, path: str, **kw: object) -> httpx.Response:
        return await self._do("GET", path, **kw)

    async def post(self, path: str, **kw: object) -> httpx.Response:
        return await self._do("POST", path, **kw)

    async def put(self, path: str, **kw: object) -> httpx.Response:
        return await self._do("PUT", path, **kw)

    async def delete(self, path: str, **kw: object) -> httpx.Response:
        return await self._do("DELETE", path, **kw)


@pytest.fixture
def fake_http(monkeypatch: pytest.MonkeyPatch):
    FakeHttp.routes = {}
    FakeHttp.calls = []
    s = production(payku_writes_enabled=True)
    monkeypatch.setattr(payku_client.httpx, "AsyncClient", FakeHttp)
    monkeypatch.setattr(payku_client, "settings", s)
    monkeypatch.setattr(write_payku, "settings", s)
    yield FakeHttp


def run_client(coro_fn):
    async def go():
        async with payku_client.PaykuClient() as c:
            return await coro_fn(c)

    return asyncio.run(go())


# ------------------------------------------------------------------ cliente ----


@pytest.mark.parametrize(
    ("method", "path", "call"),
    [
        ("GET", "/api/suclient/cl_1", lambda c: c.get_client("cl_1")),
        ("GET", "/api/sususcription/su_1", lambda c: c.get_subscription("su_1")),
        ("POST", "/api/suclient", lambda c: c.create_client({"name": "TEST"})),
        ("PUT", "/api/suclient/cl_1", lambda c: c.update_client("cl_1", {"phone": "1"})),
        ("DELETE", "/api/suclient/cl_1", lambda c: c.delete_client("cl_1")),
        ("DELETE", "/api/sususcription/su_1", lambda c: c.delete_subscription("su_1")),
    ],
)
def test_http_200_with_status_failed_raises(fake_http, method: str, path: str, call) -> None:
    fake_http.routes[(method, path)] = (200, UNPROCESSABLE)
    with pytest.raises(PaykuApiError) as e:
        run_client(call)
    assert e.value.http_status == 200
    assert e.value.method == method
    assert e.value.error_type == "Unprocessable Entity"
    assert e.value.detail == "email:is empty"
    assert "prod-pk" not in str(e.value)


def test_status_failed_is_case_insensitive_and_success_shapes_pass(fake_http) -> None:
    fake_http.routes[("GET", "/api/suclient/cl_1")] = (200, {"status": "FAILED", "type": "Not Found"})
    with pytest.raises(PaykuApiError):
        run_client(lambda c: c.get_client("cl_1"))
    # Respuestas exitosas con el estado del recurso (no "success") siguen pasando.
    for body in ({"status": "active", "id": "cl_1"}, {"status": "register"}, [{"id": "x"}], {"data": {"id": "y"}}):
        fake_http.routes[("GET", "/api/suclient/cl_1")] = (200, body)
        assert run_client(lambda c: c.get_client("cl_1")) == body


def test_http_error_status_still_raises_http_status_error(fake_http) -> None:
    fake_http.routes[("GET", "/api/suclient/cl_1")] = (404, NOT_FOUND)
    with pytest.raises(httpx.HTTPStatusError):
        run_client(lambda c: c.get_client("cl_1"))


@pytest.mark.parametrize(
    ("path", "call"),
    [
        ("/api/suclient/customers", lambda c: c.list_clients(page=3)),
        ("/api/suplan/plans", lambda c: c.list_plans()),
        ("/api/sususcription", lambda c: c.list_subscriptions(page=2)),
        ("/api/sususcriptionv3", lambda c: c.list_subscriptions_v3(page=2)),
        ("/api/transaction", lambda c: c.list_transactions(page=2)),
        ("/api/wallet/list", lambda c: c.list_wallet_movements(page=2)),
    ],
)
def test_listing_no_records_is_returned_as_empty_collection(fake_http, path: str, call) -> None:
    fake_http.routes[("GET", path)] = (200, dict(NO_RECORDS))
    body = run_client(call)
    assert body == NO_RECORDS
    assert is_no_records_response(body)
    assert payku_sync._records_from(body) == []


def test_listing_other_failed_still_raises(fake_http) -> None:
    fake_http.routes[("GET", "/api/suclient/customers")] = (200, {"status": "failed", "type": "Unauthorized"})
    with pytest.raises(PaykuApiError) as e:
        run_client(lambda c: c.list_clients())
    assert e.value.error_type == "Unauthorized"


def test_no_records_outside_listings_is_an_error(fake_http) -> None:
    fake_http.routes[("GET", "/api/suclient/cl_1")] = (200, dict(NO_RECORDS))
    with pytest.raises(PaykuApiError):
        run_client(lambda c: c.get_client("cl_1"))
    fake_http.routes[("DELETE", "/api/suclient/cl_1")] = (200, dict(NO_RECORDS))
    with pytest.raises(PaykuApiError):
        run_client(lambda c: c.delete_client("cl_1"))


def test_no_records_shape() -> None:
    assert is_no_records_response({"status": "failed", "type": "there are no records"})
    assert is_no_records_response({"status": "Failed", "type": "There are NO RECORDS"})
    assert not is_no_records_response({"status": "success", "type": "there are no records"})
    assert not is_no_records_response({"status": "failed", "type": "Not Found"})
    assert not is_no_records_response({"status": "failed", "message_error": "no records"})
    assert not is_no_records_response([])


# ----------------------------------------------------------- write_payku ----


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


def _run_for(db: Session, external_id: str) -> WriteRun:
    return db.scalars(select(WriteRun).where(WriteRun.external_id == external_id)).one()


def test_update_client_failed_body_marks_run_failed_and_leaves_local_untouched(db_session, fake_http) -> None:
    ext = f"cl_d188_{uuid.uuid4().hex[:8]}"
    original = {"id": ext, "name": "Original", "phone": "900000000"}
    client = Client(source="payku", external_id=ext, first_name="Original", raw_payload=dict(original))
    db_session.add(client)
    db_session.flush()
    fake_http.routes[("PUT", f"/api/suclient/{ext}")] = (200, UNPROCESSABLE)
    with pytest.raises(PaykuApiError):
        asyncio.run(write_payku.update_client(db_session, ext, {"phone": "900000001"}))
    run = _run_for(db_session, ext)
    assert run.status == "failed"
    assert "Unprocessable Entity" in (run.error_message or "")
    assert run.response_payload is None
    db_session.refresh(client)
    assert client.raw_payload == original and client.first_name == "Original"
    assert ("GET", f"/api/suclient/{ext}") not in fake_http.calls


def test_update_client_failed_refresh_is_not_stored_as_client(db_session, fake_http) -> None:
    ext = f"cl_d188_{uuid.uuid4().hex[:8]}"
    client = Client(source="payku", external_id=ext, first_name="Original", raw_payload={"id": ext, "name": "Original"})
    db_session.add(client)
    db_session.flush()
    fake_http.routes[("PUT", f"/api/suclient/{ext}")] = (200, {"status": "active", "id": ext})
    fake_http.routes[("GET", f"/api/suclient/{ext}")] = (200, NOT_FOUND)
    asyncio.run(write_payku.update_client(db_session, ext, {"phone": "900000001"}))
    db_session.refresh(client)
    assert client.raw_payload.get("status") != "failed"
    assert client.raw_payload.get("type") is None
    assert client.raw_payload.get("phone") == "900000001"
    assert _run_for(db_session, ext).status == "completed"


def test_delete_client_failed_body_does_not_mark_deleted(db_session, fake_http) -> None:
    ext = f"cl_d188_{uuid.uuid4().hex[:8]}"
    client = Client(source="payku", external_id=ext, first_name="X", status="active", raw_payload={"status": "active"})
    db_session.add(client)
    db_session.flush()
    fake_http.routes[("DELETE", f"/api/suclient/{ext}")] = (200, NOT_FOUND)
    with pytest.raises(PaykuApiError):
        asyncio.run(write_payku.delete_client(db_session, ext))
    assert _run_for(db_session, ext).status == "failed"
    db_session.refresh(client)
    assert client.status == "active" and client.raw_payload == {"status": "active"}


def test_delete_subscription_failed_body_does_not_mark_cancelled(db_session, fake_http) -> None:
    ext = f"su_d188_{uuid.uuid4().hex[:8]}"
    sub = Subscription(source="payku", external_id=ext, status="active", raw_payload={"status": "active"})
    db_session.add(sub)
    db_session.flush()
    fake_http.routes[("DELETE", f"/api/sususcription/{ext}")] = (200, UNPROCESSABLE)
    with pytest.raises(PaykuApiError):
        asyncio.run(write_payku.delete_subscription(db_session, ext))
    run = _run_for(db_session, ext)
    assert run.status == "failed" and run.finished_at is not None
    db_session.refresh(sub)
    assert sub.status == "active" and sub.raw_payload == {"status": "active"}


# ---------------------------------------------------- subscription_refresh ----


def test_refresh_does_not_store_failed_body_from_real_client(db_session, fake_http) -> None:
    ext = f"su_d188_{uuid.uuid4().hex[:8]}"
    fake_http.routes[("GET", f"/api/sususcription/{ext}")] = (200, NOT_FOUND)
    with pytest.raises(subscription_refresh.RefreshError) as e:
        asyncio.run(subscription_refresh.refresh_subscription(db_session, "payku", ext))
    assert e.value.code == "PROVIDER_READ_FAILED"
    assert db_session.scalar(select(PaykuSubscription).where(PaykuSubscription.external_id == ext)) is None


def test_refresh_guard_rejects_failed_dict_from_substitute_client(db_session, monkeypatch) -> None:
    class FailedPayku:
        def __init__(self, *_: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get_subscription(self, _sid):
            return dict(NOT_FOUND)

    monkeypatch.setattr(subscription_refresh, "PaykuClient", FailedPayku)
    ext = f"su_d188_{uuid.uuid4().hex[:8]}"
    with pytest.raises(subscription_refresh.RefreshError) as e:
        asyncio.run(subscription_refresh.refresh_subscription(db_session, "payku", ext))
    assert e.value.code == "PROVIDER_READ_FAILED"
    assert db_session.scalar(select(PaykuSubscription).where(PaykuSubscription.external_id == ext)) is None


# ------------------------------------------------------------------ rutas ----


@pytest.mark.parametrize(
    ("fn_name", "args", "code"),
    [
        ("update_payku_client", ("c1", writes_routes.PaykuClientUpdate(phone="1")), "payku_rejected_update"),
        ("delete_payku_client", ("c1",), "payku_rejected_deletion"),
        ("delete_payku_subscription", ("s1",), "payku_rejected_cancellation"),
    ],
)
def test_routes_map_failed_body_to_502(monkeypatch, fn_name: str, args: tuple, code: str) -> None:
    async def rejected(*_a, **_k):
        raise PaykuApiError("DELETE", "Not Found", None, 200)

    for name in ("payku_update_client", "payku_delete_client", "payku_delete_subscription"):
        monkeypatch.setattr(writes_routes, name, rejected)
    with pytest.raises(HTTPException) as e:
        asyncio.run(getattr(writes_routes, fn_name)(*args, None, SimpleNamespace(id=uuid.uuid4())))
    assert e.value.status_code == 502
    assert e.value.detail["code"] == code
