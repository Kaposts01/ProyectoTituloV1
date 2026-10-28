"""Guardas duras de escritura de Toku (sandbox/qa). Sin red: transporte httpx falso."""

import asyncio
import logging
from typing import ClassVar

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes import writes as writes_routes
from app.core.config import Settings
from app.db.session import engine
from app.integrations.toku import client as toku_client
from app.integrations.toku import write_guard
from app.integrations.toku.write_guard import (
    ENV_ALLOWED_IDS,
    ENV_ARMED,
    ENV_MAX_WRITES,
    TokuWriteBlockedError,
    WriteGuardState,
    assert_sandbox_write_allowed,
)
from app.models.crm import Client, Subscription
from app.models.write_run import WriteRun
from app.services import write_toku

DB = "postgresql+psycopg://u:p@localhost/crm"
SDB = "postgresql+psycopg://u:p@localhost/crm_sandbox"
PROD_TK = "prod-tk-secret-value"
SBX_TK = "sbx-tk-secret-value"
PROD = {
    "database_url": DB,
    "virtualpos_base_url": "https://api.virtualpos.cl",
    "virtualpos_api_key": "prod-vk",
    "virtualpos_secret_key": "prod-vs",
    "toku_base_url": "https://api.trytoku.com",
    "toku_api_key": PROD_TK,
    "toku_account_key": "prod-ta",
    "toku_writes_enabled": True,
}
SBX = {
    "sandbox_database_url": SDB,
    "virtualpos_sandbox_base_url": "https://api.virtualpos-sandbox.com",
    "virtualpos_sandbox_api_key": "sbx-vk",
    "virtualpos_sandbox_secret_key": "sbx-vs",
    "toku_base_sandbox_url": "https://api.trytoku.com",
    "toku_sandbox_api_key": SBX_TK,
    "toku_sandbox_account_key": "sbx-ta",
    "toku_sandbox_writes_enabled": True,
}


def sandbox(**kw) -> Settings:
    return Settings(_env_file=None, **{**PROD, **SBX, "app_env": "sandbox", **kw})


def production() -> Settings:
    return Settings(_env_file=None, **PROD)


ARMED = {ENV_ARMED: "1"}


def state(**env: str) -> WriteGuardState:
    return WriteGuardState(env={**ARMED, **env})


def blocked_code(method, path, body, settings=None, st=None) -> str:
    with pytest.raises(TokuWriteBlockedError) as e:
        assert_sandbox_write_allowed(method, path, body, settings or sandbox(), st or state())
    return e.value.code


def ok(method, path, body, settings=None, st=None) -> None:
    assert_sandbox_write_allowed(method, path, body, settings or sandbox(), st or state())


# ------------------------------------------------------------------ config ----


def test_config_rejects_other_toku_host_without_value() -> None:
    with pytest.raises(ValidationError, match="TOKU_BASE_SANDBOX_URL") as e:
        sandbox(toku_base_sandbox_url="https://evil.example.com")
    assert "evil.example.com" not in str(e.value)


@pytest.mark.parametrize(
    "url",
    ["http://api.trytoku.com", "https://api.trytoku.com@evil.example.com", "https://api.trytoku.com.evil.io",
     "https://user:pw@api.trytoku.com", "https://api.trytoku.com:8443"],
)
def test_config_rejects_tricky_toku_urls(url: str) -> None:
    with pytest.raises(ValidationError, match="TOKU_BASE_SANDBOX_URL"):
        sandbox(toku_base_sandbox_url=url)


