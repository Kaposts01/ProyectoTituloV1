"""TK-18: carga de reportes de Toku a tk_report_*. Fixtures sinteticas; solo corre sobre `crm_test`."""

import logging
import os
import re
import time

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from toku_reports_support import (
    PEPPER,
    PII_SENTINELS,
    SENTINEL_MAIL,
    default_row,
    product_text,
    sub_id,
    write_report,
    write_unsupported,
)

from app.core.config import settings
from app.db.session import engine
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
from app.services import toku_report_import as svc
from app.services.toku_report_import import (
    MissingPepperError,
    ReportFormatError,
    ReportImportError,
    UnsupportedReportError,
    import_report,
    resolve_subscriptions,
    safe_report_error_message,
)
from app.services.toku_report_parser import hash_product_key

TABLES = (
    "tk_report_attempts", "tk_report_debts", "tk_report_inscriptions", "tk_report_payment_methods",
    "tk_report_products", "tk_report_response_codes", "tk_report_files", "core_subscription_signals",
)  # fmt: skip
OLD, NEW = "2026-08-09 09:00:00", "2026-10-20 10:00:00"


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


@pytest.fixture(autouse=True)
def pepper(monkeypatch):
    monkeypatch.setattr(settings, "toku_report_hash_pepper", PEPPER)


def _import(db, path, name=None):
    return import_report(db, path, filename=name or path.name, uploaded_by_user_id=None)


def _count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


def _wipe(db) -> None:
    for table in TABLES:
        db.execute(text(f"DELETE FROM {table}"))
    db.commit()


def _snapshot(db) -> dict:
    out = {}
    for table in TABLES[:-1]:
        if table == "tk_report_files":
            continue
        sql = (
            f"SELECT to_jsonb(t) - 'id' - 'created_at' - 'updated_at' - 'last_file_id' - 'source_file_id' AS j, "
            f"(SELECT f.generated_at::text FROM tk_report_files f WHERE f.id = t.{'source_file_id' if table.endswith('codes') else 'last_file_id'}) AS g "
            f"FROM {table} t"
        )
        out[table] = sorted((str(r.j), r.g) for r in db.execute(text(sql)))
    return out


# ---- pepper -----------------------------------------------------------------------------------


def test_missing_pepper_fails_closed(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "toku_report_hash_pepper", "")
    path = write_report(tmp_path / "p.xlsx", "productos")
    with pytest.raises(MissingPepperError, match="falta TOKU_REPORT_HASH_PEPPER"):
        _import(db_session, path)
    assert _count(db_session, TkReportFile) == 0 and _count(db_session, TkReportProduct) == 0


def test_missing_pepper_does_not_even_open_the_file(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "toku_report_hash_pepper", "")
    with pytest.raises(MissingPepperError):
        _import(db_session, tmp_path / "no-existe.xlsx")


# ---- carga basica y contadores ----------------------------------------------------------------


def test_import_products_counts_and_content(db_session, tmp_path):
    rows = [default_row("productos", i) for i in (1, 2, 3)] + [default_row("productos", 4, Cliente=None)]
    summary = _import(db_session, write_report(tmp_path / "p.xlsx", "productos", rows), name="C:\\x\\y\\p.xlsx")
    assert (summary.rows_total, summary.rows_new, summary.rows_updated, summary.rows_skipped) == (4, 3, 0, 1)
    assert summary.skip_reasons == {"missing_customer": 1} and not summary.already_loaded
    f = db_session.scalar(select(TkReportFile))
    assert f.status == "completed" and f.filename == "p.xlsx" and f.report_type == "productos"
    assert (f.rows_total, f.rows_new, f.rows_updated, f.rows_skipped) == (4, 3, 0, 1)
    assert f.generated_at is not None and str(f.window_start) == "2026-01-01" and f.finished_at is not None
    p = db_session.scalar(select(TkReportProduct).where(TkReportProduct.subscription_external_id == sub_id(1)))
    assert p.product_key_hash == hash_product_key(product_text(1), PEPPER) and len(p.product_key_hash) == 64
    assert p.payment_method_status == "chargeable" and p.payment_method_external_id == "pm_T0001"
    assert p.last_file_id == f.id and p.source_generated_at == f.generated_at


