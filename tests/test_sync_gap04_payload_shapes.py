"""SYNC-GAP-04: relaciones leidas desde raw_payload (Toku/Payku) con distintas formas de payload.

Fija que una relacion presente (id o objeto anidado) se resuelve, y que ausente/null/vacia
queda en NULL sin romper ni perder la fila. Tambien prueba el log agregado de relaciones NULL.
"""
from __future__ import annotations

import logging

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.crm import Charge, Payment, Subscription
from app.models.payku_channel import PaykuSubscription, PaykuTransaction
from app.models.toku_channel import TokuInvoice, TokuSubscription, TokuTransaction
from app.services import channel_consolidation as cc
from app.services.channel_store import (
    extract_payku_subscription,
    extract_payku_transaction,
    extract_toku_invoice,
    extract_toku_payment_method,
    extract_toku_subscription,
)


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


# --- Extractores (channel_store): payload -> columna tipada ---------------------

@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"id": "s", "customer": "c1"}, "c1"),                      # id plano
        ({"id": "s", "customer": {"id": "c1"}}, "c1"),              # objeto anidado (id)
        ({"id": "s", "customer": {"external_id": "c1"}}, "c1"),     # objeto anidado (external_id)
        ({"id": "s", "customer": 123}, "123"),                      # id numerico
        ({"id": "s", "customer_id": "c1"}, "c1"),                   # columna plana alternativa
        ({"id": "s"}, None),                                        # ausente
        ({"id": "s", "customer": None}, None),                      # null
        ({"id": "s", "customer": {}}, None),                        # objeto vacio
        ({"id": "s", "customer": ""}, None),                        # cadena vacia
        ({"id": "s", "customer": {"id": None}}, None),              # objeto con id null
        ({"id": "s", "customer": {"name": "x"}}, None),             # objeto sin id (forma desconocida)
        ({"id": "s", "customer": ["c1"]}, "['c1']"),                # lista: str() de la lista (quirk fijado hoy)
    ],
)
def test_toku_subscription_customer_shapes(payload, expected) -> None:
    result = extract_toku_subscription(payload)
    assert result["external_id"] == "s"  # la fila nunca se pierde
    assert result["customer_id"] == expected


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"id": "i", "subscription": "s1"}, "s1"),
        ({"id": "i", "subscription": {"id": "s1"}}, "s1"),
        ({"id": "i", "subscription_id": "s1"}, "s1"),
        ({"id": "i"}, None),
        ({"id": "i", "subscription": None}, None),
        ({"id": "i", "subscription": {}}, None),
        ({"id": "i", "subscription": ""}, None),
    ],
)
def test_toku_invoice_subscription_shapes(payload, expected) -> None:
    result = extract_toku_invoice(payload)
    assert result["external_id"] == "i"
    assert result["subscription_id"] == expected


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"id": "m", "customer": "c1"}, "c1"),
        ({"id": "m", "customer": {"id": "c1"}}, "c1"),
        ({"id": "m"}, None),
        ({"id": "m", "customer": None}, None),
        ({"id": "m", "customer": {}}, None),
    ],
)
def test_toku_payment_method_customer_shapes(payload, expected) -> None:
    result = extract_toku_payment_method(payload)
    assert result["external_id"] == "m"
    assert result["customer_id"] == expected


@pytest.mark.parametrize(
    "payload,client_id,plan_id",
    [
        ({"id": "s", "client_id": "c1", "plan_id": "p1"}, "c1", "p1"),
        ({"id": "s", "client": {"id": "c1"}, "plan": {"id": "p1"}}, "c1", "p1"),
        ({"id": "s", "client": {"id": "c1"}, "plain": {"id": "p1"}}, "c1", "p1"),  # clave 'plain' de la API
        ({"id": "s"}, None, None),
        ({"id": "s", "client": None, "plan": None}, None, None),
        ({"id": "s", "client": {}, "plan": {}}, None, None),
        ({"id": "s", "client": "", "plan": ""}, None, None),
    ],
)
def test_payku_subscription_relation_shapes(payload, client_id, plan_id) -> None:
    result = extract_payku_subscription(payload)
    assert result["external_id"] == "s"
    assert result["client_id"] == client_id
    assert result["plan_id"] == plan_id


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"id": "t", "subscription_id": "s1"}, "s1"),
        ({"id": "t", "subscription": {"id": "s1"}}, "s1"),
        ({"id": "t", "subscriptions": [{"id": "s1"}]}, "s1"),
        ({"id": "t", "subscriptions": ["s1"]}, "s1"),
        ({"id": "t", "subscriptions": {"id": "s1"}}, "s1"),
        ({"id": "t", "__subscription_id": "s1"}, "s1"),
        ({"id": "t"}, None),
        ({"id": "t", "subscription": None, "subscriptions": None}, None),
        ({"id": "t", "subscription": {}, "subscriptions": []}, None),
        ({"id": "t", "subscriptions": [None]}, None),
        ({"id": "t", "subscriptions": [{}]}, None),
    ],
)
def test_payku_transaction_subscription_shapes(payload, expected) -> None:
    result = extract_payku_transaction(payload)
    assert result["external_id"] == "t"
    assert result["subscription_id"] == expected


