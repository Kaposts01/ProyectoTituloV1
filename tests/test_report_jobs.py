"""REP-02: jobs e idempotencia de los reportes por correo. SMTP simulado; destinatario ficticio, nunca un correo real."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.models.report_dispatch import ReportDispatch
from app.scheduler import engine as sched_engine
from app.scheduler.jobs import report_jobs
from app.services import alerts, report_delivery
from tests.test_scheduled_reports import FakeSMTP

TO = "persona@ejemplo.org"
MONDAY = datetime(2026, 11, 23, 10, 30, tzinfo=UTC)  # lunes 07:30 en Chile (UTC-3)


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
def smtp(monkeypatch):
    FakeSMTP.instances, FakeSMTP.messages, FakeSMTP.fail_with = [], [], None
    monkeypatch.setattr(alerts.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(alerts.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(settings, "alert_email_from", "crm@ejemplo.test")
    monkeypatch.setattr(settings, "alert_smtp_host", "smtp.ejemplo.test")
    monkeypatch.setattr(settings, "alert_smtp_port", 587)
    monkeypatch.setattr(settings, "alert_smtp_user", "")
    monkeypatch.setattr(settings, "alert_smtp_password", "")
    monkeypatch.setattr(settings, "reports_weekly_enabled", True)
    monkeypatch.setattr(settings, "reports_monthly_enabled", True)
    monkeypatch.setattr(settings, "report_email_to", TO)
    return FakeSMTP


def _rows(db):
    return db.execute(select(ReportDispatch).order_by(ReportDispatch.created_at)).scalars().all()


# ----------------------------- sin bandera, sin destinatario, sin servidor -----------------------------


def test_flag_off_sends_nothing_and_records_nothing(db_session, smtp, monkeypatch) -> None:
    monkeypatch.setattr(settings, "reports_weekly_enabled", False)
    result = report_delivery.dispatch_report(db_session, "weekly", MONDAY)
    assert (result.status, result.reason) == ("skipped", "disabled")
    assert smtp.instances == [] and _rows(db_session) == []


def test_no_recipient_or_no_host_sends_nothing(db_session, smtp, monkeypatch) -> None:
    monkeypatch.setattr(settings, "report_email_to", "")
    assert report_delivery.dispatch_report(db_session, "weekly", MONDAY).reason == "no_recipient"
    monkeypatch.setattr(settings, "report_email_to", TO)
    monkeypatch.setattr(settings, "alert_smtp_host", " ")
    assert report_delivery.dispatch_report(db_session, "weekly", MONDAY).reason == "no_smtp_host"
    assert smtp.instances == [] and _rows(db_session) == []


def test_alerts_flag_is_independent(db_session, smtp, monkeypatch) -> None:
    monkeypatch.setattr(settings, "alerts_enabled", False)
    assert report_delivery.dispatch_report(db_session, "weekly", MONDAY).status == "sent"


# ----------------------------- idempotencia -----------------------------


def test_same_period_is_sent_once(db_session, smtp) -> None:
    first = report_delivery.dispatch_report(db_session, "weekly", MONDAY)
    second = report_delivery.dispatch_report(db_session, "weekly", MONDAY + timedelta(hours=1))
    assert (first.status, first.period_key) == ("sent", "weekly:2026-W47")
    assert (second.status, second.reason) == ("skipped", "already_sent")
    assert len(smtp.messages) == 1
    (row,) = _rows(db_session)
    assert (row.status, row.attempts, row.recipients_count, row.error_class) == ("sent", 1, 1, None)
    assert row.sent_at is not None


def test_next_period_is_sent_again(db_session, smtp) -> None:
    report_delivery.dispatch_report(db_session, "weekly", MONDAY)
    report_delivery.dispatch_report(db_session, "weekly", MONDAY + timedelta(days=7))
    assert [r.period_key for r in _rows(db_session)] == ["weekly:2026-W47", "weekly:2026-W48"]
    assert len(smtp.messages) == 2


def test_failure_is_recorded_without_message_and_retried_up_to_three_times(db_session, smtp) -> None:
    smtp.fail_with = OSError(f"se cayo con {TO}")
    first = report_delivery.dispatch_report(db_session, "weekly", MONDAY)
    assert (first.status, first.error_class, first.attempts) == ("failed", "OSError", 1)
    (row,) = _rows(db_session)
    assert row.status == "failed" and row.error_class == "OSError" and TO not in str(row.error_class)
    second = report_delivery.dispatch_report(db_session, "weekly", MONDAY)
    assert second.attempts == 2 and second.status == "failed"
    smtp.fail_with = None
    third = report_delivery.dispatch_report(db_session, "weekly", MONDAY)
    assert (third.status, third.attempts) == ("sent", 3)
    assert len(smtp.messages) == 1


def test_exhausted_attempts_are_not_retried(db_session, smtp) -> None:
    smtp.fail_with = OSError("x")
    for _ in range(3):
        report_delivery.dispatch_report(db_session, "monthly", MONDAY)
    smtp.fail_with = None
    result = report_delivery.dispatch_report(db_session, "monthly", MONDAY)
    assert (result.status, result.reason) == ("skipped", "exhausted")
    assert smtp.messages == []


def test_stale_sending_logic_with_explicit_clock(db_session, smtp) -> None:
    key = report_delivery.period_key_for("weekly", MONDAY)
    stamp = MONDAY - timedelta(minutes=45)
    db_session.add(ReportDispatch(report_kind="weekly", period_key=key, status="sending", attempts=1,
                                  created_at=stamp, updated_at=stamp))
    db_session.commit()
    result = report_delivery.dispatch_report(db_session, "weekly", MONDAY)
    assert (result.status, result.attempts) == ("sent", 2)
    fresh_key = report_delivery.period_key_for("weekly", MONDAY + timedelta(days=7))
    stamp2 = MONDAY + timedelta(days=7) - timedelta(minutes=5)
    db_session.add(ReportDispatch(report_kind="weekly", period_key=fresh_key, status="sending", attempts=1,
                                  created_at=stamp2, updated_at=stamp2))
    db_session.commit()
    blocked = report_delivery.dispatch_report(db_session, "weekly", MONDAY + timedelta(days=7))
    assert (blocked.status, blocked.reason) == ("skipped", "in_progress")


def test_test_send_ignores_flag_but_never_repeats_a_key(db_session, smtp, monkeypatch) -> None:
    monkeypatch.setattr(settings, "reports_monthly_enabled", False)
    result = report_delivery.dispatch_report(db_session, "monthly", MONDAY, test=True)
    assert result.status == "sent" and result.period_key.startswith("test:")
    assert len(smtp.messages) == 1
    assert smtp.messages[0]["Subject"].startswith("[SynkmetriX ·")
    monkeypatch.setattr(settings, "report_email_to", "")
    assert report_delivery.dispatch_report(db_session, "monthly", MONDAY, test=True).reason == "no_recipient"


# ----------------------------- jobs -----------------------------


def test_jobs_are_noops_when_flags_are_off(monkeypatch) -> None:
    monkeypatch.setattr(settings, "reports_weekly_enabled", False)
    monkeypatch.setattr(settings, "reports_monthly_enabled", False)
    monkeypatch.setattr(report_jobs, "SessionLocal", lambda: pytest.fail("no debe abrir sesion"))
    asyncio.run(report_jobs.report_weekly())
    asyncio.run(report_jobs.report_monthly())
    asyncio.run(report_jobs.report_catch_up())


def _freeze(monkeypatch, moment: datetime) -> None:
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment.astimezone(tz) if tz else moment

    monkeypatch.setattr(report_jobs, "datetime", Frozen)


def test_monthly_job_runs_every_day_and_relies_on_the_idempotent_table(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_run(kind: str) -> None:
        calls.append(kind)

    monkeypatch.setattr(report_jobs, "_run", fake_run)
    monkeypatch.setattr(settings, "reports_monthly_enabled", True)
    asyncio.run(report_jobs.report_monthly())
    assert calls == ["monthly"]


def test_job_retries_failures_with_a_pause_and_stops_after_three(monkeypatch) -> None:
    attempts: list[int] = []
    sleeps: list[float] = []

    def fake_dispatch(kind: str, period_at):
        attempts.append(1)
        return report_delivery.DispatchResult("failed", "send_failed", len(attempts), "OSError")

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(report_jobs, "_dispatch_sync", fake_dispatch)
    monkeypatch.setattr(report_jobs.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(settings, "reports_weekly_enabled", True)
    asyncio.run(report_jobs.report_weekly())
    assert len(attempts) == 3 and sleeps == [report_jobs.RETRY_DELAY_SECONDS] * 2


@pytest.mark.parametrize(
    ("kind", "now_utc", "expected_key"),
    [
        # semanal: lunes 23-nov-2026 07:30 Chile = 10:30 UTC. Antes de la hora, el ultimo vencido es el del lunes anterior.
        ("weekly", datetime(2026, 11, 23, 10, 29, tzinfo=UTC), "weekly:2026-W46"),
        ("weekly", datetime(2026, 11, 23, 10, 31, tzinfo=UTC), "weekly:2026-W47"),
        ("weekly", datetime(2026, 11, 26, 15, 0, tzinfo=UTC), "weekly:2026-W47"),  # jueves, equipo recien encendido
        ("weekly", datetime(2026, 11, 29, 20, 0, tzinfo=UTC), "weekly:2026-W47"),  # domingo
        # mensual: primer dia habil de nov-2026 es lunes 2 (domingo 1) a las 07:45 = 10:45 UTC
        ("monthly", datetime(2026, 11, 1, 15, 0, tzinfo=UTC), "monthly:2026-09"),  # domingo 1: aun no vence octubre
        ("monthly", datetime(2026, 11, 2, 10, 44, tzinfo=UTC), "monthly:2026-09"),
        ("monthly", datetime(2026, 11, 2, 10, 46, tzinfo=UTC), "monthly:2026-10"),
        ("monthly", datetime(2026, 11, 20, 15, 0, tzinfo=UTC), "monthly:2026-10"),  # varios dias despues
        ("monthly", datetime(2026, 8, 3, 15, 0, tzinfo=UTC), "monthly:2026-07"),  # mes que empieza en sabado
    ],
)
def test_last_due_ref_points_to_the_last_period_whose_time_already_passed(kind, now_utc, expected_key) -> None:
    ref = report_jobs.last_due_ref(kind, now_utc)
    assert report_delivery.period_key_for(kind, ref) == expected_key


def test_machine_off_for_days_sends_the_last_due_period_once(db_session, smtp, monkeypatch) -> None:
    # El equipo estuvo apagado del lunes 23 al viernes 27 y arranca el viernes 14:00 Chile.
    boot = datetime(2026, 11, 27, 17, 0, tzinfo=UTC)
    ref = report_jobs.last_due_ref("weekly", boot)
    first = report_delivery.dispatch_report(db_session, "weekly", boot, period_at=ref)
    assert (first.status, first.period_key) == ("sent", "weekly:2026-W47")
    again = report_delivery.dispatch_report(db_session, "weekly", boot + timedelta(minutes=2), period_at=ref)
    assert (again.status, again.reason) == ("skipped", "already_sent")
    assert len(smtp.messages) == 1
    assert [r.period_key for r in _rows(db_session)] == ["weekly:2026-W47"]
    # el asunto es de la semana que se perdio, no de la siguiente
    assert "16-11-2026 al 22-11-2026" in smtp.messages[0]["Subject"]


def test_catch_up_passes_the_last_due_reference_for_each_enabled_report(monkeypatch) -> None:
    seen: list[tuple[str, str]] = []

    def fake_dispatch(kind: str, period_at):
        seen.append((kind, report_delivery.period_key_for(kind, period_at)))
        return report_delivery.DispatchResult("sent", None, 1)

    monkeypatch.setattr(report_jobs, "_dispatch_sync", fake_dispatch)
    _freeze(monkeypatch, datetime(2026, 11, 27, 17, 0, tzinfo=UTC))
    monkeypatch.setattr(settings, "reports_weekly_enabled", True)
    monkeypatch.setattr(settings, "reports_monthly_enabled", False)
    asyncio.run(report_jobs.report_catch_up())
    assert seen == [("weekly", "weekly:2026-W47")]
    seen.clear()
    monkeypatch.setattr(settings, "reports_monthly_enabled", True)
    asyncio.run(report_jobs.report_catch_up())
    assert seen == [("weekly", "weekly:2026-W47"), ("monthly", "monthly:2026-10")]


# ----------------------------- registro en el programador -----------------------------


def test_jobs_registered_with_schedule_misfire_and_idempotent() -> None:
    sched = AsyncIOScheduler(timezone="America/Santiago")
    sched_engine.register_jobs(sched)
    jobs = {j.id: j for j in sched.get_jobs()}
    weekly, monthly = jobs[report_jobs.JOB_REPORT_WEEKLY], jobs[report_jobs.JOB_REPORT_MONTHLY]
    assert "day_of_week='mon'" in str(weekly.trigger) and "hour='7'" in str(weekly.trigger) and "minute='30'" in str(weekly.trigger)
    assert "hour='7'" in str(monthly.trigger) and "minute='45'" in str(monthly.trigger)
    assert str(weekly.trigger.timezone) == "America/Santiago" and str(monthly.trigger.timezone) == "America/Santiago"
    for job in (weekly, monthly):
        assert job.misfire_grace_time == 6 * 3600 and job.coalesce is True and job.max_instances == 1
    assert report_jobs.JOB_REPORT_CATCHUP in jobs
    n_jobs = len(sched.get_jobs())
    sched_engine.register_jobs(sched)
    assert len(sched.get_jobs()) == n_jobs


def test_configured_hour_changes_the_trigger(monkeypatch) -> None:
    monkeypatch.setattr(settings, "report_weekly_hour", 8)
    sched = AsyncIOScheduler(timezone="America/Santiago")
    sched_engine.register_jobs(sched)
    assert "hour='8'" in str(sched.get_job(report_jobs.JOB_REPORT_WEEKLY).trigger)
