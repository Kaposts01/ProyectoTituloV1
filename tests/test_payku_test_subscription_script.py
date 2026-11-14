"""CRM-14C: scripts/maintenance/payku_test_subscription.py (dry-run por defecto, armado y registro en write_runs).

Sin red ni base: el proveedor y la sesion son falsos. Ninguna prueba llama a Payku ni arma escrituras reales.
"""

import asyncio
import importlib.util
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.write_run import WriteRun
from app.services.read_only_provider_sync import sanitize_record

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "maintenance" / "payku_test_subscription.py"
TODAY = date(2026, 11, 13)
EMAIL = "titular.prueba@example.cl"
RUT = "12345678-5"
BASE_ARGS = ["--email", EMAIL, "--rut", RUT, "--phone", "900000123", "--name", "Titular Prueba"]


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("payku_test_subscription", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # las dataclasses del script resuelven sus anotaciones por el modulo
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture
def no_live(mod, monkeypatch):
    async def boom(*_a, **_k):
        raise AssertionError("el dry-run no debe ejecutar nada en vivo")

    monkeypatch.setattr(mod, "_run_live", boom)


class FakeSession:
    def __init__(self) -> None:
        self.added: list = []
        self.commits = 0

    def add(self, obj) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.commits += 1


class FakeProvider:
    def __init__(self, *, client=None, customers=(), subs=(), fail_on=None) -> None:
        self.calls: list[tuple] = []
        self._client = client
        self._customers = list(customers)
        self._subs = list(subs)
        self._fail_on = fail_on

    async def get_client(self, identifier):
        self.calls.append(("GET client", identifier))
        if self._client is None:
            raise RuntimeError("not found")
        return self._client

    async def list_clients(self, page=1, per_page=50):
        self.calls.append(("GET customers", page))
        return {"customers": self._customers if page == 1 else []}

    async def list_subscriptions_v3(self, **kw):
        self.calls.append(("GET v3",))
        return {"suscriptions": self._subs}

    async def create_client(self, data):
        self.calls.append(("POST suclient", dict(data)))
        if self._fail_on == "client":
            raise RuntimeError("rechazado")
        return {"status": "success", "id": "cl-test-1"}

    async def create_plan(self, data):
        self.calls.append(("POST suplan", dict(data)))
        return {"status": "success", "id": "pl-test-1"}

    async def create_subscription(self, data):
        self.calls.append(("POST sususcription", dict(data)))
        return {"status": "register", "id": "su-test-1", "url": "https://app.payku.cl/gateway/registrosuscripcion?x=1"}

    async def delete_subscription(self, identifier):
        self.calls.append(("DELETE sususcription", identifier))
        return {"id": identifier, "status": "success"}

    async def get_subscription(self, identifier):
        self.calls.append(("GET sususcription", identifier))
        return {"id": identifier, "status": "delete"}


def _args(mod, *extra):
    return mod.parse_args([*BASE_ARGS, *extra])


def _armed_settings(**over):
    base = {"is_production": True, "payku_base_url": "https://app.payku.cl", "payku_writes_enabled": True}
    return SimpleNamespace(**{**base, **over})


def _recorder(mod):
    session = FakeSession()
    return session, mod.WriteRecorder(session, WriteRun, sanitize_record)


# --- dry-run -----------------------------------------------------------------------------------------------------------


def test_default_is_dry_run_and_prints_plan(mod, no_live, capsys) -> None:
    assert mod.main([*BASE_ARGS, "--plan-id", "pl-variable"], today=TODAY) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    for expected in ("GET /api/suclient/ti***@example.cl", "POST /api/suclient", "GET /api/suplan/pl-variable",
                     "POST /api/sususcription", "'amount': '1'", "costo:  50 CLP", "Costo total estimado: 51 CLP"):
        assert expected in out, expected
    assert EMAIL not in out and RUT not in out and "900000123" not in out  # PII enmascarada


def test_dry_run_without_plan_id_warns_about_plan_type(mod, no_live, capsys) -> None:
    mod.main(BASE_ARGS, today=TODAY)
    out = capsys.readouterr().out
    assert "POST /api/suplan" in out and "CRM TEST 261113" in out
    assert "AVISO" in out and "no esta documentado" in out


def test_dry_run_warns_when_total_exceeds_cap(mod, no_live, capsys) -> None:
    mod.main([*BASE_ARGS, "--amount", "10"], today=TODAY)
    assert "supera el tope 51 CLP" in capsys.readouterr().out


def test_find_existing_and_cancel_are_dry_run_by_default(mod, no_live, capsys) -> None:
    assert mod.main([*BASE_ARGS, "--find-existing"], today=TODAY) == 0
    out = capsys.readouterr().out
    assert "GET /api/suclient/customers" in out and "GET /api/sususcriptionv3" in out
    assert "ESCRITURA" not in out
    assert mod.main(["--cancel", "su-test-1"], today=TODAY) == 0
    out = capsys.readouterr().out
    assert "[ESCRITURA] DELETE /api/sususcription/su-test-1" in out and "DRY-RUN" in out


def test_verify_plan_lists_reads_for_the_day(mod) -> None:
    plan = mod.build_verify_plan("su-test-1", TODAY)
    assert [(s.method, s.path) for s in plan.steps] == [
        ("GET", "/api/sususcription/su-test-1"), ("GET", "/api/sususcriptionv3"), ("GET", "/api/transaction")]
    assert all(not s.write for s in plan.steps)
    assert plan.steps[2].params["date_init"] == "2026-11-13"


# --- armado ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("extra", "env", "settings_over", "message"),
    [
        ([], {"PAYKU_TEST_SUBSCRIPTION_ARMED": "1"}, {}, "--confirm-production"),
        (["--confirm-production"], {}, {}, "PAYKU_TEST_SUBSCRIPTION_ARMED"),
        (["--confirm-production"], {"PAYKU_TEST_SUBSCRIPTION_ARMED": "1"}, {"is_production": False}, "no es productivo"),
        (["--confirm-production"], {"PAYKU_TEST_SUBSCRIPTION_ARMED": "1"}, {"payku_base_url": "https://des.payku.cl"}, "app.payku.cl"),
        (["--confirm-production"], {"PAYKU_TEST_SUBSCRIPTION_ARMED": "1"}, {"payku_writes_enabled": False}, "PAYKU_WRITES_ENABLED"),
        (["--confirm-production", "--amount", "5"], {"PAYKU_TEST_SUBSCRIPTION_ARMED": "1"}, {}, "--max-total"),
    ],
)
def test_check_armed_requires_every_key(mod, extra, env, settings_over, message) -> None:
    with pytest.raises(mod.ArmingError, match=message):
        mod.check_armed(_args(mod, *extra), _armed_settings(**settings_over), env, cancel=False)