def test_all_types_import_and_catalog_severity(db_session, tmp_path):
    _import(db_session, write_report(tmp_path / "p.xlsx", "productos"))
    summary = _import(
        db_session,
        write_report(
            tmp_path / "i.xlsx", "intentos",
            [default_row("intentos", 1), default_row("intentos", 2, **{"Código de Respuesta Toku": "1019"}),
             default_row("intentos", 3, **{"Código de Respuesta Toku": "7777"})],
        ),
    )  # fmt: skip
    assert summary.catalog_codes == 4 and summary.unresolved_product == 0
    sev = {a.attempt_external_id: a.severity for a in db_session.scalars(select(TkReportAttempt))}
    assert sev == {"pi_T0001": "TE", "pi_T0002": "PE", "pi_T0003": "UNKNOWN"}
    att = db_session.scalar(select(TkReportAttempt).where(TkReportAttempt.attempt_external_id == "pi_T0001"))
    assert att.subscription_external_id == sub_id(1) and att.has_mandate is True and att.status == "FALLIDO"
    _import(db_session, write_report(tmp_path / "d.xlsx", "deudas"))
    debt = db_session.scalar(select(TkReportDebt).where(TkReportDebt.debt_external_id == "in_T0001"))
    assert str(debt.due_date) == "2026-10-05" and debt.paid is False and debt.subscription_external_id == sub_id(1)
    _import(db_session, write_report(tmp_path / "m.xlsx", "medios_pago"))
    _import(db_session, write_report(tmp_path / "s.xlsx", "inscripciones"))
    ins = db_session.scalar(select(TkReportInscription).where(TkReportInscription.inscription_external_id == "pmii_T0001"))
    assert ins.severity == "TE" and ins.response_code_full == "TEPSP1001" and ins.payment_method_external_id == "pm_T0001"
    assert ins.subscription_external_id == sub_id(1)
    assert _count(db_session, TkReportPaymentMethod) == 3


def test_payment_method_without_product_uses_empty_hash_and_same_pm_many_products(db_session, tmp_path):
    rows = [
        default_row("medios_pago", 1),
        default_row("medios_pago", 1, **{"ID Producto": product_text(9)}),
        default_row("medios_pago", 1, **{"ID Producto": None}),
    ]
    summary = _import(db_session, write_report(tmp_path / "m.xlsx", "medios_pago", rows))
    assert summary.rows_new == 3
    hashes = set(db_session.scalars(select(TkReportPaymentMethod.product_key_hash)))
    assert "" in hashes and len(hashes) == 3


def test_unsupported_and_invalid_files_create_no_file_row(db_session, tmp_path):
    with pytest.raises(UnsupportedReportError):
        _import(db_session, write_unsupported(tmp_path / "c.xlsx"))
    with pytest.raises(ReportFormatError) as exc:
        _import(db_session, write_report(tmp_path / "x.xlsx", "deudas", drop_columns=("Anulado",)))
    assert "anulado" in str(exc.value)
    assert _count(db_session, TkReportFile) == 0


# ---- idempotencia / frescura ------------------------------------------------------------------


def test_same_file_twice_is_already_loaded(db_session, tmp_path):
    path = write_report(tmp_path / "p.xlsx", "productos")
    first = _import(db_session, path)
    second = _import(db_session, path)
    assert second.already_loaded and second.status == "already_loaded" and second.file_id == first.file_id
    assert second.rows_new == first.rows_new == 3
    assert _count(db_session, TkReportFile) == 1 and _count(db_session, TkReportProduct) == 3


def test_same_report_different_sha_upserts_without_duplicates(db_session, tmp_path):
    _import(db_session, write_report(tmp_path / "a.xlsx", "productos", generated=OLD))
    rows = [default_row("productos", 1, Monto=20000), default_row("productos", 2), default_row("productos", 3),
            default_row("productos", 4)]  # fmt: skip
    summary = _import(db_session, write_report(tmp_path / "b.xlsx", "productos", rows, generated=NEW))
    assert (summary.rows_new, summary.rows_updated, summary.rows_stale) == (1, 3, 0)
    assert _count(db_session, TkReportProduct) == 4 and _count(db_session, TkReportFile) == 2
    amount = db_session.scalar(select(TkReportProduct.amount).where(TkReportProduct.subscription_external_id == sub_id(1)))
    assert int(amount) == 20000


