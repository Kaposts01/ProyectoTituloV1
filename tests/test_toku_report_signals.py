"""TK-PAR-06 + TK-20: estado y senales de suscripcion de Toku desde los reportes (`core_subscription_signals`).

Reglas (DEC-16 a DEC-25): activa = no eliminada y medio `chargeable`; racha por CUOTAS impagas «en firme» (codigo 2070 o
7 dias sin intento), no por intentos; bloqueada = 1019/1051/2043 o medio `permanent_failed`; vencida = 1010/2044/2063;
un medio con falla temporal sin racha no es recuperable. Reporte gana sobre la API para estado y medio de pago.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from toku_signals_support import GENERATED, World, api_subscription, uid

from app.core.config import settings
from app.models.core import CoreSubscription
from app.models.toku_report import CoreSubscriptionSignal
from app.services import core_toku_etl
from app.services.toku_report_signals import compute_report_signals
from tests.test_charge_recovery import db_session  # noqa: F401  (fixture)

AS_OF = GENERATED.date()  # 2026-10-20: los reportes sinteticos se generaron ese dia


def day(days_before: int) -> date:
    return AS_OF - timedelta(days=days_before)


def _setup(db: Session, **product_kw):
    """Suscripcion core + producto del reporte. Devuelve (world, sub)."""
    sub = uid("sub")
    world = World(db)
    db.add(CoreSubscription(source="toku", external_id=sub, status="ACTIVE", currency="CLP"))
    db.flush()
    world.product(sub, **product_kw)
    return world, sub


def _signal(db: Session, sub: str) -> CoreSubscriptionSignal | None:
    db.expire_all()
    return db.scalar(select(CoreSubscriptionSignal).where(CoreSubscriptionSignal.external_id == sub))


def _run(db: Session, **kw):
    return compute_report_signals(db, **kw)


# ---- activa efectiva --------------------------------------------------------------------------------------------


def test_active_means_not_deleted_and_chargeable_payment_method(db_session: Session) -> None:  # noqa: F811
    _world, sub = _setup(db_session, pm_status="chargeable")
    _run(db_session)
    s = _signal(db_session, sub)
    assert (s.lifecycle_status, s.is_chargeable, s.is_effectively_active) == ("active", True, True)
    assert s.payment_method_status == "chargeable" and not s.is_recoverable and s.recoverable_reason is None


@pytest.mark.parametrize("pm_status", ["temporary_failed", "permanent_failed", "deleted", "permanently_deleted", None])
def test_not_chargeable_payment_method_is_not_effectively_active(db_session: Session, pm_status) -> None:  # noqa: F811
    _world, sub = _setup(db_session, pm_status=pm_status)
    _run(db_session)
    s = _signal(db_session, sub)
    assert s.lifecycle_status == "active" and not s.is_chargeable and not s.is_effectively_active


def test_deleted_subscription_is_never_effectively_active_nor_recoverable(db_session: Session) -> None:  # noqa: F811
    world, sub = _setup(db_session, pm_status="permanent_failed", deleted=datetime(2026, 5, 1, 15, 0, tzinfo=UTC))
    world.failed_cuota(sub, "in_1", day(60), code="1019")
    _run(db_session)
    s = _signal(db_session, sub)
    assert s.lifecycle_status == "deleted" and not s.is_effectively_active and not s.is_recoverable


def test_chargeable_but_deleted_is_not_active(db_session: Session) -> None:  # noqa: F811
    _world, sub = _setup(db_session, pm_status="chargeable", deleted=datetime(2026, 5, 1, 15, 0, tzinfo=UTC))
    _run(db_session)
    s = _signal(db_session, sub)
    assert s.is_chargeable and not s.is_effectively_active


def test_payment_method_report_beats_the_estado_of_the_product_row(db_session: Session) -> None:  # noqa: F811
    world, sub = _setup(db_session, pm_status="chargeable")
    pm = f"pm_{sub}"
    world.payment_method(pm, "permanent_failed")
    _run(db_session)
    s = _signal(db_session, sub)
    assert s.payment_method_status == "permanent_failed" and not s.is_chargeable
    assert s.recoverable_reason == "blocked_card" and s.is_recoverable


def test_deleted_payment_method_row_counts_as_deleted(db_session: Session) -> None:  # noqa: F811
    world, sub = _setup(db_session, pm_status="chargeable")
    world.payment_method(f"pm_{sub}", "chargeable", deleted=datetime(2026, 9, 1, 15, 0, tzinfo=UTC))
    _run(db_session)
    s = _signal(db_session, sub)
    assert s.payment_method_status == "deleted" and not s.is_chargeable


# ---- racha por cuotas -------------------------------------------------------------------------------------------


def test_three_unpaid_cuotas_with_code_2070_is_a_streak_even_when_recent(db_session: Session) -> None:  # noqa: F811
    world, sub = _setup(db_session)
    world.failed_cuota(sub, "in_1", day(40), code="2070")
    world.failed_cuota(sub, "in_2", day(10), code="2070")
    world.failed_cuota(sub, "in_3", day(1), code="2070")  # un dia antes del corte: firme por el codigo
    _run(db_session)
    s = _signal(db_session, sub)
    assert s.consecutive_failed_debts == 3 and s.recoverable_reason == "streak" and s.is_recoverable
    assert s.last_response_code == "2070"


def test_cuotas_become_firm_after_seven_days_without_a_new_attempt(db_session: Session) -> None:  # noqa: F811
    world, sub = _setup(db_session)
    for i, d in enumerate((60, 40, 20)):
        world.failed_cuota(sub, f"in_{i}", day(d), code="1001")  # ultimo intento hace 20, 40, 60 dias: en firme
    _run(db_session)
    s = _signal(db_session, sub)
    assert s.consecutive_failed_debts == 3 and s.is_recoverable


def test_recent_cuota_without_2070_is_not_firm_so_the_streak_is_two(db_session: Session) -> None:  # noqa: F811
    world, sub = _setup(db_session)
    world.failed_cuota(sub, "in_1", day(60), code="1001")
    world.failed_cuota(sub, "in_2", day(40), code="1001")
    world.failed_cuota(sub, "in_3", day(2), code="1001")  # todavia puede reintentarse: no cuenta
    _run(db_session)
    s = _signal(db_session, sub)
    assert s.consecutive_failed_debts == 2 and not s.is_recoverable and s.recoverable_reason is None


def test_three_attempts_in_one_cuota_is_not_a_streak_of_three(db_session: Session) -> None:  # noqa: F811
    """El contraste real (72 suscripciones por cuotas contra 138 por intentos): 3 intentos en UNA cuota no son racha."""
    world, sub = _setup(db_session)
    world.failed_cuota(sub, "in_1", day(40), attempts=3, code="1001")
    _run(db_session)
    s = _signal(db_session, sub)
    assert s.consecutive_failed_attempts == 3 and s.consecutive_failed_debts == 1
    assert not s.is_recoverable and s.recoverable_reason is None


def test_many_attempts_over_two_cuotas_stays_below_the_threshold(db_session: Session) -> None:  # noqa: F811
    world, sub = _setup(db_session)
    world.failed_cuota(sub, "in_1", day(60), attempts=3, code="1001")
    world.failed_cuota(sub, "in_2", day(30), attempts=3, code="1001")
    _run(db_session)
    s = _signal(db_session, sub)
    assert s.consecutive_failed_attempts == 6 and s.consecutive_failed_debts == 2 and not s.is_recoverable


def test_a_paid_cuota_breaks_the_streak(db_session: Session) -> None:  # noqa: F811
    world, sub = _setup(db_session)
    for i, d in enumerate((120, 100, 80)):
        world.failed_cuota(sub, f"in_{i}", day(d))
    world.paid_cuota(sub, "in_paid", day(60))
    world.failed_cuota(sub, "in_a", day(40))
    world.failed_cuota(sub, "in_b", day(20))
    _run(db_session)
    s = _signal(db_session, sub)
    assert s.consecutive_failed_debts == 2 and not s.is_recoverable
    assert s.consecutive_failed_attempts == 2


def test_a_cuota_with_a_failure_and_then_a_payment_counts_as_paid(db_session: Session) -> None:  # noqa: F811
    world, sub = _setup(db_session)
    world.failed_cuota(sub, "in_1", day(60))
    world.failed_cuota(sub, "in_2", day(40))
    world.failed_cuota(sub, "in_3", day(20))
    world.paid_cuota(sub, "in_3", day(19))  # la cuota 3 se pago en un reintento
    _run(db_session)
    assert _signal(db_session, sub).consecutive_failed_debts == 0


def test_in_process_cuota_is_ignored_and_does_not_break_the_streak(db_session: Session) -> None:  # noqa: F811
    world, sub = _setup(db_session)
    for i, d in enumerate((60, 40, 20)):
        world.failed_cuota(sub, f"in_{i}", day(d))
    world.attempt(sub, "in_now", datetime(2026, 10, 20, 9, 0, tzinfo=UTC), status="EN PROCESO", due=day(0))
    _run(db_session)
    assert _signal(db_session, sub).consecutive_failed_debts == 3


def test_deleted_attempts_are_ignored(db_session: Session) -> None:  # noqa: F811
    world, sub = _setup(db_session)
    for i, d in enumerate((60, 40, 20)):
        world.attempt(sub, f"in_{i}", datetime.combine(day(d), datetime.min.time(), tzinfo=UTC), deleted=GENERATED)
    _run(db_session)
    assert _signal(db_session, sub).consecutive_failed_debts == 0


def test_unpaid_debts_without_attempts_count_after_seven_days_and_voided_ones_are_skipped(db_session: Session) -> None:  # noqa: F811
    world, sub = _setup(db_session)
    world.debt(sub, "in_1", day(60))
    world.debt(sub, "in_2", day(40), voided=True)
    world.debt(sub, "in_3", day(30))
    world.debt(sub, "in_4", day(20))
    world.debt(sub, "in_5", day(3))  # vencio hace 3 dias: aun no esta en firme
    _run(db_session)
    s = _signal(db_session, sub)
    assert s.consecutive_failed_debts == 3 and s.is_recoverable and s.recoverable_reason == "streak"


def test_paid_debt_in_the_debts_report_breaks_the_streak(db_session: Session) -> None:  # noqa: F811
    world, sub = _setup(db_session)
    world.failed_cuota(sub, "in_1", day(60))
    world.debt(sub, "in_2", day(40), paid=True)
    world.failed_cuota(sub, "in_3", day(20))
    _run(db_session)
    assert _signal(db_session, sub).consecutive_failed_debts == 1


# ---- tarjeta bloqueada / vencida / falla temporal -----------------------------------------------------------------


@pytest.mark.parametrize("code", ["1019", "1051", "2043"])
def test_blocked_card_codes(db_session: Session, code) -> None:  # noqa: F811
    world, sub = _setup(db_session)
    world.failed_cuota(sub, "in_1", day(3), code=code)
    _run(db_session)
    s = _signal(db_session, sub)
    assert s.recoverable_reason == "blocked_card" and s.is_recoverable and s.consecutive_failed_debts == 0


@pytest.mark.parametrize("code", ["1010", "2044", "2063"])
def test_expired_card_codes(db_session: Session, code) -> None:  # noqa: F811
    world, sub = _setup(db_session)
    world.failed_cuota(sub, "in_1", day(3), code=code)
    _run(db_session)
    s = _signal(db_session, sub)
    assert s.recoverable_reason == "expired_card" and s.is_recoverable


def test_permanent_failed_payment_method_is_a_blocked_card_without_any_attempt(db_session: Session) -> None:  # noqa: F811
    _world, sub = _setup(db_session, pm_status="permanent_failed")
    _run(db_session)
    s = _signal(db_session, sub)
    assert s.recoverable_reason == "blocked_card" and s.is_recoverable and not s.is_effectively_active


def test_a_later_authorized_attempt_clears_a_card_code(db_session: Session) -> None:  # noqa: F811
    world, sub = _setup(db_session)
    world.failed_cuota(sub, "in_1", day(10), code="1019")
    world.paid_cuota(sub, "in_2", day(2))
    _run(db_session)
    s = _signal(db_session, sub)
    assert s.recoverable_reason is None and not s.is_recoverable and s.last_response_code == "1019"


def test_temporary_failure_without_a_streak_is_not_recoverable(db_session: Session) -> None:  # noqa: F811
    world, sub = _setup(db_session, pm_status="temporary_failed")
    world.failed_cuota(sub, "in_1", day(20), attempts=2, code="1001")
    world.failed_cuota(sub, "in_2", day(5), code="1001")
    _run(db_session)
    s = _signal(db_session, sub)
    assert s.payment_method_status == "temporary_failed" and not s.is_chargeable
    assert not s.is_recoverable and s.recoverable_reason is None


def test_temporary_failure_with_a_streak_is_recoverable_by_streak(db_session: Session) -> None:  # noqa: F811
    world, sub = _setup(db_session, pm_status="temporary_failed")
    for i, d in enumerate((60, 40, 20)):
        world.failed_cuota(sub, f"in_{i}", day(d), code="1001")
    _run(db_session)
    assert _signal(db_session, sub).recoverable_reason == "streak"


def test_blocked_beats_expired_beats_streak_when_several_apply(db_session: Session) -> None:  # noqa: F811
    world, sub = _setup(db_session, pm_status="permanent_failed")
    for i, d in enumerate((60, 40, 20)):
        world.failed_cuota(sub, f"in_{i}", day(d), code="1010")
    _run(db_session)
    s = _signal(db_session, sub)
    assert s.recoverable_reason == "blocked_card" and s.consecutive_failed_debts == 3


def test_last_response_severity_and_time_come_from_the_last_failed_attempt(db_session: Session) -> None:  # noqa: F811
    world, sub = _setup(db_session)
    world.attempt(sub, "in_1", datetime(2026, 10, 1, 12, 0, tzinfo=UTC), code="1001", severity="TE")
    world.attempt(sub, "in_1", datetime(2026, 10, 9, 12, 0, tzinfo=UTC), code="1019", severity="PE")
    _run(db_session)
    s = _signal(db_session, sub)
    assert (s.last_response_code, s.last_response_severity) == ("1019", "PE")
    assert s.last_attempt_at == datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    assert s.report_generated_at == GENERATED


# ---- estado de la suscripcion (reporte > API) --------------------------------------------------------------------


def _status(db: Session, sub: str) -> str | None:
    db.expire_all()
    return db.scalar(select(CoreSubscription.status).where(CoreSubscription.external_id == sub, CoreSubscription.source == "toku"))


def test_report_status_beats_the_api_for_deleted_and_fills_null(db_session: Session) -> None:  # noqa: F811
    world = World(db_session)
    deleted, null_status, paused = uid("sub"), uid("sub"), uid("sub")
    for sub, status in ((deleted, "ACTIVE"), (null_status, None), (paused, "PAUSED")):
        db_session.add(CoreSubscription(source="toku", external_id=sub, status=status, currency="CLP"))
    db_session.flush()
    world.product(deleted, deleted=datetime(2026, 5, 1, 15, 0, tzinfo=UTC))
    world.product(null_status)
    world.product(paused)
    result = _run(db_session)
    assert _status(db_session, deleted) == "deleted_at_source"
    assert _status(db_session, null_status) == "ACTIVE"
    assert _status(db_session, paused) == "PAUSED"  # el reporte no sabe de pausas: la API manda
    assert result["status_updated"] == 2


def test_subscription_without_a_core_row_is_counted_and_skipped(db_session: Session) -> None:  # noqa: F811
    World(db_session).product(uid("sub"))
    result = _run(db_session)
    assert result["no_core_subscription"] >= 1


def test_run_is_idempotent_and_dry_run_writes_nothing(db_session: Session) -> None:  # noqa: F811
    _world, sub = _setup(db_session, pm_status="permanent_failed")
    dry = _run(db_session, dry_run=True)
    assert dry["dry_run"] is True and dry["recoverable"] >= 1 and _signal(db_session, sub) is None
    _run(db_session)
    first = _signal(db_session, sub)
    updated = first.updated_at
    _run(db_session)
    assert db_session.scalar(
        select(func.count()).select_from(CoreSubscriptionSignal).where(CoreSubscriptionSignal.external_id == sub)
    ) == 1
    assert _signal(db_session, sub).recoverable_reason == "blocked_card" and updated is not None


def test_signals_are_recomputed_when_the_data_changes(db_session: Session) -> None:  # noqa: F811
    world, sub = _setup(db_session, pm_status="permanent_failed")
    _run(db_session)
    assert _signal(db_session, sub).is_recoverable
    world.payment_method(f"pm_{sub}", "chargeable")
    _run(db_session)
    assert not _signal(db_session, sub).is_recoverable


# ---- bandera y ETL ----------------------------------------------------------------------------------------------


def test_flag_is_off_by_default() -> None:
    assert settings.toku_report_signals_enabled is False


def test_etl_does_not_compute_signals_when_the_flag_is_off(db_session: Session, monkeypatch) -> None:  # noqa: F811
    monkeypatch.setattr(settings, "toku_report_signals_enabled", False)
    api_subscription(db_session, (sub := uid("sub")))
    World(db_session).product(sub, pm_status="permanent_failed", deleted=datetime(2026, 5, 1, 15, 0, tzinfo=UTC))
    result = core_toku_etl.run_toku_core_etl(db_session)
    assert "report_signals" not in result and _signal(db_session, sub) is None
    assert _status(db_session, sub) == "ACTIVE"  # estado de la API intacto con la bandera apagada


def test_etl_computes_signals_and_status_when_the_flag_is_on(db_session: Session, monkeypatch) -> None:  # noqa: F811
    monkeypatch.setattr(settings, "toku_report_signals_enabled", True)
    api_subscription(db_session, (sub := uid("sub")))
    World(db_session).product(sub, pm_status="permanent_failed")
    result = core_toku_etl.run_toku_core_etl(db_session)
    assert result["report_signals"]["recoverable"] >= 1
    assert _signal(db_session, sub).recoverable_reason == "blocked_card"
    # un segundo ETL (el sync de la API reescribe el estado) deja el mismo resultado
    core_toku_etl.run_toku_core_etl(db_session)
    assert _signal(db_session, sub).recoverable_reason == "blocked_card"


def test_signal_rows_hold_no_personal_data_columns() -> None:
    columns = {c.name for c in CoreSubscriptionSignal.__table__.columns}
    assert not columns & {"name", "email", "rut", "government_id", "phone", "raw_payload", "product_key_hash"}
