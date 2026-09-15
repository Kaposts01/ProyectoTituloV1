from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.api.v1.routes import staging
from app.db.session import engine
from app.models.crm import Charge, Client, Payment, PaymentMethod, Plan, Subscription
from app.models.payku_channel import PaykuSubscription, PaykuTransaction
from app.models.source_record import SourceRecord
from app.models.sync_run import SyncRun
from app.models.tch import TchCliente, TchSuscripcion, TchTransaccion
from app.services.channel_store import (
    extract_payku_subscription,
    extract_payku_transaction,
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


def test_list_staging_records_isolated_by_source_and_resource_type(db_session) -> None:
    db_session.add_all(
        [
            SourceRecord(source="toku", resource_type="test_customer", external_id="toku-1", payload={"name": "Toku"}),
            SourceRecord(source="toku", resource_type="test_invoice", external_id="toku-2", payload={"amount": 100}),
            Client(source="payku", external_id="payku-1", raw_payload={"name": "Payku"}),
        ]
    )
    db_session.flush()

    response = staging.list_records(
        source="payku", resource_type="client", filter_field="id", query="payku-1", db=db_session, limit=50
    )

    assert response["total"] == 1
    assert response["items"][0]["external_id"] == "payku-1"
    assert response["items"][0]["payload"] == {"name": "Payku"}


def test_virtualpos_records_filter_by_operational_fields_and_order_dates(db_session) -> None:
    db_session.add_all(
        [
            Client(source="virtualpos1", external_id="client-1", raw_payload={"uuid": "client-1", "first_name": "Ana exclusiva", "last_name": "Rios", "status": "ACTIVO"}),
            Client(source="virtualpos1", external_id="client-2", raw_payload={"uuid": "client-2", "first_name": "Bruno", "last_name": "Rios", "status": "INACTIVO"}),
            Plan(source="virtualpos1", external_id="plan-1", raw_payload={"id": "plan-1", "automatic_renewal": "T"}),
            Plan(source="virtualpos1", external_id="plan-2", raw_payload={"id": "plan-2", "automatic_renewal": "F"}),
            Charge(source="virtualpos1", external_id="charge-old", charge_date="9999-01-01", raw_payload={"charge_date": "9999-01-01"}),
            Charge(source="virtualpos1", external_id="charge-new", charge_date="9999-02-01", raw_payload={"charge_date": "9999-02-01"}),
            Payment(source="virtualpos1", external_id="payment-old", payment_date="9999-01-01", raw_payload={"order": {"authorized_at": "9999-01-01"}}),
            Payment(source="virtualpos1", external_id="payment-new", payment_date="9999-02-01", raw_payload={"order": {"authorized_at": "9999-02-01"}}),
        ]
    )
    db_session.flush()

    clients = staging.list_records(source="virtualpos", resource_type="client", filter_field="name", query="ana exclusiva", db=db_session)
    active_plans = staging.list_records(source="virtualpos", resource_type="plan", filter_field="automatic_renewal", query="activo", db=db_session)
    charges = staging.list_records(source="virtualpos", resource_type="charge", db=db_session)
    payments = staging.list_records(source="virtualpos", resource_type="payment", db=db_session)

    assert [record["external_id"] for record in clients["items"]] == ["client-1"]
    active_plan_ids = [record["external_id"] for record in active_plans["items"]]
    charge_ids = [record["external_id"] for record in charges["items"]]
    payment_ids = [record["external_id"] for record in payments["items"]]

    assert "plan-1" in active_plan_ids
    assert "plan-2" not in active_plan_ids
    assert charge_ids.index("charge-new") < charge_ids.index("charge-old")
    assert payment_ids.index("payment-new") < payment_ids.index("payment-old")


def test_toku_and_payku_records_filter_by_visible_columns(db_session) -> None:
    db_session.add_all(
        [
            Client(source="toku", external_id="customer-filter", social_id="11.222.333-4", raw_payload={"id": "customer-filter"}),
            Subscription(source="toku", external_id="subscription-filter", client_external_id="customer-filter", raw_payload={"id": "subscription-filter"}),
            Plan(source="payku", external_id="payku-plan-filter", name="Plan Filtro Exclusivo", raw_payload={"id": "payku-plan-filter"}),
        ]
    )
    db_session.flush()

    customers = staging.list_records(source="toku", resource_type="customer", filter_field="government_id", query="222.333", db=db_session)
    subscriptions = staging.list_records(source="toku", resource_type="subscription", filter_field="customer", query="customer-filter", db=db_session)
    plans = staging.list_records(source="payku", resource_type="plan", filter_field="name", query="filtro exclusivo", db=db_session)

    assert [record["external_id"] for record in customers["items"]] == ["customer-filter"]
    assert [record["external_id"] for record in subscriptions["items"]] == ["subscription-filter"]
    assert [record["external_id"] for record in plans["items"]] == ["payku-plan-filter"]


def test_staging_summary_groups_records_and_latest_sync_by_source(db_session) -> None:
    before = staging.staging_summary(db=db_session)
    before_toku = next(source for source in before["sources"] if source["source"] == "toku")
    before_payku = next(source for source in before["sources"] if source["source"] == "payku")
    db_session.add_all(
        [
            SourceRecord(source="virtualpos", resource_type="client", external_id="vp-1", payload={}),
            Client(source="toku", external_id="summary-toku-customer", raw_payload={"id": "summary-toku-customer"}),
            Client(source="payku", external_id="summary-payku-client", raw_payload={"id": "summary-payku-client"}),
            SyncRun(
                source="toku",
                status="completed",
                    records_processed=1,
                finished_at=datetime.now(UTC),
            ),
        ]
    )
    db_session.flush()

    response = staging.staging_summary(db=db_session)
    toku = next(source for source in response["sources"] if source["source"] == "toku")
    payku = next(source for source in response["sources"] if source["source"] == "payku")

    assert toku["records"] == before_toku["records"] + 1
    assert toku["resources"]["customer"] == before_toku["resources"]["customer"] + 1
    assert toku["last_sync"] is not None
    assert toku["last_sync"]["records_processed"] == 1
    assert payku["records"] == before_payku["records"] + 1
    assert payku["resources"]["client"] == before_payku["resources"]["client"] + 1


def test_general_dashboard_aggregates_canonical_channels_and_tch(db_session) -> None:
    before = staging.general_dashboard(db=db_session)
    db_session.add_all(
        [
            Client(source="payku", external_id="general-payku-client", raw_payload={}),
            Subscription(
                source="payku", external_id="general-payku-subscription", status="active", amount="1000",
                suscription_date="2099-04-01", raw_payload={},
            ),
            Payment(
                source="payku", external_id="general-payku-payment", status="success", amount="1200",
                payment_date="2099-04-02", raw_payload={},
            ),
            Payment(
                source="payku", external_id="general-payku-rejected", status="rejected", amount="900",
                payment_date="2099-04-02", raw_payload={},
            ),
            TchCliente(rut="99.999.999-9"),
            TchSuscripcion(
                numero_ficha=999999, estado="VIGENTE", monto="2000", fecha_activacion="2099-04-03"
            ),
            TchTransaccion(numero_ficha=999999, periodo="2099-04", estado="ACEPTADA", monto="2000"),
        ]
    )
    db_session.flush()

    response = staging.general_dashboard(db=db_session)

    assert response["clients"] == before["clients"] + 2
    assert response["subscriptions"]["active"] == before["subscriptions"]["active"] + 2
    assert response["transactions"]["total"] == before["transactions"]["total"] + 3
    assert response["transactions"]["accepted"] == before["transactions"]["accepted"] + 2
    assert response["transactions"]["rejected"] == before["transactions"]["rejected"] + 1
    assert response["transactions"]["amount"] == before["transactions"]["amount"] + 3200
    assert {entry["status"] for entry in response["transactions_monthly"] if entry["year"] == 2099} >= {"Aceptadas", "Rechazadas"}
    assert {entry["status"] for entry in response["activations_monthly"] if entry["year"] == 2099} >= {"Payku", "TCH"}


def test_channel_dashboard_aggregates_local_activity_and_statuses(db_session) -> None:
    before = staging.channel_dashboard(source="payku", db=db_session)
    db_session.add_all(
        [
            Payment(source="payku", external_id="dashboard-payku-1", status="success", amount="1200", payment_date="2099-02-03", raw_payload={"id": "dashboard-payku-1"}),
            Payment(source="payku", external_id="dashboard-payku-failed", status="failed", amount="900", payment_date="2099-02-03", raw_payload={"id": "dashboard-payku-failed"}),
            Subscription(source="payku", external_id="dashboard-payku-2", status="active", amount="1000", raw_payload={"id": "dashboard-payku-2"}),
            Subscription(source="payku", external_id="dashboard-payku-suspended", status="suspended", amount="500", raw_payload={"id": "dashboard-payku-suspended"}),
        ]
    )
    db_session.flush()

    response = staging.channel_dashboard(source="payku", db=db_session)

    assert {entry["year"] for entry in response["activity"]} >= {2099}
    assert {entry["status"] for entry in response["statuses"]} >= {"success", "active"}
    assert response["activity_resource"] == "transaction"
    assert response["resources"]["subscription"] == before["resources"]["subscription"] + 1
    assert response["resources"]["transaction"] == before["resources"]["transaction"] + 1
    assert response["resource_amounts"]["subscription"] == before["resource_amounts"]["subscription"] + 1000.0
    assert response["resource_amounts"]["transaction"] == before["resource_amounts"]["transaction"] + 1200.0


def test_payku_dashboard_uses_subscription_dates_amounts_and_terminal_churn() -> None:
    records = [
        SourceRecord(
            source="payku",
            resource_type="subscription",
            external_id="active-subscription",
            payload={"status": "active", "start": "2099-01-02", "amount": "1000", "client": {"rut": "1"}},
        ),
        SourceRecord(
            source="payku",
            resource_type="subscription",
            external_id="cancelled-subscription",
            payload={"status": "cancel", "start": "2099-01-03", "end": "2099-02-04", "amount": "2000"},
        ),
        SourceRecord(
            source="payku",
            resource_type="subscription",
            external_id="suspended-subscription",
            payload={"status": "suspended", "start": "2099-01-04", "end": "2099-02-05", "amount": "3000"},
        ),
    ]

    dashboard = staging._payku_extended_data(records)

    assert dashboard["kpis"]["mrr"] == 1000
    assert dashboard["kpis"]["active_subscribers"] == 1
    assert dashboard["activation_monthly"] == [
        {"year": 2099, "month": 1, "status": "ACTIVE", "count": 1, "amount": 1000.0},
        {"year": 2099, "month": 1, "status": "CANCEL", "count": 1, "amount": 2000.0},
        {"year": 2099, "month": 1, "status": "SUSPENDED", "count": 1, "amount": 3000.0},
    ]
    assert dashboard["churn_monthly"] == [
        {"year": 2099, "month": 2, "status": "CANCEL", "count": 1, "amount": 2000.0},
        {"year": 2099, "month": 2, "status": "SUSPENDED", "count": 1, "amount": 3000.0},
    ]


def test_payku_subscription_uses_latest_successful_transaction_amount() -> None:
    subscription = extract_payku_subscription({
        "id": "subscription-1",
        "transactions": [
            {"status": "success", "amount": "1000", "created_at": "2099-01-01"},
            {"status": "failed", "amount": "9999", "created_at": "2099-02-01"},
            {"status": "success", "amount": "1200", "created_at": "2099-03-01"},
        ],
    })

    assert subscription["amount"] == "1200"


def test_payku_transaction_reads_subscription_object() -> None:
    transaction = extract_payku_transaction({
        "id": "transaction-1",
        "subscriptions": {"id": "subscription-1"},
        "amount": "1200",
        "status": "success",
    })

    assert transaction["subscription_id"] == "subscription-1"


def test_payku_consolidation_preserves_subscription_dates_and_rut(db_session) -> None:
    subscription = PaykuSubscription(
        external_id="payku-dashboard-date-test",
        client_id="client-1",
        plan_id="plan-1",
        status="cancel",
        amount=None,
        currency="CLP",
        raw_payload={"start": "2099-01-01", "end": "2099-02-01", "client": {"rut": "12.345.678-9"}},
    )
    transaction = PaykuTransaction(
        external_id="payku-dashboard-date-transaction",
        subscription_id="payku-dashboard-date-test",
        status="success",
        amount="2500",
        created_at_api="2099-01-15",
        raw_payload={},
    )
    db_session.add_all([subscription, transaction])
    db_session.flush()

    from app.services.channel_consolidation import _consolidate_payku_subscriptions

    _consolidate_payku_subscriptions(db_session)
    canonical = db_session.query(Subscription).filter_by(source="payku", external_id=subscription.external_id).one()

    assert canonical.suscription_date == "2099-01-01"
    assert canonical.canceled_at == "2099-02-01"
    assert canonical.client_social_id == "12.345.678-9"
    assert canonical.amount == "2500"
    assert subscription.amount == "2500"


def test_virtualpos_client_detail_lists_all_subscriptions_by_social_id(db_session) -> None:
    db_session.add_all(
        [
            Client(
                source="virtualpos1",
                external_id="detail-client-1",
                social_id="12.345.678-9",
                raw_payload={"uuid": "detail-client-1", "social_id": "12.345.678-9"},
            ),
            Subscription(
                source="virtualpos1",
                external_id="detail-subscription-1",
                client_social_id="12.345.678-9",
                raw_payload={"id": "detail-subscription-1", "client": {"social_id": "12.345.678-9"}},
            ),
            Subscription(
                source="virtualpos1",
                external_id="detail-subscription-2",
                client_social_id="12.345.678-9",
                raw_payload={"id": "detail-subscription-2", "client": {"social_id": "12.345.678-9"}},
            ),
            Subscription(
                source="virtualpos1",
                external_id="other-subscription",
                client_social_id="98.765.432-1",
                raw_payload={"id": "other-subscription", "client": {"social_id": "98.765.432-1"}},
            ),
        ]
    )
    db_session.flush()

    response = staging.virtualpos_client_detail(external_id="detail-client-1", db=db_session)

    assert response["client"]["external_id"] == "detail-client-1"
    assert response["subscription_total"] == 2
    assert {subscription["external_id"] for subscription in response["subscriptions"]} == {
        "detail-subscription-1",
        "detail-subscription-2",
    }


def test_virtualpos_plan_detail_lists_subscriptions_by_plan_id(db_session) -> None:
    db_session.add_all(
        [
            Plan(source="virtualpos1", external_id="detail-plan-1", raw_payload={"id": "detail-plan-1"}),
            Subscription(
                source="virtualpos1",
                external_id="plan-subscription-1",
                plan_external_id="detail-plan-1",
                raw_payload={"plan_id": "detail-plan-1"},
            ),
            Subscription(
                source="virtualpos1",
                external_id="other-plan-subscription",
                plan_external_id="plan-2",
                raw_payload={"plan_id": "plan-2"},
            ),
        ]
    )
    db_session.flush()

    response = staging.virtualpos_plan_detail(external_id="detail-plan-1", db=db_session)

    assert response["subscription_total"] == 1
    assert response["subscriptions"][0]["external_id"] == "plan-subscription-1"


def test_virtualpos_subscription_detail_returns_payment_method_and_charges(db_session) -> None:
    db_session.add_all(
        [
            Subscription(
                source="virtualpos1",
                external_id="detail-subscription-3",
                raw_payload={"payment_method": {"brand": "Visa", "last4": "1234"}},
            ),
            Charge(
                source="virtualpos1",
                external_id="detail-charge-1",
                subscription_external_id="detail-subscription-3", charge_date="2026-01-01",
                raw_payload={"amount": 1000, "charge_date": "2026-01-01"},
            ),
            Charge(
                source="virtualpos1",
                external_id="detail-charge-2",
                subscription_external_id="detail-subscription-3", charge_date="2026-02-01",
                raw_payload={"amount": 2000, "charge_date": "2026-02-01"},
            ),
            Charge(
                source="virtualpos1",
                external_id="other-charge",
                subscription_external_id="other-subscription", raw_payload={"amount": 2000},
            ),
        ]
    )
    db_session.flush()

    response = staging.virtualpos_subscription_detail(external_id="detail-subscription-3", db=db_session)

    assert response["payment_method"] == {"brand": "Visa", "last4": "1234"}
    assert response["charge_total"] == 2
    assert [charge["external_id"] for charge in response["charges"]] == [
        "detail-charge-2",
        "detail-charge-1",
    ]


def test_virtualpos_charge_detail_returns_local_staging_record(db_session) -> None:
    db_session.add(
        Charge(
            source="virtualpos1",
            external_id="detail-charge-record",
            charge_date="2026-01-01", raw_payload={"id": "detail-charge-record", "charge_date": "2026-01-01"},
        )
    )
    db_session.flush()

    response = staging.virtualpos_charge_detail(external_id="detail-charge-record", db=db_session)

    assert response["charge"]["external_id"] == "detail-charge-record"


def test_virtualpos_payment_detail_returns_local_staging_record(db_session) -> None:
    db_session.add(
        Payment(
            source="virtualpos1",
            external_id="detail-payment-record",
            raw_payload={"order": {"uuid": "payment-uuid"}},
        )
    )
    db_session.flush()

    response = staging.virtualpos_payment_detail(external_id="detail-payment-record", db=db_session)

    assert response["payment"]["external_id"] == "detail-payment-record"


def test_toku_canonical_records_use_visible_fields_and_date_ordering(db_session) -> None:
    db_session.add_all(
        [
            Charge(source="toku", external_id="invoice-old", charge_date="2099-01-01", raw_payload={"due_date": "2099-01-01"}),
            Charge(source="toku", external_id="invoice-new", charge_date="2099-02-01", raw_payload={"due_date": "2099-02-01"}),
            Payment(source="toku", external_id="transaction-old", payment_date="2099-01-01", raw_payload={"transaction_date": "2099-01-01"}),
            Payment(source="toku", external_id="transaction-new", payment_date="2099-02-01", raw_payload={"transaction_date": "2099-02-01"}),
        ]
    )
    db_session.flush()

    invoices = staging.list_records(source="toku", resource_type="invoice", db=db_session)
    transactions = staging.list_records(source="toku", resource_type="transaction", db=db_session)

    invoice_ids = [record["external_id"] for record in invoices["items"]]
    transaction_ids = [record["external_id"] for record in transactions["items"]]
    assert invoice_ids.index("invoice-new") < invoice_ids.index("invoice-old")
    assert transaction_ids.index("transaction-new") < transaction_ids.index("transaction-old")


def test_toku_payment_method_filters_use_nested_card_fields(db_session) -> None:
    db_session.add(
        PaymentMethod(
            source="toku",
            external_id="method-card-1",
            client_external_id="customer-1",
            status="chargeable",
            raw_payload={
                "payment_method": {
                    "card": {
                        "bank_name": "Banco de Prueba",
                        "card_brand": "Visa",
                        "card_type": "TC",
                        "last_digits": "1234",
                    }
                }
            },
        )
    )
    db_session.flush()

    response = staging.list_records(
        source="toku",
        resource_type="payment_method",
        filter_field="bank_name",
        query="Prueba",
        db=db_session,
    )

    assert [item["external_id"] for item in response["items"]] == ["method-card-1"]


def test_toku_payment_methods_sort_by_nested_card_field(db_session) -> None:
    db_session.add_all(
        [
            PaymentMethod(
                source="toku",
                external_id="method-bank-z",
                raw_payload={"payment_method": {"card": {"bank_name": "Zeta"}}},
            ),
            PaymentMethod(
                source="toku",
                external_id="method-bank-a",
                raw_payload={"payment_method": {"card": {"bank_name": "Alfa"}}},
            ),
        ]
    )
    db_session.flush()

    response = staging.list_records(
        source="toku",
        resource_type="payment_method",
        sort_field="bank_name",
        sort_direction="asc",
        db=db_session,
    )

    ids = [item["external_id"] for item in response["items"]]
    assert ids.index("method-bank-a") < ids.index("method-bank-z")


def test_toku_detail_and_dashboard_use_canonical_records(db_session) -> None:
    before = staging.channel_dashboard("toku", db=db_session)
    db_session.add_all(
        [
            Client(source="toku", external_id="customer-1", social_id="11.222.333-4", raw_payload={"id": "customer-1"}),
            Subscription(source="toku", external_id="subscription-1", client_external_id="customer-1", status="active", amount="1000", suscription_date="2099-02-01", raw_payload={"id": "subscription-1"}),
            PaymentMethod(source="toku", external_id="method-1", client_external_id="customer-1", status="chargeable", raw_payload={"subscription_ids": ["subscription-1"]}),
            Charge(source="toku", external_id="invoice-1", client_external_id="customer-1", subscription_external_id="subscription-1", status="PAID", amount="2000", charge_date="2099-03-01", raw_payload={"id": "invoice-1"}),
            Payment(source="toku", external_id="transaction-1", client_external_id="customer-1", status="SUCCESS", amount="1500", payment_date="2099-03-02", raw_payload={"subscription_id": "subscription-1"}),
            SourceRecord(source="toku", resource_type="customer", external_id="stale-source-record", payload={"id": "stale-source-record"}),
        ]
    )
    db_session.flush()

    detail = staging.provider_record_detail("toku", "customer", "customer-1", db=db_session)
    dashboard = staging.channel_dashboard("toku", db=db_session)

    related = {group["resource_type"]: group["items"] for group in detail["related"]}
    assert detail["record"]["payload"] == {"id": "customer-1"}
    assert {item["external_id"] for item in related["subscription"]} == {"subscription-1"}
    assert {item["external_id"] for item in related["payment_method"]} == {"method-1"}
    assert {item["external_id"] for item in related["invoice"]} == {"invoice-1"}
    assert {item["external_id"] for item in related["transaction"]} == {"transaction-1"}
    assert dashboard["records"] == before["records"] + 5
    for resource in ("customer", "payment_method", "subscription", "invoice", "transaction"):
        assert dashboard["resources"][resource] == before["resources"][resource] + 1
    assert dashboard["resource_amounts"]["subscription"] == before["resource_amounts"]["subscription"] + 1000.0
    assert dashboard["resource_amounts"]["invoice"] == before["resource_amounts"]["invoice"] + 2000.0
    assert dashboard["resource_amounts"]["transaction"] == before["resource_amounts"]["transaction"] + 1500.0
    assert {entry["year"] for entry in dashboard["activity"]} >= {2099}


def test_payku_canonical_detail_links_clients_plans_subscriptions_and_transactions(db_session) -> None:
    db_session.add_all(
        [
            Client(source="payku", external_id="client-1", raw_payload={"id": "client-1"}),
            Plan(source="payku", external_id="plan-1", raw_payload={"id": "plan-1"}),
            Subscription(source="payku", external_id="subscription-1", client_external_id="client-1", plan_external_id="plan-1", raw_payload={"id": "subscription-1"}),
            Subscription(source="payku", external_id="other-subscription", client_external_id="client-2", raw_payload={"id": "other-subscription"}),
            Payment(source="payku", external_id="transaction-1", raw_payload={"subscriptions": [{"id": "subscription-1"}]}),
            SourceRecord(source="payku", resource_type="client", external_id="stale-source-record", payload={"id": "stale-source-record"}),
        ]
    )
    db_session.flush()

    client = staging.provider_record_detail("payku", "client", "client-1", db=db_session)
    subscription = staging.provider_record_detail("payku", "subscription", "subscription-1", db=db_session)
    transaction = staging.provider_record_detail("payku", "transaction", "transaction-1", db=db_session)

    client_related = {group["resource_type"]: group["items"] for group in client["related"]}
    subscription_related = {group["resource_type"]: group["items"] for group in subscription["related"]}
    transaction_related = {group["resource_type"]: group["items"] for group in transaction["related"]}
    assert client["record"]["payload"] == {"id": "client-1"}
    assert [item["external_id"] for item in client_related["subscription"]] == ["subscription-1"]
    assert [item["external_id"] for item in subscription_related["client"]] == ["client-1"]
    assert [item["external_id"] for item in subscription_related["plan"]] == ["plan-1"]
    assert [item["external_id"] for item in subscription_related["transaction"]] == ["transaction-1"]
    assert [item["external_id"] for item in transaction_related["subscription"]] == ["subscription-1"]