# --- Consolidacion: raw_payload -> columnas centralizadas ------------------------

def test_relationship_id_shapes() -> None:
    assert cc._relationship_id("x") == "x"
    assert cc._relationship_id({"id": "x"}) == "x"
    assert cc._relationship_id({"external_id": "x"}) == "x"
    assert cc._relationship_id(None) is None
    assert cc._relationship_id({}) is None
    assert cc._relationship_id({"id": None}) is None
    assert cc._toku_payment_subscription_id({"payment_intents": [{"id_subscription": {"id": "s1"}}]}) == "s1"
    assert cc._toku_payment_subscription_id({"payment_intents": []}) is None
    assert cc._toku_payment_subscription_id({"payment_intents": None}) is None
    assert cc._toku_payment_subscription_id({"payment_intents": [{"id_subscription": None}, "bad"]}) is None
    assert cc._toku_payment_subscription_id({}) is None


def test_toku_subscription_consolidation_keeps_rows_and_nulls_missing_relations(db_session) -> None:
    shapes = {
        "g04-ts-column": dict(customer_id="col-1", raw_payload={}),
        "g04-ts-id": dict(customer_id=None, raw_payload={"customer": "str-1"}),
        "g04-ts-nested": dict(customer_id=None, raw_payload={"customer": {"id": "obj-1"}}),
        "g04-ts-absent": dict(customer_id=None, raw_payload={"other": 1}),
        "g04-ts-null": dict(customer_id=None, raw_payload={"customer": None}),
        "g04-ts-empty": dict(customer_id=None, raw_payload={"customer": {}}),
        "g04-ts-nopayload": dict(customer_id=None, raw_payload=None),
    }
    db_session.add_all([TokuSubscription(external_id=k, status="ACTIVE", **v) for k, v in shapes.items()])
    db_session.flush()

    cc._consolidate_toku_subscriptions(db_session)

    rows = {
        s.external_id: s
        for s in db_session.scalars(
            select(Subscription).where(Subscription.source == "toku", Subscription.external_id.in_(shapes))
        )
    }
    assert set(rows) == set(shapes)  # ninguna fila se pierde
    assert {k: v.client_external_id for k, v in rows.items()} == {
        "g04-ts-column": "col-1",
        "g04-ts-id": "str-1",
        "g04-ts-nested": "obj-1",
        "g04-ts-absent": None,
        "g04-ts-null": None,
        "g04-ts-empty": None,
        "g04-ts-nopayload": None,
    }


