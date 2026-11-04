"""TK-13: MRR, ARPU y suscriptores activos de Toku con «suscripcion activa efectiva» (DEC-18).

Criterio explicito (ver `app/services/toku_active.py`):
* con senal del reporte (`core_subscription_signals`) y TOKU_REPORT_SIGNALS_ENABLED, manda `is_effectively_active`;
* PAUSED y estado vacio NUNCA cuentan (d118, opcion c), haya o no senal;
* sin senal: no eliminada y con medio `chargeable` de la API.

Datos SINTETICOS (sin datos personales). Cifras del mismo mundo antes y despues (documentadas en docs/data/toku.md):

| sub | estado API | medio API | senal reporte | TK-13 v1 | d118 (vigente) |
|-----|-----------|-----------|---------------|----------|----------------|
| a   | ACTIVE    | chargeable| -             | si       | si             |
| b   | PAUSED    | chargeable| -             | si       | no             |
| c   | (vacio)   | chargeable| -             | si       | no             |
| d   | ACTIVE    | inactive  | -             | no       | no             |
| e   | CANCELLED | chargeable| -             | no       | no             |
| f   | ACTIVE    | chargeable| no efectiva   | no       | no             |
| g   | ACTIVE    | inactive  | efectiva      | si       | si             |

TK-13 v1: MRR 27.000 (a+b+c+g), 4 activas, ARPU 6.750. d118: MRR 13.000 (a+g), 2 activas, ARPU 6.500.
"""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from app.api.v1.routes import staging
from app.core.config import settings
from app.db.session import engine
from app.models.core import CoreSubscription
from app.models.crm import PaymentMethod, Subscription
from app.models.toku_report import CoreSubscriptionSignal
from app.services import dashboard_general
from app.services.toku_active import TOKU_DELETED_STATES, is_effectively_active

AMOUNTS = {"a": 10000, "b": 8000, "c": 6000, "d": 5000, "e": 4000, "f": 7000, "g": 3000}
STATUS = {"a": "ACTIVE", "b": "PAUSED", "c": None, "d": "ACTIVE", "e": "CANCELLED", "f": "ACTIVE", "g": "ACTIVE"}
API_CHARGEABLE = {"a", "b", "c", "e", "f"}
SIGNALS = {"f": False, "g": True}
EXPECTED = {"a", "g"}


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


@pytest.fixture(autouse=True)
def signals_enabled(monkeypatch):
    """Las senales solo se leen con TOKU_REPORT_SIGNALS_ENABLED (la misma bandera que las calcula)."""
    monkeypatch.setattr(settings, "toku_report_signals_enabled", True)


def ext(key: str) -> str:
    return f"sub_tk13_{key}"


def seed(db: Session) -> None:
    for key, amount in AMOUNTS.items():
        db.add(Subscription(
            source="toku", external_id=ext(key), client_external_id=f"cus_tk13_{key}", status=STATUS[key],
            amount=str(amount), suscription_date="2099-05-01", raw_payload={},
        ))
        db.add(PaymentMethod(
            source="toku", external_id=f"pm_tk13_{key}",
            status="chargeable" if key in API_CHARGEABLE else "inactive",
            raw_payload={"subscription_ids": [ext(key)]},
        ))
    now = datetime(2099, 5, 2, tzinfo=UTC)
    for key, effective in SIGNALS.items():
        core = CoreSubscription(source="toku", external_id=ext(key), status=STATUS[key])
        db.add(core)
        db.flush()
        db.add(CoreSubscriptionSignal(
            subscription_id=core.id, source="toku", external_id=ext(key),
            lifecycle_status="active" if effective else "deleted",
            payment_method_status="chargeable", is_chargeable=True, is_effectively_active=effective,
            computed_at=now,
        ))
    db.flush()


def test_rule_is_explicit() -> None:
    signals = {"s-yes": True, "s-no": False}
    # 1. La senal del reporte manda sobre la API (DEC-23), en ambos sentidos.
    assert is_effectively_active("s-yes", "CANCELLED", set(), signals) is True
    assert is_effectively_active("s-no", "ACTIVE", {"s-no"}, signals) is False
    # 2. Sin senal: no eliminada y chargeable.
    assert is_effectively_active("x", "ACTIVE", {"x"}, {}) is True
    # 0. d118 (opcion c): PAUSED y estado vacio no cuentan, ni siquiera con senal efectiva del reporte.
    assert is_effectively_active("x", "PAUSED", {"x"}, {}) is False
    assert is_effectively_active("x", "paused", {"x"}, {}) is False
    assert is_effectively_active("x", None, {"x"}, {}) is False
    assert is_effectively_active("x", "  ", {"x"}, {}) is False
    assert is_effectively_active("s-yes", "PAUSED", set(), signals) is False
    assert is_effectively_active("s-yes", None, set(), signals) is False
    assert is_effectively_active("x", "ACTIVE", set(), {}) is False  # sin medio cobrable
    for state in TOKU_DELETED_STATES:
        assert is_effectively_active("x", state.upper(), {"x"}, {}) is False


def test_toku_channel_dashboard_uses_effective_active(db_session) -> None:
    before = staging._toku_centralized_dashboard(db_session)["kpis"]
    seed(db_session)
    after = staging._toku_centralized_dashboard(db_session)["kpis"]

    assert after["active_subscribers"] - before["active_subscribers"] == len(EXPECTED)
    assert after["mrr"] - before["mrr"] == sum(AMOUNTS[k] for k in EXPECTED) == 13000
    if before["active_subscribers"] == 0:
        assert after["active_clients"] == 2
        assert after["arpu"] == 6500


def test_general_staging_dashboard_toku_counts(db_session) -> None:
    staging.invalidate_dashboard_cache()
    before = staging._compute_general_dashboard(db_session)
    seed(db_session)
    after = staging._compute_general_dashboard(db_session)

    toku_before = next(c for c in before["channels"] if c["source"] == "Toku")
    toku_after = next(c for c in after["channels"] if c["source"] == "Toku")
    assert toku_after["active_subscriptions"] - toku_before["active_subscriptions"] == 2
    assert after["subscriptions"]["amount"] - before["subscriptions"]["amount"] == 13000


def test_flag_off_ignores_report_signals(db_session, monkeypatch) -> None:
    """Con la bandera apagada manda la API: f (chargeable en la API) vuelve a contar y g (sin medio cobrable) no.

    b (PAUSED) y c (vacio) siguen fuera (d118)."""
    monkeypatch.setattr(settings, "toku_report_signals_enabled", False)
    before = staging._toku_centralized_dashboard(db_session)["kpis"]
    seed(db_session)
    after = staging._toku_centralized_dashboard(db_session)["kpis"]
    assert after["mrr"] - before["mrr"] == AMOUNTS["a"] + AMOUNTS["f"]


def test_dashboard_general_mrr_by_channel(db_session) -> None:
    today = date(2099, 5, 15)
    before = dashboard_general._mrr_by_channel(db_session, ["toku"], today).get("toku", (0, 0))
    seed(db_session)
    mrr, clients = dashboard_general._mrr_by_channel(db_session, ["toku"], today)["toku"]
    assert mrr - before[0] == 13000
    assert clients - before[1] == 2
