"""Integridad de datos de los dashboards: un solo universo de rechazo (cargos), pendientes explicitos,
rotulos honestos del churn y None cuando no hay denominador. Solo datos sinteticos."""
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.api.v1.routes import staging, tch
from app.db.session import engine
from app.models.crm import Charge, Subscription
from app.models.tch import TchRecaudacionMensual, TchTransaccion
from app.services import charge_stats, rejected_month
from app.services.charge_stats import (
    charge_rejection_stats,
    fmt_pct,
    rejection_stats_by,
)

TODAY = date(2026, 10, 15)
FAKE_NOW = datetime(2026, 10, 15, 12, 0, tzinfo=ZoneInfo("America/Santiago"))


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
def fixed_today(monkeypatch):
    monkeypatch.setattr(rejected_month, "now_chile", lambda: FAKE_NOW)
    staging.invalidate_dashboard_cache()
    yield
    staging.invalidate_dashboard_cache()


def _row(day, status, count=1, channel="VirtualPOS"):
    return {"date": day, "status": status, "count": count, "channel": channel}


# -- Punto 2: funcion pura ---------------------------------------------------------

def test_stats_excludes_cancelled_expired_voided_and_pending() -> None:
    rows = [
        _row("2026-10-01", "PAGADO", 10),
        _row("2026-10-02", "Rechazado", 5),
        _row("2026-10-03", "CANCELADO", 100),
        _row("2026-10-03", "expired", 50),
        _row("2026-10-03", "expirado", 50),
        _row("2026-10-03", "Anulada", 50),
        _row("2026-10-03", "pendiente", 50),
    ]
    out = charge_rejection_stats(rows, TODAY)
    assert (out["paid"], out["rejected"], out["evaluable"]) == (10, 5, 15)
    assert out["rate"] == 33.3


def test_stats_excludes_future_charges_by_day_and_month() -> None:
    rows = [
        _row("2026-10-15", "pagado", 1),       # hoy: cuenta
        _row("2026-10-16", "rechazado", 9),    # manana: no
        _row("2026-11", "rechazado", 9),       # mes futuro (granularidad mensual): no
        _row("2099-04-01", "rechazado", 9),
    ]
    out = charge_rejection_stats(rows, TODAY)
    assert (out["paid"], out["rejected"], out["rate"]) == (1, 0, 0.0)


def test_stats_rate_is_none_without_denominator() -> None:
    assert charge_rejection_stats([], TODAY)["rate"] is None
    only_cancelled = [_row("2026-10-01", "cancelado", 5), _row("2026-10-01", "pendiente", 5)]
    assert charge_rejection_stats(only_cancelled, TODAY)["rate"] is None


def test_stats_since_window() -> None:
    rows = [_row("2026-05-01", "rechazado", 4), _row("2026-10-01", "pagado", 1)]
    out = charge_rejection_stats(rows, TODAY, since=date(2026, 8, 1))
    assert (out["paid"], out["rejected"]) == (1, 0)


def test_stats_by_group_skips_groups_without_evaluable_charges() -> None:
    rows = [_row("2026-09-01", "rechazado", 2), _row("2026-09-02", "pagado", 2), _row("2026-08-01", "cancelado", 7)]
    out = rejection_stats_by(rows, TODAY, lambda r: r["date"][:7])
    assert set(out) == {"2026-09"}
    assert out["2026-09"]["rate"] == 50.0


def test_fmt_pct_uses_decimal_comma_and_dash_for_none() -> None:
    assert fmt_pct(98.0) == "98,0%"
    assert fmt_pct(None) == "—"


# -- Punto 2: alertas y tarjetas coherentes ----------------------------------------

def _alert_rows():
    return [
        _row("2026-09-05", "rechazado", 8, "VirtualPOS"),
        _row("2026-09-06", "pagado", 2, "VirtualPOS"),
        _row("2026-10-05", "rechazado", 6, "Toku"),
        _row("2026-10-06", "pagado", 4, "Toku"),
        _row("2026-10-07", "cancelado", 500, "Toku"),
        _row("2026-11-05", "rechazado", 30, "VirtualPOS"),   # mes futuro
        _row("2099-04-05", "rechazado", 30, "Payku"),        # mes futuro
        _row("2026-08-05", "cancelado", 3, "Payku"),         # mes sin cargos evaluables
    ]


def test_rejection_alerts_have_no_future_months_and_keep_shape() -> None:
    alerts = staging._rejection_alerts(_alert_rows(), TODAY)
    by_month = [a for a in alerts if a["tipo"] == "Alta tasa de rechazo"]
    assert {a["periodo"] for a in by_month} == {"2026-09", "2026-10"}
    for a in by_month:
        assert {"sev", "tipo", "canal", "detalle", "periodo"} <= set(a)
        assert "cargos" in a["detalle"]
    sept = next(a for a in by_month if a["periodo"] == "2026-09")
    assert sept["sev"] == "alta" and sept["canal"] == "VirtualPOS"
    assert "80,0%" in sept["detalle"] and "8 de 10" in sept["detalle"]
    assert not any("2099" in a["detalle"] or "2026-11" in a["detalle"] for a in alerts)


