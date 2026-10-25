from types import SimpleNamespace

from app.api.v1.routes import staging, tch
from app.services.rejected_month import now_chile


def _now():
    t = now_chile()
    return t.year, t.month


def _rec(rt, payload):
    return SimpleNamespace(resource_type=rt, payload=payload)


def test_rejected_current_month_filters_month_and_status() -> None:
    y, m = _now()
    rows = [
        {"year": y, "month": m, "status": "FAILED", "count": 2, "amount": 100.0},
        {"year": y, "month": m, "status": "SUCCESS", "count": 9, "amount": 900.0},
        {"year": y - 1, "month": m, "status": "FAILED", "count": 5, "amount": 500.0},
    ]
    out = staging._rejected_current_month(rows, staging._REJECTED_TX_STATUSES)
    assert out == {"count": 2, "amount": 100.0}
    assert staging._rejected_current_month([]) == {"count": 0, "amount": 0.0}


def test_payku_kpis_include_active_subscribers_and_rejected() -> None:
    y, m = _now()
    ts = f"{y}-{m:02d}-02"
    records = [
        _rec("subscription", {"status": "active", "amount": 1000, "start": ts}),
        _rec("transaction", {"status": "failed", "amount": 1000, "created_at": ts}),
        _rec("transaction", {"status": "success", "amount": 1000, "created_at": ts}),
    ]
    kpis = staging._payku_extended_data(records)["kpis"]
    assert kpis["active_subscribers"] == 1
    assert kpis["rejected_charges"] == {"count": 1, "amount": 1000.0}
    assert kpis["mrr"] == 1000


def test_toku_kpis_include_rejected_and_active_subscribers() -> None:
    y, m = _now()
    ts = f"{y}-{m:02d}-02"
    records = [
        _rec("subscription", {"status": "active", "amount": 500, "anchor": ts, "customer": "c1"}),
        _rec("transaction", {"status": "rejected", "amount": 500, "transaction_date": ts}),
    ]
    kpis = staging._toku_extended_data(records)["kpis"]
    assert kpis["active_subscribers"] == 1
    assert kpis["rejected_charges"] == {"count": 1, "amount": 500.0}


def test_vp_kpis_include_rejected_charges() -> None:
    y, m = _now()
    ts = f"{y}-{m:02d}-02"
    records = [
        _rec("subscription", {"status": "ACTIVA", "amount": 800, "suscription_date": ts}),
        _rec("charge", {"charge_date": ts, "amount": 800, "status": "RECHAZADO"}),
    ]
    kpis = staging._vp_extended_data(records)["kpis"]
    assert kpis["active_subscribers"] == 1
    assert kpis["rejected_charges"] == {"count": 1, "amount": 800.0}


def test_tch_rejected_current_month() -> None:
    y, m = _now()
    rows = [
        {"year": y, "month": m, "status": "ACEPTADA", "count": 10, "amount": 1000},
        {"year": y, "month": m, "status": "RECHAZADA", "count": 3, "amount": 300},
        {"year": y, "month": 1 if m != 1 else 2, "status": "RECHAZADA", "count": 7, "amount": 700},
    ]
    assert tch._rejected_current_month(rows) == {"count": 3, "amount": 300.0}