def test_config_accepts_exact_toku_host_and_warns(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        s = sandbox()
    assert s.toku_base_url == "https://api.trytoku.com"
    assert any("comparte host con produccion" in r.getMessage() for r in caplog.records)
    assert SBX_TK not in caplog.text


def test_config_equal_toku_keys_still_rejected() -> None:
    with pytest.raises(ValidationError, match="TOKU_SANDBOX_API_KEY") as e:
        sandbox(toku_sandbox_api_key=PROD_TK)
    assert PROD_TK not in str(e.value)


def test_config_empty_toku_url_still_allowed() -> None:
    s = sandbox(toku_base_sandbox_url="")
    assert not s.channel_enabled("toku")


# ------------------------------------------------------------- pure guard ----


def test_writes_disabled_blocks() -> None:
    assert blocked_code("POST", "/customers", {"external_id": "TEST-1"}, sandbox(toku_sandbox_writes_enabled=False)) == "WRITES_DISABLED"


def test_not_armed_blocks() -> None:
    st = WriteGuardState(env={})
    assert blocked_code("POST", "/customers", {"external_id": "TEST-1"}, st=st) == "NOT_ARMED"
    st = WriteGuardState(env={ENV_ARMED: "true"})
    assert blocked_code("POST", "/customers", {"external_id": "TEST-1"}, st=st) == "NOT_ARMED"


def test_contract_writes_does_not_arm_toku() -> None:
    st = WriteGuardState(env={"CONTRACT_WRITES": "1"})
    assert blocked_code("POST", "/customers", {"external_id": "TEST-1"}, st=st) == "NOT_ARMED"


def test_host_defense_in_depth() -> None:
    s = sandbox()
    s.toku_base_url = "https://otro.example.com"
    assert blocked_code("POST", "/customers", {"external_id": "TEST-1"}, s) == "HOST_NOT_ALLOWED"


def test_prefix_required_on_post_business_keys() -> None:
    assert blocked_code("POST", "/customers", {"external_id": "SOCIO-1"}) == "PREFIX_REQUIRED"
    assert blocked_code("POST", "/customers", {"name": "x"}) == "FIELD_MISSING"
    assert blocked_code("POST", "/subscriptions", {"product_id": "SOCIO-1", "customer": "TEST-c"}) == "PREFIX_REQUIRED"
    assert blocked_code("POST", "/payment-methods", {"external_id": "pm-1"}) == "PREFIX_REQUIRED"
    ok("POST", "/customers", {"external_id": "TEST-1", "mail": "interno@example.com"})
    ok("POST", "/subscriptions", {"product_id": "TEST-SUB-1", "customer": "TEST-1"})
    ok("POST", "/payment-methods", {"external_id": "TEST-pm-1"})


def test_subscription_customer_must_be_test_or_allowlisted() -> None:
    body = {"product_id": "TEST-SUB-1", "customer": "cus_real"}
    assert blocked_code("POST", "/subscriptions", body) == "ID_NOT_ALLOWED"
    ok("POST", "/subscriptions", body, st=state(**{ENV_ALLOWED_IDS: "cus_real"}))
    assert blocked_code("POST", "/subscriptions", {"product_id": "TEST-SUB-1"}) == "FIELD_MISSING"


def test_invoice_requires_prefix_and_disable_automatic_payment() -> None:
    base = {"product_id": "TEST-SUB-1", "invoice_external_id": "TEST-INV-1", "disable_automatic_payment": True}
    ok("POST", "/invoices", base)
    assert blocked_code("POST", "/invoices", {**base, "disable_automatic_payment": False}) == "FLAG_REQUIRED"
    no_flag = {k: v for k, v in base.items() if k != "disable_automatic_payment"}
    assert blocked_code("POST", "/invoices", no_flag) == "FLAG_REQUIRED"
    assert blocked_code("POST", "/invoices", {**base, "invoice_external_id": "CUOTA-1"}) == "PREFIX_REQUIRED"
    assert blocked_code("POST", "/invoices", {k: v for k, v in base.items() if k != "invoice_external_id"}) == "FIELD_MISSING"
    assert blocked_code("POST", "/invoices", {**base, "customer": "cus_real"}) == "ID_NOT_ALLOWED"


def test_checkout_requires_prefix_flag_and_test_refs() -> None:
    body = {
        "mode": "ENROLLMENT",
        "unique_external_id": "TEST-ALTA-1",
        "skip_message_trigger": True,
        "billing_data": {"id_customer": "TEST-1", "ids_subscription": ["TEST-SUB-1"]},
    }
    ok("POST", "/cl/checkout-sessions", body)
    assert blocked_code("POST", "/cl/checkout-sessions", {**body, "skip_message_trigger": False}) == "FLAG_REQUIRED"
    assert blocked_code("POST", "/cl/checkout-sessions", {**body, "unique_external_id": "ALTA-1"}) == "PREFIX_REQUIRED"
    bad = {**body, "billing_data": {"id_customer": "TEST-1", "ids_subscription": ["TEST-SUB-1", "sub_real"]}}
    assert blocked_code("POST", "/cl/checkout-sessions", bad) == "ID_NOT_ALLOWED"
    no_refs = {**body, "billing_data": {}}
    assert blocked_code("POST", "/cl/checkout-sessions", no_refs) == "FIELD_MISSING"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PUT", "/customers/{}"),
        ("DELETE", "/customers/{}"),
        ("PUT", "/invoices/{}"),
        ("DELETE", "/invoices/{}"),
        ("DELETE", "/subscriptions/{}"),
        ("PUT", "/payment-methods/{}"),
        ("DELETE", "/payment-methods/{}"),
        ("POST", "/subscriptions/{}/status"),
        ("POST", "/invoices/{}/void"),
    ],
)
def test_id_rule_for_put_delete_void_status(method: str, path: str) -> None:
    body = {"status": "PAUSED"} if method in ("PUT", "POST") else None
    assert blocked_code(method, path.format("sub_real"), body) == "ID_NOT_ALLOWED"
    ok(method, path.format("TEST-1"), body)
    ok(method, path.format("sub_real"), body, st=state(**{ENV_ALLOWED_IDS: " other , sub_real "}))
    # La allowlist vacia (por defecto) no permite nada; coincidencia exacta, no por prefijo.
    assert blocked_code(method, path.format("sub_real2"), body, st=state(**{ENV_ALLOWED_IDS: "sub_real"})) == "ID_NOT_ALLOWED"