def test_global_alert_matches_card_figure_for_same_dataset() -> None:
    rows = [r for r in _alert_rows() if r["date"] >= "2026-09" and r["date"] < "2026-11"]
    stats = charge_rejection_stats(rows, TODAY)
    alerts = staging._rejection_alerts(rows, TODAY)
    glob = next(a for a in alerts if a["tipo"] == "Tasa de rechazo global elevada")
    assert stats["rate"] == 70.0
    assert fmt_pct(stats["rate"]) in glob["detalle"]
    assert f"{stats['rejected']} de {stats['evaluable']}" in glob["detalle"]
    assert glob["canal"] == "Consolidado" and "cargos" in glob["detalle"] and "3 meses" in glob["detalle"]


def test_no_global_alert_without_evaluable_charges() -> None:
    alerts = staging._rejection_alerts([_row("2026-10-01", "cancelado", 9), _row("2099-01-01", "rechazado", 9)], TODAY)
    assert alerts == []


def _clean(db_session):
    db_session.execute(delete(Charge).where(Charge.source.in_(("virtualpos1", "virtualpos2", "toku", "payku"))))
    db_session.execute(delete(TchRecaudacionMensual))
    db_session.execute(delete(TchTransaccion))
    db_session.flush()


def test_general_dashboard_cards_use_charge_universe(db_session, fixed_today) -> None:
    _clean(db_session)
    db_session.add_all([
        Charge(source="virtualpos1", external_id="di-1", status="pagado", charge_date="2026-10-01", raw_payload={}),
        Charge(source="virtualpos1", external_id="di-2", status="rechazado", charge_date="2026-10-02", raw_payload={}),
        Charge(source="virtualpos2", external_id="di-3", status="rechazado", charge_date="2026-09-02", raw_payload={}),
        Charge(source="toku", external_id="di-4", status="CANCELLED", charge_date="2026-10-02", raw_payload={}),
        Charge(source="payku", external_id="di-5", status="expired", charge_date="2026-10-02", raw_payload={}),
        Charge(source="payku", external_id="di-6", status="rechazado", charge_date="2099-04-02", raw_payload={}),
        Charge(source="payku", external_id="di-7", status="rechazado", charge_date="2026-11-20", raw_payload={}),
    ])
    db_session.flush()
    data = staging.general_dashboard(db=db_session)
    tx = data["transactions"]
    assert (tx["accepted"], tx["rejected"], tx["total"]) == (1, 2, 3)
    assert tx["rejection_rate_pct"] == 66.7
    glob = next(a for a in data["alerts"] if a["tipo"] == "Tasa de rechazo global elevada")
    assert "66,7%" in glob["detalle"] and "2 de 3" in glob["detalle"]
    assert all("2099" not in a["detalle"] and "2026-11" not in a["detalle"] for a in data["alerts"])


def test_general_dashboard_rate_is_none_without_charges(db_session, fixed_today) -> None:
    _clean(db_session)
    data = staging.general_dashboard(db=db_session)
    assert data["transactions"]["rejection_rate_pct"] is None
    assert data["transactions"]["rejected"] == 0
    assert not any(a["tipo"] == "Tasa de rechazo global elevada" for a in data["alerts"])


# -- Punto 1: pendientes -----------------------------------------------------------

def test_pending_payments_counts_only_explicit_pending_states(db_session, fixed_today) -> None:
    _clean(db_session)
    statuses = ["pagado", "PAID", "rechazado", "cancelado", "Cancelled", "expirado", "EXPIRED",
                "anulado", "voided", "pendiente", "PENDIENTE", "Pending", " procesando ", "in_progress"]
    db_session.add_all([
        Charge(source=src, external_id=f"pp-{i}", status=st, charge_date="2026-10-01", raw_payload={})
        for i, (src, st) in enumerate(zip(["virtualpos1", "toku", "payku"] * 5, statuses, strict=False))
    ])
    db_session.flush()
    data = staging.general_dashboard(db=db_session)
    assert data["pending_payments"] == 4  # pendiente, PENDIENTE, Pending, ' procesando '; in_progress no
    assert "pendiente" in data["pending_payments_label"].lower()


# -- Punto 3/4: churn rotulado y None sin denominador ------------------------------

def _rec(rt, payload):
    return SimpleNamespace(resource_type=rt, payload=payload)


