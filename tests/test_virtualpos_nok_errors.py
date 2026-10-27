"""VirtualPOS responde errores de negocio con HTTP 200 + cuerpo NOK: el cliente debe tratarlos como error.

Todo offline: cliente real de la app sobre httpx.MockTransport (sin red, sin credenciales).
"""

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
from app.models.sync_run import SyncRun
from app.models.write_run import WriteRun
from app.services import virtualpos_sync
from app.services import write_virtualpos as svc

SUB = "sub-nok-1"


def _nok(code: str, message: str = "algo salió mal", provider_code: int = 400) -> dict:
    return {
        "status": "NOK", "code": provider_code,
        "error": {"error_code": code, "message": message, "doc_url": "https://doc.test/errors"},
    }


class Provider:
    """Transporte falso: responde según (método, ruta); registra las peticiones."""

    def __init__(self, routes: dict[tuple[str, str], dict | list]) -> None:
        self.routes = routes
        self.requests: list[tuple[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        self.requests.append(key)
        body = self.routes.get(key)
        if callable(body):
            body = body(request)
        if body is None:
            return httpx.Response(404, json={"status": "NOK", "code": 404}, request=request)
        return httpx.Response(200, json=body, request=request)  # siempre HTTP 200, como el proveedor

    def client(self, *_args: object, **_kwargs: object) -> VirtualPOSClient:
        real = VirtualPOSClient.__new__(VirtualPOSClient)  # sin credenciales
        real._client = httpx.AsyncClient(base_url="https://vp.test", transport=httpx.MockTransport(self.handler))
        return real

    def calls(self, method: str) -> list[str]:
        return [path for m, path in self.requests if m == method]


def _install(monkeypatch, routes) -> Provider:
    provider = Provider(routes)
    monkeypatch.setattr(svc, "VirtualPOSClient", provider.client)
    return provider


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


def _seed(db) -> None:
    db.add(Subscription(source="virtualpos1", external_id=SUB, plan_external_id="plan-nok"))
    db.add(Plan(source="virtualpos1", external_id="plan-nok", plan_type="MONTO_VARIABLE"))
    for cid in ("c-1", "c-2"):
        db.add(Charge(source="virtualpos1", external_id=cid, subscription_external_id=SUB, status="pendiente",
                      raw_payload={"id": cid, "status": "pendiente"}))
    db.flush()


def _pending_listing() -> dict:
    return {
        "status": "OK", "code": 200, "pagination": {"page": 1, "pages": 1},
        "charges": [{"id": cid, "charge_date": "2099-01-05", "amount": 1000, "status": "pendiente"}
                    for cid in ("c-1", "c-2")],
    }


def _run(db, operation, external_id=SUB):
    return list(db.scalars(select(WriteRun).where(WriteRun.operation == operation, WriteRun.external_id == external_id)))


# ---- cliente: detección central ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "call"),
    [
        ("GET", lambda c: c.get_charge("c1")),
        ("GET", lambda c: c.list_charges("s1")),
        ("POST", lambda c: c.create_charge({"amount": 1})),
        ("POST", lambda c: c.create_client({"first_name": "x"})),
        ("PUT", lambda c: c.update_client("cl1", {"first_name": "x"})),
        ("DELETE", lambda c: c.delete_charge("c1")),
        ("DELETE", lambda c: c.delete_subscription_charges("s1")),
        ("DELETE", lambda c: c.cancel_subscription("s1")),
        ("GET", lambda c: c.retry_charge("c1")),
    ],
)
def test_nok_con_http_200_lanza_error_con_codigo(method, call) -> None:
    provider = Provider({})
    provider.handler = lambda request: httpx.Response(200, json=_nok("E-078", "Fecha inválida"), request=request)
    client = provider.client()
    with pytest.raises(VirtualPOSAPIError) as info:
        asyncio.run(call(client))
    exc = info.value
    assert exc.error_code == "E-078"
    assert exc.provider_code == 400 and exc.http_status == 200
    assert "Fecha inválida" in exc.message
    assert "E-078" in str(exc)
    assert "doc.test" not in str(exc) and "doc.test" not in exc.response.text
    assert svc._provider_error_code(exc) == "E-078"
    assert json.loads(exc.response.text)["error"]["error_code"] == "E-078"


def test_error_con_dict_error_y_status_ok_tambien_se_detecta() -> None:
    provider = Provider({("GET", "/v3/charge/c1"): {"status": "OK", "error": {"error_code": "E-059", "message": "m"}}})
    with pytest.raises(VirtualPOSAPIError) as info:
        asyncio.run(provider.client().get_charge("c1"))
    assert info.value.error_code == "E-059"


def test_mensaje_del_error_se_sanea() -> None:
    body = _nok("E-086", "dup 4111111111111111\nlinea")
    provider = Provider({("POST", "/v3/charge"): body})
    with pytest.raises(VirtualPOSAPIError) as info:
        asyncio.run(provider.client().create_charge({}))
    assert "4111111111111111" not in str(info.value) and "\n" not in info.value.message


def test_respuestas_normales_no_se_ven_afectadas() -> None:
    ok = {"status": "OK", "code": 200, "charge": {"id": "c1", "status": "pendiente"}}
    provider = Provider({
        ("GET", "/v3/charge/c1"): ok,
        ("POST", "/v3/charge"): ok,
        ("DELETE", "/v3/charge/c1"): {"status": "OK", "code": 200},
        ("GET", "/v3/plans"): [{"id": "p1"}],
    })
    client = provider.client()
    assert asyncio.run(client.get_charge("c1")) == ok
    assert asyncio.run(client.create_charge({})) == ok
    assert asyncio.run(client.delete_charge("c1")) == {"status": "OK", "code": 200}
    assert asyncio.run(client.list_plans()) == [{"id": "p1"}]


def test_http_error_real_sigue_siendo_http_status_error() -> None:
    provider = Provider({})
    provider.handler = lambda request: httpx.Response(400, json=_nok("E-079"), request=request)
    with pytest.raises(httpx.HTTPStatusError) as info:
        asyncio.run(provider.client().delete_subscription_charges("s1"))
    assert svc._provider_error_code(info.value) == "E-079"


def test_nok_en_lectura_no_se_reintenta(monkeypatch) -> None:
    monkeypatch.setattr(settings, "virtualpos_read_retries", 3)
    provider = Provider({("GET", "/v3/charge/c1"): _nok("E-059")})
    with pytest.raises(VirtualPOSAPIError):
        asyncio.run(provider.client().get_charge("c1"))
    assert provider.calls("GET") == ["/v3/charge/c1"]


# ---- write_virtualpos ------------------------------------------------------------------------------------


def test_cancel_selected_nok_e059_queda_skipped_y_no_se_reconcilia(monkeypatch, db_session) -> None:
    _seed(db_session)
    provider = _install(monkeypatch, {
        ("GET", f"/v3/suscription/{SUB}/charges"): _pending_listing(),
        ("DELETE", "/v3/charge/c-1"): _nok("E-059", "El cargo ya está cancelado"),
    })
    result = asyncio.run(svc.cancel_future_charges(db_session, SUB, charge_ids=["c-1"]))
    assert result["cancelled"] == [] and result["noop"] is True
    assert result["skipped"] == [{"id": "c-1", "reason": "E-059"}]
    assert provider.calls("DELETE") == ["/v3/charge/c-1"]
    assert db_session.scalar(select(Charge).where(Charge.external_id == "c-1")).status == "pendiente"
    assert _run(db_session, "cancel_future_charges")[0].status == "completed"


def test_cancel_selected_otro_nok_falla_y_no_marca_cancelado(monkeypatch, db_session) -> None:
    _seed(db_session)
    _install(monkeypatch, {
        ("GET", f"/v3/suscription/{SUB}/charges"): _pending_listing(),
        ("DELETE", "/v3/charge/c-1"): _nok("E-050"),
    })
    with pytest.raises(VirtualPOSAPIError):
        asyncio.run(svc.cancel_future_charges(db_session, SUB, charge_ids=["c-1"]))
    run = _run(db_session, "cancel_future_charges")[0]
    assert run.status == "failed" and "E-050" in run.error_message
    assert db_session.scalar(select(Charge).where(Charge.external_id == "c-1")).status == "pendiente"


def test_cancel_plural_nok_e079_es_noop(monkeypatch, db_session) -> None:
    _seed(db_session)
    _install(monkeypatch, {
        ("GET", f"/v3/suscription/{SUB}/charges"): _pending_listing(),
        ("DELETE", f"/v3/charges/{SUB}"): _nok("E-079", "No hay cargos pendientes"),
    })
    result = asyncio.run(svc.cancel_future_charges(db_session, SUB))
    assert result["noop"] is True and result["cancelled"] == []
    assert _run(db_session, "cancel_future_charges")[0].status == "completed"
    assert db_session.scalar(select(Charge).where(Charge.external_id == "c-1")).status == "pendiente"


def test_create_charge_nok_e078_falla_con_codigo(monkeypatch, db_session) -> None:
    _seed(db_session)
    _install(monkeypatch, {("POST", "/v3/charge"): _nok("E-078", "La fecha debe ser mayor o igual a hoy")})
    with pytest.raises(VirtualPOSAPIError) as info:
        asyncio.run(svc.create_charge(db_session, SUB, {"charge_date": "2020-01-01", "amount": 1000}))
    assert info.value.error_code == "E-078"
    runs = _run(db_session, "create_charge", "pending")
    assert any(r.status == "failed" and "E-078" in (r.error_message or "") for r in runs)
    assert db_session.scalar(select(Charge).where(Charge.external_id == "cid_new")) is None


def test_reassign_con_nok_en_post_no_cancela_nada(monkeypatch, db_session) -> None:
    _seed(db_session)
    provider = _install(monkeypatch, {
        ("GET", f"/v3/suscription/{SUB}/charges"): _pending_listing(),
        ("POST", "/v3/charge"): _nok("E-078"),
    })
    with pytest.raises(VirtualPOSAPIError):
        asyncio.run(svc.reassign_subscription_amount(db_session, SUB, 5000, "2099-01-05", dry_run=False))
    assert provider.calls("DELETE") == []
    run = _run(db_session, "reassign_subscription_amount")[0]
    assert run.status == "failed" and "E-078" in run.error_message


def test_cancel_charge_nok_marca_failed_y_no_cancela_local(monkeypatch, db_session) -> None:
    _seed(db_session)
    _install(monkeypatch, {("DELETE", "/v3/charge/c-1"): _nok("E-059")})
    with pytest.raises(VirtualPOSAPIError):
        asyncio.run(svc.cancel_charge(db_session, "c-1"))
    assert _run(db_session, "cancel_charge", "c-1")[0].status == "failed"
    assert db_session.scalar(select(Charge).where(Charge.external_id == "c-1")).status == "pendiente"


def test_retry_charge_nok_marca_failed(monkeypatch, db_session) -> None:
    _seed(db_session)
    _install(monkeypatch, {("GET", "/v3/charge/c-1/retry"): _nok("E-060")})
    with pytest.raises(VirtualPOSAPIError):
        asyncio.run(svc.retry_charge(db_session, "c-1"))
    run = _run(db_session, "retry_charge", "c-1")[0]
    assert run.status == "failed" and "E-060" in run.error_message


def test_adopcion_por_internal_code_no_aplica() -> None:
    """internal_code no se expone en los cargos listados (docs/datos): no se inventa el campo ni se adopta."""
    import inspect

    assert "internal_code" not in inspect.getsource(svc._list_pending_charges)


# ---- sync ---------------------------------------------------------------------------------------------------


def test_sync_con_nok_falla_el_run_con_el_codigo(monkeypatch, db_session) -> None:
    provider = Provider({("GET", "/v3/clients"): _nok("E-001", "Credenciales inválidas", 401)})
    monkeypatch.setattr(virtualpos_sync, "VirtualPOSClient", lambda *a: provider.client())
    with pytest.raises(VirtualPOSAPIError):
        asyncio.run(virtualpos_sync.sync_virtualpos(db_session))
    run = db_session.scalars(
        select(SyncRun).where(SyncRun.source == virtualpos_sync.SOURCE, SyncRun.status == "failed")
        .order_by(SyncRun.started_at.desc())
    ).first()
    assert run is not None and "E-001" in run.error_message and "Sync interrumpido" in run.error_message
