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
        for table in ("core_subscriptions", "vp_report_subscriptions", "vp_payments", "vp_subscriptions",
                      "vp_charges", "vp_plans"):
            column = "subscription_external_id" if table == "vp_report_subscriptions" else "external_id"
            conn.execute(text(f"DELETE FROM {table} WHERE {column} LIKE :p"), {"p": PREFIX + "%"})
        conn.execute(text("DELETE FROM vp_report_files WHERE filename LIKE :p"), {"p": PREFIX + "%"})
    command.upgrade(_cfg(), "head")


def _columns(engine, table: str) -> dict[str, str]:
    return {c["name"]: str(c["type"]) for c in inspect(engine).get_columns(table)}


def test_chain_0060() -> None:
    m60 = _load("*_0060_vp_promoted_columns.py")
    assert (m60.revision, m60.down_revision) == ("20261102_0060", "20261102_0054")


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
