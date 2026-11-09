"""Guardas duras de escritura de Payku (sandbox/qa), d165. Sin red: transporte httpx falso, sin BD."""

import asyncio
import uuid
from types import SimpleNamespace
from typing import ClassVar

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes import writes as writes_routes
from app.core.config import Settings
from app.db.session import engine
from app.integrations.payku import client as payku_client
from app.integrations.payku import write_guard
from app.integrations.payku.write_guard import (
    ENV_ALLOWED_IDS,
    ENV_ARMED,
    ENV_MAX_WRITES,
    PaykuWriteBlockedError,
    WriteGuardState,
    assert_sandbox_write_allowed,
)
from app.models.crm import Client
from app.models.write_run import WriteRun
from app.services import write_payku

DB = "postgresql+psycopg://u:p@localhost/crm"
SDB = "postgresql+psycopg://u:p@localhost/crm_sandbox"
PROD = {
    "database_url": DB,
    "virtualpos_base_url": "https://api.virtualpos.cl",
    "virtualpos_api_key": "prod-vk",
    "virtualpos_secret_key": "prod-vs",
    "payku_base_url": "https://app.payku.cl",
    "payku_public_token": "prod-pk-public",
    "payku_private_token": "prod-pk-private",
    "payku_writes_enabled": False,
}
SBX = {
    "sandbox_database_url": SDB,
    "virtualpos_sandbox_base_url": "https://api.virtualpos-sandbox.com",
    "virtualpos_sandbox_api_key": "sbx-vk",
    "virtualpos_sandbox_secret_key": "sbx-vs",
    "payku_sandbox_base_url": "https://des.payku.cl",
    "payku_sandbox_public_token": "sbx-pk-public",
    "payku_sandbox_private_token": "sbx-pk-private",
    "payku_sandbox_writes_enabled": True,
}
ARMED = {ENV_ARMED: "1"}
CLIENT_OK = {"name": "TEST-socio", "email": "socio@example.test", "phone": "900000000"}


def sandbox(**kw) -> Settings:
    return Settings(_env_file=None, **{**PROD, **SBX, "app_env": "sandbox", **kw})


def production(**kw) -> Settings:
    return Settings(_env_file=None, **{**PROD, "app_env": "production", **kw})


def guard(
    method: str,
    path: str,
    body=None,
    s: Settings | None = None,
    env: dict | None = None,
    state: WriteGuardState | None = None,
) -> WriteGuardState:
    state = state or WriteGuardState(env=dict(ARMED if env is None else env))
    assert_sandbox_write_allowed(method, path, body, s or sandbox(), state)
    return state


def code_of(method: str, path: str, body=None, **kw) -> str:
    with pytest.raises(PaykuWriteBlockedError) as e:
        guard(method, path, body, **kw)
    return e.value.code


# ------------------------------------------------------------- funcion pura ----


def test_settings_sandbox_maps_payku_writes_flag() -> None:
    assert sandbox().payku_writes_enabled is True
    assert sandbox(payku_sandbox_writes_enabled=False).payku_writes_enabled is False


def test_writes_disabled_blocks_even_if_armed() -> None:
    assert (
        code_of(
            "POST",
            "/api/suclient",
            CLIENT_OK,
            s=sandbox(payku_sandbox_writes_enabled=False),
        )
        == "WRITES_DISABLED"
    )


def test_not_armed_blocks() -> None:
    assert code_of("POST", "/api/suclient", CLIENT_OK, env={}) == "NOT_ARMED"
    assert (
        code_of("POST", "/api/suclient", CLIENT_OK, env={ENV_ARMED: "true"})
        == "NOT_ARMED"
    )


def test_unknown_host_blocks() -> None:
    assert (
        code_of(
            "POST",
            "/api/suclient",
            CLIENT_OK,
            s=sandbox(payku_sandbox_base_url="https://payku.other.test"),
        )
        == "HOST_NOT_ALLOWED"
    )
    assert (
        code_of(
            "POST",
            "/api/suclient",
            CLIENT_OK,
            s=sandbox(payku_sandbox_base_url="http://des.payku.cl"),
        )
        == "HOST_NOT_ALLOWED"
    )


def test_production_settings_passed_to_guard_fail_closed() -> None:
    assert (
        code_of(
            "POST", "/api/suclient", CLIENT_OK, s=production(payku_writes_enabled=True)
        )
        == "ENV_NOT_SANDBOX"
    )


