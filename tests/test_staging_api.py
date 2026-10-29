from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.api.v1.routes import reports, staging
from app.db.session import engine
from app.models.crm import Charge, Client, Payment, PaymentMethod, Plan, Subscription
from app.models.payku_channel import PaykuSubscription, PaykuTransaction
from app.models.source_record import SourceRecord
from app.models.sync_run import SyncRun
from app.models.tch import (
    TchCliente,
    TchRecaudacionMensual,
    TchSuscripcion,
    TchTransaccion,
)
from app.services.channel_store import (
    extract_payku_subscription,
    extract_payku_transaction,
    extract_toku_invoice,
    extract_toku_payment_method,
    extract_toku_subscription,
)


def test_cstg_exposes_virtualpos_charge_subscription_id() -> None:
    record = SimpleNamespace(
        id="charge-1",
        source="virtualpos1",
        external_id="charge-1",
        raw_payload={"id": "charge-1"},
        subscription_external_id="subscription-1",
        updated_at=None,
    )

    result = staging._cstg(record, "charge")

    assert result["payload"]["subscription_id"] == "subscription-1"


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


def test_virtualpos_charge_subscription_filter_falls_back_to_raw_payload(db_session) -> None:
    db_session.add(
        Charge(
            source="virtualpos1",
            external_id="legacy-charge",
            subscription_external_id=None,
            raw_payload={"suscription_id": "legacy-subscription"},
        )
    )
    db_session.flush()

    response = staging.list_records(
        source="virtualpos",
        resource_type="charge",
        filter_field="subscription_id",
        query="legacy-subscription",
        db=db_session,
    )

    assert [item["external_id"] for item in response["items"]] == ["legacy-charge"]


def test_virtualpos_multiple_column_filters_and_typed_ordering(db_session) -> None:
    db_session.add_all(
        [
            Client(source="virtualpos1", external_id="client-alpha", raw_payload={"uuid": "client-alpha", "first_name": "Alba", "last_name": "Rios", "email": "alba.filterestunique@example.org", "status": "ACTIVO"}),
            Client(source="virtualpos1", external_id="client-zeta", raw_payload={"uuid": "client-zeta", "first_name": "Zoe", "last_name": "Rios", "email": "zoe.filterestunique@example.org", "status": "INACTIVO"}),
            Plan(source="virtualpos1", external_id="plan-20", raw_payload={"id": "plan-20", "name": "Plan veinte", "amount": "20"}),
            Plan(source="virtualpos1", external_id="plan-100", raw_payload={"id": "plan-100", "name": "Plan cien", "amount": "100"}),
            Charge(source="virtualpos1", external_id="charge-april", charge_date="2099-04-01", raw_payload={"id": "charge-april", "amount": "20", "charge_date": "2099-04-01"}),
            Charge(source="virtualpos1", external_id="charge-may", charge_date="2099-05-01", raw_payload={"id": "charge-may", "amount": "100", "charge_date": "2099-05-01"}),
        ]
    )
    db_session.flush()

    clients = staging._list_vp(
        "virtualpos", db_session, "client", None, None, "name", "asc", 0, 50,
        filters=["email:filterestunique", "status:ACTIVO"],
    )
    plans = staging._list_vp("virtualpos", db_session, "plan", None, None, "amount", "asc", 0, 50)
    charges = staging._list_vp(
        "virtualpos", db_session, "charge", None, None, "charge_date", "desc", 0, 50,
        amount_min="50", date_from="2099-05-01", date_to="2099-05-31",
    )

    assert [item["external_id"] for item in clients["items"]] == ["client-alpha"]
    plan_ids = [item["external_id"] for item in plans["items"]]
    assert plan_ids.index("plan-20") < plan_ids.index("plan-100")
    assert [item["external_id"] for item in charges["items"]] == ["charge-may"]


