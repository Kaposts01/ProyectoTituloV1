"""d205 b: siembra DEMO de VirtualPOS (scripts/sandbox/seed_vp_demo.py).

Las funciones reciben la sesion inyectada: aqui corren contra `crm_test`. El modulo NO toca el entorno al importarse
(solo `main()` fija APP_ENV=sandbox y valida la base).
"""

import importlib.util
import os
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models.crm import Charge, Payment, Subscription

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "sandbox" / "seed_vp_demo.py"


def _load():
    spec = importlib.util.spec_from_file_location("seed_vp_demo_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sv = _load()


@pytest.fixture(autouse=True)
def _clean():
    def run() -> None:
        db = SessionLocal()
        try:
            sv.remove(db)
            db.commit()
        finally:
            db.close()
    run()
    yield
    run()


def _count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model).where(model.external_id.like("DEMO-VP-%")))


def test_importing_the_module_does_not_touch_the_environment() -> None:
    assert os.environ.get("APP_ENV") != "sandbox"


@pytest.mark.parametrize("name", ["crm", "crm_test", "crm_sandbox_test", "crm_qa", "", None, "postgres"])
def test_guard_rejects_non_sandbox_databases(name) -> None:
    with pytest.raises(SystemExit):
        sv.guard_database(name)


def test_guard_accepts_sandbox() -> None:
    assert sv.guard_database("crm_sandbox") == "crm_sandbox"


def test_rows_are_synthetic() -> None:
    rows = sv.build_rows()
    assert len(rows["subscriptions"]) == 3 and len(rows["charges"]) == 6 and len(rows["payments"]) == 3
    for table in rows.values():
        assert all(r["external_id"].startswith("DEMO-VP-") for r in table)
    for sub in rows["subscriptions"]:
        client = sub["raw_payload"]["client"]
        assert client["first_name"].startswith("DEMO-") and client["email"].endswith("@example.test")
        number, dv = client["social_id"].split("-")
        assert number.startswith("43") and len(number) == 8 and dv == sv.rut_dv(int(number))
    assert sv.rut_dv(11111111) == "1" and sv.rut_dv(12345678) == "5"


def test_seed_is_idempotent_and_remove_reverts() -> None:
    db = SessionLocal()
    try:
        first = sv.seed(db)
        db.commit()
        assert first == {"subscriptions": (3, 0), "charges": (6, 0), "payments": (3, 0)}
        second = sv.seed(db)
        db.commit()
        assert second == {"subscriptions": (0, 3), "charges": (0, 6), "payments": (0, 3)}
        assert (_count(db, Subscription), _count(db, Charge), _count(db, Payment)) == (3, 6, 3)
        removed = sv.remove(db)
        db.commit()
        assert (removed["subscriptions"], removed["charges"], removed["payments"]) == (3, 6, 3)
        assert (_count(db, Subscription), _count(db, Charge), _count(db, Payment)) == (0, 0, 0)
    finally:
        db.close()