@pytest.mark.parametrize(
    "path",
    ["/api/suclient/cl_real", "/api/sususcription/su_real"],
)
def test_armed_but_id_outside_allowlist_blocks(path: str) -> None:
    assert code_of("DELETE", path) == "ID_NOT_ALLOWED"
    guard("DELETE", path, env={**ARMED, ENV_ALLOWED_IDS: "otro, cl_real ,su_real"})


def test_put_requires_allowlisted_id_and_synthetic_fields() -> None:
    assert code_of("PUT", "/api/suclient/cl_real", {"phone": "1"}) == "ID_NOT_ALLOWED"
    env = {**ARMED, ENV_ALLOWED_IDS: "cl_real"}
    guard("PUT", "/api/suclient/cl_real", {"phone": "1"}, env=env)
    assert (
        code_of("PUT", "/api/suclient/cl_real", {"email": "persona@gmail.com"}, env=env)
        == "EMAIL_DOMAIN_REQUIRED"
    )
    assert (
        code_of("PUT", "/api/suclient/cl_real", {"name": "Persona"}, env=env)
        == "PREFIX_REQUIRED"
    )


def test_create_client_requires_synthetic_data() -> None:
    guard("POST", "/api/suclient", CLIENT_OK)
    assert (
        code_of("POST", "/api/suclient", {**CLIENT_OK, "name": "Persona"})
        == "PREFIX_REQUIRED"
    )
    assert (
        code_of("POST", "/api/suclient", {**CLIENT_OK, "email": "x@example.test.cl"})
        == "EMAIL_DOMAIN_REQUIRED"
    )
    assert code_of("POST", "/api/suclient", {"name": "TEST-a"}) == "FIELD_MISSING"
    assert code_of("POST", "/api/suplan", {"name": "Plan real"}) == "PREFIX_REQUIRED"
    guard("POST", "/api/suplan", {"name": "TEST-plan"})


def test_create_subscription_references_must_be_allowlisted() -> None:
    body = {"client": "cl_real", "plan": "pl_real"}
    assert code_of("POST", "/api/sususcription", body) == "ID_NOT_ALLOWED"
    assert (
        code_of(
            "POST",
            "/api/sususcription",
            body,
            env={**ARMED, ENV_ALLOWED_IDS: "cl_real"},
        )
        == "ID_NOT_ALLOWED"
    )
    guard(
        "POST",
        "/api/sususcription",
        body,
        env={**ARMED, ENV_ALLOWED_IDS: "cl_real,pl_real"},
    )


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/transaction"),
        ("POST", "/api/sutransaction"),
        ("POST", "/api/suinscriptionscards"),
        ("POST", "/api/suscriptionsdeletecards"),
        ("POST", "/api/wallet/withdraw"),
        ("POST", "/api/wallet/payout"),
        ("POST", "/api/nullification"),
        ("POST", "/api/mall"),
        ("POST", "/api/escrow"),
        ("POST", "/api/conciliation"),
        ("POST", "/api/maclient"),
        ("DELETE", "/api/maclient/TEST-1"),
        ("PUT", "/api/sususcription/TEST-1"),
    ],
)
def test_unlisted_endpoints_blocked(method: str, path: str) -> None:
    assert code_of(method, path, {"name": "TEST-x"}) == "ENDPOINT_NOT_ALLOWED"


def test_path_and_body_shape() -> None:
    assert code_of("DELETE", "/api/suclient/../x") == "PATH_INVALID"
    assert code_of("DELETE", "/api/suclient/TEST-1?x=1") == "PATH_INVALID"
    assert code_of("POST", "/api/suclient", [CLIENT_OK]) == "BULK_BLOCKED"
    assert code_of("POST", "/api/suclient", "x") == "BODY_INVALID"


def test_cap_reached_blocks() -> None:
    state = WriteGuardState(env={**ARMED, ENV_MAX_WRITES: "2"})
    guard("DELETE", "/api/suclient/TEST-1", state=state)
    guard("DELETE", "/api/suclient/TEST-2", state=state)
    with pytest.raises(PaykuWriteBlockedError) as e:
        guard("DELETE", "/api/suclient/TEST-3", state=state)
    assert e.value.code == "CAP_REACHED"
    assert state.writes == 2