def test_status_filter_values_include_records_outside_the_current_page(db_session) -> None:
    db_session.add_all([
        Subscription(source="payku", external_id="active", status="active", raw_payload={}),
        Subscription(source="payku", external_id="cancelled", status="cancelled", raw_payload={}),
    ])
    db_session.flush()

    response = staging.list_record_filter_values(
        source="payku", resource_type="subscription", filter_field="status", db=db_session
    )

    assert {value.lower() for value in response["values"]} >= {"active", "cancelled"}


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
            # Tarjetas de rechazo = universo de CARGOS hasta hoy (no meses futuros): periodo pasado.
            TchRecaudacionMensual(
                periodo="2026-09", aceptadas_cantidad=1, aceptadas_monto="2000",
                rechazadas_cantidad=0, rechazadas_monto="0", archivo_origen="control.xlsx",
            ),
            Charge(source="payku", external_id="general-payku-charge-ok", status="pagado",
                   charge_date="2026-09-02", raw_payload={}),
            Charge(source="payku", external_id="general-payku-charge-rej", status="rechazado",
                   charge_date="2026-09-02", raw_payload={}),
            Charge(source="payku", external_id="general-payku-charge-cancel", status="cancelado",
                   charge_date="2026-09-02", raw_payload={}),
        ]
    )
    db_session.flush()
    staging.invalidate_dashboard_cache()
    response = staging.general_dashboard(db=db_session)

    assert response["clients"] == before["clients"] + 2
    assert response["subscriptions"]["active"] == before["subscriptions"]["active"] + 2
    assert response["transactions"]["total"] == before["transactions"]["total"] + 3
    assert response["transactions"]["accepted"] == before["transactions"]["accepted"] + 2
    assert response["transactions"]["rejected"] == before["transactions"]["rejected"] + 1
    assert response["transactions"]["amount"] == before["transactions"]["amount"] + 3200
    assert {entry["status"] for entry in response["transactions_monthly"] if entry["year"] == 2099} >= {"Aceptadas", "Rechazadas"}
    assert {entry["status"] for entry in response["activations_monthly"] if entry["year"] == 2099} >= {"Payku", "TCH"}


def test_pending_payments_counts_only_explicit_pending_charges(db_session) -> None:
    # Antes 'in_progress' (estado no terminal desconocido) contaba como pendiente; ahora solo estados
    # explicitamente pendientes (pendiente/pending/procesando). Ver tests/test_dashboard_data_integrity.py.
    staging.invalidate_dashboard_cache()
    before = staging.general_dashboard(db=db_session)
    db_session.add_all([
        Charge(source="payku", external_id="pend-1", status="pending", charge_date="2099-05-01", raw_payload={}),
        Charge(source="payku", external_id="pend-2", status="Pendiente", charge_date="2099-05-01", raw_payload={}),
        Charge(source="payku", external_id="pend-3", status="in_progress", charge_date="2099-05-01", raw_payload={}),
        Charge(source="payku", external_id="term-paid", status="pagado", charge_date="2099-05-01", raw_payload={}),
        Charge(source="payku", external_id="term-rej", status="rejected", charge_date="2099-05-01", raw_payload={}),
    ])
    db_session.flush()
    staging.invalidate_dashboard_cache()
    after = staging.general_dashboard(db=db_session)

    assert after["pending_payments"] == before["pending_payments"] + 2


def test_sync_success_rate_100_when_all_runs_completed(db_session) -> None:
    from sqlalchemy import delete as sa_delete
    db_session.execute(sa_delete(SyncRun))
    db_session.flush()
    db_session.add_all([
        SyncRun(source="toku", status="completed", started_at=datetime.now(UTC), records_processed=10),
        SyncRun(source="payku", status="completed", started_at=datetime.now(UTC), records_processed=5),
    ])
    db_session.flush()
    staging.invalidate_dashboard_cache()
    response = staging.general_dashboard(db=db_session)

    assert response["sync_success_rate_pct"] == 100.0


def test_sync_success_rate_null_when_no_runs_in_30_days(db_session) -> None:
    from sqlalchemy import delete as sa_delete
    db_session.execute(sa_delete(SyncRun))
    db_session.flush()
    staging.invalidate_dashboard_cache()
    response = staging.general_dashboard(db=db_session)

    assert response["sync_success_rate_pct"] is None


def test_dashboard_channel_endpoint_returns_subset_by_source(db_session) -> None:
    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    client = TestClient(fastapi_app)
    staging.invalidate_dashboard_cache()
    response = client.get(
        "/api/v1/staging/dashboard/channel/toku",
        headers={"Authorization": "Bearer test"},
    )
    assert response.status_code in (200, 401, 403)
    if response.status_code == 200:
        data = response.json()
        assert data["channel"] == "Toku"
        assert "clients" in data
        assert "transactions_monthly" in data


def test_report_series_filters_events_to_the_requested_date_range(db_session) -> None:
    db_session.add_all(
        [
            Payment(source="payku", external_id="report-in", status="success", amount="1200", payment_date="2099-04-15", raw_payload={}),
            Payment(source="payku", external_id="report-out", status="success", amount="900", payment_date="2099-05-01", raw_payload={}),
            Charge(source="payku", external_id="report-charge", status="rejected", amount="500", charge_date="2099-04-20", raw_payload={}),
            Subscription(source="payku", external_id="report-sub", amount="1000", suscription_date="2099-04-02", canceled_at="2099-04-30", raw_payload={}),
        ]
    )
    db_session.flush()

    response = reports._series(db_session, "payku", date(2099, 4, 1), date(2099, 4, 30))

    assert response["transactions"] == [{"year": 2099, "month": 4, "status": "Aceptadas", "count": 1, "amount": 1200.0}]
    assert response["charges"] == [{"year": 2099, "month": 4, "status": "Rechazadas", "count": 1, "amount": 500.0}]
    assert response["activations"] == [{"year": 2099, "month": 4, "status": "Altas", "count": 1, "amount": 1000.0}]
    assert response["cancellations"] == [{"year": 2099, "month": 4, "status": "Bajas", "count": 1, "amount": 1000.0}]


