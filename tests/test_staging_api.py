from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app.api.v1.routes import staging
from app.db.session import engine
from app.models.source_record import SourceRecord
from app.models.sync_run import SyncRun


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
            SourceRecord(source="payku", resource_type="client", external_id="payku-1", payload={"name": "Payku"}),
        ]
    )
    db_session.flush()

    response = staging.list_records(source="toku", resource_type="test_customer", db=db_session, limit=50)

    assert response["total"] == 1
    assert response["items"][0]["external_id"] == "toku-1"
    assert response["items"][0]["payload"] == {"name": "Toku"}


def test_virtualpos_records_filter_by_operational_fields_and_order_dates(db_session) -> None:
    db_session.add_all(
        [
            SourceRecord(source="virtualpos", resource_type="client", external_id="client-1", payload={"uuid": "client-1", "first_name": "Ana", "last_name": "Rios", "status": "ACTIVO"}),
            SourceRecord(source="virtualpos", resource_type="client", external_id="client-2", payload={"uuid": "client-2", "first_name": "Bruno", "last_name": "Rios", "status": "INACTIVO"}),
            SourceRecord(source="virtualpos", resource_type="plan", external_id="plan-1", payload={"id": "plan-1", "automatic_renewal": "T"}),
            SourceRecord(source="virtualpos", resource_type="plan", external_id="plan-2", payload={"id": "plan-2", "automatic_renewal": "F"}),
            SourceRecord(source="virtualpos", resource_type="charge", external_id="charge-old", payload={"charge_date": "9999-01-01"}),
            SourceRecord(source="virtualpos", resource_type="charge", external_id="charge-new", payload={"charge_date": "9999-02-01"}),
            SourceRecord(source="virtualpos", resource_type="payment", external_id="payment-old", payload={"order": {"authorized_at": "9999-01-01"}}),
            SourceRecord(source="virtualpos", resource_type="payment", external_id="payment-new", payload={"order": {"authorized_at": "9999-02-01"}}),
        ]
    )
    db_session.flush()

    clients = staging.list_records(source="virtualpos", resource_type="client", filter_field="name", query="ana", db=db_session)
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
            SourceRecord(source="toku", resource_type="customer", external_id="toku-customer-filter", payload={"id": "customer-filter", "government_id": "11.222.333-4"}),
            SourceRecord(source="toku", resource_type="subscription", external_id="toku-subscription-filter", payload={"id": "subscription-filter", "customer": "customer-filter"}),
            SourceRecord(source="payku", resource_type="plan", external_id="payku-plan-filter", payload={"id": "payku-plan-filter", "name": "Plan Filtro Exclusivo"}),
        ]
    )
    db_session.flush()

    customers = staging.list_records(source="toku", resource_type="customer", filter_field="government_id", query="222.333", db=db_session)
    subscriptions = staging.list_records(source="toku", resource_type="subscription", filter_field="customer", query="customer-filter", db=db_session)
    plans = staging.list_records(source="payku", resource_type="plan", filter_field="name", query="filtro exclusivo", db=db_session)

    assert [record["external_id"] for record in customers["items"]] == ["toku-customer-filter"]
    assert [record["external_id"] for record in subscriptions["items"]] == ["toku-subscription-filter"]
    assert [record["external_id"] for record in plans["items"]] == ["payku-plan-filter"]


def test_staging_summary_groups_records_and_latest_sync_by_source(db_session) -> None:
    before = staging.staging_summary(db=db_session)
    before_toku = next(source for source in before["sources"] if source["source"] == "toku")
    db_session.add_all(
        [
            SourceRecord(source="virtualpos", resource_type="client", external_id="vp-1", payload={}),
            SourceRecord(source="toku", resource_type="test_transaction", external_id="summary-toku-1", payload={}),
            SourceRecord(source="toku", resource_type="test_customer", external_id="summary-toku-2", payload={}),
            SyncRun(
                source="toku",
                status="completed",
                records_processed=2,
                finished_at=datetime.now(UTC),
            ),
        ]
    )
    db_session.flush()

    response = staging.staging_summary(db=db_session)
    toku = next(source for source in response["sources"] if source["source"] == "toku")

    assert toku["records"] == before_toku["records"] + 2
    assert toku["resources"]["test_customer"] == 1
    assert toku["resources"]["test_transaction"] == 1
    assert toku["last_sync"] is not None
    assert toku["last_sync"]["records_processed"] == 2


def test_channel_dashboard_aggregates_local_activity_and_statuses(db_session) -> None:
    db_session.add_all(
        [
            SourceRecord(
                source="payku",
                resource_type="transaction",
                external_id="dashboard-payku-1",
                payload={"id": "dashboard-payku-1", "status": "success", "amount": "1200", "created_at": "2099-02-03"},
            ),
            SourceRecord(
                source="payku",
                resource_type="subscription",
                external_id="dashboard-payku-2",
                payload={"id": "dashboard-payku-2", "status": "active"},
            ),
        ]
    )
    db_session.flush()

    response = staging.channel_dashboard(source="payku", db=db_session)

    assert {entry["year"] for entry in response["activity"]} >= {2099}
    assert {entry["status"] for entry in response["statuses"]} >= {"success", "active"}
    assert response["activity_resource"] == "transaction"