def test_blocked_attempts_do_not_consume_cap() -> None:
    state = WriteGuardState(env={**ARMED, ENV_MAX_WRITES: "1"})
    with pytest.raises(PaykuWriteBlockedError):
        guard("DELETE", "/api/suclient/cl_real", state=state)
    assert state.writes == 0
    guard("DELETE", "/api/suclient/TEST-1", state=state)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("", 25), ("x", 25), ("-1", 25), ("0", 0), ("9999", 500), ("3", 3)],
)
def test_max_writes_parsing(raw: str, expected: int) -> None:
    assert write_guard._max_writes({ENV_MAX_WRITES: raw}) == expected


def test_armed_key_is_process_only_not_from_dotenv() -> None:
    # Igual que Toku: Settings no expone las variables de proceso; el estado por defecto lee os.environ.
    assert not hasattr(sandbox(), "payku_sandbox_allow_writes_armed")
    assert WriteGuardState().environ() is write_guard.os.environ


def test_messages_do_not_leak_values() -> None:
    with pytest.raises(PaykuWriteBlockedError) as e:
        guard("POST", "/api/suclient", {**CLIENT_OK, "email": "persona.real@gmail.com"})
    assert "persona.real" not in str(e.value)
    assert "sbx-pk" not in str(e.value)


# ------------------------------------------------- cliente con transporte falso ----


class FakeHttp:
    """Sustituye httpx.AsyncClient: registra llamadas; con `forbid=True` falla el test si se usa la red."""

    forbid = False
    calls: ClassVar[list[tuple[str, str]]] = []

    def __init__(self, **_: object) -> None:
        pass

    async def aclose(self) -> None:
        return None

    async def _do(self, method: str, path: str, **_: object) -> httpx.Response:
        if FakeHttp.forbid:
            raise AssertionError(
                f"Se intento tocar la red: {method} (no deberia ocurrir)"
            )
        FakeHttp.calls.append((method, path))
        return httpx.Response(
            200,
            json={"status": "success"},
            request=httpx.Request(method, "https://fake.invalid" + path),
        )

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
    FakeHttp.forbid = False
    FakeHttp.calls = []
    monkeypatch.setattr(payku_client.httpx, "AsyncClient", FakeHttp)
    monkeypatch.setattr(payku_client, "PROCESS_STATE", WriteGuardState(env=dict(ARMED)))
    yield FakeHttp
    FakeHttp.forbid = False


def run_client(coro_fn):
    async def go():
        async with payku_client.PaykuClient() as c:
            return await coro_fn(c)

    return asyncio.run(go())


def test_client_not_armed_never_touches_network(monkeypatch, fake_http) -> None:
    monkeypatch.setattr(payku_client, "settings", sandbox())
    monkeypatch.setattr(payku_client, "PROCESS_STATE", WriteGuardState(env={}))
    fake_http.forbid = True
    with pytest.raises(PaykuWriteBlockedError) as e:
        run_client(lambda c: c.create_client(dict(CLIENT_OK)))
    assert e.value.code == "NOT_ARMED"


def test_client_id_outside_allowlist_never_touches_network(
    monkeypatch, fake_http
) -> None:
    monkeypatch.setattr(payku_client, "settings", sandbox())
    fake_http.forbid = True
    with pytest.raises(PaykuWriteBlockedError) as e:
        run_client(lambda c: c.delete_subscription("su_real"))
    assert e.value.code == "ID_NOT_ALLOWED"


def test_client_cap_reached_never_touches_network(monkeypatch, fake_http) -> None:
    monkeypatch.setattr(payku_client, "settings", sandbox())
    monkeypatch.setattr(
        payku_client,
        "PROCESS_STATE",
        WriteGuardState(env={**ARMED, ENV_MAX_WRITES: "1"}),
    )
    run_client(lambda c: c.delete_client("TEST-1"))
    fake_http.forbid = True
    with pytest.raises(PaykuWriteBlockedError) as e:
        run_client(lambda c: c.delete_client("TEST-2"))
    assert e.value.code == "CAP_REACHED"


