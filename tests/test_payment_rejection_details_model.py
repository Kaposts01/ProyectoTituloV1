"""RJ-12: esquema de payment_rejection_details (tabla unica de glosa de rechazo por canal; solo sobre crm_test)."""

import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.rejection import CAPTURE_SOURCES, PaymentRejectionDetail

ROOT = Path(__file__).resolve().parent.parent


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


def _detail(**overrides) -> PaymentRejectionDetail:
    values = dict(
        source="virtualpos1",
        charge_external_id="rj12-ch-" + uuid.uuid4().hex[:8],
        payment_external_id="rj12-pay-" + uuid.uuid4().hex[:8],
        code="-3",
        reason="Excede monto maximo",
        capture_source="api_charges",
    )
    values.update(overrides)
    return PaymentRejectionDetail(**values)


def test_single_head_and_review_0043_chained_a_0042():
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    assert len(script.get_heads()) == 1  # un solo head (no se fija cual: crece con cada migracion)
    assert script.get_revision("20261029_0044").down_revision == "20261029_0043"
    assert script.get_revision("20261029_0043").down_revision == "20261029_0042"


def test_table_columns_and_indexes_exist():
    insp = inspect(engine)
    assert "payment_rejection_details" in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("payment_rejection_details")}
    assert cols == {
        "id", "source", "charge_external_id", "payment_external_id", "subscription_external_id", "code", "reason",
        "acquirer_code", "doc_url", "amount", "rejected_at", "captured_at", "capture_source", "checked_at",
    }
    index_names = {i["name"] for i in insp.get_indexes("payment_rejection_details")}
    assert {
        "uq_prd_dedupe", "ix_prd_source_charge", "ix_prd_source_payment", "ix_prd_source_subscription",
        "ix_prd_checked_at",
    } <= index_names


def test_model_exposes_the_four_sources_of_capture():
    assert set(CAPTURE_SOURCES) == {"api_charges", "api_payment", "report_pat", "toku_projection"}


def test_inserts_and_recovers_with_values_by_default(db_session: Session) -> None:
    row = _detail()
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)
    assert row.captured_at is not None and row.checked_at is not None
    assert row.id is not None


def test_uniqueness_by_source_charge_payment_and_code(db_session: Session) -> None:
    first = _detail(code="-3")
    db_session.add(first)
    db_session.flush()
    db_session.add(_detail(source=first.source, charge_external_id=first.charge_external_id,
                           payment_external_id=first.payment_external_id, code="-3"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_other_code_or_source_for_the_same_charge_is_different(db_session: Session) -> None:
    first = _detail(code="-3")
    db_session.add(first)
    db_session.flush()
    db_session.add_all([
        _detail(source=first.source, charge_external_id=first.charge_external_id,
                payment_external_id=first.payment_external_id, code="-11"),
        _detail(source="virtualpos2", charge_external_id=first.charge_external_id,
                payment_external_id=first.payment_external_id, code="-3"),
    ])
    db_session.flush()


def test_uniqueness_also_when_the_payment_is_null(db_session: Session) -> None:
    """Rechazo sin pago asociado: NULL no debe permitir duplicados (indice con coalesce)."""
    first = _detail(payment_external_id=None)
    db_session.add(first)
    db_session.flush()
    db_session.add(_detail(source=first.source, charge_external_id=first.charge_external_id,
                           payment_external_id=None, code=first.code))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_capture_source_invalid_rejects(db_session: Session) -> None:
    db_session.add(_detail(capture_source="inventado"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_charge_or_payment_required(db_session: Session) -> None:
    db_session.add(_detail(charge_external_id=None, payment_external_id=None))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_without_columns_of_data_personal():
    cols = {c["name"] for c in inspect(engine).get_columns("payment_rejection_details")}
    forbidden = {"email", "rut", "social_id", "phone", "first_name", "last_name", "card_number", "raw_payload"}
    assert not (cols & forbidden)


def test_migracion_0043_define_downgrade():
    text_src = (ROOT / "alembic" / "versions" / "20261029_0043_payment_rejection_details.py").read_text(encoding="utf-8")
    assert "def downgrade" in text_src and 'op.drop_table("payment_rejection_details")' in text_src
    # Solo crea la tabla nueva: ninguna sentencia toca datos existentes.
    upper = text_src.upper()
    assert "UPDATE " not in upper and "INSERT " not in upper and "DELETE " not in upper