def test_report_dates_require_a_strictly_increasing_range() -> None:
    assert reports._parse_date("2099-04-01", "date_from") == date(2099, 4, 1)
    with pytest.raises(Exception, match="date_from must use YYYY-MM-DD"):
        reports._parse_date("04-01-2099", "date_from")


def test_virtualpos_report_uses_historical_snapshot_and_period_charges(db_session) -> None:
    db_session.add_all(
        [
            Client(source="virtualpos1", external_id="report-client", provider_created_at="2099-04-01", raw_payload={}),
            Subscription(
                source="virtualpos1", external_id="report-active", client_external_id="report-client",
                suscription_date="2099-04-02", amount="1000", raw_payload={},
            ),
            Charge(
                source="virtualpos1", external_id="report-paid", subscription_external_id="report-active",
                status="pagado", amount="99999999", charge_date="2099-04-20", raw_payload={},
            ),
            Charge(
                source="virtualpos1", external_id="report-rejected", subscription_external_id="report-active",
                status="rechazado", amount="1200", charge_date="2099-04-21", raw_payload={},
            ),
        ]
    )
    db_session.flush()

    report = reports._virtualpos_report_data(db_session, date(2099, 4, 1), date(2099, 4, 30))

    assert report["kpis"]["n_activas"] >= 1
    assert report["kpis"]["total_clientes"] >= 1
    assert report["kpis"]["cargos_pag"] == 1
    assert report["kpis"]["cargos_rec"] == 1
    assert report["kpis"]["total_recaudado"] == 99999999
    assert report["tabla_activas"][0]["producto"] == "report-active"
    assert "Dashboard de Socios" in reports._virtualpos_report_html(date(2099, 4, 1), date(2099, 4, 30), report)


def test_tch_report_uses_tch_dashboard_permission() -> None:
    user = SimpleNamespace(roles=[SimpleNamespace(permissions=[SimpleNamespace(code="tch.dashboard.view")])])

    reports._require_report_access(user, "tch")


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


def test_virtualpos_dashboard_returns_its_latest_sync_run(db_session) -> None:
    db_session.add(
        SyncRun(source="virtualpos1", status="completed", records_processed=12, finished_at=datetime.now(UTC))
    )
    db_session.flush()

    dashboard = staging.channel_dashboard(source="virtualpos", db=db_session)

    assert dashboard["last_sync"]["status"] == "completed"
    assert dashboard["last_sync"]["records_processed"] == 12


def test_payku_dashboard_keeps_year_filter_when_only_subscription_dates_exist(db_session) -> None:
    db_session.add(
        Subscription(
            source="payku",
            external_id="dashboard-payku-dated-subscription",
            status="active",
            amount="1000",
            suscription_date="2099-03-01",
            raw_payload={},
        )
    )
    db_session.flush()

    dashboard = staging.channel_dashboard(source="payku", db=db_session)

    assert 2099 in dashboard["years"]


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
    assert dashboard["active_subs_monthly"] == [
        {"year": 2099, "month": 1, "count": 3},
        {"year": 2099, "month": 2, "count": 1},
    ]
    assert dashboard["churn_rate_monthly"] == [
        {"year": 2099, "month": 1, "rate": 0.0},
        {"year": 2099, "month": 2, "rate": 66.7},
    ]


def test_toku_dashboard_uses_transactions_for_payment_series_and_labels_alerts() -> None:
    records = [
        SourceRecord(source="toku", resource_type="subscription", external_id="active", payload={"status": "active", "anchor": "2099-01-01", "amount": "1000"}),
        SourceRecord(source="toku", resource_type="subscription", external_id="ended", payload={"status": "cancelled", "anchor": "2099-01-01", "end_date": "2099-02-01", "amount": "1000"}),
        SourceRecord(source="toku", resource_type="invoice", external_id="invoice", payload={"status": "PAID", "due_date": "2099-01-01", "amount": "1000"}),
        SourceRecord(source="toku", resource_type="transaction", external_id="transaction", payload={"status": "SUCCESS", "transaction_date": "2099-01-02", "amount": "1000"}),
    ]

    dashboard = staging._toku_extended_data(records)

    assert dashboard["payments_monthly"] == dashboard["transactions_monthly"]
    assert dashboard["payments_monthly"] != dashboard["invoices_monthly"]
    assert {alert["canal"] for alert in dashboard["alerts"]} == {"Toku"}
    assert dashboard["churn_rate_monthly"][-1] == {"year": 2099, "month": 2, "rate": 50.0}