def test_check_armed_requires_rut(mod) -> None:
    args = mod.parse_args(["--email", EMAIL, "--phone", "1", "--name", "N", "--confirm-production"])
    with pytest.raises(mod.ArmingError, match="--rut"):
        mod.check_armed(args, _armed_settings(), {"PAYKU_TEST_SUBSCRIPTION_ARMED": "1"}, cancel=False)


def test_check_armed_passes_with_all_keys(mod) -> None:
    mod.check_armed(_args(mod, "--confirm-production"), _armed_settings(), {"PAYKU_TEST_SUBSCRIPTION_ARMED": "1"},
                    cancel=False)


def test_apply_without_keys_is_blocked_before_any_call(mod, monkeypatch, capsys) -> None:
    import app.integrations.payku.client as client_module

    def forbidden(*_a, **_k):
        raise AssertionError("no debe construirse el cliente de Payku")

    monkeypatch.setattr(client_module, "PaykuClient", forbidden)
    monkeypatch.delenv("PAYKU_TEST_SUBSCRIPTION_ARMED", raising=False)
    assert mod.main([*BASE_ARGS, "--apply", "--confirm-production"], today=TODAY) == 2
    assert "BLOQUEADO" in capsys.readouterr().out


def test_reads_against_production_require_confirmation(mod, monkeypatch, capsys) -> None:
    import app.integrations.payku.client as client_module

    monkeypatch.setattr(client_module, "PaykuClient", lambda *a, **k: (_ for _ in ()).throw(AssertionError("sin red")))
    assert mod.main([*BASE_ARGS, "--find-existing", "--execute-read"], today=TODAY) == 2
    assert "--confirm-production" in capsys.readouterr().out