def test_client_all_guards_ok_calls_fake_transport(monkeypatch, fake_http) -> None:
    monkeypatch.setattr(payku_client, "settings", sandbox())
    monkeypatch.setattr(
        payku_client,
        "PROCESS_STATE",
        WriteGuardState(env={**ARMED, ENV_ALLOWED_IDS: "cl_real"}),
    )
    assert run_client(lambda c: c.create_client(dict(CLIENT_OK))) == {
        "status": "success"
    }
    run_client(lambda c: c.update_client("cl_real", {"phone": "900000001"}))
    run_client(lambda c: c.delete_client("cl_real"))
    assert fake_http.calls == [
        ("POST", "/api/suclient"),
        ("PUT", "/api/suclient/cl_real"),
        ("DELETE", "/api/suclient/cl_real"),
    ]


def test_client_reads_are_not_guarded(monkeypatch, fake_http) -> None:
    monkeypatch.setattr(
        payku_client, "settings", sandbox(payku_sandbox_writes_enabled=False)
    )
    monkeypatch.setattr(payku_client, "PROCESS_STATE", WriteGuardState(env={}))
    assert run_client(lambda c: c.get_client("cl_real")) == {"status": "success"}


def test_production_client_unaffected_by_guard(monkeypatch, fake_http) -> None:
    """Produccion: sin variables de proceso, sin allowlist y con cupo 0, el cliente no consulta la guarda."""
    monkeypatch.setattr(payku_client, "settings", production())
    monkeypatch.setattr(
        payku_client, "PROCESS_STATE", WriteGuardState(env={ENV_MAX_WRITES: "0"})
    )

    def explode(*_a, **_k):
        raise AssertionError("la guarda de sandbox no debe invocarse en produccion")

    monkeypatch.setattr(payku_client, "assert_sandbox_write_allowed", explode)
    run_client(lambda c: c.delete_client("cl_real"))
    run_client(
        lambda c: c.create_client({"name": "Persona", "email": "x@y.cl", "phone": "1"})
    )
    assert fake_http.calls == [
        ("DELETE", "/api/suclient/cl_real"),
        ("POST", "/api/suclient"),
    ]


def test_production_service_flag_unchanged() -> None:
    # La bandera de produccion sigue apagada por defecto y no la tocan las variables de sandbox.
    assert production().payku_writes_enabled is False
    assert production(payku_sandbox_writes_enabled=True).payku_writes_enabled is False


# ---------------------------------------- write_payku (BD de pruebas, con rollback) ----


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


def test_write_payku_blocked_registers_write_run_blocked(
    monkeypatch, db_session, fake_http
) -> None:
    s = sandbox()
    monkeypatch.setattr(payku_client, "settings", s)
    monkeypatch.setattr(write_payku, "settings", s)
    db_session.add(
        Client(source="payku", external_id="cl_guard_1", first_name="X", raw_payload={})
    )
    db_session.flush()
    fake_http.forbid = True
    with pytest.raises(PaykuWriteBlockedError):
        asyncio.run(write_payku.delete_client(db_session, "cl_guard_1"))
    run = db_session.scalars(
        select(WriteRun).where(WriteRun.external_id == "cl_guard_1")
    ).one()
    assert run.status == "blocked"
    assert "ID_NOT_ALLOWED" in (run.error_message or "")
    assert "sbx-pk" not in (run.error_message or "")


# ---------------------------------------------------------------- rutas ----


@pytest.mark.parametrize(
    ("fn_name", "args"),
    [
        ("update_payku_client", ("c1", writes_routes.PaykuClientUpdate(phone="1"))),
        ("delete_payku_client", ("c1",)),
        ("delete_payku_subscription", ("s1",)),
    ],
)
def test_routes_map_guard_block_to_403(monkeypatch, fn_name: str, args: tuple) -> None:
    async def blocked(*_a, **_k):
        raise PaykuWriteBlockedError("NOT_ARMED", "falta el interruptor de proceso")

    for name in (
        "payku_update_client",
        "payku_delete_client",
        "payku_delete_subscription",
    ):
        monkeypatch.setattr(writes_routes, name, blocked)
    with pytest.raises(HTTPException) as e:
        actor = SimpleNamespace(id=uuid.uuid4())
        asyncio.run(getattr(writes_routes, fn_name)(*args, None, actor))
    assert e.value.status_code == 403
    assert e.value.detail["code"] == "payku_write_blocked"
    assert "NOT_ARMED" in e.value.detail["message"]
    assert "falta el interruptor" not in e.value.detail["message"]
