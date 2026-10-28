"""TANDA 3: endurecimiento de las guardas de escritura de Toku (revision independiente).

Sin red: transporte httpx falso (reutiliza los fixtures de test_toku_write_guard).
"""

import asyncio
import logging
import threading

import pytest
import test_toku_write_guard as base
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app import main as main_module
from app.api.v1.routes import writes as writes_routes
from app.core import config as config_module
from app.core.config import LEGACY_PRODUCTION_ALIASES, Settings
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
from app.models.crm import Client
from app.models.write_run import WriteRun
from app.services import write_toku

fake_http = base.fake_http
db_session = base.db_session
PROD = base.PROD
SBX = base.SBX
PROD_TK = base.PROD_TK
ARMED = base.ARMED
sandbox = base.sandbox
production = base.production
state = base.state
blocked_code = base.blocked_code
ok = base.ok
use_settings = base.use_settings
run_client = base.run_client
_sub = base._sub


def dev_settings(env: str = "development", **kw) -> Settings:
    return Settings(_env_file=None, **{**PROD, "app_env": env, **kw})


# ---- (1) orden de guardas en delete_subscription ----------------------------------


def _inv(*ids: str) -> list[dict]:
    return [{"id": i} for i in ids]


def _non_get(fake) -> list[tuple[str, str]]:
    return [c for c in fake.calls if c[0] != "GET"]


def test_delete_subscription_aborts_before_any_void_when_subscription_not_allowed(
    monkeypatch, db_session, fake_http
) -> None:
    """Caso del revisor: invoices permitidas, suscripcion no -> no se anula NINGUNA invoice."""
    use_settings(monkeypatch, sandbox())
    st = WriteGuardState(env=dict(ARMED))
    monkeypatch.setattr(toku_client, "PROCESS_STATE", st)
    db_session.add(_sub("sub_real_nope"))
    db_session.flush()
    fake_http.invoices = _inv("TEST-IN-1", "TEST-IN-2")
    with pytest.raises(TokuWriteBlockedError) as e:
        asyncio.run(write_toku.delete_subscription(db_session, "sub_real_nope"))
    assert e.value.code == "ID_NOT_ALLOWED"
    assert _non_get(fake_http) == []
    assert st.writes == 0
    run = db_session.scalars(select(WriteRun).where(WriteRun.external_id == "sub_real_nope")).one()
    assert run.status == "blocked"


def test_delete_subscription_aborts_when_an_invoice_is_not_allowed(monkeypatch, db_session, fake_http) -> None:
    """Caso inverso: suscripcion permitida, una invoice no -> no se anula ni se borra nada."""
    use_settings(monkeypatch, sandbox())
    st = WriteGuardState(env=dict(ARMED))
    monkeypatch.setattr(toku_client, "PROCESS_STATE", st)
    db_session.add(_sub("TEST-SUB-OK"))
    db_session.flush()
    fake_http.invoices = _inv("TEST-IN-1", "in_real")
    with pytest.raises(TokuWriteBlockedError) as e:
        asyncio.run(write_toku.delete_subscription(db_session, "TEST-SUB-OK"))
    assert e.value.code == "ID_NOT_ALLOWED"
    assert _non_get(fake_http) == []
    assert st.writes == 0
    run = db_session.scalars(select(WriteRun).where(WriteRun.external_id == "TEST-SUB-OK")).one()
    assert run.status == "blocked"


def test_delete_subscription_aborts_without_any_network_when_subscription_not_allowed(
    monkeypatch, db_session, fake_http
) -> None:
    use_settings(monkeypatch, sandbox())
    monkeypatch.setattr(toku_client, "PROCESS_STATE", WriteGuardState(env=dict(ARMED)))
    db_session.add(_sub("sub_real_2"))
    db_session.flush()
    fake_http.forbid = True  # ni siquiera lectura: se valida el DELETE antes de listar
    with pytest.raises(TokuWriteBlockedError):
        asyncio.run(write_toku.delete_subscription(db_session, "sub_real_2"))