def test_channel_alerts_identify_their_source() -> None:
    alerts = staging._channel_alerts(
        [],
        [{"year": 2099, "month": 1, "count": 1}],
        [{"year": 2099, "month": 1, "count": 2}],
        {"churn_rate": 15},
        "Payku",
    )

    assert {alert["canal"] for alert in alerts} == {"Payku"}


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


def test_payku_transaction_reads_historical_transaction_identifier() -> None:
    transaction = extract_payku_transaction({
        "transaction": 12345,
        "__subscription_id": "subscription-1",
        "created_at": "2099-01-15T12:00:00",
    })

    assert transaction["external_id"] == "12345"
    assert transaction["subscription_id"] == "subscription-1"
    assert transaction["created_at_api"] == "2099-01-15T12:00:00"


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
                plan_external_id=None,
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


def test_virtualpos_plan_list_counts_non_failed_active_and_cobrable_subscriptions(db_session) -> None:
    db_session.add_all(
        [
            Plan(source="virtualpos1", external_id="metrics-plan", raw_payload={"id": "metrics-plan"}),
            Subscription(source="virtualpos1", external_id="active-cobrable", plan_external_id="metrics-plan", status="ACTIVA", raw_payload={}),
            Subscription(source="virtualpos1", external_id="active-uncobrable", plan_external_id="metrics-plan", status="ACTIVA", raw_payload={}),
            Subscription(source="virtualpos1", external_id="cancelled", plan_external_id="metrics-plan", status="CANCELADA", raw_payload={}),
            Subscription(source="virtualpos1", external_id="failed", plan_external_id="metrics-plan", status="SUSCRIPCION_FALLIDA", raw_payload={}),
            Charge(source="virtualpos1", external_id="recent-paid", subscription_external_id="active-cobrable", status="pagado", charge_date="2099-01-01", raw_payload={}),
            Charge(source="virtualpos1", external_id="old-paid", subscription_external_id="active-uncobrable", status="pagado", charge_date="2000-01-01", raw_payload={}),
        ]
    )
    db_session.flush()

    response = staging.list_records(source="virtualpos", resource_type="plan", db=db_session)
    plan = next(item for item in response["items"] if item["external_id"] == "metrics-plan")

    assert plan["subscription_count"] == 3
    assert plan["active_subscription_count"] == 2
    assert plan["cobrable_subscription_count"] == 1


def test_virtualpos_charge_and_payment_details_include_verified_relationships(db_session) -> None:
    db_session.add_all(
        [
            Client(source="virtualpos1", external_id="related-client", social_id="11.111.111-1", first_name="Ana", last_name="Rios", raw_payload={}),
            Plan(source="virtualpos1", external_id="related-plan", name="Plan mensual", raw_payload={}),
            Subscription(source="virtualpos1", external_id="related-subscription", client_external_id="related-client", client_social_id="11.111.111-1", plan_external_id="related-plan", raw_payload={}),
            Charge(source="virtualpos1", external_id="related-charge", subscription_external_id="related-subscription", raw_payload={"payment": {"order": {"uuid": "related-payment"}}}),
            Payment(source="virtualpos1", external_id="related-payment", raw_payload={"order": {"uuid": "related-payment"}}),
            Payment(source="virtualpos1", external_id="direct-payment", client_external_id="related-client", raw_payload={"order": {"uuid": "direct-payment"}}),
        ]
    )
    db_session.flush()

    charge = staging.virtualpos_charge_detail(external_id="related-charge", db=db_session)
    payment = staging.virtualpos_payment_detail(external_id="related-payment", db=db_session)
    direct_payment = staging.virtualpos_payment_detail(external_id="direct-payment", db=db_session)
    charges = staging.list_records(source="virtualpos", resource_type="charge", filter_field="id", query="related-charge", db=db_session)
    payments = staging.list_records(source="virtualpos", resource_type="payment", filter_field="uuid", query="related-payment", db=db_session)
    listed_charge = next(item for item in charges["items"] if item["external_id"] == "related-charge")
    listed_payment = next(item for item in payments["items"] if item["external_id"] == "related-payment")

    assert charge["subscription"]["external_id"] == "related-subscription"
    assert charge["client"]["external_id"] == "related-client"
    assert charge["payment"]["external_id"] == "related-payment"
    assert payment["charge"]["external_id"] == "related-charge"
    assert payment["subscription"]["plan_name"] == "Plan mensual"
    assert listed_charge["client_name"] == "Ana Rios"
    assert listed_charge["client_social_id"] == "11.111.111-1"
    assert listed_payment["client_name"] == "Ana Rios"
    assert direct_payment["client"]["external_id"] == "related-client"
    assert direct_payment["charge"] is None
    assert direct_payment["subscription"] is None


