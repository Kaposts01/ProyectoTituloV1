"""TCH-PAR-14 (ADR-001): el RUT es solo el external_id del canal; sin verificador valido no es senal de identidad.

RUT sinteticos (calculados con el modulo 11, sin relacion con personas reales) y documentos inventados.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.core import CoreClientAttribute, ExternalIdentity
from app.models.crm import Client, Subscription
from app.models.tch import TchClient, TchSubscription
from app.services import channel_consolidation
from app.services.core_tch_etl import run_tch_core_etl
from app.services.tch_rut import (
    check_digit,
    identity_rut,
    is_valid_rut,
    normalize_tch_rut,
)
from scripts import etl_tch
from tests.tch_synthetic import write_report

VALID = "11.111.111-1"  # verificador correcto
BAD_DV = "11.111.111-2"  # forma de RUT, verificador incorrecto


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
        session.close()
    finally:
        transaction.rollback()
        connection.close()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("11111111-1", VALID),
        ("11.111.111-1", VALID),
        (" 111111111 ", VALID),  # sin guion: el ultimo caracter es el verificador
        ("8765432-k", "8.765.432-K"),
        (111111111, VALID),
        ("11111111-2", BAD_DV),  # verificador incorrecto: conserva la llave del canal (no se migra)
        ("AB123456", "EXT-AB123456"),  # pasaporte: aislado, no "12.345-6"
        ("P-0099 77", "EXT-P009977"),
        ("", None),
        ("  ", None),
        (None, None),
    ],
)
def test_normalize_tch_rut(raw, expected) -> None:
    assert normalize_tch_rut(raw) == expected
    assert etl_tch._norm_rut(raw) == expected


def test_isolated_keys_never_collapse_and_fit_the_column() -> None:
    assert normalize_tch_rut("AB123456") != normalize_tch_rut("CD123456")
    assert len(normalize_tch_rut("PASAPORTE-ABCDEFGHIJKLMNOPQRST")) <= 20


@pytest.mark.parametrize(
    ("value", "valid"),
    [(VALID, True), ("8.765.432-K", True), (BAD_DV, False), ("EXT-AB123456", False), ("1-9", False), (None, False), ("", False)],
)
def test_is_valid_rut_checks_the_check_digit(value, valid) -> None:
    assert is_valid_rut(value) is valid
    assert identity_rut(value) == (value if valid else None)


def test_check_digit_module_11() -> None:
    assert check_digit("11111111") == "1"
    assert check_digit("8765432") == "K"


def test_etl_isolates_documents_that_are_not_ruts(db_session, tmp_path) -> None:
    path = write_report(
        tmp_path / "20260131 TCH IG ENERO 2026.xlsx",
        active=[
            {"ficha": 950001, "rut": "11111111-1"},
            {"ficha": 950002, "rut": "11111111-2"},
            {"ficha": 950003, "rut": "AB123456"},
            {"ficha": 950004, "rut": "CD123456"},
        ],
    )
    etl_tch._process_file(path, db_session)
    keys = set(db_session.scalars(select(TchClient.rut).where(TchClient.rut.in_([VALID, BAD_DV, "EXT-AB123456", "EXT-CD123456", "12.345-6"]))))
    assert keys == {VALID, BAD_DV, "EXT-AB123456", "EXT-CD123456"}  # los dos pasaportes no colapsan en "12.345-6"
    by_file = dict(db_session.execute(select(TchSubscription.file_number, TchSubscription.client_rut).where(TchSubscription.file_number.between(950001, 950004))).all())
    assert by_file[950003] == "EXT-AB123456" and by_file[950004] == "EXT-CD123456"


def _seed(db) -> None:
    for rut, ficha in ((VALID, 951001), (BAD_DV, 951002), ("EXT-AB123456", 951003)):
        db.add(TchClient(rut=rut, name="Sintetico"))
        db.add(TchSubscription(file_number=ficha, client_rut=rut, status="VIGENTE"))
    db.flush()


def test_core_etl_emits_rut_attribute_only_for_valid_ruts_and_prunes_old_invalid_ones(db_session) -> None:
    _seed(db_session)
    db_session.add(CoreClientAttribute(id=uuid.uuid4(), source="tch", attribute_type="rut", attribute_value=BAD_DV))
    db_session.flush()

    run_tch_core_etl(db_session)
    run_tch_core_etl(db_session)  # idempotente

    ruts = set(db_session.scalars(select(CoreClientAttribute.attribute_value).where(CoreClientAttribute.source == "tch", CoreClientAttribute.attribute_type == "rut")))
    assert ruts == {VALID}
    # Las tres llaves siguen siendo identidades externas del canal (RUT como external_id, ADR-001).
    externals = set(db_session.scalars(select(ExternalIdentity.external_id).where(ExternalIdentity.source == "tch")))
    assert {VALID, BAD_DV, "EXT-AB123456"} <= externals


def test_consolidation_sets_social_id_only_for_valid_ruts(db_session) -> None:
    _seed(db_session)
    channel_consolidation._consolidate_tch_clients(db_session)
    channel_consolidation._consolidate_tch_subscriptions(db_session)

    social = dict(db_session.execute(select(Client.external_id, Client.social_id).where(Client.source == "tch", Client.external_id.in_([VALID, BAD_DV, "EXT-AB123456"]))).all())
    assert social == {VALID: VALID, BAD_DV: None, "EXT-AB123456": None}
    subs = dict(db_session.execute(select(Subscription.external_id, Subscription.client_social_id).where(Subscription.source == "tch", Subscription.external_id.in_(["951001", "951002", "951003"]))).all())
    assert subs == {"951001": VALID, "951002": None, "951003": None}
