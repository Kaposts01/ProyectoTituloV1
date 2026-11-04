"""VP-PAR-10: los KPIs, graficos y alertas excluyen cobros FUTUROS (fecha posterior a hoy, hora de Chile).

VirtualPOS programa los cobros de los proximos meses y, al cancelar una suscripcion, los deja en estado
`cancelado` con fecha futura (~150 mil filas). Esos cobros no ocurrieron: no son cancelados reales, ni
pendientes por cobrar, ni parte de una racha de rechazos, ni intentos de cobro.
"""

import uuid
from datetime import date, datetime

import pytest
from sqlalchemy.orm import Session

from app.api.v1.routes import recovery, staging
from app.db.session import engine
from app.models.crm import Charge, Subscription
from app.services import charge_stats, rejected_month

TODAY = date(2026, 10, 29)


@pytest.fixture(autouse=True)
def chile_today(monkeypatch):
    monkeypatch.setattr(rejected_month, "now_chile", lambda: datetime(2026, 10, 29, 12, 0, tzinfo=rejected_month.CHILE_TZ))


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    staging._dashboard_cache.clear()
    try:
        yield session
    finally:
        staging._dashboard_cache.clear()
        session.close()
        transaction.rollback()
        connection.close()


def _charge(db: Session, status: str, charge_date: str, sub: str = "fc-sub", source: str = "virtualpos1") -> Charge:
    charge = Charge(source=source, external_id=f"fc-{uuid.uuid4().hex[:12]}", subscription_external_id=sub,
                    status=status, charge_date=charge_date, amount="1000")
    db.add(charge)
    return charge


# --- charge_stats ---------------------------------------------------------------------------------


def test_is_future_charge_uses_the_chile_date() -> None:
    assert charge_stats.is_future_charge("2026-10-30", TODAY) is True
    assert charge_stats.is_future_charge("2026-10-29T23:00:00", TODAY) is False  # hoy no es futuro
    assert charge_stats.is_future_charge("2026-11", TODAY) is True
    assert charge_stats.is_future_charge("2026-10", TODAY) is False  # 'YYYY-MM' = dia 1
    assert charge_stats.is_future_charge(None, TODAY) is False
    assert charge_stats.is_future_charge("basura", TODAY) is False


def test_counts_in_universe_excludes_future_and_cancelled_expired_voided() -> None:
    ok = charge_stats.counts_in_universe
    assert ok("rechazado", "2026-10-01", TODAY) and ok("pagado", "2026-10-29", TODAY) and ok("pendiente", "2026-10-29", TODAY)
    assert not ok("cancelado", "2026-10-01", TODAY)
    assert not ok("expirado", "2026-10-01", TODAY) and not ok("anulado", "2026-10-01", TODAY)
    assert not ok("pendiente", "2026-11-05", TODAY) and not ok("cancelado", "2027-03-05", TODAY)
    assert not ok("pagado", None, TODAY)


def test_chile_today_follows_the_single_clock() -> None:
    assert charge_stats.chile_today() == TODAY


# --- alerta: racha de rechazos -------------------------------------------------------------------------


def _streak_alert(db: Session):
    return [a for a in staging._vp_centralized_alerts(db, ["virtualpos1"], (), {"fc-sub"}, set()) if a.get("id") == "racha-rechazos"]


def test_rejection_streak_is_not_hidden_by_future_cancelled_charges(db_session) -> None:
    db_session.add(Subscription(source="virtualpos1", external_id="fc-sub", status="ACTIVA"))
    _charge(db_session, "rechazado", "2026-10-05")
    _charge(db_session, "rechazado", "2026-09-05")
    for future in ("2026-11-05", "2026-12-05", "2027-01-05", "2027-02-05"):  # cobros futuros cancelados al dar de baja
        _charge(db_session, "cancelado", future)
    _charge(db_session, "pendiente", "2026-11-20")
    db_session.flush()
    alerts = _streak_alert(db_session)
    assert alerts and alerts[0]["detalle"].startswith("1 suscripción")


def test_a_cancelled_past_charge_does_not_break_a_streak(db_session) -> None:
    db_session.add(Subscription(source="virtualpos1", external_id="fc-sub", status="ACTIVA"))
    _charge(db_session, "rechazado", "2026-10-05")
    _charge(db_session, "cancelado", "2026-09-20")
    _charge(db_session, "rechazado", "2026-09-05")
    db_session.flush()
    assert _streak_alert(db_session)