def test_churn_window_labels_per_channel() -> None:
    sub = _rec("subscription", {"status": "ACTIVA", "amount": 100, "suscription_date": "2026-01-05"})
    vp = staging._vp_extended_data([sub])
    assert vp["kpis"]["churn_window_label"] == vp["churn_window_label"] == "promedio de 3 meses"
    tk = staging._toku_extended_data([_rec("subscription", {"status": "active", "amount": 1, "anchor": "2026-01-01", "customer": "c"})])
    assert tk["kpis"]["churn_window_label"] == tk["churn_window_label"] == "acumulado histórico"
    pk = staging._payku_extended_data([_rec("subscription", {"status": "active", "amount": 1, "start": "2026-01-01"})])
    assert pk["kpis"]["churn_window_label"] == pk["churn_window_label"] == "acumulado histórico"


@pytest.mark.parametrize("builder", [staging._vp_extended_data, staging._toku_extended_data, staging._payku_extended_data])
def test_empty_channel_ratios_are_none_and_counts_zero(builder) -> None:
    kpis = builder([])["kpis"]
    assert kpis["churn_rate"] is None and kpis["arpu"] is None and kpis["ltv"] is None
    assert kpis["mrr"] == 0 and kpis["active_subscribers"] == 0 and kpis["active_clients"] == 0


def test_payku_arpu_subtext_count_has_no_floor_of_one() -> None:
    # Causa del '1 cliente con subs activas' con 0 activas: piso `or 1` en active_clients.
    subs = [_rec("subscription", {"id": "s1", "status": "cancel", "start": "2026-01-01", "end": "2026-02-01", "amount": 5})]
    kpis = staging._payku_extended_data(subs, [])["kpis"]
    assert kpis["active_clients"] == 0 and kpis["arpu"] is None
    assert kpis["churn_rate"] == 100.0


def test_vp_churn_is_none_without_base_and_zero_with_base_and_no_bajas() -> None:
    assert staging._vp_extended_data([])["kpis"]["churn_rate"] is None
    kpis = staging._vp_extended_data([_rec("subscription", {"status": "ACTIVA", "amount": 100, "suscription_date": "2026-01-05"})])["kpis"]
    assert kpis["churn_rate"] == 0.0
    assert kpis["ltv"] is None  # churn 0 -> LTV indefinido


def test_churn_alert_text_says_what_it_measures() -> None:
    kpis = {"churn_rate": 15.0, "churn_window_label": "promedio de 3 meses"}
    alerts = staging._channel_alerts([], [], [], kpis, "VirtualPOS")
    detalle = alerts[0]["detalle"]
    assert alerts[0]["tipo"] == "Churn rate elevado" and alerts[0]["canal"] == "VirtualPOS"
    assert "promedio de 3 meses" in detalle and "15,0%" in detalle and "histórica" not in detalle


def test_channel_alert_ignores_none_churn() -> None:
    assert staging._channel_alerts([], [], [], {"churn_rate": None}, "Toku") == []


def test_general_dashboard_churn_none_and_label(db_session, fixed_today) -> None:
    data = staging.general_dashboard(db=db_session)
    assert "churn_window_label" in data and "mes" in data["churn_window_label"]
    assert data["churn_rate_pct"] is None or isinstance(data["churn_rate_pct"], float)


def test_general_churn_is_none_when_no_active_subscriptions(db_session, fixed_today) -> None:
    db_session.execute(delete(Subscription).where(Subscription.source.in_(("virtualpos1", "virtualpos2", "toku", "payku"))))
    db_session.execute(delete(TchRecaudacionMensual))
    db_session.flush()
    data = staging.general_dashboard(db=db_session)
    if data["subscriptions"]["active"] == 0:
        assert data["churn_rate_pct"] is None


def test_tch_summary_nulls_and_label(db_session, monkeypatch) -> None:
    from app.models.tch import TchSuscripcion

    monkeypatch.setattr(tch, "_get_db", lambda: db_session)
    db_session.execute(delete(TchRecaudacionMensual))
    db_session.execute(delete(TchTransaccion))
    db_session.execute(delete(TchSuscripcion))
    db_session.flush()
    out = tch.tch_summary()
    assert out["kpis"]["churn_rate"] is None and out["kpis"]["arpu"] is None and out["kpis"]["ltv"] is None
    assert out["transacciones"]["tasa_rechazo_pct"] is None
    assert out["kpis"]["churn_window_label"] == out["churn_window_label"] == "promedio mensual histórico"
    assert out["kpis"]["mrr"] == 0


def test_charge_stats_module_reuses_billing_plan_normalisation() -> None:
    from app.services import billing_plan

    assert billing_plan.CANCELLED_STATES <= charge_stats.EXCLUDED_STATES
    assert billing_plan.PENDING_STATES <= charge_stats.PENDING_DASHBOARD_STATES