def test_virtualpos_client_and_subscription_details_list_payments_by_client_social_id(db_session) -> None:
    db_session.add_all(
        [
            Client(source="virtualpos1", external_id="payment-client", social_id="22.222.222-2", raw_payload={}),
            Subscription(source="virtualpos1", external_id="payment-subscription", client_social_id="22.222.222-2", raw_payload={}),
            Payment(source="virtualpos1", external_id="payment-by-rut", raw_payload={"client": {"social_id": "22.222.222-2"}, "order": {"uuid": "payment-by-rut"}}),
        ]
    )
    db_session.flush()

    client = staging.virtualpos_client_detail(external_id="payment-client", db=db_session)
    subscription = staging.virtualpos_subscription_detail(external_id="payment-subscription", db=db_session)

    assert [payment["external_id"] for payment in client["payments"]] == ["payment-by-rut"]
    assert [payment["external_id"] for payment in subscription["payments"]] == ["payment-by-rut"]


def test_virtualpos_charge_uses_embedded_subscription_client_name_when_client_is_missing(db_session) -> None:
    db_session.add_all(
        [
            Subscription(source="virtualpos1", external_id="embedded-client-subscription", client_social_id="33.333.333-3", raw_payload={"client": {"first_name": "Ana", "last_name": "Sin ficha", "social_id": "33.333.333-3"}}),
            Charge(source="virtualpos1", external_id="embedded-client-charge", subscription_external_id="embedded-client-subscription", raw_payload={}),
        ]
    )
    db_session.flush()

    response = staging.list_records(source="virtualpos", resource_type="charge", filter_field="id", query="embedded-client-charge", db=db_session)

    assert response["items"][0]["client_name"] == "Ana Sin ficha"


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


def test_toku_dashboard_metrics_only_include_operational_statuses(db_session) -> None:
    before = staging.channel_dashboard("toku", db=db_session)
    db_session.add_all(
        [
            Subscription(source="toku", external_id="active-chargeable", client_external_id="customer-1", status="ACTIVE", amount="1000"),
            Subscription(source="toku", external_id="active-not-chargeable", client_external_id="customer-2", status="ACTIVE", amount="2000"),
            PaymentMethod(source="toku", external_id="chargeable", status="CHARGEABLE", raw_payload={"subscription_ids": ["active-chargeable"]}),
            PaymentMethod(source="toku", external_id="not-chargeable", status="INACTIVE", raw_payload={"subscription_ids": ["active-not-chargeable"]}),
            Charge(source="toku", external_id="paid", status="PAID", amount="3000"),
            Charge(source="toku", external_id="unpaid", status="PENDING", amount="4000"),
            Payment(source="toku", external_id="success", status="SUCCESS", amount="5000"),
            Payment(source="toku", external_id="failed", status="FAILED", amount="6000"),
        ]
    )
    db_session.flush()

    dashboard = staging.channel_dashboard("toku", db=db_session)

    assert dashboard["resources"]["subscription"] == before["resources"]["subscription"] + 1
    assert dashboard["resources"]["payment_method"] == before["resources"]["payment_method"] + 1
    assert dashboard["resources"]["invoice"] == before["resources"]["invoice"] + 1
    assert dashboard["resources"]["transaction"] == before["resources"]["transaction"] + 1
    assert dashboard["resource_amounts"]["subscription"] == before["resource_amounts"]["subscription"] + 1000.0
    assert dashboard["resource_amounts"]["invoice"] == before["resource_amounts"]["invoice"] + 3000.0
    assert dashboard["resource_amounts"]["transaction"] == before["resource_amounts"]["transaction"] + 5000.0
    assert dashboard["kpis"]["mrr"] == before["kpis"]["mrr"] + 1000.0
    assert dashboard["kpis"]["arpu"] == round(
        dashboard["kpis"]["mrr"] / dashboard["kpis"]["active_clients"], 0
    )


