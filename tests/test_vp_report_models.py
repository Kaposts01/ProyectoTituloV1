"""VP-PAR-02 (parte 1): modelo y migracion 20261029_0045 del importador de reportes PAT de VirtualPOS.

Datos 100% sinteticos. Sin columnas personales ni contenido de archivo.
"""

import importlib.util
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.vp_report import VpReportFile, VpReportPayment, VpReportSubscription

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "alembic" / "versions" / "20261029_0045_vp_report_tables.py"
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
SHA = "a" * 64

FORBIDDEN_COLUMNS = {
    "name", "nombre", "first_name", "last_name", "apellido", "mail", "email", "phone", "telefono", "rut",
    "social_id", "government_id", "birth_date", "gender", "address", "direccion", "comuna", "region", "raw_payload",
    "card_number", "pan", "cvv", "cvc", "seller_code", "seller_id",
}


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


def _expect_integrity(db: Session, obj) -> None:
    with pytest.raises(DBAPIError):  # IntegrityError (CHECK/UNIQUE) o DataError (columna demasiado corta)
        with db.begin_nested():
            db.add(obj)
            db.flush()


def _file(db: Session, report_type: str = "transacciones", sha: str | None = None) -> VpReportFile:
    f = VpReportFile(report_type=report_type, file_sha256=sha or uuid.uuid4().hex * 2, filename="synthetic.csv")
    db.add(f)
    db.flush()
    return f


def _payment(f: VpReportFile, charge: str = "cid_T0001", **kw) -> VpReportPayment:
    values = dict(charge_external_id=charge, source_generated_at=NOW, last_file_id=f.id)
    values.update(kw)
    return VpReportPayment(**values)


def _subscription(f: VpReportFile, sub: str = "S0001", **kw) -> VpReportSubscription:
    values = dict(subscription_external_id=sub, source_generated_at=NOW, last_file_id=f.id)
    values.update(kw)
    return VpReportSubscription(**values)


def test_tables_exist_and_have_no_personal_columns() -> None:
    insp = inspect(engine)
    for table in ("vp_report_files", "vp_report_payments", "vp_report_subscriptions"):
        assert insp.has_table(table), table
        columns = {c["name"] for c in insp.get_columns(table)}
        assert not (columns & FORBIDDEN_COLUMNS), (table, columns & FORBIDDEN_COLUMNS)


def test_expected_columns_are_promoted() -> None:
    insp = inspect(engine)
    pay = {c["name"] for c in insp.get_columns("vp_report_payments")}
    assert {
        "charge_external_id", "payment_external_id", "subscription_external_id", "platform", "platform_status",
        "charge_status", "scheduled_date", "amount", "response_code", "response_text", "payment_medium",
        "authorized_at", "processing_fee", "payout_amount", "payout_date", "pos_alias", "seller_code_hash",
        "subscription_origin", "charge_origin", "card_last4", "source_generated_at", "last_file_id",
    } <= pay
    sub = {c["name"] for c in insp.get_columns("vp_report_subscriptions")}
    assert {
        "subscription_external_id", "platform", "platform_status", "status", "canceled_at", "rejection_reason",
        "card_type", "card_brand", "card_last4", "pos_alias", "seller_code_hash", "channel_origin",
    } <= sub
    files = {c["name"] for c in insp.get_columns("vp_report_files")}
    assert {"file_sha256", "report_type", "filename", "rows_total", "window_start", "window_end", "loaded_at", "status"} <= files


def test_file_minimal_insert_and_defaults(db_session: Session) -> None:
    f = _file(db_session)
    row = db_session.get(VpReportFile, f.id)
    assert row.status == "running" and row.rows_total == 0 and row.loaded_at is not None


def test_file_sha256_is_unique_across_types(db_session: Session) -> None:
    _file(db_session, "transacciones", SHA)
    _expect_integrity(db_session, VpReportFile(report_type="transacciones", file_sha256=SHA, filename="x.csv"))
    _expect_integrity(db_session, VpReportFile(report_type="suscriptores", file_sha256=SHA, filename="x.csv"))


def test_file_checks(db_session: Session) -> None:
    _expect_integrity(db_session, VpReportFile(report_type="otro", file_sha256="b" * 64, filename="x"))
    _expect_integrity(db_session, VpReportFile(report_type="transacciones", file_sha256="XYZ", filename="x"))
    _expect_integrity(
        db_session, VpReportFile(report_type="transacciones", file_sha256="c" * 64, filename="x", status="raro")
    )
    _expect_integrity(
        db_session, VpReportFile(report_type="transacciones", file_sha256="d" * 64, filename="x", rows_total=-1)
    )


def test_payment_unique_charge_and_defaults(db_session: Session) -> None:
    f = _file(db_session)
    db_session.add(_payment(f, amount=Decimal("9990"), scheduled_date=date(2026, 10, 1), card_last4="1234"))
    db_session.flush()
    p = db_session.scalar(select(VpReportPayment))
    assert p.platform is None and p.platform_status == "unresolved" and p.created_at is not None
    _expect_integrity(db_session, _payment(f))


def test_payment_checks(db_session: Session) -> None:
    f = _file(db_session)
    _expect_integrity(db_session, _payment(f, "cid_A", card_last4="12345"))  # nunca un PAN
    _expect_integrity(db_session, _payment(f, "cid_B", card_last4="12a4"))
    _expect_integrity(db_session, _payment(f, "cid_C", seller_code_hash="no-es-hash"))
    _expect_integrity(db_session, _payment(f, "cid_D", platform_status="rara"))
    _expect_integrity(db_session, _payment(f, "cid_E", platform="virtualpos1", platform_status="unresolved"))
    _expect_integrity(db_session, _payment(f, "cid_F", platform=None, platform_status="resolved"))
    db_session.add(_payment(f, "cid_OK", platform="virtualpos2", platform_status="resolved", seller_code_hash="e" * 64))
    db_session.flush()


def test_subscription_unique_and_checks(db_session: Session) -> None:
    f = _file(db_session, "suscriptores")
    db_session.add(_subscription(f, card_last4="4321", card_type="TD", charges_total=12))
    db_session.flush()
    _expect_integrity(db_session, _subscription(f))
    _expect_integrity(db_session, _subscription(f, "S2", card_last4="123"))
    _expect_integrity(db_session, _subscription(f, "S3", platform_status="x"))


def test_foreign_key_to_file_is_enforced(db_session: Session) -> None:
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(VpReportPayment(charge_external_id="cid_X", source_generated_at=NOW, last_file_id=uuid.uuid4()))
            db_session.flush()


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_0045", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_is_linear_and_has_a_real_downgrade() -> None:
    mod = _load_migration()
    assert mod.revision == "20261029_0045" and mod.down_revision == "20261029_0044"
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1
    source = MIGRATION.read_text(encoding="utf-8")
    for table in ("vp_report_payments", "vp_report_subscriptions", "vp_report_files"):
        assert f'op.drop_table("{table}")' in source
