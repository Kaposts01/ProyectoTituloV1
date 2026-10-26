"""POST /etl/run (410), dashboards centralizados Toku/Payku y calculo de mes en hora Chile."""
import uuid
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.routes import staging, tch
from app.core.config import settings
from app.core.security import ACCESS_COOKIE, create_access_token, get_current_user
from app.db.session import SessionLocal, engine
from app.main import app
from app.models.crm import PaymentMethod, Subscription
from app.models.etl_run import EtlRun
from app.models.payku_channel import PaykuTransaction as PkTx
from app.models.tch import TchRecaudacionMensual
from app.services import rejected_month


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


# -- (a) POST /etl/run ---------------------------------------------------------

def test_etl_run_returns_410_with_auth_and_csrf_and_creates_no_run(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    user = SimpleNamespace(
        id=uuid.uuid4(), is_active=True,
        roles=[SimpleNamespace(name="r", permissions=[SimpleNamespace(code="etl.run")])],
    )
    token, csrf = create_access_token(user)
    app.dependency_overrides[get_current_user] = lambda: user
    with SessionLocal() as other:
        before = other.scalar(select(func.count()).select_from(EtlRun))
    try:
        client = TestClient(app)
        client.cookies.set(ACCESS_COOKIE, token)
        no_csrf = client.post("/api/v1/etl/run")
        ok = client.post("/api/v1/etl/run", headers={"X-CSRF-Token": csrf})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert no_csrf.status_code == 403
    assert ok.status_code == 410
    with SessionLocal() as other:
        assert other.scalar(select(func.count()).select_from(EtlRun)) == before


# -- (b) Toku ------------------------------------------------------------------

def test_toku_dashboard_active_subscribers_and_churn_exclude_non_chargeable(db_session) -> None:
    before = staging._toku_centralized_dashboard(db_session)
    db_session.add_all([
        Subscription(source="toku", external_id="kpi-active-ok", client_external_id="kpi-c1",
                     status="ACTIVE", amount="1000", suscription_date="2099-03-01", raw_payload={}),
        Subscription(source="toku", external_id="kpi-active-nocharge", client_external_id="kpi-c2",
                     status="ACTIVE", amount="2000", suscription_date="2099-03-02", raw_payload={}),
        Subscription(source="toku", external_id="kpi-cancelled", client_external_id="kpi-c3",
                     status="CANCELLED", amount="3000", suscription_date="2099-03-03",
                     canceled_at="2099-03-20", raw_payload={}),
        PaymentMethod(source="toku", external_id="kpi-pm-ok", status="CHARGEABLE",
                      raw_payload={"subscription_ids": ["kpi-active-ok"]}),
        PaymentMethod(source="toku", external_id="kpi-pm-bad", status="INACTIVE",
                      raw_payload={"subscription_ids": ["kpi-active-nocharge"]}),
    ])
    db_session.flush()

    after = staging._toku_centralized_dashboard(db_session)

    assert after["kpis"]["active_subscribers"] == before["kpis"]["active_subscribers"] + 1
    assert after["kpis"]["mrr"] == before["kpis"]["mrr"] + 1000
    act = {r["status"]: r["count"] for r in after["activation_monthly"] if (r["year"], r["month"]) == (2099, 3)}
    assert act.get("ACTIVE") == 1  # la activa no chargeable queda fuera
    assert act.get("CANCELLED") == 1
    churn = [r for r in after["churn_monthly"] if (r["year"], r["month"]) == (2099, 3)]
    assert sum(r["count"] for r in churn) == 1
    assert 0 < after["kpis"]["churn_rate"] <= 100


# -- (c) Payku -----------------------------------------------------------------

def _payku_sub(ext_id: str, rut: str | None, amount: str = "1000") -> Subscription:
    return Subscription(source="payku", external_id=ext_id, status="active", amount=amount,
                        client_social_id=rut, suscription_date="2099-04-01", raw_payload={})


def test_payku_dashboard_mrr_and_arpu_use_only_subscriptions_with_success(db_session) -> None:
    before = staging._payku_centralized_dashboard(db_session)
    db_session.add_all([
        _payku_sub("kpi-pk-1", "11111111-1"),
        _payku_sub("kpi-pk-2", "22222222-2"),
        _payku_sub("kpi-pk-nosuccess", "33333333-3"),
        PkTx(external_id="kpi-tx-1a", subscription_id="kpi-pk-1", status="success", amount="1000",
             created_at_api="2099-04-01T10:00:00"),
        PkTx(external_id="kpi-tx-1b", subscription_id="kpi-pk-1", status="success", amount="1200",
             created_at_api="2099-05-01T10:00:00"),
        PkTx(external_id="kpi-tx-2", subscription_id="kpi-pk-2", status="success", amount="800",
             created_at_api=None),
        PkTx(external_id="kpi-tx-ns", subscription_id="kpi-pk-nosuccess", status="failed", amount="5000",
             created_at_api="2099-05-01T10:00:00"),
    ])
    db_session.flush()

    after = staging._payku_centralized_dashboard(db_session)["kpis"]
    prev = before["kpis"]

    assert after["active_subscribers"] == prev["active_subscribers"] + 3
    assert after["mrr"] == prev["mrr"] + 1200 + 800  # ultima success; failed no suma
    # ARPU: solo suscripciones que aportan al MRR (la 'nosuccess' no entra al denominador).
    assert after["active_clients"] == prev["active_clients"] + 2
    assert after["arpu"] == round(after["mrr"] / after["active_clients"], 0)


def _tx(sub, amount, created, ext, status="success"):
    return {"subscription_id": sub, "status": status, "amount": amount, "created_at": created, "external_id": ext}


def test_payku_last_success_is_deterministic_and_handles_none_dates() -> None:
    ids = {"s1", "s2"}
    rows = [
        _tx("s1", "100", "2099-01-01", "a"),
        _tx("s1", "300", "2099-01-01", "b"),  # empate de fecha: gana mayor external_id
        _tx("s1", "999", None, "z"),           # sin fecha: siempre la mas antigua
        _tx("s2", "50", None, "a"),            # unica con None: cuenta
    ]
    forward = staging._payku_last_success_by_sub(ids, rows)
    backward = staging._payku_last_success_by_sub(ids, list(reversed(rows)))
    assert forward == backward == {"s1": 300.0, "s2": 50.0}


def test_payku_arpu_equals_current_when_all_active_have_success() -> None:
    subs = [
        SimpleNamespace(resource_type="subscription", payload={
            "id": f"s{i}", "status": "active", "amount": "1000", "start": "2099-01-01", "client": {"rut": f"r{i}"}})
        for i in range(3)
    ]
    rows = [_tx(f"s{i}", "1000", "2099-01-02", f"t{i}") for i in range(3)]
    legacy = staging._payku_extended_data(subs)["kpis"]
    new = staging._payku_extended_data(subs, rows)["kpis"]
    assert (new["mrr"], new["active_clients"], new["arpu"]) == (
        legacy["mrr"], legacy["active_clients"], legacy["arpu"]
    )


# -- Mes en hora Chile ---------------------------------------------------------

def test_rejected_month_uses_chile_time_not_utc(monkeypatch) -> None:
    # 2099-01-31 23:00 en Santiago ya es febrero en UTC: el mes correcto es enero.
    fake = datetime(2099, 1, 31, 23, 0, tzinfo=ZoneInfo("America/Santiago"))
    monkeypatch.setattr(rejected_month, "now_chile", lambda: fake)
    rows = [
        {"year": 2099, "month": 1, "status": "FAILED", "count": 2, "amount": 100.004},
        {"year": 2099, "month": 2, "status": "FAILED", "count": 9, "amount": 900.0},
    ]
    assert staging._rejected_current_month(rows, staging._REJECTED_TX_STATUSES) == {"count": 2, "amount": 100.0}
    tch_rows = [
        {"year": 2099, "month": 1, "status": "RECHAZADA", "count": 3, "amount": 300},
        {"year": 2099, "month": 1, "status": "ACEPTADA", "count": 7, "amount": 700},
        {"year": 2099, "month": 2, "status": "RECHAZADA", "count": 5, "amount": 500},
    ]
    assert tch._rejected_current_month(tch_rows) == {"count": 3, "amount": 300.0}


# -- TCH recaudo mensual -------------------------------------------------------

def _ctrl(periodo, acc_n, acc_m):
    return TchRecaudacionMensual(
        periodo=periodo, aceptadas_cantidad=acc_n, aceptadas_monto=acc_m,
        rechazadas_cantidad=0, rechazadas_monto="0", archivo_origen="x.xlsx",
    )


def test_tch_recaudo_adds_accepted_transactions_and_keeps_legacy_alias() -> None:
    out = tch._recaudo_mensual_kpis([_ctrl("2026-09", 200, "1600000")])
    assert out["accepted_transactions"] == out["active_clients"] == 200


@pytest.mark.parametrize(
    "raw,expected",
    [("$1.600.000", 1600000.0), ("1600000.50", 1600000.0), ("abc", 0.0), ("", 0.0)],
)
def test_tch_recaudo_amount_parsing_is_defensive(raw, expected) -> None:
    out = tch._recaudo_mensual_kpis([_ctrl("2026-09", 2, raw)])
    assert out["mrr"] == expected


def test_tch_summary_reports_monthly_series_source(db_session, monkeypatch) -> None:
    from sqlalchemy import delete

    monkeypatch.setattr(tch, "_get_db", lambda: db_session)
    db_session.execute(delete(TchRecaudacionMensual))
    db_session.flush()
    assert tch.tch_summary()["transacciones_fuente"] == "transacciones"

    db_session.add(TchRecaudacionMensual(
        periodo="2099-01", aceptadas_cantidad=1, aceptadas_monto="100",
        rechazadas_cantidad=0, rechazadas_monto="0", archivo_origen="t.xlsx",
    ))
    db_session.flush()
    assert tch.tch_summary()["transacciones_fuente"] == "recaudacion_mensual"
