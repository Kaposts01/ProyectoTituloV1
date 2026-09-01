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
                payload={"amount": 1000},
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
    assert response["charge_total"] == 1
    assert response["charges"][0]["external_id"] == "detail-charge-1"


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
