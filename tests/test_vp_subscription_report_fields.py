"""VP-PAR-09: motivo de rechazo y ultimos 4 de las suscripciones VP desde SuscriptoresPAT. CSV sinteticos."""

import pytest
from sqlalchemy.orm import Session
from vp_reports_support import PEPPER, sub_id, subscription_row, write_report

from app.core.config import settings
from app.db.session import engine
from app.models.vp import VpSubscription
from app.services import core_vp_etl
from app.services.vp_report_import import import_report, subscription_report_fields

P1, P2 = "virtualpos1", "virtualpos2"


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
    monkeypatch.setattr(settings, "vp_report_hash_pepper", PEPPER)


def _sub(db, n, platform=P1, last4=None, status="ACTIVA"):
    raw = {"payment_method": {"last4CardDigit": last4}} if last4 else {}
    db.add(VpSubscription(platform=platform, external_id=sub_id(n), status=status, raw_payload=raw))
    db.flush()


def _load(db, tmp_path, rows):
    path = write_report(tmp_path / "SuscriptoresPAT-VirtualPOS-1792500000.csv", "suscriptores", rows)
    return import_report(db, path, filename=path.name, uploaded_by_user_id=None)


def test_report_fields_only_for_resolved_rows(db_session, tmp_path):
    _sub(db_session, 1, status="FALLIDA")
    _load(db_session, tmp_path, [
        subscription_row(1, **{"Estado de suscripción": "FALLIDA", "Motivo de rechazo": "Tarjeta sin fondos",
                               "Últimos 4 dígitos pan": "4321"}),
        subscription_row(2, **{"Motivo de rechazo": "Otro"}),  # sin vp_subscriptions: plataforma sin resolver
    ])
    fields = subscription_report_fields(db_session)
    assert fields == {(P1, sub_id(1)): {"rejection_reason": "Tarjeta sin fondos", "card_last4": "4321",
                                        "card_type": "TD", "card_brand": "visa"}}


def test_projection_prefers_api_card_and_fills_missing_last4_from_report(db_session, tmp_path):
    _sub(db_session, 1, last4="1111")                 # la API tiene tarjeta vigente: manda la API
    _sub(db_session, 2, status="FALLIDA")             # sin tarjeta en la API: se completa con el reporte
    _sub(db_session, 3, platform=P2)                  # sin reporte ni API
    _load(db_session, tmp_path, [
        subscription_row(1, **{"Últimos 4 dígitos pan": "9999"}),
        subscription_row(2, **{"Estado de suscripción": "FALLIDA", "Motivo de rechazo": "Rechazo del emisor",
                               "Últimos 4 dígitos pan": "2222"}),
    ])
    out = core_vp_etl.project_subscription_report_fields(db_session)
    assert out[(P1, sub_id(1))] == {"rejection_reason": None, "card_last4": "1111", "card_last4_source": "api"}
    assert out[(P1, sub_id(2))] == {"rejection_reason": "Rechazo del emisor", "card_last4": "2222",
                                    "card_last4_source": "report"}
    assert out[(P2, sub_id(3))] == {"rejection_reason": None, "card_last4": None, "card_last4_source": None}


def test_persist_writes_core_subscriptions_and_is_idempotent(db_session, tmp_path):
    """VP-PAR-09 (resto): la proyeccion queda guardada en `core_subscriptions` (migracion 0060)."""
    from app.models.core import CoreSubscription

    _sub(db_session, 1, last4="1111")
    _sub(db_session, 2, status="FALLIDA")
    db_session.add(VpSubscription(platform=P1, external_id=sub_id(3), status="CANCELADA", card_last4="3333", raw_payload={}))
    for n in (1, 2, 3):
        db_session.add(CoreSubscription(source=P1, external_id=sub_id(n), status="ACTIVA",
                                        card_last4="0000" if n == 3 else None,
                                        card_last4_source="report" if n == 3 else None))
    db_session.flush()
    _load(db_session, tmp_path, [
        subscription_row(1, **{"Últimos 4 dígitos pan": "9999"}),
        subscription_row(2, **{"Estado de suscripción": "FALLIDA", "Motivo de rechazo": "Rechazo del emisor",
                               "Últimos 4 dígitos pan": "2222"}),
    ])
    fields = core_vp_etl.project_subscription_report_fields(db_session)
    assert core_vp_etl.persist_subscription_report_fields(db_session, fields) == 3
    db_session.expire_all()
    rows = {s.external_id: (s.card_last4, s.card_last4_source, s.rejection_reason)
            for s in db_session.query(CoreSubscription).filter(CoreSubscription.source == P1)}
    assert rows[sub_id(1)] == ("1111", "api", None)
    assert rows[sub_id(2)] == ("2222", "report", "Rechazo del emisor")
    assert rows[sub_id(3)] == ("3333", "api", None)  # la columna promovida de la API manda sobre lo guardado
    assert core_vp_etl.persist_subscription_report_fields(db_session, fields) == 0
