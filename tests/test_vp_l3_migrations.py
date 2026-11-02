# ruff: noqa: DTZ001  (las columnas vp_* son timestamp SIN zona: se comparan datetimes ingenuos)
"""Migraciones 0060 (VP-PAR-07/09) y 0061 (VP-PAR-13) con datos sinteticos sucios, ida y vuelta, solo en `*_test`.

Cada prueba baja a la revision anterior, inserta filas sinteticas con SQL crudo (el modelo ya esta en la forma de
`head`), sube, verifica la conversion y el log, vuelve a bajar y sube a `head`. Las filas se borran al final.
"""

import importlib.util
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from alembic import command

ROOT = Path(__file__).resolve().parent.parent
VERSIONS = ROOT / "alembic" / "versions"
PREFIX = "zzl3-"  # external_id de las filas de esta prueba


def _load(pattern: str):
    path = next(VERSIONS.glob(pattern))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cfg() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    return cfg


@pytest.fixture
def test_engine():
    from app.core.config import settings
    from app.db.session import engine

    if not (make_url(settings.database_url).database or "").endswith("_test"):
        pytest.skip("settings no apunta a una base *_test; no se ejecuta por seguridad.")
    yield engine
    with engine.begin() as conn:
        for table in ("core_subscriptions", "vp_report_subscriptions", "vp_report_payments", "vp_payments",
                      "vp_subscriptions", "vp_charges", "vp_plans"):
            column = {"vp_report_subscriptions": "subscription_external_id",
                      "vp_report_payments": "charge_external_id"}.get(table, "external_id")
            conn.execute(text(f"DELETE FROM {table} WHERE {column} LIKE :p"), {"p": PREFIX + "%"})
        conn.execute(text("DELETE FROM vp_report_files WHERE filename LIKE :p"), {"p": PREFIX + "%"})
    command.upgrade(_cfg(), "head")


def _columns(engine, table: str) -> dict[str, str]:
    return {c["name"]: str(c["type"]) for c in inspect(engine).get_columns(table)}


def test_chain_0060_0061() -> None:
    m60, m61 = _load("*_0060_vp_promoted_columns.py"), _load("*_0061_vp_typed_columns.py")
    assert (m60.revision, m60.down_revision) == ("20261102_0060", "20261102_0054")
    assert (m61.revision, m61.down_revision) == ("20261102_0061", "20261102_0060")


# ── 0060 ──────────────────────────────────────────────────────────────────────

_PAYMENTS = {
    # pagado: todo convertible
    "pay-ok": {"order": {"authorized_at": "2021-09-08 11:21:31", "deposits": [
        {"processing_fee": 117, "payout_amount": 9783, "payout_date": "2021-09-21"}]}, "client": {"social_id": "1-9"}},
    # pendiente: la API manda "" (no es un error: queda NULL sin contarse como no convertible)
    "pay-pending": {"order": {"authorized_at": "", "deposits": []}, "client": {"social_id": ""}},
    # detalle (`payment.order`) con valores sucios: fecha imposible, monto con texto, fecha de abono basura
    "pay-dirty": {"payment": {"order": {"authorized_at": "2021-02-30 10:00:00", "deposits": [
        {"processing_fee": "12a", "payout_amount": "9783.50", "payout_date": "pronto"}]}}},
    "pay-null": None,
}

_SUBSCRIPTIONS = {
    "sub-api": {"payment_method": {"last4CardDigit": "6623", "brand": "VISA", "card_type": "TC"},
                "terminal_pos": "POS 1", "origin": "WEB"},
    "sub-report": {"payment_method": {"last4CardDigit": "66"}},  # ultimos 4 invalidos: no se promueven
    "sub-none": {"terminal_pos": {"raro": 1}, "origin": ""},
}


