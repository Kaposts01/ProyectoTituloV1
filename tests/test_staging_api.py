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