def test_toku_invoice_and_transaction_consolidation_null_relations(db_session) -> None:
    db_session.add_all(
        [
            TokuInvoice(external_id="g04-inv-nested", raw_payload={"subscription": {"id": "s1"}, "customer": {"id": "c1"}}),
            TokuInvoice(external_id="g04-inv-empty", raw_payload={"subscription": {}, "customer": None}),
            TokuInvoice(external_id="g04-inv-absent", raw_payload={}),
            TokuTransaction(
                external_id="g04-tx-ok",
                raw_payload={"customer": "c1", "payment_intents": [{"id_subscription": "s1"}]},
            ),
            TokuTransaction(external_id="g04-tx-none", raw_payload={"customer": None, "payment_intents": []}),
            TokuTransaction(external_id="g04-tx-absent", raw_payload={}),
        ]
    )
    db_session.flush()

    cc._consolidate_toku_invoices(db_session)
    cc._consolidate_toku_transactions(db_session)

    charges = {
        c.external_id: (c.subscription_external_id, c.client_external_id)
        for c in db_session.scalars(
            select(Charge).where(Charge.source == "toku", Charge.external_id.like("g04-inv-%"))
        )
    }
    assert charges == {
        "g04-inv-nested": ("s1", "c1"),
        "g04-inv-empty": (None, None),
        "g04-inv-absent": (None, None),
    }
    payments = {
        p.external_id: (p.charge_external_id, p.client_external_id)
        for p in db_session.scalars(
            select(Payment).where(Payment.source == "toku", Payment.external_id.like("g04-tx-%"))
        )
    }
    assert payments == {
        "g04-tx-ok": ("s1", "c1"),
        "g04-tx-none": (None, None),
        "g04-tx-absent": (None, None),
    }


def test_payku_consolidation_keeps_rows_with_null_relations(db_session) -> None:
    db_session.add_all(
        [
            PaykuSubscription(external_id="g04-ps-full", client_id="c1", plan_id="p1", status="active", raw_payload={}),
            PaykuSubscription(external_id="g04-ps-none", client_id=None, plan_id=None, status="active", raw_payload={"client": None}),
            PaykuTransaction(external_id="g04-pt-full", subscription_id="g04-ps-full", status="success", raw_payload={}),
            PaykuTransaction(external_id="g04-pt-none", subscription_id=None, status="success", raw_payload={}),
        ]
    )
    db_session.flush()

    cc._consolidate_payku_subscriptions(db_session)
    cc._consolidate_payku_transactions(db_session)

    subs = {
        s.external_id: (s.client_external_id, s.plan_external_id)
        for s in db_session.scalars(
            select(Subscription).where(Subscription.source == "payku", Subscription.external_id.like("g04-ps-%"))
        )
    }
    assert subs == {"g04-ps-full": ("c1", "p1"), "g04-ps-none": (None, None)}
    pays = {
        p.external_id: p.charge_external_id
        for p in db_session.scalars(
            select(Payment).where(Payment.source == "payku", Payment.external_id.like("g04-pt-%"))
        )
    }
    assert pays == {"g04-pt-full": "g04-ps-full", "g04-pt-none": None}


# --- Log agregado de relaciones NULL (sin PII) ------------------------------------

def test_log_null_relations_reports_only_counts(caplog) -> None:
    rows = [
        {"external_id": "secret-ext-1", "client_external_id": "12.345.678-5", "plan_external_id": None},
        {"external_id": "secret-ext-2", "client_external_id": None, "plan_external_id": None},
        {"external_id": "secret-ext-3", "client_external_id": None, "plan_external_id": "p1"},
    ]
    with caplog.at_level(logging.WARNING, logger=cc.logger.name):
        cc._log_null_relations("payku.subscription", rows, ("client_external_id", "plan_external_id"))

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "payku.subscription" in message
    assert "client_external_id=2" in message and "plan_external_id=2" in message and "de 3 filas" in message
    for leaked in ("secret-ext", "12.345.678-5", "p1"):
        assert leaked not in message


def test_log_null_relations_silent_when_nothing_null_or_no_rows(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger=cc.logger.name):
        cc._log_null_relations("toku.invoice", [], ("subscription_external_id",))
        cc._log_null_relations("toku.invoice", [{"subscription_external_id": "s1"}], ("subscription_external_id",))
    assert caplog.records == []


def test_toku_subscription_consolidation_emits_null_relation_log(db_session, caplog) -> None:
    db_session.add_all(
        [
            TokuSubscription(external_id="g04-log-a", status="ACTIVE", raw_payload={"customer": None}),
            TokuSubscription(external_id="g04-log-b", status="ACTIVE", raw_payload={"customer": "c-1"}),
        ]
    )
    db_session.flush()

    with caplog.at_level(logging.WARNING, logger=cc.logger.name):
        cc._consolidate_toku_subscriptions(db_session)

    messages = [r.getMessage() for r in caplog.records if "relaciones NULL toku.subscription" in r.getMessage()]
    assert len(messages) == 1
    assert "client_external_id=" in messages[0]
    assert "g04-log" not in messages[0]
