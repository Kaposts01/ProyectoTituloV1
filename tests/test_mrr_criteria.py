from types import SimpleNamespace

from app.api.v1.routes import staging, tch
from app.models.tch import TchMonthlyCollection


def _sub(sub_id, amount, status="active"):
    return SimpleNamespace(
        resource_type="subscription",
        payload={"id": sub_id, "status": status, "amount": amount, "start": "2099-01-02"},
    )


def _tx(sub_id, amount, created_at, status="success"):
    return {"subscription_id": sub_id, "status": status, "amount": amount, "created_at": created_at}


def test_payku_mrr_uses_latest_success_not_first() -> None:
    rows = [_tx("s1", "1000", "2099-01-01"), _tx("s1", "1200", "2099-03-01"), _tx("s1", "1100", "2099-02-01")]
    kpis = staging._payku_extended_data([_sub("s1", "1000")], rows)["kpis"]
    assert kpis["mrr"] == 1200


def test_payku_mrr_ignores_non_success_transactions() -> None:
    rows = [_tx("s1", "1000", "2099-01-01"), _tx("s1", "9999", "2099-05-01", status="failed")]
    assert staging._payku_extended_data([_sub("s1", "1000")], rows)["kpis"]["mrr"] == 1000


def test_payku_active_subscription_without_success_does_not_add() -> None:
    rows = [_tx("s1", "500", "2099-01-01", status="failed"), _tx("s2", "700", "2099-01-01")]
    records = [_sub("s1", "500"), _sub("s2", "700")]
    assert staging._payku_extended_data(records, rows)["kpis"]["mrr"] == 700


def test_payku_mrr_ignores_inactive_subscriptions() -> None:
    rows = [_tx("s1", "1000", "2099-01-01"), _tx("s2", "2000", "2099-01-01")]
    records = [_sub("s1", "1000"), _sub("s2", "2000", status="cancel")]
    assert staging._payku_extended_data(records, rows)["kpis"]["mrr"] == 1000


def test_payku_mrr_matches_subscription_amount_in_normal_case() -> None:
    records = [_sub("s1", "1000"), _sub("s2", "2500")]
    rows = [_tx("s1", "1000", "2099-01-01"), _tx("s1", "1000", "2099-02-01"), _tx("s2", "2500", "2099-02-01")]
    with_tx = staging._payku_extended_data(records, rows)["kpis"]["mrr"]
    legacy = staging._payku_extended_data(records)["kpis"]["mrr"]
    assert with_tx == legacy == 3500


def _ctrl(periodo, acc_n, acc_m, rej_n, rej_m):
    return TchMonthlyCollection(
        period=periodo, accepted_count=acc_n, accepted_amount=acc_m,
        rejected_count=rej_n, rejected_amount=rej_m, source_file="x.xlsx",
    )


def test_tch_recaudo_mensual_uses_last_period_with_accepted() -> None:
    controles = [
        _ctrl("2026-08", 100, "800000", 5, "40000"),
        _ctrl("2026-09", 200, "1600000", 10, "90000"),
        _ctrl("2026-10", 0, "0", 3, "30000"),
    ]
    out = tch._monthly_collection_kpis(controles)
    assert out == {
        "period": "2026-09",
        "mrr": 1600000.0,
        "active_clients": 200,
        "accepted_transactions": 200,
        "arpu": 8000.0,
        "rejected_count": 10,
        "rejected_amount": 90000.0,
    }


def test_tch_recaudo_mensual_none_without_accepted() -> None:
    assert tch._monthly_collection_kpis([]) is None
    assert tch._monthly_collection_kpis([_ctrl("2026-10", 0, "0", 3, "30000")]) is None