def test_write_cap_per_process() -> None:
    st = state(**{ENV_MAX_WRITES: "2"})
    ok("DELETE", "/customers/TEST-1", None, st=st)
    ok("DELETE", "/customers/TEST-2", None, st=st)
    assert blocked_code("DELETE", "/customers/TEST-3", None, st=st) == "CAP_REACHED"
    assert st.writes == 2  # el bloqueo no consume cupo


def test_blocked_writes_do_not_consume_cap_and_default_is_25() -> None:
    st = state()
    for _ in range(5):
        blocked_code("DELETE", "/customers/real", None, st=st)
    assert st.writes == 0
    for i in range(25):
        ok("DELETE", f"/customers/TEST-{i}", None, st=st)
    assert blocked_code("DELETE", "/customers/TEST-x", None, st=st) == "CAP_REACHED"


def test_cap_zero_or_invalid_value() -> None:
    assert blocked_code("DELETE", "/customers/TEST-1", None, st=state(**{ENV_MAX_WRITES: "0"})) == "CAP_REACHED"
    st = state(**{ENV_MAX_WRITES: "abc"})  # invalido -> default 25
    ok("DELETE", "/customers/TEST-1", None, st=st)


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/payment-methods/batch", {"external_id": "TEST-1"}),
        ("/payment-methods/subscriptions/bulk", {"external_id": "TEST-1"}),
        ("/customers", [{"external_id": "TEST-1"}]),
        ("/subscriptions/associate/bulk", {}),
    ],
)
def test_bulk_and_batch_blocked(path: str, body) -> None:
    assert blocked_code("POST", path, body) == "BULK_BLOCKED"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/organization/payments"),
        ("POST", "/subscriptions/associate/payment-method"),
        ("DELETE", "/customers"),
        ("PATCH", "/customers/TEST-1"),
        ("POST", "/customers/TEST-1"),
        ("PUT", "/customers/TEST-1/extra"),
    ],
)
def test_unknown_endpoint_blocked(method: str, path: str) -> None:
    assert blocked_code(method, path, {"external_id": "TEST-1"}) == "ENDPOINT_NOT_ALLOWED"