def test_toku_customer_detail_follows_subscription_and_payment_method_relationships(db_session) -> None:
    db_session.add_all(
        [
            Client(source="toku", external_id="customer-related", social_id="12.345.678-5"),
            Subscription(
                source="toku",
                external_id="subscription-related",
                status="ACTIVE",
                raw_payload={"customer": "customer-related"},
            ),
            PaymentMethod(
                source="toku",
                external_id="method-related",
                raw_payload={"customer": {"rut": "12.345.678-5"}, "subscription_ids": ["subscription-related"]},
            ),
            Charge(
                source="toku",
                external_id="invoice-related",
                raw_payload={"subscription": "subscription-related"},
            ),
            Payment(
                source="toku",
                external_id="transaction-related",
                status="SUCCESS",
                payment_date="2099-04-01",
                raw_payload={"customer": "customer-related", "payment_intents": [{"id_subscription": "subscription-related"}]},
            ),
        ]
    )
    db_session.flush()

    detail = staging.provider_record_detail("toku", "customer", "customer-related", db=db_session)

    related = {group["resource_type"]: group["items"] for group in detail["related"]}
    assert {item["external_id"] for item in related["subscription"]} >= {"subscription-related"}
    assert {item["external_id"] for item in related["payment_method"]} >= {"method-related"}
    assert {item["external_id"] for item in related["invoice"]} >= {"invoice-related"}
    assert {item["external_id"] for item in related["transaction"]} >= {"transaction-related"}

    subscription = staging.provider_record_detail("toku", "subscription", "subscription-related", db=db_session)
    subscription_related = {group["resource_type"]: group["items"] for group in subscription["related"]}
    assert {item["external_id"] for item in subscription_related["payment_method"]} >= {"method-related"}
    assert {item["external_id"] for item in subscription_related["invoice"]} >= {"invoice-related"}
    assert {item["external_id"] for item in subscription_related["transaction"]} >= {"transaction-related"}
    assert subscription["record"]["last_paid_date"] == "2099-04-01"
    assert subscription["record"]["secondary_status"] == "cobrable"

    filtered = staging.list_records(
        source="toku", resource_type="subscription", filter_field="secondary_status", query="cobrable", db=db_session, limit=1000
    )
    assert "subscription-related" in {item["external_id"] for item in filtered["items"]}

    ordered = staging.list_records(
        source="toku", resource_type="subscription", sort_field="secondary_status", sort_direction="desc", db=db_session, limit=1000
    )
    secondary_statuses = [item["secondary_status"].casefold() for item in ordered["items"]]
    assert secondary_statuses == sorted(secondary_statuses, reverse=True)

    values = staging.list_record_filter_values(
        source="toku", resource_type="subscription", filter_field="secondary_status", db=db_session
    )
    assert "cobrable" in values["values"]


def test_extract_toku_relationship_ids_accept_strings_and_objects() -> None:
    assert extract_toku_subscription({"id": "subscription-1", "customer": "customer-1"})["customer_id"] == "customer-1"
    assert extract_toku_invoice({"id": "invoice-1", "subscription": {"external_id": "subscription-1"}})["subscription_id"] == "subscription-1"
    assert extract_toku_payment_method({"payment_method": {"id": "method-1"}, "customer": "customer-1"})["customer_id"] == "customer-1"
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


def test_general_clients_searches_each_consolidated_client_field(db_session) -> None:
    db_session.add_all(
        [
            Client(
                source="payku",
                external_id="general-search-payku",
                social_id="99.111.222-3",
                first_name="Carla",
                last_name="Prueba",
                email="carla.busqueda@example.test",
                phone_number="+56912345678",
                raw_payload={},
            ),
            Subscription(
                source="payku",
                external_id="general-search-subscription",
                client_external_id="general-search-payku",
                status="active",
                raw_payload={},
            ),
        ]
    )
    db_session.flush()

    by_rut = staging._general_clients(db_session, "991112223", "rut")
    by_name = staging._general_clients(db_session, "carla", "name")
    by_last_name = staging._general_clients(db_session, "prueba", "last_name")
    by_platform = staging._general_clients(db_session, "payku", "platform")
    by_email = staging._general_clients(db_session, "busqueda@example", "email")
    by_phone = staging._general_clients(db_session, "912345678", "phone")

    for result in (by_rut, by_name, by_last_name, by_platform, by_email, by_phone):
        client = next(item for item in result if item["rut"] == "99.111.222-3")
        assert client["name"] == "Carla Prueba"
        assert client["origins"] == ["Payku"]
        assert client["active_origins"] == ["Payku"]


