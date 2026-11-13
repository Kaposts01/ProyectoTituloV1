"""d212: scripts/maintenance/redact_raw_payload_accounts.py (dry-run por defecto, --apply con --confirm-database)."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.models.tch import TchSubscription
from tests.test_charge_recovery import db_session  # noqa: F401  (fixture)

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "maintenance" / "redact_raw_payload_accounts.py"
ACCOUNT = "000123456789"  # sintetico
OTHER = "009876543210"  # sintetico


@pytest.fixture
def script():
    spec = importlib.util.spec_from_file_location("redact_raw_payload_accounts_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload() -> dict:
    return {
        "Número Cuenta": ACCOUNT,
        "Tipo Cuenta": "Corriente",
        "Numero Ficha": "990777123",
        "detalle": [{"N° Cuenta": int(OTHER)}, {"cuenta": "virtualpos1"}],
        "Cuenta Bancaria": "1234",  # ya corta: no se toca
    }


def _seed(db) -> TchSubscription:
    sub = TchSubscription(file_number=990777, status="VIGENTE", raw_payload=_payload())
    db.add(sub)
    db.commit()  # el dry-run termina con rollback: los datos de arranque deben estar confirmados
    return sub


def _reload(db, sub_id):
    db.expire_all()
    return db.scalar(select(TchSubscription).where(TchSubscription.id == sub_id)).raw_payload


def test_redact_keeps_only_last_four_digits(script) -> None:
    out, changed = script.redact(_payload())
    assert changed == 2
    assert out["Número Cuenta"] == "••••6789"
    assert out["detalle"][0]["N° Cuenta"] == "••••3210"
    assert out["Tipo Cuenta"] == "Corriente" and out["Numero Ficha"] == "990777123"
    assert out["detalle"][1] == {"cuenta": "virtualpos1"} and out["Cuenta Bancaria"] == "1234"
    assert script.redact(out) == (out, 0)  # idempotente


def test_dry_run_is_default_counts_only_and_writes_nothing(script, db_session, capsys) -> None:  # noqa: F811
    sub = _seed(db_session)
    assert script.main([], session_factory=lambda: db_session) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and "tch_suscripciones.raw_payload" in out
    assert ACCOUNT not in out and "6789" not in out
    assert _reload(db_session, sub.id) == _payload()


def test_apply_requires_exact_database_confirmation(script, db_session, capsys) -> None:  # noqa: F811
    sub = _seed(db_session)
    assert script.main(["--apply"], session_factory=lambda: db_session) == 2
    assert script.main(["--apply", "--confirm-database", "crm"], session_factory=lambda: db_session) == 2
    assert "--confirm-database" in capsys.readouterr().out
    assert _reload(db_session, sub.id) == _payload()


def test_apply_redacts_in_one_transaction_and_reports_counts(script, db_session, capsys) -> None:  # noqa: F811
    sub = _seed(db_session)
    current = db_session.execute(text("SELECT current_database()")).scalar_one()
    assert script.main(["--apply", "--confirm-database", current], session_factory=lambda: db_session) == 0
    out = capsys.readouterr().out
    assert "APPLY" in out and ACCOUNT not in out
    payload = _reload(db_session, sub.id)
    assert payload["Número Cuenta"] == "••••6789" and payload["detalle"][0]["N° Cuenta"] == "••••3210"
    assert payload["Tipo Cuenta"] == "Corriente"
    # segunda pasada: nada que cambiar en esta fila
    report = script.run(db_session, apply=False, confirm_database=None)
    assert ACCOUNT not in str(report)
    assert _reload(db_session, sub.id) == payload