@pytest.mark.parametrize("path", ["/customers/TEST-1/../x", "/customers/TEST-1?x=1", "/customers/TEST-%2e", "//customers/TEST-1"])
def test_suspicious_paths_blocked(path: str) -> None:
    assert blocked_code("DELETE", path, None) == "PATH_INVALID"


def test_error_messages_have_no_keys_or_pii() -> None:
    pii = "persona.real@example.org"
    secrets = (PROD_TK, SBX_TK, "sbx-ta", pii, "cus_real_9999")
    cases = [
        ("POST", "/customers", {"external_id": "SOCIO-77", "mail": pii}),
        ("DELETE", "/customers/cus_real_9999", None),
        ("POST", "/subscriptions", {"product_id": "TEST-1", "customer": "cus_real_9999"}),
        ("PUT", "/customers/cus_real_9999", {"mail": pii}),
    ]
    for method, path, body in cases:
        with pytest.raises(TokuWriteBlockedError) as e:
            assert_sandbox_write_allowed(method, path, body, sandbox(), state())
        text = f"{e.value} {e.value.code} {e.value.message}"
        assert not any(s in text for s in secrets)
        assert "SOCIO-77" not in text


# ------------------------------------------------- cliente con transporte falso ----


class FakeHttp:
    """Sustituye httpx.AsyncClient: registra llamadas; con `forbid=True` falla el test si se usa la red."""

    forbid = False
    calls: ClassVar[list[tuple[str, str]]] = []

    def __init__(self, **_: object) -> None:
        pass

    async def aclose(self) -> None:
        return None

    async def _do(self, method: str, path: str, **kw: object) -> httpx.Response:
        if FakeHttp.forbid:
            raise AssertionError(f"Se intento tocar la red: {method} (no deberia ocurrir)")
        FakeHttp.calls.append((method, path))
        payload = {"invoices": []} if path.startswith("/invoices") and method == "GET" else {"id": "x"}
        return httpx.Response(200, json=payload, request=httpx.Request(method, "https://fake.invalid" + path))

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
    monkeypatch.setattr(toku_client.httpx, "AsyncClient", FakeHttp)
    monkeypatch.setattr(toku_client, "PROCESS_STATE", WriteGuardState(env=dict(ARMED)))
    yield FakeHttp
    FakeHttp.forbid = False


def use_settings(monkeypatch: pytest.MonkeyPatch, s: Settings) -> None:
    monkeypatch.setattr(toku_client, "settings", s)
    monkeypatch.setattr(write_toku, "settings", s)


def run_client(coro_fn):
    async def go():
        async with toku_client.TokuClient() as c:
            return await coro_fn(c)

    return asyncio.run(go())


def test_client_sandbox_writes_disabled_never_touches_network(monkeypatch, fake_http) -> None:
    use_settings(monkeypatch, sandbox(toku_sandbox_writes_enabled=False))
    fake_http.forbid = True
    with pytest.raises(TokuWriteBlockedError) as e:
        run_client(lambda c: c.create_customer({"external_id": "TEST-1"}))
    assert e.value.code == "WRITES_DISABLED"


def test_client_sandbox_not_armed_never_touches_network(monkeypatch, fake_http) -> None:
    use_settings(monkeypatch, sandbox())
    monkeypatch.setattr(toku_client, "PROCESS_STATE", WriteGuardState(env={}))
    fake_http.forbid = True
    with pytest.raises(TokuWriteBlockedError) as e:
        run_client(lambda c: c.create_customer({"external_id": "TEST-1"}))
    assert e.value.code == "NOT_ARMED"


