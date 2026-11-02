"""RJ-11 / backfill de TK-PAR-04: el reporte «Intentos de pago» completa el codigo de los FAILED sin codigo. Sinteticos."""

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import CoreCharge, CorePayment
from app.models.toku_channel import TokuTransaction
from app.models.toku_report import TkReportAttempt, TkReportFile
from app.services.toku_failed_payments import materialize_failed_toku_payments
from app.services.toku_rejection_projection import (
    load_report_attempt_codes,
    project_toku_rejections,
)
from tests.test_charge_recovery import db_session  # noqa: F401  (fixture)


def _uid(prefix: str = "rj11") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _file(db: Session) -> uuid.UUID:
    f = TkReportFile(report_type="intentos", file_sha256=hashlib.sha256(_uid().encode()).hexdigest(),
                     filename="Toku_intentosdepago.xlsx", status="completed")
    db.add(f)
    db.flush()
    return f.id


def _attempt(db: Session, file_id, *, attempt_id: str, debt: str, at: datetime, code: str | None,
             status: str = "FALLIDO", deleted: bool = False) -> None:
    db.add(TkReportAttempt(
        attempt_external_id=attempt_id, debt_external_id=debt, customer_external_id="cus_sintetico", status=status,
        attempted_at=at, response_code=code, severity="TE" if code else None,
        deleted_at_source=at if deleted else None, source_generated_at=at, last_file_id=file_id,
    ))
    db.flush()


def _tx(db: Session, invoice: str, date: str, *, code: str | None = None, message: str | None = None,
        intent_id: str | None = None) -> TokuTransaction:
    transaction = {"id": _uid("tx"), "status": "FAILED", "transaction_date": date}
    if code:
        transaction["response_code"] = code
    if message:
        transaction["original_response_message"] = message
    tx = TokuTransaction(external_id=transaction["id"], status="FAILED", created_at_api=date, amount="9990",
                         raw_payload={"transaction": transaction,
                                      "payment_intents": [{"id": intent_id or _uid("pi"), "id_invoice": invoice}]})
    db.add(tx)
    db.flush()
    return tx


def _charge(db: Session, invoice: str) -> CoreCharge:
    charge = CoreCharge(source="toku", external_id=invoice)
    db.add(charge)
    db.flush()
    return charge


def test_exact_match_by_payment_intent_id_fills_the_missing_code(db_session: Session) -> None:  # noqa: F811
    file_id = _file(db_session)
    inv, pi = _uid("in"), _uid("pi")
    charge = _charge(db_session, inv)
    _tx(db_session, inv, "2025-03-05T14:00:00", intent_id=pi)  # sin codigo ni glosa (nov-2024 a oct-2025)
    _attempt(db_session, file_id, attempt_id=pi, debt=inv, at=datetime(2025, 3, 5, 14, tzinfo=UTC), code="1008")
    stats = project_toku_rejections(db_session)
    assert stats["codes_from_report_by_id"] >= 1
    db_session.expire(charge)
    assert charge.latest_rejection_code == "1008"


def test_debt_and_chile_day_match_only_when_unambiguous(db_session: Session) -> None:  # noqa: F811
    file_id = _file(db_session)
    inv_ok, inv_amb = _uid("in"), _uid("in")
    ok, amb = _charge(db_session, inv_ok), _charge(db_session, inv_amb)
    # 02:30 UTC del 6 = 23:30 del 5 en Chile (UTC-3): el dia se compara en hora de Chile
    _tx(db_session, inv_ok, "2025-03-06T02:30:00")
    _attempt(db_session, file_id, attempt_id=_uid("pi"), debt=inv_ok, at=datetime(2025, 3, 5, 20, tzinfo=UTC), code="1019")
    _tx(db_session, inv_amb, "2025-03-05T15:00:00")
    _attempt(db_session, file_id, attempt_id=_uid("pi"), debt=inv_amb, at=datetime(2025, 3, 5, 13, tzinfo=UTC), code="1001")
    _attempt(db_session, file_id, attempt_id=_uid("pi"), debt=inv_amb, at=datetime(2025, 3, 5, 16, tzinfo=UTC), code="2070")
    project_toku_rejections(db_session)
    db_session.expire_all()
    assert ok.latest_rejection_code == "1019"
    assert amb.latest_rejection_code is None  # dos codigos distintos ese dia: ambiguo, no se usa


def test_api_code_wins_and_report_wins_over_iso(db_session: Session) -> None:  # noqa: F811
    file_id = _file(db_session)
    inv_api, inv_iso = _uid("in"), _uid("in")
    api, iso = _charge(db_session, inv_api), _charge(db_session, inv_iso)
    pi_api, pi_iso = _uid("pi"), _uid("pi")
    _tx(db_session, inv_api, "2025-03-05T14:00:00", code="TEPSP2070", intent_id=pi_api)
    _tx(db_session, inv_iso, "2025-03-05T14:00:00", message="[51] EXCEDE SALDO MAXIMO", intent_id=pi_iso)
    for pi, inv in ((pi_api, inv_api), (pi_iso, inv_iso)):
        _attempt(db_session, file_id, attempt_id=pi, debt=inv, at=datetime(2025, 3, 5, 14, tzinfo=UTC), code="1008")
    project_toku_rejections(db_session)
    db_session.expire_all()
    assert api.latest_rejection_code == "TEPSP2070"
    assert (iso.latest_rejection_code, iso.latest_rejection_reason) == ("1008", "EXCEDE SALDO MAXIMO")


def test_ignores_deleted_authorized_and_codeless_attempts(db_session: Session) -> None:  # noqa: F811
    file_id = _file(db_session)
    at = datetime(2025, 3, 5, 14, tzinfo=UTC)
    _attempt(db_session, file_id, attempt_id="pi_del", debt="in_x", at=at, code="1008", deleted=True)
    _attempt(db_session, file_id, attempt_id="pi_aut", debt="in_y", at=at, code="0000", status="AUTORIZADO")
    _attempt(db_session, file_id, attempt_id="pi_nul", debt="in_z", at=at, code=None)
    index = load_report_attempt_codes(db_session)
    assert not {"pi_del", "pi_aut", "pi_nul"} & set(index.by_id)


def test_backfill_is_idempotent_and_failed_payments_use_the_same_code(db_session: Session) -> None:  # noqa: F811
    file_id = _file(db_session)
    inv, pi = _uid("in"), _uid("pi")
    _charge(db_session, inv)
    tx = _tx(db_session, inv, "2025-03-05T14:00:00", intent_id=pi)
    _attempt(db_session, file_id, attempt_id=pi, debt=inv, at=datetime(2025, 3, 5, 14, tzinfo=UTC), code="1008")
    assert project_toku_rejections(db_session)["charges_updated"] >= 1
    assert project_toku_rejections(db_session)["charges_updated"] == 0  # segunda corrida: nada que escribir
    materialize_failed_toku_payments(db_session)
    payment = db_session.scalar(select(CorePayment).where(CorePayment.source == "toku", CorePayment.external_id == tx.external_id))
    assert payment.rejection_code == "1008"