def _seed_0060(conn) -> None:
    for ext, raw in _PAYMENTS.items():
        conn.execute(text("INSERT INTO vp_payments (id, external_id, platform, raw_payload) "
                          "VALUES (:id, :ext, 'virtualpos1', CAST(:raw AS jsonb))"),
                     {"id": uuid.uuid4(), "ext": PREFIX + ext, "raw": None if raw is None else _json(raw)})
    for ext, raw in _SUBSCRIPTIONS.items():
        conn.execute(text("INSERT INTO vp_subscriptions (id, external_id, platform, status, raw_payload) "
                          "VALUES (:id, :ext, 'virtualpos1', 'FALLIDA', CAST(:raw AS jsonb))"),
                     {"id": uuid.uuid4(), "ext": PREFIX + ext, "raw": _json(raw)})
        conn.execute(text("INSERT INTO core_subscriptions (id, source, external_id, status) "
                          "VALUES (:id, 'virtualpos1', :ext, 'FALLIDA')"), {"id": uuid.uuid4(), "ext": PREFIX + ext})
    file_id = uuid.uuid4()
    conn.execute(text("INSERT INTO vp_report_files (id, report_type, file_sha256, filename, status) "
                      "VALUES (:id, 'suscriptores', :sha, :name, 'completed')"),
                 {"id": file_id, "sha": uuid.uuid4().hex * 2, "name": PREFIX + "SuscriptoresPAT.csv"})
    for ext, last4, reason in (("sub-api", "9999", None), ("sub-report", "2222", "  Rechazo del emisor  ")):
        conn.execute(text("INSERT INTO vp_report_subscriptions (id, subscription_external_id, platform, platform_status,"
                          " card_last4, rejection_reason, source_generated_at, last_file_id) VALUES (:id, :ext,"
                          " 'virtualpos1', 'resolved', :l4, :reason, now(), :file)"),
                     {"id": uuid.uuid4(), "ext": PREFIX + ext, "l4": last4, "reason": reason, "file": file_id})


def _json(value) -> str:
    import json

    return json.dumps(value)


def test_0060_backfills_from_raw_payload_with_dirty_data_and_roundtrips(test_engine, caplog) -> None:
    cfg = _cfg()
    command.downgrade(cfg, "20261102_0054")
    assert "authorized_at" not in _columns(test_engine, "vp_payments")
    with test_engine.begin() as conn:
        _seed_0060(conn)

    with caplog.at_level(logging.INFO, logger="alembic.vp_l3"):
        command.upgrade(cfg, "20261102_0060")
    with test_engine.connect() as conn:
        pays = {r.external_id.removeprefix(PREFIX): r for r in conn.execute(text(
            "SELECT external_id, client_social_id, authorized_at, processing_fee, payout_amount, payout_date "
            "FROM vp_payments WHERE external_id LIKE :p"), {"p": PREFIX + "%"})}
        subs = {r.external_id.removeprefix(PREFIX): r for r in conn.execute(text(
            "SELECT external_id, card_type, card_brand, card_last4, terminal_pos, origin "
            "FROM vp_subscriptions WHERE external_id LIKE :p"), {"p": PREFIX + "%"})}
        core = {r.external_id.removeprefix(PREFIX): r for r in conn.execute(text(
            "SELECT external_id, rejection_reason, card_last4, card_last4_source "
            "FROM core_subscriptions WHERE external_id LIKE :p"), {"p": PREFIX + "%"})}
    assert len(pays) == 4 and len(subs) == 3 and len(core) == 3  # sin perder filas

    ok = pays["pay-ok"]
    assert (ok.client_social_id, ok.authorized_at, ok.processing_fee, ok.payout_amount, ok.payout_date) == (
        "1-9", datetime(2021, 9, 8, 11, 21, 31), Decimal("117"), Decimal("9783"), date(2021, 9, 21))
    pending = pays["pay-pending"]
    assert (pending.client_social_id, pending.authorized_at, pending.processing_fee) == (None, None, None)
    dirty = pays["pay-dirty"]
    assert (dirty.authorized_at, dirty.processing_fee, dirty.payout_amount, dirty.payout_date) == (
        None, None, Decimal("9783.50"), None)
    assert pays["pay-null"].authorized_at is None

    assert (subs["sub-api"].card_type, subs["sub-api"].card_brand, subs["sub-api"].card_last4,
            subs["sub-api"].terminal_pos, subs["sub-api"].origin) == ("TC", "VISA", "6623", "POS 1", "WEB")
    assert subs["sub-report"].card_last4 is None
    assert (subs["sub-none"].terminal_pos, subs["sub-none"].origin) == (None, None)

    # VP-PAR-09: la API manda, el reporte completa; motivo solo del reporte.
    assert (core["sub-api"].card_last4, core["sub-api"].card_last4_source, core["sub-api"].rejection_reason) == (
        "6623", "api", None)
    assert (core["sub-report"].card_last4, core["sub-report"].card_last4_source,
            core["sub-report"].rejection_reason) == ("2222", "report", "Rechazo del emisor")
    assert (core["sub-none"].card_last4, core["sub-none"].card_last4_source) == (None, None)

    messages = "\n".join(r.getMessage() for r in caplog.records if r.name == "alembic.vp_l3")
    # pay-dirty: authorized_at, processing_fee y payout_date informados pero no convertibles.
    assert "no convertibles (quedan NULL): authorized_at=1, processing_fee=1, payout_amount=0, payout_date=1" in messages

    command.downgrade(cfg, "20261102_0054")
    assert not {"authorized_at", "processing_fee", "client_social_id"} & set(_columns(test_engine, "vp_payments"))
    assert not {"card_last4", "rejection_reason"} & set(_columns(test_engine, "core_subscriptions"))
    with test_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM vp_payments WHERE external_id LIKE :p"),
                            {"p": PREFIX + "%"}).scalar() == 4