def test_general_subscriptions_combine_channels_and_filter_fields(db_session) -> None:
    db_session.add_all(
        [
            Client(source="toku", external_id="general-sub-client", social_id="88.777.666-5", first_name="Pablo", last_name="Cliente", raw_payload={}),
            Subscription(source="toku", external_id="general-sub-toku", client_external_id="general-sub-client", status="active", amount="2500", currency="CLP", suscription_date="2099-05-01", raw_payload={}),
            TchCliente(rut="77.666.555-4", nombre="Tania", apellido="TCH"),
            TchSuscripcion(numero_ficha=987654, cliente_rut="77.666.555-4", estado="VIGENTE", equivalente_pesos="3500", fecha_activacion="2099-05-02"),
        ]
    )
    db_session.flush()

    by_client = staging._general_subscriptions(db_session, "pablo", "client")
    by_platform = staging._general_subscriptions(db_session, "tch", "platform")
    by_rut = staging._general_subscriptions(db_session, "776665554", "rut")

    toku = next(item for item in by_client if item["id"] == "general-sub-toku")
    tch = next(item for item in by_platform if item["id"] == "987654")
    assert toku["platform"] == "Toku"
    assert toku["rut"] == "88.777.666-5"
    assert toku["amount"] == "2500"
    assert tch["client"] == "Tania TCH"
    assert tch["currency"] == "CLP"
    assert any(item["id"] == "987654" for item in by_rut)


def test_general_subscriptions_exclude_non_operational_statuses(db_session) -> None:
    db_session.add_all(
        [
            Subscription(source="virtualpos1", external_id="excluded-vp", status="SUSCRIPCION_FALLIDA", raw_payload={}),
            Subscription(source="payku", external_id="excluded-payku", status="register", raw_payload={}),
            Subscription(source="tch", external_id="excluded-tch-canonical", status="RECHAZADA", raw_payload={}),
            TchSuscripcion(numero_ficha=765432, estado="RECHAZADA"),
            Subscription(source="virtualpos1", external_id="included-vp", status="ACTIVA", raw_payload={}),
        ]
    )
    db_session.flush()

    ids = {item["id"] for item in staging._general_subscriptions(db_session)}

    assert "included-vp" in ids
    assert {"excluded-vp", "excluded-payku", "excluded-tch-canonical", "765432"}.isdisjoint(ids)


def test_general_dashboard_routes_precede_the_provider_detail_route() -> None:
    paths = [route.path for route in staging.router.routes]

    assert paths.index("/dashboard/general/clients") < paths.index("/{source}/{resource_type}/{external_id}")
    assert paths.index("/dashboard/general/subscriptions") < paths.index("/{source}/{resource_type}/{external_id}")


# --- TK-10: filtro/orden por secondary_status son globales (antes de paginar) ---

def _seed_secondary_status_subs(db_session, source: str, prefix: str) -> dict[str, str]:
    """Siembra suscripciones activas con 3 estados secundarios distintos; devuelve {external_id: estado}."""
    expected = {
        f"{prefix}-cobrable-a": "cobrable",
        f"{prefix}-cobrable-b": "cobrable",
        f"{prefix}-incobrable-a": "incobrable",
        f"{prefix}-incobrable-b": "incobrable",
        f"{prefix}-nunca": "Nunca Cobrado",
        f"{prefix}-inactiva": "inactiva",
    }
    paid_dates = {"cobrable": "2099-04-01", "incobrable": "2000-01-01"}
    rows: list = []
    for external_id, secondary in expected.items():
        rows.append(
            Subscription(
                source=source,
                external_id=external_id,
                status="CANCELED" if secondary == "inactiva" else "ACTIVE",
                raw_payload={"id": external_id},
            )
        )
        if secondary in paid_dates:
            if source == "toku":
                rows.append(
                    Payment(
                        source="toku",
                        external_id=f"{external_id}-tx",
                        status="SUCCESS",
                        payment_date=paid_dates[secondary],
                        raw_payload={"payment_intents": [{"id_subscription": external_id}]},
                    )
                )
            else:
                rows.append(
                    Charge(
                        source=source,
                        external_id=f"{external_id}-charge",
                        subscription_external_id=external_id,
                        status="pagado",
                        charge_date=paid_dates[secondary],
                        raw_payload={},
                    )
                )
    db_session.add_all(rows)
    db_session.flush()
    return expected


