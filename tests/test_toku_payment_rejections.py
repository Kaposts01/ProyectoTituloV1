"""TK-PAR-03: el rechazo de cada intento de Toku llega a `payments.rejection_*` canónico.

Payloads sintéticos con la forma de `GET /transactions` (ver `test_toku_rejection_projection`). No llama a Toku.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.crm import Payment
from app.services import channel_consolidation
from app.services.toku_rejection_projection import (
    project_toku_payment_rejections,
    toku_transaction_rejection,
)
from tests.test_charge_recovery import db_session  # noqa: F401  (fixture)
from tests.test_toku_rejection_projection import _tx, _uid


def test_pure_projection_only_for_failed_and_normalizes_reason() -> None:
    failed = _tx("inv", code="tepsp1008", message="[51] RECHAZADA- REINTENTAR EL 01-10-2025 A LAS 07:33")
    assert toku_transaction_rejection(failed.raw_payload, "FAILED") == (
        "TEPSP1008", "RECHAZADA- REINTENTAR", datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
    )
    ok = _tx("inv", status="SUCCESS", code="SUTOK0000")
    assert toku_transaction_rejection(ok.raw_payload, "SUCCESS") == (None, None, None)
    iso = _tx("inv", code=None, message="[05] RECHAZADA- CONTACTE A SU EMISOR")
    assert toku_transaction_rejection(iso.raw_payload, "FAILED")[0] == "ISO:05"
    empty = _tx("inv", code=None, message=None)
    assert toku_transaction_rejection(empty.raw_payload, "FAILED") == (None, None, None)
    assert toku_transaction_rejection(None, "FAILED") == (None, None, None)


def test_consolidation_writes_rejection_columns(db_session: Session) -> None:  # noqa: F811
    failed, ok = _tx(_uid(), code="PEPSP1019", message="[78] Bloqueada"), _tx(_uid(), status="SUCCESS", code="SUTOK0000")
    db_session.add_all([failed, ok])
    db_session.flush()
    channel_consolidation._consolidate_toku_transactions(db_session)
    rows = {p.external_id: p for p in db_session.query(Payment).filter(
        Payment.source == "toku", Payment.external_id.in_([failed.external_id, ok.external_id]))}
    assert (rows[failed.external_id].rejection_code, rows[failed.external_id].rejection_reason) == ("PEPSP1019", "Bloqueada")
    assert rows[failed.external_id].rejected_at == datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    assert (rows[ok.external_id].rejection_code, rows[ok.external_id].rejected_at) == (None, None)


def test_backfill_is_idempotent_and_dry_run_does_not_write(db_session: Session) -> None:  # noqa: F811
    tx = _tx(_uid(), code="TEPSP2070", message="[91] RECHAZADA- SISTEMA EMISOR NO OPERATIVO")
    db_session.add(tx)
    payment = Payment(source="toku", external_id=tx.external_id, status="FAILED")
    db_session.add(payment)
    db_session.flush()

    dry = project_toku_payment_rejections(db_session, apply=False)
    assert dry["payments_updated"] >= 1 and dry["skipped"] is None
    db_session.expire(payment)
    assert payment.rejection_code is None

    project_toku_payment_rejections(db_session)
    db_session.expire(payment)
    assert payment.rejection_code == "TEPSP2070"
    assert payment.rejection_reason == "RECHAZADA- SISTEMA EMISOR NO OPERATIVO"

    again = project_toku_payment_rejections(db_session)
    assert again["payments_updated"] == 0