# ── 0061 ──────────────────────────────────────────────────────────────────────

P = "virtualpos1"
TODAY = date(2026, 11, 2)

# (external_id, suscripcion, estado, charge_date, amount): texto tal como lo guardaba la sync antes de la 0061.
_CHARGES = (
    ("c-a1", "s-a", "pagado", "2026-09-05", "5000"),
    ("c-a2", "s-a", "pagado", "2026-10-05", "6000"),     # ultimo pagado <= hoy: monto vigente de s-a
    ("c-a3", "s-a", "pagado", "2027-01-05", "8888"),     # futuro: no cuenta
    ("c-b1", "s-b", "pagado", "2026-10-10", "n/a"),      # sucio: monto no numerico
    ("c-b2", "s-b", "pagado", "2026-09-10", "4500"),
    ("c-c1", "s-c", "pagado", "pronto", "7000"),         # sucio: fecha no convertible
    ("c-c2", "s-c", "procesando", "2026-10-20 10:15:00", " 7100 "),
    ("c-d1", "s-d", "rechazado", "2026-10-01", ""),      # vacio: NULL, no cuenta como no convertible
)
_SUBS = (  # (external_id, amount, suscription_date, canceled_at)
    ("s-a", "5000", "2021-09-08 11:20:31", None),
    ("s-b", "abc", "2026-02-30 10:00:00", ""),           # sucios: monto y fecha imposible
    ("s-c", "100", "2026-01-05", "2026-10-29"),
    ("s-d", "3000", "2026-03-01 08:00:00", "2026-10-31 23:59:59"),
)
_PAYS = (("p-1", "9990", "2021-09-08 11:21:31"), ("p-2", "12a", "mañana"))
_EXPECTED_LOST = {
    "vp_plans.amount": 1, "vp_subscriptions.amount": 1, "vp_subscriptions.suscription_date": 1,
    "vp_subscriptions.canceled_at": 0, "vp_charges.amount": 1, "vp_charges.charge_date": 1,
    "vp_payments.amount": 1, "vp_payments.payment_date": 1,
}