# --- ejecucion con proveedor falso y registro en write_runs ------------------------------------------------------------


def test_apply_create_records_each_write(mod) -> None:
    provider = FakeProvider()
    session, recorder = _recorder(mod)
    result = asyncio.run(mod.apply_create(_args(mod, "--plan-id", "pl-variable"), provider, recorder, ("k",), TODAY))
    assert result["subscription_id"] == "su-test-1" and result["client_id"] == "cl-test-1"
    assert result["enroll_url"].startswith("https://app.payku.cl/gateway/")
    writes = [c for c in provider.calls if c[0].startswith(("POST", "DELETE"))]
    assert [c[0] for c in writes] == ["POST suclient", "POST sususcription"]
    assert writes[1][1] == {"plan": "pl-variable", "client": "cl-test-1", "amount": "1"}
    runs = session.added
    assert [r.operation for r in runs] == ["test_subscription.create_client", "test_subscription.create_subscription"]
    assert all(r.source == "payku" and r.status == "completed" and r.finished_at for r in runs)
    assert [r.external_id for r in runs] == ["cl-test-1", "su-test-1"]
    assert runs[0].request_payload["marker"] == "CRM-14C"
    assert EMAIL not in str(runs[0].request_payload) and RUT not in str(runs[0].request_payload)


def test_apply_create_reuses_existing_client_and_creates_plan(mod) -> None:
    provider = FakeProvider(client={"id": "cl-old", "email": EMAIL})
    session, recorder = _recorder(mod)
    asyncio.run(mod.apply_create(_args(mod), provider, recorder, ("k",), TODAY))
    assert "POST suclient" not in [c[0] for c in provider.calls]
    assert [r.operation for r in session.added] == ["test_subscription.create_plan", "test_subscription.create_subscription"]


def test_apply_create_aborts_if_person_already_has_active_subscription(mod) -> None:
    provider = FakeProvider(customers=[{"id": "cl-rut", "rut": "12.345.678-5", "email": "otro@example.cl"}],
                            subs=[{"id": "su-old", "status": "active", "client": {"id": "cl-rut"}}])
    session, recorder = _recorder(mod)
    with pytest.raises(mod.ArmingError, match="ya existe"):
        asyncio.run(mod.apply_create(_args(mod), provider, recorder, ("k",), TODAY))
    assert session.added == []
    assert not [c for c in provider.calls if c[0].startswith("POST")]


def test_failed_write_is_recorded_as_failed(mod) -> None:
    provider = FakeProvider(fail_on="client")
    session, recorder = _recorder(mod)
    with pytest.raises(RuntimeError):
        asyncio.run(mod.apply_create(_args(mod, "--plan-id", "pl-v"), provider, recorder, ("k",), TODAY))
    assert len(session.added) == 1 and session.added[0].status == "failed" and "rechazado" in session.added[0].error_message


def test_apply_cancel_records_write_and_rereads(mod) -> None:
    provider = FakeProvider()
    session, recorder = _recorder(mod)
    out = asyncio.run(mod.apply_cancel("su-test-1", provider, recorder, ("k",)))
    assert out["after"]["status"] == "delete"
    run = session.added[0]
    assert (run.operation, run.external_id, run.status) == ("test_subscription.cancel_subscription", "su-test-1", "completed")


def test_find_existing_matches_by_rut_ignoring_format(mod) -> None:
    provider = FakeProvider(customers=[{"id": "cl-9", "rut": "123456785", "email": "x@example.cl"}],
                            subs=[{"id": "su-9", "status": "cancel", "client": {"id": "cl-9"}}])
    found = asyncio.run(mod.find_existing(provider, None, "12.345.678-5"))
    assert found == {"client_id": "cl-9", "subscriptions": [{"id": "su-9", "status": "cancel"}]}
    assert all(c[0].startswith("GET") for c in provider.calls)  # solo lecturas