def test_delete_subscription_aborts_when_cap_cannot_cover_voids_plus_delete(
    monkeypatch, db_session, fake_http
) -> None:
    use_settings(monkeypatch, sandbox())
    st = WriteGuardState(env={**ARMED, ENV_MAX_WRITES: "2"})
    monkeypatch.setattr(toku_client, "PROCESS_STATE", st)
    db_session.add(_sub("TEST-SUB-CAP"))
    db_session.flush()
    fake_http.invoices = _inv("TEST-IN-1", "TEST-IN-2")  # 2 voids + 1 delete = 3 > 2
    with pytest.raises(TokuWriteBlockedError) as e:
        asyncio.run(write_toku.delete_subscription(db_session, "TEST-SUB-CAP"))
    assert e.value.code == "CAP_REACHED"
    assert _non_get(fake_http) == []
    assert st.writes == 0


def test_delete_subscription_sandbox_happy_path_voids_then_deletes(monkeypatch, db_session, fake_http) -> None:
    use_settings(monkeypatch, sandbox())
    st = WriteGuardState(env=dict(ARMED))
    monkeypatch.setattr(toku_client, "PROCESS_STATE", st)
    db_session.add(_sub("TEST-SUB-HP"))
    db_session.flush()
    fake_http.invoices = _inv("TEST-IN-1", "TEST-IN-2")
    sub = asyncio.run(write_toku.delete_subscription(db_session, "TEST-SUB-HP"))
    assert sub.status == "deleted"
    assert _non_get(fake_http) == [
        ("POST", "/invoices/TEST-IN-1/void"),
        ("POST", "/invoices/TEST-IN-2/void"),
        ("DELETE", "/subscriptions/TEST-SUB-HP"),
    ]
    assert st.writes == 3


def test_delete_subscription_production_unchanged(monkeypatch, db_session, fake_http) -> None:
    use_settings(monkeypatch, production())
    monkeypatch.setattr(toku_client, "PROCESS_STATE", WriteGuardState(env={ENV_MAX_WRITES: "0"}))
    db_session.add(_sub("sub_prod_ok"))
    db_session.flush()
    fake_http.invoices = _inv("in_real_1")
    asyncio.run(write_toku.delete_subscription(db_session, "sub_prod_ok"))
    assert _non_get(fake_http) == [
        ("POST", "/invoices/in_real_1/void"),
        ("DELETE", "/subscriptions/sub_prod_ok"),
    ]


def test_check_only_helper_never_consumes_cap() -> None:
    st = state(**{ENV_MAX_WRITES: "1"})
    ops = [("DELETE", "/customers/TEST-1", None)]
    for _ in range(5):
        write_guard.check_sandbox_writes_allowed(ops, sandbox(), st)
    assert st.writes == 0
    with pytest.raises(TokuWriteBlockedError) as e:
        write_guard.check_sandbox_writes_allowed(ops * 2, sandbox(), st)
    assert e.value.code == "CAP_REACHED"
    assert st.writes == 0


# ---- (2) aviso de alias de produccion con escrituras habilitadas ---------------------


@pytest.fixture
def reset_dev_warning(monkeypatch):
    monkeypatch.setattr(config_module, "_dev_alias_warning_emitted", False)


@pytest.mark.parametrize("env", ["development", "dev", "local", "Development"])
def test_dev_alias_with_toku_writes_warns_once_without_values(env, caplog, reset_dev_warning) -> None:
    s = dev_settings(env)
    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        config_module.warn_unguarded_dev_writes(s)
        config_module.warn_unguarded_dev_writes(s)  # una sola vez por proceso
    msgs = [r.getMessage() for r in caplog.records if "TOKU_WRITES_ENABLED" in r.getMessage()]
    assert len(msgs) == 1
    assert "APP_ENV" in msgs[0]
    for secret in (PROD_TK, "prod-ta", "prod-vk", "prod-vs"):
        assert secret not in caplog.text


def test_dev_alias_with_writes_disabled_does_not_warn(caplog, reset_dev_warning) -> None:
    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        config_module.warn_unguarded_dev_writes(dev_settings(toku_writes_enabled=False))
    assert "TOKU_WRITES_ENABLED" not in caplog.text


def test_sandbox_and_production_do_not_warn(caplog, reset_dev_warning) -> None:
    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        config_module.warn_unguarded_dev_writes(sandbox())
        config_module.warn_unguarded_dev_writes(production())
    assert "TOKU_WRITES_ENABLED" not in caplog.text