def test_client_sandbox_without_test_prefix_blocked_and_with_prefix_allowed(monkeypatch, fake_http) -> None:
    use_settings(monkeypatch, sandbox())
    fake_http.forbid = True
    with pytest.raises(TokuWriteBlockedError):
        run_client(lambda c: c.create_customer({"external_id": "SOCIO-1"}))
    fake_http.forbid = False
    assert run_client(lambda c: c.create_customer({"external_id": "TEST-1"})) == {"id": "x"}
    assert fake_http.calls == [("POST", "/customers")]


def test_client_sandbox_put_delete_allowlist(monkeypatch, fake_http) -> None:
    use_settings(monkeypatch, sandbox())
    fake_http.forbid = True
    with pytest.raises(TokuWriteBlockedError):
        run_client(lambda c: c.delete_customer("cus_real"))
    with pytest.raises(TokuWriteBlockedError):
        run_client(lambda c: c.update_customer("cus_real", {"name": "x"}))
    fake_http.forbid = False
    monkeypatch.setattr(toku_client, "PROCESS_STATE", WriteGuardState(env={**ARMED, ENV_ALLOWED_IDS: "cus_real"}))
    run_client(lambda c: c.delete_customer("cus_real"))
    run_client(lambda c: c.update_customer("TEST-2", {"name": "x"}))
    assert fake_http.calls == [("DELETE", "/customers/cus_real"), ("PUT", "/customers/TEST-2")]


def test_client_sandbox_bulk_and_unknown_blocked(monkeypatch, fake_http) -> None:
    use_settings(monkeypatch, sandbox())
    fake_http.forbid = True
    with pytest.raises(TokuWriteBlockedError) as e1:
        run_client(lambda c: c.batch_clabe_inscription({"external_id": "TEST-1"}))
    with pytest.raises(TokuWriteBlockedError) as e2:
        run_client(lambda c: c.bulk_associate_subscriptions({}))
    with pytest.raises(TokuWriteBlockedError) as e3:
        run_client(lambda c: c.associate_payment_method_to_subscription({}))
    assert (e1.value.code, e2.value.code, e3.value.code) == ("BULK_BLOCKED", "BULK_BLOCKED", "ENDPOINT_NOT_ALLOWED")


def test_client_sandbox_cap(monkeypatch, fake_http) -> None:
    use_settings(monkeypatch, sandbox())
    monkeypatch.setattr(toku_client, "PROCESS_STATE", WriteGuardState(env={**ARMED, ENV_MAX_WRITES: "1"}))
    run_client(lambda c: c.delete_customer("TEST-1"))
    fake_http.forbid = True
    with pytest.raises(TokuWriteBlockedError) as e:
        run_client(lambda c: c.delete_customer("TEST-2"))
    assert e.value.code == "CAP_REACHED"


def test_client_sandbox_reads_are_not_guarded(monkeypatch, fake_http) -> None:
    use_settings(monkeypatch, sandbox(toku_sandbox_writes_enabled=False))
    monkeypatch.setattr(toku_client, "PROCESS_STATE", WriteGuardState(env={}))
    assert run_client(lambda c: c.get_customer("cus_real")) == {"id": "x"}


def test_production_writes_unchanged_no_guard(monkeypatch, fake_http) -> None:
    """Regresion: en produccion el cliente escribe como antes (sin TEST-, sin interruptor, sin tope)."""
    use_settings(monkeypatch, production())
    monkeypatch.setattr(toku_client, "PROCESS_STATE", WriteGuardState(env={ENV_MAX_WRITES: "1"}))

    def boom(*_a, **_k):
        raise AssertionError("la guarda no debe invocarse en produccion")

    monkeypatch.setattr(toku_client, "assert_sandbox_write_allowed", boom)

    async def many(c):
        for i in range(5):
            await c.create_customer({"external_id": f"SOCIO-{i}"})
        await c.update_customer("cus_real", {"name": "x"})
        await c.delete_invoice("in_real")
        await c.void_invoice("in_real", {"delete_invoice": False})
        await c.change_subscription_status("sub_real", {"status": "PAUSED"})
        await c.batch_clabe_inscription({})

    run_client(many)
    assert len(fake_http.calls) == 10