# --- dashboard: pendientes y deudas mensuales -----------------------------------------------------------


def _debts(data: dict) -> dict[tuple[int, int, str], int]:
    return {(d["year"], d["month"], d["charge_status"]): d["count"] for d in data["debts_monthly"] if d["status"] == "VirtualPOS"}


def test_pending_payments_ignore_future_scheduled_charges(db_session) -> None:
    before = staging._compute_general_dashboard(db_session)["pending_payments"]
    _charge(db_session, "pendiente", "2026-10-28")   # pendiente de verdad
    _charge(db_session, "procesando", "2026-10-29")  # hoy
    _charge(db_session, "pendiente", "2026-11-05")   # programado: no es un pendiente por cobrar
    _charge(db_session, "pendiente", "2027-02-05")
    db_session.flush()
    assert staging._compute_general_dashboard(db_session)["pending_payments"] == before + 2


def test_monthly_debts_do_not_count_future_months_or_cancelled_charges(db_session) -> None:
    before = _debts(staging._compute_general_dashboard(db_session))
    _charge(db_session, "pagado", "2026-09-05")
    _charge(db_session, "rechazado", "2026-09-06")
    _charge(db_session, "cancelado", "2026-09-07")   # cancelado real del pasado: no es deuda ni rechazo
    _charge(db_session, "cancelado", "2026-12-05")   # futuro
    _charge(db_session, "pendiente", "2027-01-05")   # futuro
    _charge(db_session, "rechazado", "2026-10-30")   # un dia despues de hoy
    db_session.flush()
    after = _debts(staging._compute_general_dashboard(db_session))
    assert after.get((2026, 9, "pagada"), 0) - before.get((2026, 9, "pagada"), 0) == 1
    assert after.get((2026, 9, "rechazada"), 0) - before.get((2026, 9, "rechazada"), 0) == 1
    for future in ((2026, 12), (2027, 1), (2026, 10)):
        assert after.get((*future, "rechazada"), 0) == before.get((*future, "rechazada"), 0)
        assert after.get((*future, "pagada"), 0) == before.get((*future, "pagada"), 0)


# --- grafico de cobros por estado del dashboard VirtualPOS ---------------------------------------------------


def test_vp_charges_by_month_skip_future_charges() -> None:
    class Rec:
        def __init__(self, rtype, payload):
            self.resource_type, self.payload = rtype, payload

    records = [
        Rec("charge", {"charge_date": "2026-09-05", "status": "pagado", "amount": 1000}),
        Rec("charge", {"charge_date": "2026-09-06", "status": "cancelado", "amount": 1000}),
        Rec("charge", {"charge_date": "2026-12-05", "status": "cancelado", "amount": 1000}),
        Rec("charge", {"charge_date": "2026-11-01", "status": "pendiente", "amount": 1000}),
    ]
    rows = staging._vp_extended_data(records)["charges_monthly"]
    months = {(r["year"], r["month"]) for r in rows}
    assert months == {(2026, 9)}
    assert sum(r["count"] for r in rows) == 2  # el cancelado pasado sigue siendo un dato real


# --- recuperador: intentos ---------------------------------------------------------------------------------------


def test_recovery_attempts_do_not_count_future_or_cancelled_charges() -> None:
    def make(status, date_):
        return Charge(source="virtualpos1", external_id=uuid.uuid4().hex, subscription_external_id="s1",
                      status=status, charge_date=date_, amount="1000")

    charges = [make("pagado", "2026-08-05"), make("rechazado", "2026-09-05"), make("rechazado", "2026-10-05"),
               make("cancelado", "2026-10-20")]  # cancelado pasado
    charges += [make("cancelado", f"2027-{m:02d}-05") for m in range(1, 7)]  # programados y cancelados al dar de baja
    charges.append(make("pendiente", "2026-11-05"))
    stats = recovery._charge_stats(charges)[("virtualpos1", "s1")]
    assert stats["attempts"] == 3
    assert stats["last_paid"] == "2026-08-05" and stats["last_rejected"].charge_date == "2026-10-05"