def test_lifespan_emits_the_dev_alias_warning(monkeypatch, caplog, reset_dev_warning) -> None:
    monkeypatch.setattr(main_module, "settings", dev_settings())
    monkeypatch.setattr(main_module, "_cleanup_zombie_runs", lambda: None)
    monkeypatch.setattr(main_module, "scheduler_should_start", lambda: False)

    async def go() -> None:
        async with main_module.lifespan(main_module.app):
            pass

    with caplog.at_level(logging.WARNING, logger="app.core.config"):
        asyncio.run(go())
    assert "TOKU_WRITES_ENABLED" in caplog.text


# ---- (8) alias de desarrollo: comportamiento sin cambios (hallazgo documentado) ------


@pytest.mark.parametrize("env", ["development", "dev", "local"])
def test_dev_alias_is_production_and_guard_does_not_run(env, monkeypatch, fake_http) -> None:
    """HALLAZGO: development/dev/local cuentan como produccion; TOKU_SANDBOX_* se ignoran y
    `_guard_write` es no-op. Por diseno (decision del usuario: solo aviso)."""
    s = dev_settings(env, **SBX)
    assert s.is_production is True
    assert s.toku_api_key == PROD_TK  # las llaves sandbox no se aplican
    use_settings(monkeypatch, s)
    monkeypatch.setattr(toku_client, "PROCESS_STATE", WriteGuardState(env={}))  # sin ARMED

    def boom(*_a, **_k):
        raise AssertionError("la guarda no debe correr con alias de produccion")

    monkeypatch.setattr(toku_client, "assert_sandbox_write_allowed", boom)
    run_client(lambda c: c.create_customer({"external_id": "SOCIO-1"}))
    assert fake_http.calls == [("POST", "/customers")]


def test_legacy_aliases_unchanged() -> None:
    assert LEGACY_PRODUCTION_ALIASES == ("production", "prod", "development", "dev", "local")


@pytest.mark.parametrize("env", ["qa2", "staging", ""])
def test_unknown_app_env_rejected(env: str) -> None:
    with pytest.raises(ValidationError, match="APP_ENV"):
        Settings(_env_file=None, **{**PROD, "app_env": env})


def test_real_process_state_end_to_end_with_setenv(monkeypatch, fake_http) -> None:
    """PROCESS_STATE real (sin inyectar `env=`): lee os.environ."""
    use_settings(monkeypatch, sandbox())
    monkeypatch.setattr(toku_client, "PROCESS_STATE", write_guard.PROCESS_STATE)
    monkeypatch.setattr(write_guard.PROCESS_STATE, "writes", 0)
    monkeypatch.delenv(ENV_ARMED, raising=False)
    monkeypatch.delenv(ENV_MAX_WRITES, raising=False)
    monkeypatch.delenv(ENV_ALLOWED_IDS, raising=False)
    fake_http.forbid = True
    with pytest.raises(TokuWriteBlockedError) as e:
        run_client(lambda c: c.create_customer({"external_id": "TEST-1"}))
    assert e.value.code == "NOT_ARMED"
    fake_http.forbid = False
    monkeypatch.setenv(ENV_ARMED, "1")
    monkeypatch.setenv(ENV_MAX_WRITES, "1")
    run_client(lambda c: c.create_customer({"external_id": "TEST-1"}))
    fake_http.forbid = True
    with pytest.raises(TokuWriteBlockedError) as e2:
        run_client(lambda c: c.create_customer({"external_id": "TEST-2"}))
    assert e2.value.code == "CAP_REACHED"


# ---- (3) rutas e ids endurecidos ---------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/Customers/TEST-1",
        "/customers/TEST-1\n",
        "/customers/TEST-1 ",
        "/customers/TEST 1",
        "/customers/TEST-1\t",
        "/customers/TEST-1\x00",
        "/customers/TEST-é1",
        "/customers/.",
    ],
)
def test_hardened_paths_are_blocked(path: str) -> None:
    assert blocked_code("DELETE", path, None) in ("ENDPOINT_NOT_ALLOWED", "PATH_INVALID")


@pytest.mark.parametrize("path", ["/customers/TEST-%2e%2e", "/customers/TEST-\\", "/customers/TEST-1/../x"])
def test_encoded_or_backslash_paths_are_path_invalid(path: str) -> None:
    assert blocked_code("DELETE", path, None) == "PATH_INVALID"