def _freshness_files(tmp_path):
    old_rows = [default_row("productos", 1, Monto=1000, **{"Fecha de Eliminación": "2026-07-01T00:00:00"}),
                default_row("productos", 2, Monto=1000), default_row("productos", 3, Monto=1000)]  # fmt: skip
    new_rows = [default_row("productos", 1, Monto=2000), default_row("productos", 2, Monto=2000, Estado="permanent_failed")]
    return (
        write_report(tmp_path / "old.xlsx", "productos", old_rows, generated=OLD),
        write_report(tmp_path / "new.xlsx", "productos", new_rows, generated=NEW),
    )


def test_freshness_guard_old_after_new_does_not_overwrite(db_session, tmp_path):
    old, new = _freshness_files(tmp_path)
    _import(db_session, new)
    summary = _import(db_session, old)
    assert summary.rows_stale == 2 and summary.rows_new == 1 and summary.rows_updated == 0
    p2 = db_session.scalar(select(TkReportProduct).where(TkReportProduct.subscription_external_id == sub_id(2)))
    assert int(p2.amount) == 2000 and p2.payment_method_status == "permanent_failed"
    assert p2.source_generated_at.date().isoformat() == "2026-10-20"


def test_load_order_does_not_change_final_state(db_session, tmp_path):
    old, new = _freshness_files(tmp_path)
    _import(db_session, old)
    _import(db_session, new)
    forward = _snapshot(db_session)
    _wipe(db_session)
    _import(db_session, new)
    _import(db_session, old)
    backward = _snapshot(db_session)
    assert forward == backward and len(forward["tk_report_products"]) == 3


def test_deleted_at_source_is_never_undeleted_by_null(db_session, tmp_path):
    old, new = _freshness_files(tmp_path)  # old: sub 1 eliminado; new: sub 1 sin eliminacion (NULL)
    for first, second in ((old, new), (new, old)):
        _wipe(db_session)
        _import(db_session, first)
        _import(db_session, second)
        deleted = db_session.scalar(
            select(TkReportProduct.deleted_at_source).where(TkReportProduct.subscription_external_id == sub_id(1))
        )
        assert deleted is not None and deleted.date().isoformat() == "2026-07-01"


def test_newer_deletion_replaces_older_deletion(db_session, tmp_path):
    a = write_report(tmp_path / "a.xlsx", "productos", [default_row("productos", 1, **{"Fecha de Eliminación": "2026-05-01"})], generated=OLD)
    b = write_report(tmp_path / "b.xlsx", "productos", [default_row("productos", 1, **{"Fecha de Eliminación": "2026-09-01"})], generated=NEW)
    _import(db_session, a)
    _import(db_session, b)
    d = db_session.scalar(select(TkReportProduct.deleted_at_source))
    assert d.date().isoformat() == "2026-09-01"


def test_catalog_older_file_does_not_overwrite_newer_catalog(db_session, tmp_path):
    new_cat = [("Código Toku", "Gravedad", "Mensaje", "Descripción"), ("1001", "PE", "Mensaje nuevo", None)]
    old_cat = [("Código Toku", "Gravedad", "Mensaje", "Descripción"), ("1001", "TE", "Mensaje viejo", None)]
    _import(db_session, write_report(tmp_path / "n.xlsx", "intentos", [default_row("intentos", 1)], generated=NEW, catalog=new_cat))
    _import(db_session, write_report(tmp_path / "o.xlsx", "intentos", [default_row("intentos", 2)], generated=OLD, catalog=old_cat))
    code = db_session.scalar(select(TkReportResponseCode).where(TkReportResponseCode.code == "1001"))
    assert code.message == "Mensaje nuevo" and code.severity == "PE"


# ---- resolucion producto -> sub_ --------------------------------------------------------------


