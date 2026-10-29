"""VP-PAR-08 / PK-PAR-08 (parte de codigo): `scripts/diagnostics/parity_check.py`, conteos por canal, mes y estado.

El script es de SOLO LECTURA: cuenta filas ya cargadas en la base (nunca lee reportes ni llama a un proveedor) y
no imprime datos personales: solo canal, entidad, mes, estado, cantidad y suma de montos.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.crm import Charge, Payment
from app.models.tch import TchRecaudacionMensual, TchTransaccion
from app.services import rejected_month
from scripts.diagnostics import parity_check


@pytest.fixture(autouse=True)
def chile_today(monkeypatch):
    monkeypatch.setattr(rejected_month, "now_chile", lambda: datetime(2026, 10, 29, 12, tzinfo=rejected_month.CHILE_TZ))


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


def _charge(source, status, date_, amount="1000"):
    return Charge(source=source, external_id=f"pc-{uuid.uuid4().hex[:12]}", status=status, charge_date=date_, amount=amount)


def _pay(source, status, date_, amount="500"):
    return Payment(source=source, external_id=f"pp-{uuid.uuid4().hex[:12]}", status=status, payment_date=date_, amount=amount)


def _rows(db, channel, **kw):
    return {(r["entity"], r["month"], r["status"]): (r["count"], r["amount"]) for r in parity_check.collect(db, channel, **kw)}


def _delta(after, before, key):
    return tuple(a - b for a, b in zip(after.get(key, (0, 0)), before.get(key, (0, 0)), strict=True))


def test_virtualpos_counts_charges_and_payments_by_month_and_status(db_session) -> None:
    before = _rows(db_session, "virtualpos")
    db_session.add_all([
        _charge("virtualpos1", "pagado", "2026-08-05"), _charge("virtualpos2", "pagado", "2026-08-20", "2000"),
        _charge("virtualpos1", "rechazado", "2026-08-06"), _charge("virtualpos1", "cancelado", "2026-08-07"),
        _charge("toku", "pagado", "2026-08-05"),  # otro canal: no cuenta
        _pay("virtualpos1", "AUTHORIZED", "2026-08-05T10:00:00"),
    ])
    db_session.flush()
    after = _rows(db_session, "virtualpos")
    assert _delta(after, before, ("charge", "2026-08", "pagado")) == (2, 3000)
    assert _delta(after, before, ("charge", "2026-08", "rechazado")) == (1, 1000)
    assert _delta(after, before, ("charge", "2026-08", "cancelado")) == (1, 1000)
    assert _delta(after, before, ("payment", "2026-08", "AUTHORIZED")) == (1, 500)


def test_future_charges_are_excluded_by_default_and_included_on_request(db_session) -> None:
    before = _rows(db_session, "virtualpos")
    db_session.add_all([_charge("virtualpos1", "cancelado", "2027-02-05"), _charge("virtualpos1", "cancelado", "2026-10-29")])
    db_session.flush()
    default = _rows(db_session, "virtualpos")
    assert _delta(default, before, ("charge", "2027-02", "cancelado")) == (0, 0)
    assert _delta(default, before, ("charge", "2026-10", "cancelado")) == (1, 1000)  # hoy no es futuro
    with_future = _rows(db_session, "virtualpos", include_future=True)
    assert with_future[("charge", "2027-02", "cancelado")][0] >= 1


def test_month_range_filters(db_session) -> None:
    db_session.add_all([_charge("toku", "PAID", "2026-01-10"), _charge("toku", "PAID", "2026-03-10"), _charge("toku", "PAID", "2026-06-10")])
    db_session.flush()
    rows = _rows(db_session, "toku", from_month="2026-02", to_month="2026-04")
    assert ("charge", "2026-03", "PAID") in rows
    assert ("charge", "2026-01", "PAID") not in rows and ("charge", "2026-06", "PAID") not in rows


def test_payku_and_toku_channels_are_separated(db_session) -> None:
    db_session.add_all([_pay("payku", "success", "2026-05-02"), _charge("payku", "x", "2026-05-02"), _pay("toku", "PAID", "2026-05-02")])
    db_session.flush()
    payku = parity_check.collect(db_session, "payku")
    assert {r["channel"] for r in payku} == {"payku"}
    toku = parity_check.collect(db_session, "toku")
    assert {r["channel"] for r in toku} == {"toku"}


def test_tch_counts_transactions_by_period_and_the_monthly_control(db_session) -> None:
    before = _rows(db_session, "tch")
    db_session.add_all([
        TchTransaccion(numero_ficha=9_990_001, periodo="2026-07", estado="ACEPTADA", monto="5000", dedupe_key=f"pc-{uuid.uuid4().hex}"),
        TchTransaccion(numero_ficha=9_990_002, periodo="2026-07", estado="RECHAZADA", monto="$5.000", dedupe_key=f"pc-{uuid.uuid4().hex}"),
        TchRecaudacionMensual(periodo="2099-01", aceptadas_cantidad=10, aceptadas_monto="50000", rechazadas_cantidad=2,
                              rechazadas_monto="10000", archivo_origen="x.xlsx"),
    ])
    db_session.flush()
    after = _rows(db_session, "tch", include_future=True)
    assert _delta(after, before, ("transaction", "2026-07", "ACEPTADA"))[0] == 1
    assert _delta(after, before, ("transaction", "2026-07", "RECHAZADA")) == (1, 0)  # monto no numerico: no suma
    assert after[("control_mensual", "2099-01", "ACEPTADA")] == (10, 50000)
    assert after[("control_mensual", "2099-01", "RECHAZADA")] == (2, 10000)


def test_unknown_channel_is_rejected(db_session) -> None:
    with pytest.raises(ValueError):
        parity_check.collect(db_session, "otro")


def test_table_output_is_aligned_and_has_no_free_text(db_session) -> None:
    rows = [{"channel": "toku", "entity": "charge", "month": "2026-03", "status": "PAID", "count": 7, "amount": 1234.5}]
    text = parity_check.format_table(rows)
    lines = text.splitlines()
    assert lines[0].split() == ["canal", "entidad", "mes", "estado", "cantidad", "monto"]
    assert set(lines[1]) <= {"-", " "}
    assert lines[2].split() == ["toku", "charge", "2026-03", "PAID", "7", "1.234,50"]
    assert parity_check.format_table([]).strip() == "(sin filas)"


def test_cli_prints_one_table_per_channel_and_reads_only(db_session, monkeypatch, capsys) -> None:
    db_session.add(_charge("payku", "x", "2026-05-02"))
    db_session.flush()
    monkeypatch.setattr(parity_check, "open_readonly_session", lambda: db_session)
    assert parity_check.main(["--channel", "payku", "--from", "2026-05", "--to", "2026-05"]) == 0
    out = capsys.readouterr().out
    assert "canal" in out and "payku" in out and "2026-05" in out
    # el script no escribe: el unico SQL de control es SET TRANSACTION READ ONLY (lo cubre otro test)


def test_open_readonly_session_sets_a_read_only_transaction() -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    db = parity_check.open_readonly_session()
    try:
        with pytest.raises(DBAPIError):
            db.execute(text("CREATE TABLE parity_check_should_fail (x int)"))
    finally:
        db.rollback()
        db.close()


def test_cli_rejects_a_bad_month_or_channel() -> None:
    with pytest.raises(SystemExit):
        parity_check.main(["--channel", "otro"])
    with pytest.raises(SystemExit):
        parity_check.main(["--from", "2026-13"])