def _seed_0061(conn) -> None:
    for ext, amount in (("plan-1", "3500"), ("plan-2", "x")):
        conn.execute(text("INSERT INTO vp_plans (id, external_id, platform, amount) VALUES (:id, :ext, :p, :a)"),
                     {"id": uuid.uuid4(), "ext": PREFIX + ext, "p": P, "a": amount})
    for ext, amount, started, canceled in _SUBS:
        conn.execute(text("INSERT INTO vp_subscriptions (id, external_id, platform, status, amount, suscription_date,"
                          " canceled_at) VALUES (:id, :ext, :p, 'ACTIVA', :a, :s, :c)"),
                     {"id": uuid.uuid4(), "ext": PREFIX + ext, "p": P, "a": amount, "s": started, "c": canceled})
    for ext, sub, status, day, amount in _CHARGES:
        conn.execute(text("INSERT INTO vp_charges (id, external_id, platform, subscription_external_id, status,"
                          " charge_date, amount) VALUES (:id, :ext, :p, :sub, :st, :d, :a)"),
                     {"id": uuid.uuid4(), "ext": PREFIX + ext, "p": P, "sub": PREFIX + sub, "st": status, "d": day,
                      "a": amount})
    for ext, amount, paid in _PAYS:
        conn.execute(text("INSERT INTO vp_payments (id, external_id, platform, amount, payment_date)"
                          " VALUES (:id, :ext, :p, :a, :d)"),
                     {"id": uuid.uuid4(), "ext": PREFIX + ext, "p": P, "a": amount, "d": paid})
    # Ventana de la paridad VP-PAR-11: dos cobros del reporte, 2026-09-01 a 2026-10-31.
    file_id = uuid.uuid4()
    conn.execute(text("INSERT INTO vp_report_files (id, report_type, file_sha256, filename, status)"
                      " VALUES (:id, 'transacciones', :sha, :name, 'completed')"),
                 {"id": file_id, "sha": uuid.uuid4().hex * 2, "name": PREFIX + "TransaccionesPAT.csv"})
    for ext, day in (("r-1", "2026-09-01"), ("r-2", "2026-10-31")):
        conn.execute(text("INSERT INTO vp_report_payments (id, charge_external_id, platform_status, scheduled_date,"
                          " source_generated_at, last_file_id) VALUES (:id, :ext, 'unresolved', :d, now(), :f)"),
                     {"id": uuid.uuid4(), "ext": PREFIX + ext, "d": day, "f": file_id})


def _old_kpis(conn) -> tuple[dict, dict]:
    """Los mismos KPIs con las consultas sobre TEXTO de antes de la 0061 (`vp_current_amount`, `vp_parity`)."""
    current = {r[0]: Decimal(r[1].strip()) for r in conn.execute(text(r"""
        SELECT DISTINCT ON (platform, subscription_external_id) subscription_external_id, amount
        FROM vp_charges
        WHERE platform = :p AND subscription_external_id LIKE :pref AND charge_date IS NOT NULL
          AND lower(trim(status)) IN ('pagado', 'procesando') AND substr(charge_date, 1, 10) <= :today
          AND amount ~ '^\s*\d+(\.\d+)?\s*$'
        ORDER BY platform, subscription_external_id, charge_date DESC, external_id DESC
    """), {"p": P, "pref": PREFIX + "%", "today": TODAY.isoformat()})}
    parity = dict(conn.execute(text(r"""
        SELECT substring(charge_date, 1, 7), count(*) FROM vp_charges
        WHERE charge_date ~ '^\d{4}-\d{2}-\d{2}'
          AND substring(charge_date, 1, 10) BETWEEN '2026-09-01' AND '2026-10-31'
        GROUP BY 1
    """)).all())
    return current, parity


def _new_kpis(engine) -> tuple[dict, dict]:
    from sqlalchemy.orm import Session

    from app.services.vp_current_amount import load_current_amount
    from app.services.vp_parity import compute_vp_parity

    with Session(bind=engine) as db:
        current = {sub: amount for (_src, sub), amount in load_current_amount(
            db, family="vp", sources=[P], today=TODAY, subscription_ids=[PREFIX + s for s, *_ in _SUBS]).items()}
        parity = {m.month: m.base for m in compute_vp_parity(db).months if m.base}
    return current, parity


def _lost_by_column(messages: str) -> dict[str, int]:
    out = {}
    for line in messages.splitlines():
        if line.startswith("0061 ") and "no convertibles (quedan NULL)" in line:
            column, rest = line.removeprefix("0061 ").split(": ", 1)
            out[column] = int(rest.split(" informadas, ")[1].split()[0])
    return out


def _rows(conn, sql: str) -> dict:
    return {r[0].removeprefix(PREFIX): tuple(r[1:]) for r in conn.execute(text(sql), {"p": PREFIX + "%"})}