def test_product_resolution_resolved_unresolved_and_late(db_session, tmp_path):
    rows = [default_row("intentos", 1), default_row("intentos", 2), default_row("intentos", 77)]
    first = _import(db_session, write_report(tmp_path / "i.xlsx", "intentos", rows))
    assert first.unresolved_product == 3
    assert db_session.scalar(select(func.count()).select_from(TkReportAttempt).where(TkReportAttempt.subscription_external_id.is_(None))) == 3
    debts = _import(db_session, write_report(tmp_path / "d.xlsx", "deudas", [default_row("deudas", 1), default_row("deudas", 88)]))
    assert debts.unresolved_product == 2
    products = _import(db_session, write_report(tmp_path / "p.xlsx", "productos"))  # subs 1..3
    assert products.resolved_later == {"attempts": 2, "debts": 1}
    resolved = dict(db_session.execute(select(TkReportAttempt.attempt_external_id, TkReportAttempt.subscription_external_id)).all())
    assert resolved == {"pi_T0001": sub_id(1), "pi_T0002": sub_id(2), "pi_T0077": None}
    assert resolve_subscriptions(db_session) == {"attempts": 0, "debts": 0}  # idempotente


def test_resolution_prefers_non_deleted_subscription_for_same_hash(db_session, tmp_path):
    same = product_text(1)
    rows = [
        default_row("productos", 1, **{"ID Producto": same, "Fecha de Eliminación": "2026-02-01"}),
        default_row("productos", 2, **{"ID Producto": same}),
    ]
    _import(db_session, write_report(tmp_path / "p.xlsx", "productos", rows))
    _import(db_session, write_report(tmp_path / "i.xlsx", "intentos", [default_row("intentos", 1)]))
    assert db_session.scalar(select(TkReportAttempt.subscription_external_id)) == sub_id(2)


# ---- fallas y transaccion ---------------------------------------------------------------------


def test_fatal_chunk_rolls_back_everything_and_marks_failed(db_session, tmp_path, monkeypatch, caplog):
    rows = [default_row("productos", i) for i in range(1, 6)]
    path = write_report(tmp_path / "p.xlsx", "productos", rows)
    monkeypatch.setattr(svc, "CHUNK_SIZE", 2)
    real = svc._upsert_rows
    calls = []

    def boom(db, spec, chunk, generated_at):
        calls.append(len(chunk))
        if len(calls) == 2:
            raise RuntimeError(f"fila rota de {SENTINEL_MAIL} rut 00.000.001-K")
        return real(db, spec, chunk, generated_at)

    monkeypatch.setattr(svc, "_upsert_rows", boom)
    with caplog.at_level(logging.DEBUG), pytest.raises(ReportImportError) as exc:
        _import(db_session, path)
    assert calls == [2, 2]
    assert _count(db_session, TkReportProduct) == 0
    f = db_session.scalar(select(TkReportFile))
    assert f.status == "failed" and f.error_label == "load:RuntimeError" and f.finished_at is not None
    assert (f.rows_total, f.rows_new) == (0, 0)
    blob = str(exc.value) + repr(exc.value.detail) + f.error_label + caplog.text
    assert "00.000.001" not in blob and SENTINEL_MAIL not in blob
    assert exc.value.__cause__ is None and exc.value.label == f.error_label

    # reintento del mismo archivo despues de la falla: reutiliza la fila y completa
    monkeypatch.setattr(svc, "_upsert_rows", real)
    again = _import(db_session, path)
    assert again.rows_new == 5 and again.file_id == f.id and _count(db_session, TkReportFile) == 1
    assert db_session.scalar(select(TkReportFile.status)) == "completed"


def test_db_error_label_has_no_parameters(db_session, tmp_path):
    # due_day fuera de rango no pasa por el parser (queda None); forzamos una violacion real de BD
    # con un monto que desborda NUMERIC(14,2) mediante un registro construido a mano.
    from app.services import toku_report_parser as parser

    rec = parser.ProductRecord(sub_id(1), "a" * 64, "cus_T0001", None, None, None, None, 99, None, None, None)
    f = TkReportFile(report_type="productos", file_sha256="b" * 64, filename="x.xlsx")
    db_session.add(f)
    db_session.flush()
    row = {**vars(rec), "source_generated_at": f.created_at, "last_file_id": f.id}
    with pytest.raises(Exception) as exc:
        with db_session.begin_nested():
            svc._upsert_rows(db_session, svc._SPECS["productos"], [row], f.created_at)
    assert svc._failure_label("load", exc.value).startswith("load:IntegrityError/")


