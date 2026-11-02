"""UI-28 y UI-29: un solo universo de rechazo (charge_stats) en `debts_monthly` y en el KPI `rejected_charges`.

Datos SINTETICOS (sin datos personales). Se usan años lejanos (2001 y 2099) para no chocar con otros datos de la base.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.api.v1.routes import staging
from app.db.session import engine
from app.models.crm import Charge, Payment
from app.services import rejected_month
from app.services.charge_stats import REJECTION_BASIS_LABELS, rejected_month_kpi


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


def test_debts_monthly_only_paid_and_rejected(db_session) -> None:
    """Pendiente, procesando, cancelado y un estado desconocido ya no cuentan como «rechazada»."""
    for i, status in enumerate(("pagado", "rechazado", "rechazado", "pendiente", "procesando", "cancelado", "raro")):
        db_session.add(Charge(
            source="virtualpos1", external_id=f"ui28-{i}", status=status, amount="1000",
            charge_date=f"2001-03-{i + 1:02d}", raw_payload={},
        ))
    db_session.flush()
    staging.invalidate_dashboard_cache()
    data = staging._compute_general_dashboard(db_session)

    rows = {
        r["charge_status"]: (r["count"], r["amount"])
        for r in data["debts_monthly"]
        if (r["year"], r["month"], r["status"]) == (2001, 3, "VirtualPOS")
    }
    assert rows == {"pagada": (1, 1000.0), "rechazada": (2, 2000.0)}


def test_rejected_month_kpi_rule() -> None:
    today = date(2099, 3, 15)
    rows = [
        {"date": "2099-03-02", "status": "FAILED", "amount": "100"},
        {"date": "2099-03-10", "status": "Rechazado", "count": 2, "amount": 400},
        {"date": "2099-03-20", "status": "FAILED", "amount": 999},  # futuro: fuera
        {"date": "2099-02-28", "status": "FAILED", "amount": 999},  # otro mes
        {"date": "2099-03-03", "status": "pendiente", "amount": 999},  # pendiente no es rechazo
        {"date": "2099-03-04", "status": "cancelado", "amount": 999},
        {"date": "2099-03-05", "status": "SUCCESS", "amount": 999},
    ]
    out = rejected_month_kpi(rows, today, "toku")
    assert out == {
        "count": 3, "amount": 500.0, "basis": "transacciones", "basis_label": REJECTION_BASIS_LABELS["transacciones"],
    }
    assert rejected_month_kpi(rows, today, "virtualpos")["basis"] == "cargos"
    assert rejected_month_kpi([], today, "tch")["count"] == 0


def test_toku_and_payku_rejected_kpi_from_transactions(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        rejected_month, "now_chile", lambda: datetime(2099, 3, 15, 12, 0, tzinfo=ZoneInfo("America/Santiago"))
    )
    for source in ("toku", "payku"):
        for i, (status, day) in enumerate((
            ("FAILED", "2099-03-02T10:00:00"), ("FAILED", "2099-03-20T10:00:00"),
            ("SUCCESS", "2099-03-03T10:00:00"), ("FAILED", "2099-02-28T10:00:00"),
        )):
            db_session.add(Payment(
                source=source, external_id=f"ui29-{source}-{i}", status=status, amount="700",
                payment_date=day, raw_payload={},
            ))
    db_session.flush()
    for source in ("toku", "payku"):
        out = staging._payment_rejected_month_kpi(db_session, source)
        assert (out["count"], out["amount"], out["basis"]) == (1, 700.0, "transacciones")


def test_reports_use_the_same_rejection_universe(db_session, monkeypatch) -> None:
    """UI-30: reportes HTML con la misma regla: sin cancelados, pendientes ni cargos futuros en la tasa."""
    from app.api.v1.routes import reports

    monkeypatch.setattr(reports, "chile_today", lambda: date(2001, 6, 15))
    rows = (
        ("pagado", "2001-06-01"), ("rechazado", "2001-06-02"), ("pendiente", "2001-06-03"),
        ("cancelado", "2001-06-04"), ("rechazado", "2001-06-20"),  # futuro respecto a hoy
    )
    for i, (status, day) in enumerate(rows):
        db_session.add(Charge(
            source="virtualpos1", external_id=f"ui30-{i}", status=status, amount="1000", charge_date=day, raw_payload={},
        ))
    db_session.flush()

    series = reports._series(db_session, "virtualpos", date(2001, 6, 1), date(2001, 6, 30))
    assert {r["status"]: r["count"] for r in series["charges"]} == {"Aceptadas": 1, "Rechazadas": 1, "Pendientes": 1}

    period = reports._auto_period_data(db_session, date(2001, 6, 1), date(2001, 6, 30))
    vp = period["channels"]["virtualpos"]
    assert (vp["rejected"], vp["total_charges"], vp["rejection_rate"]) == (1, 2, 50.0)
