# ruff: noqa: DTZ001  (las columnas vp_* son timestamp SIN zona: se comparan datetimes ingenuos)
"""VP-PAR-07 / VP-PAR-13: conversion de valores VirtualPOS a columnas tipadas y extractores del sync. Datos sinteticos."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.services.channel_store import extract_vp_payment, extract_vp_subscription
from app.services.vp_typed_fields import (
    as_legacy_text,
    parse_amount,
    parse_date,
    parse_timestamp,
    payment_typed_fields,
    subscription_typed_fields,
)


@pytest.mark.parametrize(("value", "expected"), [
    (9990, Decimal("9990")), ("6990", Decimal("6990")), (" 12.50 ", Decimal("12.50")), ("-3", Decimal("-3")),
    ("", None), (None, None), ("12a", None), ("1e5", None), ("NaN", None), (True, None), (float("nan"), None),
])
def test_parse_amount(value, expected) -> None:
    assert parse_amount(value) == expected


@pytest.mark.parametrize(("value", "expected"), [
    ("2021-09-08 11:20:31", datetime(2021, 9, 8, 11, 20, 31)),
    ("2021-09-08T11:20:31Z", datetime(2021, 9, 8, 11, 20, 31)),
    ("2021-09-08", datetime(2021, 9, 8)),
    ("2021-09-08 11:20", datetime(2021, 9, 8, 11, 20)),
    ("2021-02-30 10:00:00", None), ("", None), ("pronto", None), (None, None), ("2021-09-08 24:00:00", None),
])
def test_parse_timestamp(value, expected) -> None:
    assert parse_timestamp(value) == expected


@pytest.mark.parametrize(("value", "expected"), [
    ("2026-10-05", date(2026, 10, 5)), ("2023-01-30 23:48:48", date(2023, 1, 30)), ("2026-13-01", None), ("", None),
])
def test_parse_date(value, expected) -> None:
    assert parse_date(value) == expected


@pytest.mark.parametrize(("value", "expected"), [
    (Decimal("15000.00"), "15000"), (Decimal("9990.5"), "9990.5"), (Decimal("0.00"), "0"),
    (datetime(2021, 9, 8, 11, 20, 31), "2021-09-08 11:20:31"), (datetime(2026, 1, 5), "2026-01-05"),
    (date(2026, 10, 5), "2026-10-05"), (None, None), ("x", "x"),
])
def test_as_legacy_text(value, expected) -> None:
    assert as_legacy_text(value) == expected


def test_payment_fields_read_list_and_detail_shapes() -> None:
    listed = {"order": {"authorized_at": "2021-09-08 11:21:31", "deposits": [
        {"processing_fee": 117, "payout_amount": 9783, "payout_date": "2021-09-21"}]}, "client": {"social_id": "1-9"}}
    assert payment_typed_fields(listed) == {
        "client_social_id": "1-9", "authorized_at": "2021-09-08 11:21:31", "processing_fee": Decimal("117"),
        "payout_amount": Decimal("9783"), "payout_date": "2021-09-21"}
    detail = {"payment": {"order": {"authorized_at": "", "deposits": "?"}}}
    assert payment_typed_fields(detail) == {
        "client_social_id": None, "authorized_at": None, "processing_fee": None, "payout_amount": None,
        "payout_date": None}


def test_subscription_fields_never_promote_seller_or_invalid_last4() -> None:
    payload = {"payment_method": {"last4CardDigit": 6623, "brand": " VISA ", "card_type": "TD", "bin": "405188"},
               "terminal_pos": "POS 1", "origin": "WEB", "seller_id": "11111111-1"}
    assert subscription_typed_fields(payload) == {
        "card_type": "TD", "card_brand": "VISA", "card_last4": "6623", "terminal_pos": "POS 1", "origin": "WEB"}
    assert subscription_typed_fields({"payment_method": {"last4CardDigit": "12345"}})["card_last4"] is None


@pytest.fixture
def db_session():
    from sqlalchemy.orm import Session

    from app.db.session import engine

    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_typed_vp_columns_reach_crm_tables_as_the_same_text(db_session) -> None:
    """VP-PAR-13: las tablas `crm` (texto) reciben lo mismo que antes de tipar `vp_*`."""
    from sqlalchemy import select

    from app.models.crm import Charge, Subscription
    from app.models.vp import VpCharge, VpSubscription
    from app.services import channel_consolidation as cc
    from app.services.channel_store import store_vp_resources

    store_vp_resources(db_session, "subscription", [{
        "id": "l3-sub", "status": "CANCELADA", "suscription_date": "2021-09-08 11:20:31", "canceled_at": "2026-10-29",
        "amount": 9990}], platform="virtualpos1")
    store_vp_resources(db_session, "charge", [
        {"id": "l3-c1", "charge_date": "2026-10-05", "amount": "15000.00", "status": "rechazado"},
        {"id": "l3-c2", "charge_date": "", "amount": "", "status": "cancelado"},  # sucio: NULL, sin romper el lote
    ], platform="virtualpos1", subscription_external_id="l3-sub")
    vp = db_session.scalar(select(VpSubscription).where(VpSubscription.external_id == "l3-sub"))
    assert (vp.suscription_date, vp.canceled_at, vp.amount) == (
        datetime(2021, 9, 8, 11, 20, 31), datetime(2026, 10, 29), Decimal("9990"))
    assert db_session.scalar(select(VpCharge.charge_date).where(VpCharge.external_id == "l3-c2")) is None

    cc._consolidate_vp_subscriptions(db_session, ("virtualpos1", "l3-sub"))
    cc._consolidate_vp_charges(db_session, ("virtualpos1", "l3-sub"))
    sub = db_session.scalar(select(Subscription).where(Subscription.external_id == "l3-sub"))
    assert (sub.suscription_date, sub.canceled_at, sub.amount) == ("2021-09-08 11:20:31", "2026-10-29", "9990")
    charges = {c.external_id: (c.charge_date, c.amount) for c in db_session.scalars(
        select(Charge).where(Charge.subscription_external_id == "l3-sub"))}
    assert charges == {"l3-c1": ("2026-10-05", "15000"), "l3-c2": (None, None)}


def test_extractors_include_promoted_columns() -> None:
    sub = extract_vp_subscription({"id": "s1", "payment_method": {"last4CardDigit": "1111"}, "origin": "API"})
    assert (sub["card_last4"], sub["origin"]) == ("1111", "API")
    pay = extract_vp_payment({"order": {"uuid": "u1", "authorized_at": "2026-10-05 10:00:00", "amount": 9990}})
    assert (pay["external_id"], pay["authorized_at"], pay["processing_fee"]) == ("u1", "2026-10-05 10:00:00", None)
    assert "charge_external_id" not in pay  # VP-PAR-06 sigue vigente
