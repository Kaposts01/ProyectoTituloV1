"""TK-17: modelos y migraciones del importador de reportes de Toku. Datos 100% sinteticos."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import Base, engine
from app.models.auth import Permission, Role
from app.models.core import CoreSubscription
from app.models.toku_report import (
    CoreSubscriptionSignal,
    TkReportAttempt,
    TkReportDebt,
    TkReportFile,
    TkReportInscription,
    TkReportPaymentMethod,
    TkReportProduct,
    TkReportResponseCode,
)
from app.services.rbac import (
    PERMISSIONS,
    executive_permission_codes,
    seed_default_roles,
    seed_permissions,
    support_permission_codes,
)

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
SHA = "c" * 64
PERMISSION = "toku.reports.import"

FORBIDDEN_COLUMNS = {
    "name", "nombre", "mail", "email", "phone", "celular", "rut", "government_id", "token", "bin",
    "card_number", "numero_tarjeta", "account", "cuenta", "raw_payload", "external_id_cliente",
}  # fmt: skip


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
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(obj)
            db.flush()


def _file(db: Session, report_type: str = "productos", sha: str | None = None) -> TkReportFile:
    f = TkReportFile(report_type=report_type, file_sha256=sha or uuid.uuid4().hex * 2, filename="synthetic.xlsx")
    db.add(f)
    db.flush()
    return f


def _product(f: TkReportFile, sub: str = "sub_T0001", **kw) -> TkReportProduct:
    values = dict(
        subscription_external_id=sub, product_key_hash=HASH_A, customer_external_id="cus_T0001",
        source_generated_at=NOW, last_file_id=f.id,
    )  # fmt: skip
    values.update(kw)
    return TkReportProduct(**values)


def _attempt(f: TkReportFile, attempt: str = "pi_T0001", **kw) -> TkReportAttempt:
    values = dict(
        attempt_external_id=attempt, debt_external_id="in_T0001", customer_external_id="cus_T0001",
        source_generated_at=NOW, last_file_id=f.id,
    )  # fmt: skip
    values.update(kw)
    return TkReportAttempt(**values)


def _inscription(f: TkReportFile, ins: str = "pmii_T0001", **kw) -> TkReportInscription:
    values = dict(inscription_external_id=ins, source_generated_at=NOW, last_file_id=f.id)
    values.update(kw)
    return TkReportInscription(**values)


def _core_sub(db: Session, ext: str = "sub_T0001") -> CoreSubscription:
    sub = CoreSubscription(source="toku", external_id=ext)
    db.add(sub)
    db.flush()
    return sub


def _signal(sub: CoreSubscription, **kw) -> CoreSubscriptionSignal:
    values = dict(subscription_id=sub.id, source="toku", external_id=sub.external_id,
                  lifecycle_status="active", computed_at=NOW)  # fmt: skip
    values.update(kw)
    return CoreSubscriptionSignal(**values)


# ---- inserciones minimas ----------------------------------------------------------------------


def test_minimal_insert_each_table(db_session: Session) -> None:
    f = _file(db_session)
    db_session.add_all([
        TkReportResponseCode(code="0001", severity="SU", message="Aprobada", source_file_id=f.id),
        _product(f, amount=Decimal("5000.00"), due_day=15, is_recurring=True),
        TkReportPaymentMethod(
            payment_method_external_id="pm_T0001", source_generated_at=NOW, last_file_id=f.id
        ),
        _attempt(f, severity="UNKNOWN", amount=Decimal("5000")),
        TkReportDebt(
            debt_external_id="in_T0001", due_date=date(2026, 10, 5), amount=Decimal("5000"),
            paid=False, voided=False, source_generated_at=NOW, last_file_id=f.id,
        ),
        _inscription(f, severity="PE"),
    ])  # fmt: skip
    db_session.flush()
    pm = db_session.scalar(select(TkReportPaymentMethod))
    assert pm.product_key_hash == ""  # "sin producto"
    assert pm.created_at is not None and pm.updated_at is not None
    f_row = db_session.get(TkReportFile, f.id)
    assert f_row.status == "running" and f_row.rows_total == 0 and f_row.started_at is not None


# ---- UNIQUE de claves naturales -----------------------------------------------------------------


def test_unique_file_type_sha(db_session: Session) -> None:
    _file(db_session, "productos", SHA)
    _expect_integrity(db_session, TkReportFile(report_type="productos", file_sha256=SHA, filename="x.xlsx"))
    db_session.add(TkReportFile(report_type="intentos", file_sha256=SHA, filename="x.xlsx"))
    db_session.flush()  # mismo hash en otro tipo es valido


def test_unique_response_code(db_session: Session) -> None:
    db_session.add(TkReportResponseCode(code="0001", severity="SU", message="m"))
    db_session.flush()
    _expect_integrity(db_session, TkReportResponseCode(code="0001", severity="TE", message="m2"))


def test_unique_product_subscription(db_session: Session) -> None:
    f = _file(db_session)
    db_session.add(_product(f))
    db_session.flush()
    _expect_integrity(db_session, _product(f))


def test_payment_method_unique_per_product_allows_same_pm_other_product(db_session: Session) -> None:
    f = _file(db_session)

    def pm(h: str) -> TkReportPaymentMethod:
        return TkReportPaymentMethod(
            payment_method_external_id="pm_T0001", product_key_hash=h, source_generated_at=NOW, last_file_id=f.id
        )

    db_session.add_all([pm(HASH_A), pm(HASH_B), pm("")])
    db_session.flush()
    _expect_integrity(db_session, pm(HASH_A))
    _expect_integrity(db_session, pm(""))


def test_unique_attempt_debt_inscription(db_session: Session) -> None:
    f = _file(db_session)
    db_session.add_all([
        _attempt(f),
        TkReportDebt(
            debt_external_id="in_T0001", due_date=date(2026, 10, 5), amount=Decimal("1"),
            paid=True, voided=False, source_generated_at=NOW, last_file_id=f.id,
        ),
        _inscription(f),
    ])  # fmt: skip
    db_session.flush()
    _expect_integrity(db_session, _attempt(f))
    _expect_integrity(
        db_session,
        TkReportDebt(
            debt_external_id="in_T0001", due_date=date(2026, 11, 5), amount=Decimal("1"),
            paid=True, voided=False, source_generated_at=NOW, last_file_id=f.id,
        ),
    )  # fmt: skip
    _expect_integrity(db_session, _inscription(f))


# ---- CHECK -------------------------------------------------------------------------------------


def test_check_constraints(db_session: Session) -> None:
    f = _file(db_session)
    _expect_integrity(db_session, TkReportFile(report_type="otro", file_sha256="d" * 64, filename="x"))
    _expect_integrity(db_session, TkReportFile(report_type="pagos", file_sha256="d" * 64, filename="x", status="bad"))
    _expect_integrity(db_session, TkReportFile(report_type="pagos", file_sha256="XYZ", filename="x"))
    _expect_integrity(
        db_session, TkReportFile(report_type="pagos", file_sha256="e" * 64, filename="x", rows_skipped=-1)
    )
    _expect_integrity(db_session, TkReportResponseCode(code="01", severity="SU", message="m"))
    _expect_integrity(db_session, TkReportResponseCode(code="0002", severity="UNKNOWN", message="m"))
    _expect_integrity(db_session, _product(f, "sub_T0002", due_day=0))
    _expect_integrity(db_session, _product(f, "sub_T0003", due_day=32))
    _expect_integrity(db_session, _attempt(f, "pi_T0002", severity="XX"))
    _expect_integrity(db_session, _inscription(f, "pmii_T0002", severity="XX"))
    db_session.add_all([_product(f, "sub_T0004", due_day=31), _product(f, "sub_T0005", due_day=1)])
    db_session.flush()


def test_signal_check_constraints(db_session: Session) -> None:
    sub = _core_sub(db_session)
    _expect_integrity(db_session, _signal(sub, lifecycle_status="zombie"))
    _expect_integrity(db_session, _signal(sub, last_response_severity="XX"))
    _expect_integrity(db_session, _signal(sub, recoverable_reason="other"))
    _expect_integrity(db_session, _signal(sub, consecutive_failed_debts=-1))
    _expect_integrity(db_session, _signal(sub, consecutive_failed_attempts=-1))
    db_session.add(_signal(sub, recoverable_reason="expired_card", last_response_severity="UNKNOWN"))
    db_session.flush()


# ---- senales: FK, CASCADE, defaults, unicidad ------------------------------------------------------


def test_signal_defaults_and_unique(db_session: Session) -> None:
    sub = _core_sub(db_session)
    signal = _signal(sub)
    db_session.add(signal)
    db_session.flush()
    db_session.refresh(signal)
    assert signal.is_chargeable is False
    assert signal.is_effectively_active is False
    assert signal.is_recoverable is False
    assert signal.consecutive_failed_debts == 0 and signal.consecutive_failed_attempts == 0
    assert signal.recoverable_reason is None and signal.last_response_severity is None
    assert signal.created_at is not None and signal.updated_at is not None
    _expect_integrity(db_session, _signal(sub))  # UNIQUE(subscription_id)
    other = _core_sub(db_session, "sub_T0002")
    _expect_integrity(db_session, _signal(other, external_id="sub_T0001"))  # UNIQUE(source, external_id)


def test_signal_fk_requires_subscription_and_cascades(db_session: Session) -> None:
    _expect_integrity(db_session, _signal(CoreSubscription(id=uuid.uuid4(), source="toku", external_id="x")))
    sub = _core_sub(db_session)
    db_session.add(_signal(sub))
    db_session.flush()
    db_session.execute(text("DELETE FROM core_subscriptions WHERE id = :id"), {"id": sub.id})
    assert db_session.scalar(select(CoreSubscriptionSignal).where(CoreSubscriptionSignal.subscription_id == sub.id)) is None


# ---- permiso ----------------------------------------------------------------------------------


def test_permission_in_catalog_and_admin_only(db_session: Session) -> None:
    assert PERMISSION in PERMISSIONS and not PERMISSION.endswith(".view")
    admin = db_session.scalar(select(Role).where(Role.name == "admin"))
    if admin is None:
        admin = Role(name="admin", description="admin")
        db_session.add(admin)
        db_session.flush()
    seed_permissions(db_session)
    db_session.refresh(admin)
    assert PERMISSION in {p.code for p in admin.permissions}
    assert db_session.scalar(select(Permission).where(Permission.code == PERMISSION)).description


def test_support_and_executive_do_not_have_permission(db_session: Session) -> None:
    assert PERMISSION not in support_permission_codes()
    assert PERMISSION not in executive_permission_codes()
    seed_permissions(db_session)
    seed_default_roles(db_session)
    for name in ("soporte", "ejecutivo"):
        role = db_session.scalar(select(Role).where(Role.name == name))
        assert role is not None
        assert PERMISSION not in {p.code for p in role.permissions}


# ---- guarda de PII ------------------------------------------------------------------------------


def test_pii_guard_no_forbidden_columns() -> None:
    tables = [
        t for name, t in Base.metadata.tables.items()
        if name.startswith("tk_report_") or name == "core_subscription_signals"
    ]  # fmt: skip
    assert len(tables) == 8
    offenders = [f"{t.name}.{c.name}" for t in tables for c in t.columns if c.name.lower() in FORBIDDEN_COLUMNS]
    assert not offenders, offenders
    # tampoco columnas JSON/crudas
    raw = [f"{t.name}.{c.name}" for t in tables for c in t.columns if "payload" in c.name or "raw" in c.name]
    assert not raw, raw