def test_lowercase_test_prefix_is_not_accepted() -> None:
    assert blocked_code("DELETE", "/customers/test-1", None) == "ID_NOT_ALLOWED"
    assert blocked_code("POST", "/customers", {"external_id": "test-1"}) == "PREFIX_REQUIRED"


@pytest.mark.parametrize("real_id", ["cus_AbC123", "sub_x1Y2", "in_9z", "pm_Q-1.2:3"])
def test_real_toku_ids_still_allowed_via_allowlist(real_id: str) -> None:
    st = state(**{ENV_ALLOWED_IDS: real_id})
    ok("DELETE", f"/customers/{real_id}", None, st=st)
    ok("POST", f"/invoices/{real_id}/void", {}, st=st)


def test_test_prefixed_external_ids_still_allowed() -> None:
    ok("DELETE", "/subscriptions/TEST-SUB_1.a:b", None)


# ---- (4) mensajes al cliente -------------------------------------------------------


def test_route_403_does_not_leak_variable_names(monkeypatch) -> None:
    async def blocked(*_a, **_k):
        raise TokuWriteBlockedError(
            "ID_NOT_ALLOWED", f"el id no esta en {ENV_ALLOWED_IDS} ni {ENV_MAX_WRITES} {ENV_ARMED}"
        )

    monkeypatch.setattr(writes_routes, "delete_customer", blocked)
    with pytest.raises(HTTPException) as e:
        asyncio.run(writes_routes.delete_toku_customer("c1", None))
    assert e.value.status_code == 403
    assert e.value.detail == "Escritura Toku bloqueada por las guardas de ambiente (ID_NOT_ALLOWED)."
    for name in (ENV_ALLOWED_IDS, ENV_MAX_WRITES, ENV_ARMED, "TOKU_SANDBOX"):
        assert name not in e.value.detail


# ---- (5) tope del cupo -------------------------------------------------------------


def test_cap_is_clipped_to_ceiling() -> None:
    assert write_guard.MAX_WRITES_CEILING == 500
    assert write_guard._max_writes({ENV_MAX_WRITES: "100000"}) == 500
    assert write_guard._max_writes({ENV_MAX_WRITES: "500"}) == 500
    assert write_guard._max_writes({ENV_MAX_WRITES: "499"}) == 499
    st = state(**{ENV_MAX_WRITES: "99999999"})
    for i in range(500):
        ok("DELETE", f"/customers/TEST-{i}", None, st=st)
    assert blocked_code("DELETE", "/customers/TEST-x", None, st=st) == "CAP_REACHED"


@pytest.mark.parametrize("raw", ["-5", "-1", "abc", "1.5", ""])
def test_cap_negative_or_non_numeric_falls_back_to_default(raw: str) -> None:
    assert write_guard._max_writes({ENV_MAX_WRITES: raw}) == 25


def test_cap_zero_still_blocks_everything() -> None:
    assert write_guard._max_writes({ENV_MAX_WRITES: "0"}) == 0


# ---- (6) referencias ---------------------------------------------------------------

_INV_BODY = {
    "customer": "TEST-C1", "product_id": "TEST-SUB-1", "invoice_external_id": "TEST-INV-1",
    "disable_automatic_payment": True,
}


def test_invoice_customer_is_required() -> None:
    assert blocked_code("POST", "/invoices", {k: v for k, v in _INV_BODY.items() if k != "customer"}) == "FIELD_MISSING"
    ok("POST", "/invoices", _INV_BODY)


@pytest.mark.parametrize(
    "extra",
    ["customer_id", "id_customer", "customer_external_id", "mail", "government_id", "id_subscription",
     "id_payment_method"],
)
def test_invoice_rejects_unknown_reference_keys(extra: str) -> None:
    assert blocked_code("POST", "/invoices", {**_INV_BODY, extra: "x"}) == "REFERENCE_NOT_ALLOWED"


def test_invoice_subscription_reference_must_be_test_or_allowlisted() -> None:
    assert blocked_code("POST", "/invoices", {**_INV_BODY, "subscription": "sub_real"}) == "ID_NOT_ALLOWED"
    ok("POST", "/invoices", {**_INV_BODY, "subscription": "TEST-SUB-1"})