@pytest.mark.parametrize("source,prefix", [("toku", "tk10-toku"), ("virtualpos", "tk10-vp")])
def test_secondary_status_filter_is_global_before_pagination(db_session, source, prefix) -> None:
    db_source = "virtualpos1" if source == "virtualpos" else source
    expected = _seed_secondary_status_subs(db_session, db_source, prefix)
    mine = {k for k in expected}

    def fetch(**kwargs):
        return staging.list_records(
            source=source, resource_type="subscription", filter_field="secondary_status",
            query="cobrable", db=db_session, **kwargs,
        )

    full = fetch(limit=100000, offset=0)
    full_ids = [item["external_id"] for item in full["items"]]
    # total refleja el filtrado completo, no la pagina ni el universo sin filtrar
    assert full["total"] == len(full_ids)
    assert {i for i in full_ids if i in mine} == {f"{prefix}-cobrable-a", f"{prefix}-cobrable-b"}
    assert all(item["secondary_status"] == "cobrable" for item in full["items"])

    # Pagina 2 con limit pequeno: mismos registros que el corte global, con total global
    page2 = fetch(limit=1, offset=1)
    assert page2["total"] == full["total"]
    assert page2["offset"] == 1 and page2["limit"] == 1
    assert [item["external_id"] for item in page2["items"]] == full_ids[1:2]
    assert all(item["secondary_status"] == "cobrable" for item in page2["items"])

    # Paginas sucesivas (y la ultima) coinciden con el corte global; acotado para no hacer N consultas
    for offset in (0, 2, 4, max(full["total"] - 2, 0)):
        page = fetch(limit=2, offset=offset)
        assert page["total"] == full["total"]
        assert [item["external_id"] for item in page["items"]] == full_ids[offset: offset + 2]

    # Offset mas alla del total: sin items, total intacto
    beyond = fetch(limit=2, offset=full["total"] + 10)
    assert beyond["items"] == [] and beyond["total"] == full["total"]


@pytest.mark.parametrize("source,prefix", [("toku", "tk10s-toku"), ("virtualpos", "tk10s-vp")])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_secondary_status_sort_is_global_before_pagination(db_session, source, prefix, direction) -> None:
    db_source = "virtualpos1" if source == "virtualpos" else source
    expected = _seed_secondary_status_subs(db_session, db_source, prefix)

    def fetch(**kwargs):
        return staging.list_records(
            source=source, resource_type="subscription", sort_field="secondary_status",
            sort_direction=direction, db=db_session, **kwargs,
        )

    full = fetch(limit=100000, offset=0)
    full_ids = [item["external_id"] for item in full["items"]]
    keys = [item["secondary_status"].casefold() for item in full["items"]]
    assert keys == sorted(keys, reverse=direction == "desc")
    assert {i for i in full_ids if i.startswith(prefix)} == set(expected)

    # Cada pagina (offset > 0, limit pequeno) es el corte del orden global y total no es el de la pagina
    for offset in (0, 3, max(full["total"] - 3, 0)):
        page = fetch(limit=3, offset=offset)
        assert page["total"] == full["total"] == len(full_ids)
        assert [item["external_id"] for item in page["items"]] == full_ids[offset: offset + 3]
    page2 = fetch(limit=2, offset=2)
    assert [item["external_id"] for item in page2["items"]] == full_ids[2:4]


def test_month_coverage_gaps_helper() -> None:
    gaps = staging._month_coverage_gaps
    assert gaps([]) == []
    assert gaps([{"year": 2099, "month": 3}]) == []
    assert gaps([{"year": 2099, "month": 3}, {"year": 2099, "month": 4}]) == []
    assert gaps([{"year": 2098, "month": 11}, {"year": 2099, "month": 2}]) == [
        {"year": 2098, "month": 12},
        {"year": 2099, "month": 1},
    ]
    assert gaps([{"year": 2099, "month": 5}, {"year": 2099, "month": 5}, {"year": 2099, "month": 7}]) == [
        {"year": 2099, "month": 6}
    ]


def test_toku_activity_uses_payments_and_keeps_invoice_activity(db_session) -> None:
    db_session.add_all(
        [
            Charge(source="toku", external_id="act-inv-1", client_external_id="c", status="PAID", amount="2000", charge_date="2097-03-01", raw_payload={}),
            Payment(source="toku", external_id="act-pay-1", client_external_id="c", status="SUCCESS", amount="1500", payment_date="2098-05-02", raw_payload={}),
        ]
    )
    db_session.flush()
    dashboard = staging.channel_dashboard("toku", db=db_session)
    assert dashboard["activity_resource"] == "transaction"
    assert any(e["year"] == 2098 and e["month"] == 5 for e in dashboard["activity"])
    assert not any(e["year"] == 2097 for e in dashboard["activity"])
    assert any(e["year"] == 2097 and e["month"] == 3 for e in dashboard["invoice_activity"])
    assert {2097, 2098} <= set(dashboard["years"])


def test_payku_dashboard_exposes_coverage_gaps(db_session) -> None:
    db_session.add_all(
        [
            Payment(source="payku", external_id="gap-1", status="SUCCESS", amount="100", payment_date="2097-11-05", raw_payload={}),
            Payment(source="payku", external_id="gap-2", status="SUCCESS", amount="100", payment_date="2098-02-05", raw_payload={}),
        ]
    )
    db_session.flush()
    gaps = staging.channel_dashboard("payku", db=db_session)["coverage_gaps"]
    assert {"year": 2097, "month": 12} in gaps and {"year": 2098, "month": 1} in gaps
    assert {"year": 2097, "month": 11} not in gaps