def test_virtualpos_client_detail_lists_all_subscriptions_by_social_id(db_session) -> None:
    db_session.add_all(
        [
            SourceRecord(
                source="virtualpos",
                resource_type="client",
                external_id="detail-client-1",
                payload={"uuid": "detail-client-1", "social_id": "12.345.678-9"},
            ),
            SourceRecord(
                source="virtualpos",
                resource_type="subscription",
                external_id="detail-subscription-1",
                payload={"id": "detail-subscription-1", "client": {"social_id": "12.345.678-9"}},
            ),
            SourceRecord(
                source="virtualpos",
                resource_type="subscription",
                external_id="detail-subscription-2",
                payload={"id": "detail-subscription-2", "client": {"social_id": "12.345.678-9"}},
            ),
            SourceRecord(
                source="virtualpos",
                resource_type="subscription",
                external_id="other-subscription",
                payload={"id": "other-subscription", "client": {"social_id": "98.765.432-1"}},
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
            SourceRecord(source="virtualpos", resource_type="plan", external_id="detail-plan-1", payload={"id": "plan-1"}),
            SourceRecord(
                source="virtualpos",
                resource_type="subscription",
                external_id="plan-subscription-1",
                payload={"plan_id": "plan-1"},
            ),
            SourceRecord(
                source="virtualpos",
                resource_type="subscription",
                external_id="other-plan-subscription",
                payload={"plan_id": "plan-2"},
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
            SourceRecord(
                source="virtualpos",
                resource_type="subscription",
                external_id="detail-subscription-3",
                payload={"payment_method": {"brand": "Visa", "last4": "1234"}},
            ),
            SourceRecord(
                source="virtualpos",
                resource_type="charge",
                external_id="detail-charge-1",
                payload={"amount": 1000, "charge_date": "2026-01-01"},
                sync_context={"subscription_external_id": "detail-subscription-3"},
            ),
            SourceRecord(
                source="virtualpos",
                resource_type="charge",
                external_id="detail-charge-2",
                payload={"amount": 2000, "charge_date": "2026-02-01"},
                sync_context={"subscription_external_id": "detail-subscription-3"},
            ),
            SourceRecord(
                source="virtualpos",
                resource_type="charge",
                external_id="other-charge",
                payload={"amount": 2000},
                sync_context={"subscription_external_id": "other-subscription"},
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
        SourceRecord(
            source="virtualpos",
            resource_type="charge",
            external_id="detail-charge-record",
            payload={"id": "detail-charge-record", "charge_date": "2026-01-01"},
        )
    )
    db_session.flush()

    response = staging.virtualpos_charge_detail(external_id="detail-charge-record", db=db_session)

    assert response["charge"]["external_id"] == "detail-charge-record"


def test_virtualpos_payment_detail_returns_local_staging_record(db_session) -> None:
    db_session.add(
        SourceRecord(
            source="virtualpos",
            resource_type="payment",
            external_id="detail-payment-record",
            payload={"order": {"uuid": "payment-uuid"}},
        )
    )
    db_session.flush()

    response = staging.virtualpos_payment_detail(external_id="detail-payment-record", db=db_session)

    assert response["payment"]["external_id"] == "detail-payment-record"


def test_toku_detail_returns_only_explicit_related_records(db_session) -> None:
    db_session.add_all(
        [
            SourceRecord(source="toku", resource_type="customer", external_id="toku-customer-1", payload={"id": "customer-1"}),
            SourceRecord(source="toku", resource_type="subscription", external_id="toku-subscription-1", payload={"customer": "customer-1"}),
            SourceRecord(source="toku", resource_type="invoice", external_id="toku-invoice-1", payload={"customer": "customer-1"}),
            SourceRecord(source="toku", resource_type="transaction", external_id="toku-transaction-1", payload={"customer_id": "customer-1"}),
            SourceRecord(source="toku", resource_type="subscription", external_id="toku-other-subscription", payload={"customer": "customer-2"}),
        ]
    )
    db_session.flush()

    response = staging.provider_record_detail("toku", "customer", "toku-customer-1", db=db_session)

    related = {group["resource_type"]: group["items"] for group in response["related"]}
    assert {item["external_id"] for item in related["subscription"]} == {"toku-subscription-1"}
    assert {item["external_id"] for item in related["invoice"]} == {"toku-invoice-1"}
    assert {item["external_id"] for item in related["transaction"]} == {"toku-transaction-1"}


def test_payku_detail_returns_subscriptions_by_explicit_client_id(db_session) -> None:
    db_session.add_all(
        [
            SourceRecord(source="payku", resource_type="client", external_id="payku-client-1", payload={"id": "client-1"}),
            SourceRecord(source="payku", resource_type="subscription", external_id="payku-subscription-1", payload={"client": {"id": "client-1"}}),
            SourceRecord(source="payku", resource_type="subscription", external_id="payku-other-subscription", payload={"client": {"id": "client-2"}}),
        ]
    )
    db_session.flush()

    response = staging.provider_record_detail("payku", "client", "payku-client-1", db=db_session)

    assert response["related"][0]["resource_type"] == "subscription"
    assert [item["external_id"] for item in response["related"][0]["items"]] == ["payku-subscription-1"]