@pytest.mark.parametrize("extra", ["customer_id", "id_customer", "id_organization", "mail", "government_id"])
def test_payment_method_rejects_unknown_reference_keys(extra: str) -> None:
    body = {"external_id": "TEST-pm-1", extra: "x"}
    assert blocked_code("POST", "/payment-methods", body) == "REFERENCE_NOT_ALLOWED"
    ok("POST", "/payment-methods", {"external_id": "TEST-pm-1", "customer": "TEST-C1"})


_PUT_CODES = ("PREFIX_REQUIRED", "ID_NOT_ALLOWED", "REFERENCE_NOT_ALLOWED")


@pytest.mark.parametrize(
    ("path", "field", "bad"),
    [
        ("/customers/TEST-1", "external_id", "SOCIO-1"),
        ("/invoices/TEST-1", "customer", "cus_real"),
        ("/invoices/TEST-1", "product_id", "SOCIO-1"),
        ("/invoices/TEST-1", "subscription", "sub_real"),
        ("/invoices/TEST-1", "invoice_external_id", "CUOTA-1"),
        ("/payment-methods/TEST-1", "external_id", "pm-1"),
        ("/subscriptions/TEST-1", "customer", "cus_real"),
        ("/subscriptions/TEST-1", "customer_id", "cus_real"),
    ],
)
def test_put_cannot_repoint_reference_fields_to_non_test_values(path: str, field: str, bad: str) -> None:
    assert blocked_code("PUT", path, {field: bad}) in _PUT_CODES
    assert blocked_code("PUT", path, {field: ["TEST-1", bad]}) in _PUT_CODES


def test_put_with_test_references_or_plain_fields_is_allowed() -> None:
    ok("PUT", "/invoices/TEST-1", {"amount": 5, "customer": "TEST-C1"})
    ok("PUT", "/customers/TEST-1", {"name": "x", "mail": "interno@example.com"})
    ok("PUT", "/customers/TEST-1", {"external_id": "TEST-9"})
    bad = {"external_id": "TEST-9", "customer_id": "cus_real"}
    assert blocked_code("PUT", "/customers/TEST-1", bad) == "REFERENCE_NOT_ALLOWED"
    ok("PUT", "/subscriptions/sub_real", {"customer": "cus_real"}, st=state(**{ENV_ALLOWED_IDS: "sub_real,cus_real"}))


# ---- (7) _BULK_RE: falso positivo documentado --------------------------------------


def test_bulk_regex_false_positive_is_expected_fail_closed() -> None:
    """Un id que contiene 'bulk'/'batch' se bloquea como BULK_BLOCKED aunque sea inocuo.
    Falla cerrado, sin impacto de seguridad; se acepta a proposito."""
    assert blocked_code("DELETE", "/customers/TEST-bulkcustomer", None) == "BULK_BLOCKED"
    assert blocked_code("DELETE", "/customers/TEST-Batch-1", None) == "BULK_BLOCKED"


# ---- (8) cuerpos raros -------------------------------------------------------------


@pytest.mark.parametrize("body", ["texto", None, 5, ["TEST-1"]])
def test_post_non_dict_body_blocked(body) -> None:
    assert blocked_code("POST", "/customers", body) in ("BODY_INVALID", "BULK_BLOCKED")


def test_nested_body_does_not_satisfy_top_level_fields() -> None:
    assert blocked_code("POST", "/customers", {"data": {"external_id": "TEST-1"}}) == "FIELD_MISSING"
    assert blocked_code("POST", "/customers", {"external_id": {"x": "TEST-1"}}) == "PREFIX_REQUIRED"


@pytest.mark.parametrize("ext", [["TEST-1", "REAL-1"], {"a": "TEST-1"}, [], ["TEST-1", 5], 123, True])
def test_external_id_list_dict_or_mixed_blocked(ext) -> None:
    assert blocked_code("POST", "/customers", {"external_id": ext}) in ("PREFIX_REQUIRED", "FIELD_MISSING")


def test_customer_as_dict_or_list_blocked() -> None:
    body = {"product_id": "TEST-SUB-1"}
    assert blocked_code("POST", "/subscriptions", {**body, "customer": {"id": "TEST-1"}}) == "ID_NOT_ALLOWED"
    assert blocked_code("POST", "/subscriptions", {**body, "customer": ["TEST-1", "cus_real"]}) == "ID_NOT_ALLOWED"
    assert blocked_code("POST", "/subscriptions", {**body, "customer": None}) == "ID_NOT_ALLOWED"


# ---- (8) concurrencia sobre el cupo ------------------------------------------------