# ---------------------------------------- write_toku + rutas (BD de pruebas) ----


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


def test_write_toku_blocked_registers_write_run_blocked(monkeypatch, db_session, fake_http) -> None:
    use_settings(monkeypatch, sandbox())
    db_session.add(Client(source="toku", external_id="cus_guard_1", first_name="X", raw_payload={}))
    db_session.flush()
    fake_http.forbid = True
    with pytest.raises(TokuWriteBlockedError):
        asyncio.run(write_toku.delete_customer(db_session, "cus_guard_1"))
    run = db_session.scalars(select(WriteRun).where(WriteRun.external_id == "cus_guard_1")).one()
    assert run.status == "blocked"
    assert "ID_NOT_ALLOWED" in (run.error_message or "")
    assert SBX_TK not in (run.error_message or "")


def _sub(ext: str) -> Subscription:
    return Subscription(source="toku", external_id=ext, raw_payload={})


def test_delete_subscription_fails_closed_when_unpaid_listing_fails_in_sandbox(monkeypatch, db_session, fake_http) -> None:
    use_settings(monkeypatch, sandbox())
    monkeypatch.setattr(toku_client, "PROCESS_STATE", WriteGuardState(env=dict(ARMED)))
    db_session.add(_sub("TEST-SUB-FC"))
    db_session.flush()

    async def failing_get(self, path, params=None):
        raise RuntimeError("listado caido")

    monkeypatch.setattr(toku_client.TokuClient, "_get", failing_get)
    with pytest.raises(RuntimeError):
        asyncio.run(write_toku.delete_subscription(db_session, "TEST-SUB-FC"))
    assert ("DELETE", "/subscriptions/TEST-SUB-FC") not in fake_http.calls
    run = db_session.scalars(select(WriteRun).where(WriteRun.external_id == "TEST-SUB-FC")).one()
    assert run.status == "failed"


def test_delete_subscription_keeps_warning_behavior_in_production(monkeypatch, db_session, fake_http) -> None:
    use_settings(monkeypatch, production())
    db_session.add(_sub("sub_prod_fc"))
    db_session.flush()

    async def failing_get(self, path, params=None):
        raise RuntimeError("listado caido")

    monkeypatch.setattr(toku_client.TokuClient, "_get", failing_get)
    sub = asyncio.run(write_toku.delete_subscription(db_session, "sub_prod_fc"))
    assert sub.status == "deleted"
    assert ("DELETE", "/subscriptions/sub_prod_fc") in fake_http.calls


@pytest.mark.parametrize(
    ("fn_name", "args"),
    [
        ("update_toku_customer", ("c1", writes_routes.TokuCustomerUpdate(name="n"))),
        ("delete_toku_customer", ("c1",)),
        ("change_toku_subscription_status", ("s1", writes_routes.TokuSubscriptionStatusChange(status="PAUSED"))),
        ("delete_toku_subscription", ("s1",)),
        ("update_toku_invoice", ("i1", writes_routes.TokuInvoiceUpdate(amount=5))),
        ("delete_toku_invoice", ("i1",)),
    ],
)
def test_routes_map_guard_block_to_403(monkeypatch, fn_name: str, args: tuple) -> None:
    async def blocked(*_a, **_k):
        raise TokuWriteBlockedError("NOT_ARMED", "falta el interruptor de proceso")

    for name in ("update_customer", "delete_customer", "change_subscription_status", "toku_delete_subscription",
                 "toku_update_invoice", "toku_delete_invoice"):
        monkeypatch.setattr(writes_routes, name, blocked)
    with pytest.raises(HTTPException) as e:
        asyncio.run(getattr(writes_routes, fn_name)(*args, None))
    assert e.value.status_code == 403
    assert "NOT_ARMED" in e.value.detail


def test_module_exports_and_defaults() -> None:
    assert write_guard.DEFAULT_MAX_WRITES == 25
    assert write_guard.TEST_PREFIX == "TEST-"
