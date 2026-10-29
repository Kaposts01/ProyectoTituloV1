"""RJ-01: proyección de rechazos de Toku (tk_transactions FAILED) a core_charges.latest_rejection_*.

Payloads sintéticos con la forma real de `GET /transactions`:
`transaction{status,response_code,original_response_message,transaction_date}` y
`payment_intents[0].id_invoice`.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.core import CoreCharge, CorePayment
from app.models.toku_channel import TokuTransaction
from app.services import core_toku_etl
from app.services.toku_rejection_projection import project_toku_rejections
from tests.test_charge_recovery import db_session  # noqa: F401  (fixture)


def _uid() -> str:
    return "rj01-" + uuid.uuid4().hex[:10]


def _tx(invoice: str | None, *, status: str = "FAILED", code: str | None = "TEPSP1008",
        message: str | None = "[51] EXCEDE SALDO MAXIMO", date: str = "2026-10-05T12:00:00.000000") -> TokuTransaction:
    transaction = {"id": _uid(), "type": "PAYMENT", "status": status, "transaction_date": date}
    if code is not None:
        transaction["response_code"] = code
    if message is not None:
        transaction["original_response_message"] = message
    intents = [{"id": _uid(), "id_invoice": invoice, "id_subscription": _uid()}] if invoice else []
    return TokuTransaction(external_id=transaction["id"], status=status, created_at_api=date,
                           raw_payload={"transaction": transaction, "payment_intents": intents})


def _charge(db: Session, invoice: str, **kw) -> CoreCharge:
    charge = CoreCharge(source="toku", external_id=invoice, **kw)
    db.add(charge)
    db.flush()
    return charge


def _fresh(db: Session, charge: CoreCharge) -> CoreCharge:
    db.expire(charge)
    return charge


def test_failed_transaction_is_projected_with_normalized_reason_text(db_session: Session) -> None:  # noqa: F811
    inv = _uid()
    charge = _charge(db_session, inv)
    db_session.add(_tx(inv, message="[51] RECHAZADA- REINTENTAR EL 01-10-2025 A LAS 07:33"))
    db_session.flush()
    stats = project_toku_rejections(db_session)
    assert stats["charges_updated"] >= 1
    _fresh(db_session, charge)
    assert charge.latest_rejection_code == "TEPSP1008"
    assert charge.latest_rejection_reason == "RECHAZADA- REINTENTAR"
    assert charge.latest_rejection_at == datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    assert charge.latest_rejection_payment_id is None


def test_latest_attempt_per_invoice_wins(db_session: Session) -> None:  # noqa: F811
    inv = _uid()
    charge = _charge(db_session, inv)
    db_session.add_all([
        _tx(inv, code="TEPSP1001", message="[51] EXCEDE SALDO MAXIMO", date="2026-09-01T10:00:00"),
        _tx(inv, code="PEPSP1019", message="[78] Bloqueada / Primer uso o Condicion Especial", date="2026-10-02T10:00:00"),
        _tx(inv, code="TEPSP2070", message="[91] RECHAZADA- SISTEMA EMISOR NO OPERATIVO", date="2026-09-15T10:00:00"),
    ])
    db_session.flush()
    project_toku_rejections(db_session)
    _fresh(db_session, charge)
    assert charge.latest_rejection_code == "PEPSP1019"
    assert charge.latest_rejection_at == datetime(2026, 10, 2, 10, 0, tzinfo=UTC)


def test_missing_response_code_falls_back_to_iso_from_reason_text(db_session: Session) -> None:  # noqa: F811
    inv = _uid()
    charge = _charge(db_session, inv)
    db_session.add(_tx(inv, code=None, message="[05] RECHAZADA- CONTACTE A SU EMISOR"))
    db_session.flush()
    project_toku_rejections(db_session)
    _fresh(db_session, charge)
    assert charge.latest_rejection_code == "ISO:05"
    assert charge.latest_rejection_reason == "RECHAZADA- CONTACTE A SU EMISOR"


def test_code_without_reason_text_and_reason_text_without_any_code(db_session: Session) -> None:  # noqa: F811
    inv1, inv2 = _uid(), _uid()
    c1, c2 = _charge(db_session, inv1), _charge(db_session, inv2)
    db_session.add_all([_tx(inv1, code="PEPSP1019", message=None), _tx(inv2, code=None, message="BRAND_CHARGE_LIMIT-EXCEEDED")])
    db_session.flush()
    project_toku_rejections(db_session)
    _fresh(db_session, c1), _fresh(db_session, c2)
    assert (c1.latest_rejection_code, c1.latest_rejection_reason) == ("PEPSP1019", None)
    assert (c2.latest_rejection_code, c2.latest_rejection_reason) == (None, "BRAND_CHARGE_LIMIT-EXCEEDED")


def test_rows_without_information_status_or_invoice_are_ignored(db_session: Session) -> None:  # noqa: F811
    no_info, success, aborted = _uid(), _uid(), _uid()
    charges = [_charge(db_session, i) for i in (no_info, success, aborted)]
    db_session.add_all([
        _tx(no_info, code=None, message=None),
        _tx(success, status="SUCCESS", code="SUTOK0000", message=None),
        _tx(aborted, status="ABORTED"),
        _tx(None),  # sin payment_intents
    ])
    db_session.flush()
    stats = project_toku_rejections(db_session)
    for charge in charges:
        assert _fresh(db_session, charge).latest_rejection_code is None
    assert stats["failed_without_information"] >= 1
    assert stats["failed_without_invoice"] >= 1


def test_invoice_without_core_charge_is_counted_not_created(db_session: Session) -> None:  # noqa: F811
    inv = _uid()
    db_session.add(_tx(inv))
    db_session.flush()
    before = db_session.scalar(select(func.count()).select_from(CoreCharge))
    payments_before = db_session.scalar(select(func.count()).select_from(CorePayment))
    stats = project_toku_rejections(db_session)
    assert stats["invoices_without_core_charge"] >= 1
    assert db_session.scalar(select(func.count()).select_from(CoreCharge)) == before
    assert db_session.scalar(select(func.count()).select_from(CorePayment)) == payments_before  # no se materializan pagos


def test_idempotent_and_dry_run_does_not_write(db_session: Session) -> None:  # noqa: F811
    inv = _uid()
    charge = _charge(db_session, inv)
    db_session.add(_tx(inv))
    db_session.flush()

    dry = project_toku_rejections(db_session, apply=False)
    assert dry["applied"] is False and dry["charges_updated"] >= 1
    assert _fresh(db_session, charge).latest_rejection_code is None

    applied = project_toku_rejections(db_session)
    assert applied["applied"] is True and applied["charges_updated"] == dry["charges_updated"]
    assert _fresh(db_session, charge).latest_rejection_code == "TEPSP1008"

    again = project_toku_rejections(db_session)
    assert again["charges_updated"] == 0
    assert again["charges_unchanged"] >= 1


def test_never_replaces_a_newer_existing_rejection_and_updates_an_older_one(db_session: Session) -> None:  # noqa: F811
    inv_new, inv_old = _uid(), _uid()
    newer = _charge(db_session, inv_new, latest_rejection_code="MANUAL", latest_rejection_reason="mas nuevo",
                    latest_rejection_at=datetime(2027, 1, 1, tzinfo=UTC))
    older = _charge(db_session, inv_old, latest_rejection_code="VIEJO", latest_rejection_reason="mas viejo",
                    latest_rejection_at=datetime(2020, 1, 1, tzinfo=UTC))
    db_session.add_all([_tx(inv_new), _tx(inv_old)])
    db_session.flush()
    project_toku_rejections(db_session)
    assert _fresh(db_session, newer).latest_rejection_code == "MANUAL"
    assert _fresh(db_session, older).latest_rejection_code == "TEPSP1008"


def test_other_sources_are_not_touched(db_session: Session) -> None:  # noqa: F811
    inv = _uid()
    other = CoreCharge(source="payku", external_id=inv)
    db_session.add_all([other, _tx(inv)])
    db_session.flush()
    project_toku_rejections(db_session)
    assert _fresh(db_session, other).latest_rejection_code is None


def test_toku_core_etl_invokes_the_projection(db_session: Session, monkeypatch) -> None:  # noqa: F811
    calls: list[str] = []
    monkeypatch.setattr(core_toku_etl, "materialize_core_clients", lambda *a, **k: 0)
    for name in ("_materialize_client_attributes", "_materialize_subscriptions", "_materialize_stub_subscriptions",
                 "_materialize_charges", "_materialize_payments"):
        monkeypatch.setattr(core_toku_etl, name, lambda *a, _n=name, **k: calls.append(_n) or 0)
    monkeypatch.setattr(core_toku_etl, "project_toku_rejections",
                        lambda db, **k: calls.append("project") or {"charges_updated": 7})
    result = core_toku_etl.run_toku_core_etl(db_session)
    assert calls[-2:] == ["_materialize_payments", "project"]  # después de cobros y pagos
    assert result["charges_rejection_projected"] == 7


def test_maintenance_script_is_dry_run_unless_apply_is_explicit() -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "maintenance" / "project_toku_rejections.py"
    spec = importlib.util.spec_from_file_location("project_toku_rejections_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.parse_args([]).apply is False
    assert module.parse_args(["--apply"]).apply is True
