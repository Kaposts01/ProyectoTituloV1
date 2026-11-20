"""PERF-03g: la semilla sintetica y el inicio de sesion del presupuesto de rendimiento (solo logica pura, sin base)."""

import importlib.util
from datetime import date
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "sandbox"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed = _load("seed_perf_ci")
login = _load("perf_ci_login")


def test_seed_is_synthetic_deterministic_and_unique():
    rows = seed.build_rows(40, date(2026, 11, 20))
    assert rows == seed.build_rows(40, date(2026, 11, 20))
    assert {table: len(items) for table, items in rows.items() if table != "payments"} == {
        "clients": 40, "subscriptions": 40, "charges": 120,
    }
    external_ids = [row["external_id"] for items in rows.values() for row in items]
    assert len(external_ids) == len(set(external_ids))
    assert all(eid.startswith(seed.PREFIX) for eid in external_ids)
    assert all(row["email"].endswith("@example.test") for row in rows["clients"])
    # cada pago cuelga de un cobro pagado
    paid = {row["external_id"] for row in rows["charges"] if row["status"] == "pagado"}
    assert {row["charge_external_id"] for row in rows["payments"]} == paid


def test_seed_ruts_are_in_the_synthetic_range_with_valid_check_digit():
    rut = seed.synthetic_rut(1)
    number, dv = rut.split("-")
    assert number == str(seed.RUT_BASE + 1)
    assert dv == seed.rut_dv(int(number))


@pytest.mark.parametrize("name", ["crm", "crm_test", "", None, "produccion"])
def test_seed_refuses_non_sandbox_databases(name):
    with pytest.raises(SystemExit):
        seed.guard_database(name)


def test_seed_accepts_sandbox_and_qa_databases():
    assert seed.guard_database("crm_sandbox") == "crm_sandbox"
    assert seed.guard_database("crm_qa") == "crm_qa"


def test_login_picks_the_access_cookie_only():
    headers = ["csrf=abc; Path=/", "crm_access_token_sandbox=tok123; HttpOnly; Path=/; SameSite=lax"]
    assert login.session_cookie(headers) == "crm_access_token_sandbox=tok123"
    with pytest.raises(SystemExit):
        login.session_cookie(["otra=1; Path=/"])


def test_login_only_talks_to_the_local_backend():
    with pytest.raises(SystemExit):
        login.login("https://crm.example.org", "u", "p")
