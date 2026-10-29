from datetime import date

from app.services.dashboard_performance import build_monthly_performance


def payment(day, amount, source="payku", status="success", currency="CLP"):
    return {
        "date": day,
        "amount": amount,
        "source": source,
        "status": status,
        "currency": currency,
    }


def test_cash_is_observed_clp_only_and_excludes_future():
    result = build_monthly_performance(
        [
            payment("2026-01-10", "0.1"),
            payment("2026-01-11", "0.2"),
            payment("2026-01-12", "5", currency="UF"),
            payment("2026-01-12", "6", currency=None),
            payment("2026-03-01", "100"),
            payment("bad", "100"),
            payment("2026-01-01", "NaN"),
            payment("2026-01-13", "1.7", status="rejected"),
        ],
        [],
        [],
        date(2026, 2, 20),
    )
    january, february = result["monthly"]
    assert january["channels"]["Toku"] is None
    assert january["channels"]["Payku"] == 0.3
    assert january["revenue"] == 0.3
    assert january["rejected_amount"] == 1.7
    assert january["collection_rate"] == 15
    assert february["revenue"] is None
    assert february["active"] is None
    assert february["partial_month"] is True
    assert result["default_period"] == "2026-01"
    assert result["excluded"]["other_or_missing_currency"] == 2


def test_tch_control_replaces_only_same_month_without_double_count():
    result = build_monthly_performance(
        [
            payment("2026-01-02", "100", source="tch"),
            payment("2026-02-02", "30", source="tch"),
            payment("2026-01-02", "10"),
        ],
        [],
        [
            {"period": "2026-01", "accepted": "20", "rejected": "5"},
            {"period": "2027-01", "accepted": "999", "rejected": "0"},
        ],
        date(2026, 2, 28),
    )
    january, february = result["monthly"]
    assert january["revenue"] == 30
    assert january["channels"]["TCH"] == 20
    assert february["revenue"] == 30
    assert february["partial_month"] is False


def test_stock_movements_and_churn_have_same_month_boundaries():
    result = build_monthly_performance(
        [],
        [
            {"start": "2025-12-01", "end": "2026-01-01", "status": "cancel"},
            {"start": "2026-01-01", "end": None, "status": "active"},
            {"start": "2026-01-31", "end": "2026-01-31", "status": "cancel"},
            {"start": "2026-02-01", "end": None, "status": "active"},
            {"start": "2025-11-01", "end": None, "status": "cancel"},
        ],
        [],
        date(2026, 2, 20),
    )
    january = next(m for m in result["monthly"] if m["period"] == "2026-01")
    assert january["opening"] == 1
    assert january["activations"] == 2
    assert january["cancellations"] == 2
    assert january["active"] == january["opening"] + january["net_growth"] == 1
    assert (
        january["churn"] == 100
    )  # only cancellations belonging to the opening population
    assert result["excluded"]["subscriptions_without_valid_interval"] == 1


def test_empty_data_does_not_claim_zero_or_divide_by_zero():
    result = build_monthly_performance([], [], [], date(2026, 5, 1))
    row = result["monthly"][0]
    assert row["revenue"] is None
    assert row["collection_rate"] is None
    assert row["churn"] is None
    assert row["opening"] is None


def test_timestamp_uses_chile_month_and_accepted_zero_is_observed():
    result = build_monthly_performance(
        [payment("2026-02-01T01:00:00Z", "0")], [], [], date(2026, 2, 28)
    )
    assert result["monthly"][0]["period"] == "2026-01"
    assert result["monthly"][0]["revenue"] == 0
    assert result["monthly"][1]["revenue"] is None


def test_invalid_control_falls_back_to_detail():
    result = build_monthly_performance(
        [payment("2026-01-02", "100", source="tch")],
        [],
        [
            {"period": "2026-01", "accepted": "bad", "rejected": "0"},
        ],
        date(2026, 1, 31),
    )
    assert result["monthly"][0]["revenue"] == 100
    assert result["excluded"]["invalid_or_future_controls"] == 1


def test_channel_and_centralized_tch_copies_are_not_counted_twice():
    import os

    import pytest
    from sqlalchemy.orm import Session

    from app.db.session import engine
    from app.models.crm import Payment, Subscription
    from app.models.source_record import (
        SourceRecord,  # noqa: F401 - register FK metadata
    )
    from app.models.tch import TchSuscripcion, TchTransaccion
    from app.services.dashboard_performance import monthly_performance

    if engine.url.database == "crm" and os.environ.get("CI") != "true":
        pytest.skip("Requires the explicitly isolated validation database.")
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            try:
                db.add_all(
                    [
                        Payment(
                            source="tch",
                            external_id="performance-copy",
                            status="aceptada",
                            amount="100",
                            currency="CLP",
                            payment_date="2000-01-15",
                            raw_payload={},
                        ),
                        Subscription(
                            source="tch",
                            external_id="performance-copy",
                            status="VIGENTE",
                            suscription_date="2000-01-01",
                            raw_payload={},
                        ),
                        TchSuscripcion(
                            numero_ficha=987654321,
                            estado="VIGENTE",
                            fecha_activacion="2000-01-01",
                        ),
                        TchTransaccion(
                            numero_ficha=987654321,
                            estado="ACEPTADA",
                            periodo="2000-01",
                            monto="100",
                        ),
                    ]
                )
                db.flush()
                result = monthly_performance(db, date(2000, 1, 31))
                row = result["monthly"][-1]
                assert row["revenue"] == 100
                assert row["active"] == 1
            finally:
                db.rollback()
                transaction.rollback()


def test_empty_controls_do_not_turn_missing_months_into_zero_revenue():
    result = build_monthly_performance(
        [],
        [],
        [
            {"period": "2026-01", "accepted": "50", "rejected": "0", "count": 1},
            {"period": "2026-02", "accepted": "0", "rejected": "0", "count": 0},
        ],
        date(2026, 2, 20),
    )
    assert result["default_period"] == "2026-01"
    assert result["monthly"][-1]["revenue"] is None