def test_0061_alters_types_without_losing_rows_and_keeps_kpis(test_engine, caplog) -> None:
    cfg = _cfg()
    command.downgrade(cfg, "20261102_0060")
    assert _columns(test_engine, "vp_charges")["charge_date"].startswith("VARCHAR")
    tables = ("vp_plans", "vp_subscriptions", "vp_charges", "vp_payments")
    with test_engine.begin() as conn:
        _seed_0061(conn)
        old_current, old_parity = _old_kpis(conn)
        before = {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in tables}

    with caplog.at_level(logging.INFO, logger="alembic.vp_l3"):
        command.upgrade(cfg, "20261102_0061")

    cols = {t: _columns(test_engine, t) for t in tables}
    assert (cols["vp_charges"]["amount"], cols["vp_charges"]["charge_date"]) == ("NUMERIC", "DATE")
    assert (cols["vp_subscriptions"]["suscription_date"], cols["vp_subscriptions"]["canceled_at"]) == ("TIMESTAMP",) * 2
    assert (cols["vp_payments"]["payment_date"], cols["vp_plans"]["amount"]) == ("TIMESTAMP", "NUMERIC")
    charges_sql = "SELECT external_id, charge_date, amount FROM vp_charges WHERE external_id LIKE :p"
    subs_sql = ("SELECT external_id, amount, suscription_date, canceled_at FROM vp_subscriptions "
                "WHERE external_id LIKE :p")
    with test_engine.connect() as conn:
        after = {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in tables}
        charges, subs = _rows(conn, charges_sql), _rows(conn, subs_sql)
        pays = _rows(conn, "SELECT external_id, amount, payment_date FROM vp_payments WHERE external_id LIKE :p")
    assert after == before  # ninguna fila se pierde
    assert charges["c-a2"] == (date(2026, 10, 5), Decimal("6000"))
    assert charges["c-c2"] == (date(2026, 10, 20), Decimal("7100"))
    assert charges["c-b1"] == (date(2026, 10, 10), None) and charges["c-c1"] == (None, Decimal("7000"))
    assert charges["c-d1"] == (date(2026, 10, 1), None)
    assert subs["s-a"] == (Decimal("5000"), datetime(2021, 9, 8, 11, 20, 31), None)
    assert subs["s-b"] == (None, None, None)
    assert subs["s-c"] == (Decimal("100"), datetime(2026, 1, 5), datetime(2026, 10, 29))
    assert pays == {"p-1": (Decimal("9990"), datetime(2021, 9, 8, 11, 21, 31)), "p-2": (None, None)}

    messages = "\n".join(r.getMessage() for r in caplog.records if r.name == "alembic.vp_l3")
    assert _lost_by_column(messages) == _EXPECTED_LOST  # la base de test no tiene otras filas sucias
    assert "0061 total de valores no convertibles que quedaron NULL: 7" in messages

    # Los KPIs que casteaban texto dan las mismas cifras con las columnas tipadas.
    new_current, new_parity = _new_kpis(test_engine)
    assert old_current == {PREFIX + "s-a": Decimal("6000"), PREFIX + "s-b": Decimal("4500"),
                           PREFIX + "s-c": Decimal("7100")}
    assert new_current == {**old_current, PREFIX + "s-d": Decimal("3000")}  # s-d: sin cobro vigente, monto de la sub
    assert old_parity == {"2026-09": 2, "2026-10": 4}
    assert new_parity == old_parity

    command.downgrade(cfg, "20261102_0060")
    assert _columns(test_engine, "vp_charges")["amount"].startswith("VARCHAR")
    with test_engine.connect() as conn:
        back, sub_back = _rows(conn, charges_sql), _rows(conn, subs_sql)
    assert back["c-a2"] == ("2026-10-05", "6000") and back["c-c2"] == ("2026-10-20", "7100")
    assert back["c-b1"] == ("2026-10-10", None)
    assert sub_back["s-a"] == ("5000", "2021-09-08 11:20:31", None)
    assert sub_back["s-c"] == ("100", "2026-01-05", "2026-10-29")
    assert sub_back["s-d"] == ("3000", "2026-03-01 08:00:00", "2026-10-31 23:59:59")