def test_concurrent_writes_respect_cap_of_one() -> None:
    st = state(**{ENV_MAX_WRITES: "1"})

    async def attempt(i: int) -> str:
        await asyncio.sleep(0)
        try:
            assert_sandbox_write_allowed("DELETE", f"/customers/TEST-{i}", None, sandbox(), st)
            return "ok"
        except TokuWriteBlockedError as exc:
            return exc.code

    async def go():
        return await asyncio.gather(attempt(1), attempt(2))

    assert sorted(asyncio.run(go())) == ["CAP_REACHED", "ok"]
    assert st.writes == 1


def test_concurrent_client_writes_respect_cap_of_one(monkeypatch, fake_http) -> None:
    use_settings(monkeypatch, sandbox())
    monkeypatch.setattr(toku_client, "PROCESS_STATE", WriteGuardState(env={**ARMED, ENV_MAX_WRITES: "1"}))

    async def many(c):
        return await asyncio.gather(c.delete_customer("TEST-1"), c.delete_customer("TEST-2"), return_exceptions=True)

    res = run_client(many)
    assert sum(isinstance(r, TokuWriteBlockedError) for r in res) == 1
    assert len(fake_http.calls) == 1


def test_concurrent_threads_respect_cap() -> None:
    st = state(**{ENV_MAX_WRITES: "5"})
    passed: list[int] = []

    def worker(i: int) -> None:
        try:
            assert_sandbox_write_allowed("DELETE", f"/customers/TEST-{i}", None, sandbox(), st)
            passed.append(i)
        except TokuWriteBlockedError:
            pass

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(passed) == 5
    assert st.writes == 5


# ---- (8) ruta de API completa: CSRF + permisos + 403 de la guarda ---------------------


def _api_client(monkeypatch, db_session, perms):
    import uuid
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from app.api.v1.routes.crm import get_db
    from app.core.config import settings as app_settings
    from app.core.security import ACCESS_COOKIE, create_access_token, get_current_user

    monkeypatch.setattr(app_settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    user = SimpleNamespace(
        id=uuid.uuid4(), is_active=True,
        roles=[SimpleNamespace(name="r", permissions=[SimpleNamespace(code=p) for p in perms])],
    )
    token, csrf = create_access_token(user)
    main_module.app.dependency_overrides[get_current_user] = lambda: user
    main_module.app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(main_module.app)
    client.cookies.set(ACCESS_COOKIE, token)
    return client, csrf, (get_current_user, get_db)


def test_full_api_route_csrf_permissions_and_guard_403(monkeypatch, db_session, fake_http) -> None:
    use_settings(monkeypatch, sandbox())
    monkeypatch.setattr(toku_client, "PROCESS_STATE", WriteGuardState(env=dict(ARMED)))
    db_session.add(Client(source="toku", external_id="cus_api_guard", first_name="X", raw_payload={}))
    db_session.flush()
    fake_http.forbid = True
    url = "/api/v1/writes/toku/customers/cus_api_guard"

    client, csrf, deps = _api_client(monkeypatch, db_session, ["toku.customers.delete"])
    try:
        assert client.delete(url).status_code in (401, 403)  # sin CSRF
        r = client.delete(url, headers={"X-CSRF-Token": csrf})  # guarda: id no TEST- ni allowlist
        assert r.status_code == 403
        detail = r.json()["detail"]
        assert "ID_NOT_ALLOWED" in detail
        for name in (ENV_ALLOWED_IDS, ENV_MAX_WRITES, ENV_ARMED, "TOKU_SANDBOX"):
            assert name not in detail
        run = db_session.scalars(select(WriteRun).where(WriteRun.external_id == "cus_api_guard")).one()
        assert run.status == "blocked"
        assert ENV_ALLOWED_IDS in (run.error_message or "")  # el detalle completo queda en el write_run
        # sin permiso -> 403 antes de llegar a la guarda (no crea otro write_run)
        client2, csrf2, _ = _api_client(monkeypatch, db_session, [])
        assert client2.delete(url, headers={"X-CSRF-Token": csrf2}).status_code == 403
        assert len(db_session.scalars(select(WriteRun).where(WriteRun.external_id == "cus_api_guard")).all()) == 1
    finally:
        for dep in deps:
            main_module.app.dependency_overrides.pop(dep, None)
