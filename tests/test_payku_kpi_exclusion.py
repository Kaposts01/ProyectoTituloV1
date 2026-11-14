"""d207: PAYKU_KPI_EXCLUDED_IDS saca una suscripcion de prueba de los indicadores.

Cada prueba siembra datos sinteticos (sin PII, sin Payku) con una suscripcion EXCLUIDA y otra NORMAL, y comprueba que
el indicador cuenta solo la normal. Base de test con transaccion revertida.
"""

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select, true
from sqlalchemy.orm import Session

from app.api.v1.routes import staging
from app.core.config import settings
from app.db.session import engine
from app.models.core import CoreCharge, CorePayment, CoreSubscription
from app.models.crm import Payment, Subscription
from app.models.payku_channel import PaykuCycle, PaykuSubscription, PaykuTransaction
from app.services import (
    channel_consolidation,
    core_payku_etl,
    dashboard_general,
    recovery_payku,
)
from app.services.export_queries import ExportFilters, _charges_payku_cycles
from app.services.payku_kpi_exclusion import (
    excluded_subscription_ids,
    is_excluded,
    not_excluded,
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


@pytest.fixture
def ids(monkeypatch):
    tag = uuid.uuid4().hex[:8]
    excluded, normal = f"su-excl-{tag}", f"su-norm-{tag}"
    monkeypatch.setattr(settings, "payku_kpi_excluded_ids", f" {excluded} ,, ")
    return excluded, normal


def _paid(tx: str) -> list[dict]:
    return [
        {"payment_cycle_day": "2097-03-09", "payment_day": "2097-03-09", "status": "success", "amount_paid": 1,
         "try_number": 1, "paid_number": 1, "transactions": [{"transaction": tx}]},
        {"payment_cycle_day": "2097-04-09", "payment_day": "2097-04-10", "status": "rejected", "amount_paid": 0,
         "try_number": 1, "paid_number": 2, "transactions": []},
    ]


def _seed_channel(db: Session, sub_ids: tuple[str, ...], status: str = "active") -> None:
    for sub in sub_ids:
        db.add(PaykuSubscription(external_id=sub, status=status, amount="1",
                                 raw_payload={"id": sub, "start": "2097-03-01", "paid": _paid(f"tx-{sub}")}))
        db.add(PaykuTransaction(external_id=f"tx-{sub}", subscription_id=sub, status="success", amount="1",
                                created_at_api="2097-03-09 10:00:00"))
        db.add(PaykuTransaction(external_id=f"rej-{sub}", subscription_id=sub, status="rejected", amount="0",
                                created_at_api="2097-04-10 10:00:00"))
    db.flush()


def _run_core_steps(db: Session) -> None:
    core_payku_etl._refresh_normalized_statuses(db)
    core_payku_etl._purge_excluded_subscriptions(db)
    core_payku_etl._materialize_subscriptions(db)
    core_payku_etl._materialize_cycles(db)
    core_payku_etl._materialize_charges(db)
    core_payku_etl._materialize_payments(db)
    core_payku_etl._link_payments_to_charges(db)


def _core_counts(db: Session, sub: str) -> tuple[int, int, int]:
    subs = db.scalar(select(func.count()).select_from(CoreSubscription)
                     .where(CoreSubscription.source == "payku", CoreSubscription.external_id == sub))
    charges = db.scalar(select(func.count()).select_from(CoreCharge)
                        .where(CoreCharge.source == "payku", CoreCharge.external_id.like(f"{sub}:%")))
    payments = db.scalar(select(func.count()).select_from(CorePayment)
                         .where(CorePayment.source == "payku", CorePayment.external_id.in_([f"tx-{sub}", f"rej-{sub}"])))
    return subs, charges, payments


# -- Configuracion y helper -----------------------------------------------------------------------------------------

def test_setting_parses_list_and_defaults_to_empty(monkeypatch) -> None:
    monkeypatch.setattr(settings, "payku_kpi_excluded_ids", "")
    assert excluded_subscription_ids() == frozenset()
    assert not_excluded(PaykuTransaction.subscription_id).compare(true())
    monkeypatch.setattr(settings, "payku_kpi_excluded_ids", "su-a, su-b ,")
    assert excluded_subscription_ids() == frozenset({"su-a", "su-b"})
    assert is_excluded("su-a") and not is_excluded("su-c") and not is_excluded(None)


def test_env_example_lists_the_variable_without_value() -> None:
    from pathlib import Path

    lines = (Path(__file__).resolve().parent.parent / ".env.example").read_text(encoding="utf-8").splitlines()
    assert "PAYKU_KPI_EXCLUDED_IDS=" in lines


# -- ETL Core -------------------------------------------------------------------------------------------------------

def test_core_etl_skips_excluded_subscription_and_its_charges_and_payments(db_session: Session, ids) -> None:
    excluded, normal = ids
    _seed_channel(db_session, (excluded, normal))
    _run_core_steps(db_session)
    assert _core_counts(db_session, normal) == (1, 2, 2)
    assert _core_counts(db_session, excluded) == (0, 0, 0)
    # La tabla cruda se conserva (trazabilidad)
    assert db_session.scalar(select(func.count()).select_from(PaykuTransaction)
                             .where(PaykuTransaction.subscription_id == excluded)) == 2


def test_core_etl_removes_already_materialized_and_restores_when_unlisted(db_session: Session, ids,
                                                                          monkeypatch) -> None:
    excluded, normal = ids
    _seed_channel(db_session, (excluded, normal))
    monkeypatch.setattr(settings, "payku_kpi_excluded_ids", "")
    _run_core_steps(db_session)
    assert _core_counts(db_session, excluded) == (1, 2, 2)

    monkeypatch.setattr(settings, "payku_kpi_excluded_ids", excluded)
    assert core_payku_etl._purge_excluded_subscriptions(db_session) == 1
    _run_core_steps(db_session)
    assert _core_counts(db_session, excluded) == (0, 0, 0)
    assert _core_counts(db_session, normal) == (1, 2, 2)

    monkeypatch.setattr(settings, "payku_kpi_excluded_ids", "")
    _run_core_steps(db_session)
    assert _core_counts(db_session, excluded) == (1, 2, 2)


# -- Consolidacion a las tablas centrales (tableros de canal y general) ---------------------------------------------

def test_consolidation_skips_excluded_subscription_and_transactions(db_session: Session, ids) -> None:
    excluded, normal = ids
    _seed_channel(db_session, (excluded, normal))
    for sub in (excluded, normal):
        channel_consolidation._consolidate_payku_subscriptions(db_session, scope=("payku", sub))
        channel_consolidation._consolidate_payku_transactions(db_session, scope=("payku", sub))
    db_session.flush()

    def count(model, column, value) -> int:
        return db_session.scalar(select(func.count()).select_from(model)
                                 .where(model.source == "payku", column == value))

    assert count(Subscription, Subscription.external_id, normal) == 1
    assert count(Payment, Payment.charge_external_id, normal) == 2
    assert count(Subscription, Subscription.external_id, excluded) == 0
    assert count(Payment, Payment.charge_external_id, excluded) == 0


# -- Lecturas directas de p_transactions / p_cycles -----------------------------------------------------------------

def _central_active(db: Session, sub_ids: tuple[str, ...]) -> None:
    """Simula filas centrales ya existentes (id cargado tarde): las lecturas directas igual deben excluir."""
    for i, sub in enumerate(sub_ids):
        db.add(Subscription(source="payku", external_id=sub, status="active", amount="1",
                            client_social_id=f"9999999{i}-{i}", suscription_date="2097-03-01", raw_payload={}))
    db.flush()


def test_dashboard_general_mrr_ignores_excluded(db_session: Session, ids) -> None:
    excluded, normal = ids
    today = date(2097, 4, 15)
    before = dashboard_general._mrr_by_channel(db_session, ["payku"], today).get("payku", (0.0, 0))
    _seed_channel(db_session, (excluded, normal))
    _central_active(db_session, (excluded, normal))
    after = dashboard_general._mrr_by_channel(db_session, ["payku"], today)["payku"]
    assert after[0] == before[0] + 1  # solo el cobro success de la normal
    assert after[1] == before[1] + 1


def test_payku_summary_mrr_ignores_excluded(db_session: Session, ids) -> None:
    excluded, normal = ids
    before = staging._payku_centralized_dashboard(db_session)["kpis"]["mrr"]
    _seed_channel(db_session, (excluded, normal))
    _central_active(db_session, (excluded, normal))
    after = staging._payku_centralized_dashboard(db_session)["kpis"]["mrr"]
    assert after == before + 1


def test_recovery_views_ignore_excluded(db_session: Session, ids) -> None:
    excluded, normal = ids
    window = (date(2097, 1, 1), date(2097, 12, 31))
    for sub in (excluded, normal):
        db_session.add(PaykuSubscription(external_id=sub, status="suspended", status_normalized="suspended"))
        core = CoreSubscription(source="payku", external_id=sub, status="suspended", amount=1, currency="CLP",
                                started_at=datetime(2097, 1, 1, tzinfo=UTC), ended_at=datetime(2097, 4, 1, tzinfo=UTC))
        db_session.add(core)
        db_session.flush()
        db_session.add(PaykuTransaction(external_id=f"rej-{sub}", subscription_id=sub, status="rejected",
                                        status_normalized="rejected"))
        db_session.add(CorePayment(source="payku", external_id=f"rej-{sub}", subscription_id=core.id,
                                   source_status="rejected", occurred_at=datetime(2097, 4, 10, tzinfo=UTC), amount=0,
                                   currency="CLP"))
    db_session.flush()

    suspended = {r["subscription_id"] for r in recovery_payku.suspended(db_session, *window, 0, 500)["items"]}
    assert normal in suspended and excluded not in suspended
    rejected = {r["charge_id"] for r in recovery_payku.rejected(db_session, *window, 0, 500)["items"]}
    assert f"rej-{normal}" in rejected and f"rej-{excluded}" not in rejected


def test_general_charges_export_ignores_excluded_cycles(db_session: Session, ids) -> None:
    excluded, normal = ids
    for sub in (excluded, normal):
        db_session.add(PaykuCycle(external_id=f"{sub}:2097-03-09", subscription_id=sub, cycle_day="2097-03-09",
                                  status="success", status_normalized="paid", amount_paid="1"))
    db_session.flush()
    rows = db_session.execute(_charges_payku_cycles(("payku",), ExportFilters(), False)).all()
    charge_ids = {row.charge_id for row in rows}
    assert f"{normal}:2097-03-09" in charge_ids and f"{excluded}:2097-03-09" not in charge_ids