def test_safe_report_error_message_redacts_rut_email_and_long_numbers():
    exc = ValueError("rut 12.345.678-K y 12345678-5 mail juan.perez@example.invalid tarjeta 4111111111111111")
    msg = safe_report_error_message(exc)
    assert "12.345.678" not in msg and "juan" not in msg and "4111" not in msg and msg.count("[redacted]") == 4


# ---- chunking ---------------------------------------------------------------------------------


def test_attempts_file_over_chunk_size_is_loaded_in_chunks(db_session, tmp_path, monkeypatch):
    n = 2500
    rows = [default_row("intentos", i) for i in range(1, n + 1)]
    path = write_report(tmp_path / "i.xlsx", "intentos", rows)
    sizes = []
    real = svc._upsert_rows
    monkeypatch.setattr(svc, "_upsert_rows", lambda db, spec, chunk, g: (sizes.append(len(chunk)), real(db, spec, chunk, g))[1])
    summary = _import(db_session, path)
    assert sizes == [2000, 500] and summary.rows_new == n and summary.rows_total == n
    assert _count(db_session, TkReportAttempt) == n
    again = _import(db_session, write_report(tmp_path / "i2.xlsx", "intentos", rows, generated=NEW))
    assert again.rows_updated == n and again.rows_new == 0 and _count(db_session, TkReportAttempt) == n


@pytest.mark.skipif(not os.environ.get("TOKU_PERF_TEST"), reason="medicion manual: TOKU_PERF_TEST=1")
def test_perf_30000_attempts(db_session, tmp_path, capsys):
    n = 30000
    rows = [default_row("intentos", i) for i in range(1, n + 1)]
    path = write_report(tmp_path / "big.xlsx", "intentos", rows)
    t0 = time.perf_counter()
    summary = _import(db_session, path)
    elapsed = time.perf_counter() - t0
    with capsys.disabled():
        print(f"\n[perf] 30000 intentos: {elapsed:.1f} s ({n / elapsed:.0f} filas/s)")
    assert summary.rows_new == n


# ---- PII --------------------------------------------------------------------------------------


def test_no_pii_sentinels_in_any_table_logs_or_files(db_session, tmp_path, caplog):
    before = set(os.listdir(tmp_path))
    paths = [
        write_report(tmp_path / f"{t}.xlsx", t, extra_columns={"extra": "SENTINELA-COLUMNA-EXTRA"})
        for t in ("productos", "medios_pago", "intentos", "deudas", "inscripciones")
    ]
    generated = set(os.listdir(tmp_path)) - before
    with caplog.at_level(logging.DEBUG):
        for p in paths:
            _import(db_session, p, name=f"C:\\Users\\socio\\Downloads\\{p.name}")
    assert set(os.listdir(tmp_path)) == before | generated  # no se escribio ni copio ningun archivo

    needles = [s.lower() for s in (*PII_SENTINELS, "Donación Mensual", "donacion mensual", "00000001-K", "00000002-K", "01/01/2030")]
    total_rows = 0
    for table in TABLES:
        for (blob,) in db_session.execute(text(f"SELECT t::text FROM {table} t")):
            total_rows += 1
            low = blob.lower()
            for needle in needles:
                assert needle not in low, (table, needle)
            assert not re.search(r"\d{1,2}\.\d{3}\.\d{3}-[\dkK]", blob), table
    assert total_rows > 10
    assert _count(db_session, CoreSubscriptionSignal) == 0
    assert all(n not in caplog.text.lower() for n in needles)
    assert set(db_session.scalars(select(TkReportFile.filename))) <= {p.name for p in paths}

    columns = {r[0] for r in db_session.execute(text(
        "SELECT data_type FROM information_schema.columns WHERE table_name = 'tk_report_files'"
    ))}  # fmt: skip
    assert "bytea" not in columns  # el archivo no se guarda

