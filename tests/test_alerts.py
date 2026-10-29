"""SYNC-D-08: alertas por correo de fallos de sincronizacion. SOLO con un servidor SMTP falso en memoria.

Ninguna prueba abre un socket ni envia un correo real; el destinatario es ficticio (`alerts@example.test`).
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import ClassVar

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.v1.routes import sync_runs
from app.core.config import settings
from app.db.session import engine
from app.models.auth import User
from app.models.billing import BillingChangeRequest
from app.models.cancellation import SubscriptionCancellationRequest
from app.models.etl_run import EtlRun
from app.models.source_record import SourceRecord
from app.models.sync_run import SyncRun
from app.models.webhook_event import WebhookEvent
from app.scheduler.jobs import alert_jobs
from app.services import alerts, core_etl_mark

NOW = datetime(2099, 6, 1, 12, 0, tzinfo=UTC)
TO = "alerts@example.test"
PII_RUT = "12.345.678-5"
PII_MAIL = "juan.perez@example.com"


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    session.execute(delete(SyncRun))
    session.execute(delete(EtlRun))
    session.execute(delete(WebhookEvent))
    session.execute(delete(SourceRecord).where(SourceRecord.source.in_(("alert_state", "core_etl"))))
    session.flush()
    sync_runs.clear_sync_health_cache()
    try:
        yield session
    finally:
        sync_runs.clear_sync_health_cache()
        session.close()
        transaction.rollback()
        connection.close()


class FakeSMTP:
    """Servidor SMTP falso en memoria: registra conexiones, llamadas y mensajes."""

    instances: ClassVar[list["FakeSMTP"]] = []
    messages: ClassVar[list] = []
    fail_on_send: ClassVar[bool] = False

    def __init__(self, host, port=0, timeout=None, **kw):
        self.host, self.port, self.timeout = host, port, timeout
        self.calls: list[str] = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self, **kw):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(f"login:{user}")

    def send_message(self, msg, **kw):
        if FakeSMTP.fail_on_send:
            raise OSError("smtp caido user=juan.perez@example.com")
        self.calls.append("send")
        FakeSMTP.messages.append(msg)

    def quit(self):
        self.calls.append("quit")


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.instances, FakeSMTP.messages, FakeSMTP.fail_on_send = [], [], False
    monkeypatch.setattr(alerts.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(alerts.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(settings, "alerts_enabled", True)
    monkeypatch.setattr(settings, "alert_email_to", TO)
    monkeypatch.setattr(settings, "alert_email_from", "crm@example.test")
    monkeypatch.setattr(settings, "alert_smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "alert_smtp_port", 587)
    monkeypatch.setattr(settings, "alert_smtp_user", "")
    monkeypatch.setattr(settings, "alert_smtp_password", "")
    monkeypatch.setattr(settings, "alert_smtp_starttls", True)
    return FakeSMTP


def _run(db, hours_ago, source="toku", status="completed", error=None):
    started = NOW - timedelta(hours=hours_ago)
    db.add(SyncRun(source=source, status=status, started_at=started, finished_at=started, error_message=error))
    db.flush()


def _check(db, at=NOW):
    return alerts.run_alert_check(db, now=at)


def _subjects():
    return [m["Subject"] for m in FakeSMTP.messages]


def _text(msg) -> str:
    return msg.get_body(preferencelist=("plain",)).get_content()


def _user(db) -> User:
    user = User(username=f"u-{uuid.uuid4().hex[:10]}", password_hash="x")
    db.add(user)
    db.flush()
    return user


def _cancellation(db, status, updated_ago_min=0, sub="sub-1"):
    user = _user(db)
    row = SubscriptionCancellationRequest(
        channel="virtualpos1", subscription_external_id=sub, reason_code="member_request",
        reason_comment=f"El socio {PII_MAIL} {PII_RUT} pidio la baja", requested_by_user_id=user.id, status=status,
        requires_reconciliation=status == "requires_reconciliation", updated_at=NOW - timedelta(minutes=updated_ago_min))
    db.add(row)
    db.flush()
    return row


def _billing(db, status, updated_ago_min=0, sub="sub-1"):
    user = _user(db)
    row = BillingChangeRequest(
        request_type="change_amount", platform="virtualpos1", subscription_external_id=sub,
        requested_by_user_id=user.id, new_amount=Decimal("7000"), previous_amount=Decimal("9990"), status=status,
        rules_snapshot={"self_approval_enabled": True, "dual_approval_enabled": False},
        plan_preview={"create": [], "cancel": [], "covered": [], "manual_review": []},
        updated_at=NOW - timedelta(minutes=updated_ago_min))
    db.add(row)
    db.flush()
    return row


# ----------------------------- apagada, destinatario y servidor -----------------------------


def test_flag_off_by_default_and_nothing_is_sent(db_session, smtp, monkeypatch):
    assert type(settings).model_fields["alerts_enabled"].default is False
    monkeypatch.setattr(settings, "alerts_enabled", False)
    _run(db_session, 3, status="failed")
    _run(db_session, 2, status="failed")
    result = _check(db_session)
    assert result.sent == 0 and smtp.instances == []
    assert db_session.scalar(select(SourceRecord).where(SourceRecord.source == "alert_state")) is None


def test_missing_recipient_sends_nothing_and_logs_a_warning(db_session, smtp, monkeypatch, caplog):
    monkeypatch.setattr(settings, "alert_email_to", "  ")
    _run(db_session, 3, status="failed")
    _run(db_session, 2, status="failed")
    with caplog.at_level(logging.WARNING, logger="app.services.alerts"):
        result = _check(db_session)
    assert result.sent == 0 and smtp.instances == []
    assert any("ALERT_EMAIL_TO" in r.getMessage() for r in caplog.records)
    # sin estado guardado: al definir el destinatario la alerta sale en el siguiente chequeo
    monkeypatch.setattr(settings, "alert_email_to", TO)
    assert _check(db_session).sent == 1


def test_missing_smtp_host_sends_nothing_and_logs_a_warning(db_session, smtp, monkeypatch, caplog):
    monkeypatch.setattr(settings, "alert_smtp_host", "")
    _run(db_session, 3, status="failed")
    _run(db_session, 2, status="failed")
    with caplog.at_level(logging.WARNING, logger="app.services.alerts"):
        assert _check(db_session).sent == 0
    assert smtp.instances == [] and any("ALERT_SMTP_HOST" in r.getMessage() for r in caplog.records)


def test_no_active_condition_sends_nothing(db_session, smtp):
    _run(db_session, 1)
    assert _check(db_session).sent == 0 and smtp.instances == []


def test_recipients_may_be_a_comma_separated_list(db_session, smtp, monkeypatch):
    monkeypatch.setattr(settings, "alert_email_to", f"{TO}, otro@example.test")
    _run(db_session, 3, status="failed")
    _run(db_session, 2, status="failed")
    _check(db_session)
    assert smtp.messages[0]["To"] == f"{TO}, otro@example.test"


# ----------------------------- condiciones -----------------------------


def test_two_consecutive_failed_runs_alert_the_channel(db_session, smtp):
    _run(db_session, 3, status="failed")
    _run(db_session, 2, status="failed")
    result = _check(db_session)
    assert result.sent == 1
    msg = smtp.messages[0]
    assert "toku" in msg["Subject"].lower() and msg["Subject"].startswith("[SynkmetriX")
    body = _text(msg)
    assert "2 corridas fallidas seguidas" in body
    assert "/admin/sincronizaciones" in body
    assert "Activa desde" in body


def test_two_days_without_success_alert_the_channel(db_session, smtp):
    _run(db_session, 80)  # ultimo exito hace 3 dias y 8 horas, sin fallos posteriores
    assert _check(db_session).sent == 1
    body = _text(smtp.messages[0])
    assert "3 días sin una sincronización exitosa" in body


def test_one_day_without_success_does_not_alert(db_session, smtp):
    _run(db_session, 30)
    assert _check(db_session).sent == 0


def test_one_failed_run_does_not_alert(db_session, smtp):
    _run(db_session, 5)
    _run(db_session, 1, status="failed")
    assert _check(db_session).sent == 0


def test_core_lag_over_24h_alerts_and_within_24h_does_not(db_session, smtp):
    _run(db_session, 1)
    core_etl_mark.record(db_session, "toku", {}, finished_at=NOW - timedelta(hours=10))
    assert _check(db_session).sent == 0
    core_etl_mark.record(db_session, "toku", {}, finished_at=NOW - timedelta(hours=30))
    assert _check(db_session).sent == 1
    body = _text(smtp.messages[0])
    assert "ETL Core" in body and "29" in body


def _webhook(db, status, hours_ago, source="toku"):
    ev = WebhookEvent(source=source, event_type="subscription.updated", resource_type="subscription",
                      resource_external_id=PII_RUT, subscription_external_id=PII_RUT, payload_masked={"email": PII_MAIL},
                      dedupe_key=uuid.uuid4().hex + uuid.uuid4().hex, status=status, last_error_code="UNEXPECTED",
                      received_at=NOW - timedelta(hours=hours_ago), processed_at=NOW - timedelta(hours=hours_ago))
    db.add(ev)
    db.flush()


def test_recent_failed_webhook_events_alert_with_counts_only(db_session, smtp):
    _webhook(db_session, "failed", 2)
    _webhook(db_session, "failed", 3)
    _webhook(db_session, "done", 1)
    assert _check(db_session).sent == 1
    body = _text(smtp.messages[0])
    assert "webhook" in smtp.messages[0]["Subject"].lower() and "2 evento" in body and "toku" in body


def test_old_failed_webhook_events_do_not_alert(db_session, smtp):
    _webhook(db_session, "failed", 30)
    assert _check(db_session).sent == 0


@pytest.mark.parametrize(("status", "age", "expected"), [
    ("requires_reconciliation", 1, 1),
    ("applying", 45, 1),
    ("applying", 5, 0),
])
def test_stuck_cancellation_requests(db_session, smtp, status, age, expected):
    _cancellation(db_session, status, age)
    assert _check(db_session).sent == expected
    if expected:
        assert "baja" in smtp.messages[0]["Subject"].lower()


@pytest.mark.parametrize(("status", "age", "expected"), [
    ("requiere_conciliacion", 1, 1),
    ("aplicando", 45, 1),
    ("aplicando", 5, 0),
])
def test_stuck_billing_requests(db_session, smtp, status, age, expected):
    _billing(db_session, status, age)
    assert _check(db_session).sent == expected
    if expected:
        assert "cobro" in smtp.messages[0]["Subject"].lower()


# ----------------------------- deduplicacion y recuperacion -----------------------------


def test_dedupe_one_alert_then_a_reminder_every_6_hours(db_session, smtp):
    _run(db_session, 3, status="failed")
    _run(db_session, 2, status="failed")
    assert _check(db_session).sent == 1
    assert _check(db_session, NOW + timedelta(minutes=15)).sent == 0
    assert _check(db_session, NOW + timedelta(hours=5, minutes=59)).sent == 0
    reminder = _check(db_session, NOW + timedelta(hours=6))
    assert reminder.sent == 1 and "Recordatorio" in smtp.messages[-1]["Subject"]
    assert _check(db_session, NOW + timedelta(hours=11, minutes=59)).sent == 0
    assert _check(db_session, NOW + timedelta(hours=12)).sent == 1
    assert len(smtp.messages) == 3


def test_independent_conditions_alert_independently(db_session, smtp):
    _run(db_session, 3, source="toku", status="failed")
    _run(db_session, 2, source="toku", status="failed")
    _run(db_session, 3, source="payku", status="failed")
    _run(db_session, 2, source="payku", status="failed")
    assert _check(db_session).sent == 2
    assert _check(db_session, NOW + timedelta(minutes=15)).sent == 0


def test_recovery_notice_once_and_a_new_alert_after_it(db_session, smtp):
    _run(db_session, 3, status="failed")
    _run(db_session, 2, status="failed")
    assert _check(db_session).sent == 1
    later = NOW + timedelta(hours=1)
    db_session.add(SyncRun(source="toku", status="completed", started_at=later, finished_at=later))
    db_session.flush()
    sync_runs.clear_sync_health_cache()
    assert _check(db_session, later + timedelta(minutes=1)).sent == 1
    assert "Recuperado" in smtp.messages[-1]["Subject"]
    assert "normalizó" in _text(smtp.messages[-1]).lower() or "recuper" in _text(smtp.messages[-1]).lower()
    assert _check(db_session, later + timedelta(minutes=16)).sent == 0
    # vuelve a fallar: nueva alerta de inmediato
    for minutes in (20, 30):
        t = later + timedelta(minutes=minutes)
        db_session.add(SyncRun(source="toku", status="failed", started_at=t, finished_at=t))
    db_session.flush()
    assert _check(db_session, later + timedelta(minutes=45)).sent == 1
    assert "Recuperado" not in smtp.messages[-1]["Subject"] and "Recordatorio" not in smtp.messages[-1]["Subject"]


# ----------------------------- SMTP -----------------------------


def test_smtp_failure_does_not_raise_and_is_retried_on_the_next_tick(db_session, smtp, caplog):
    _run(db_session, 3, status="failed")
    _run(db_session, 2, status="failed")
    smtp.fail_on_send = True
    with caplog.at_level(logging.WARNING, logger="app.services.alerts"):
        result = _check(db_session)
    assert result.sent == 0 and result.failed == 1
    assert PII_MAIL not in caplog.text  # solo el nombre de la clase de la excepcion
    smtp.fail_on_send = False
    assert _check(db_session, NOW + timedelta(minutes=15)).sent == 1
    assert len(smtp.messages) == 1


def test_connection_failure_does_not_raise(db_session, smtp, monkeypatch):
    def boom(*a, **k):
        raise ConnectionRefusedError("no hay servidor")

    monkeypatch.setattr(alerts.smtplib, "SMTP", boom)
    _run(db_session, 3, status="failed")
    _run(db_session, 2, status="failed")
    assert _check(db_session).failed == 1


def test_starttls_login_and_short_timeout(db_session, smtp, monkeypatch):
    monkeypatch.setattr(settings, "alert_smtp_user", "usuario-falso")
    monkeypatch.setattr(settings, "alert_smtp_password", "clave-falsa")
    _run(db_session, 3, status="failed")
    _run(db_session, 2, status="failed")
    _check(db_session)
    server = smtp.instances[0]
    assert server.timeout is not None and server.timeout <= 15
    assert server.calls == ["ehlo", "starttls", "ehlo", "login:usuario-falso", "send", "quit"] or \
        server.calls == ["ehlo", "starttls", "ehlo", "login:usuario-falso", "send"]


def test_no_starttls_and_no_login_when_not_configured(db_session, smtp, monkeypatch):
    monkeypatch.setattr(settings, "alert_smtp_starttls", False)
    _run(db_session, 3, status="failed")
    _run(db_session, 2, status="failed")
    _check(db_session)
    calls = smtp.instances[0].calls
    assert "starttls" not in calls and not any(c.startswith("login") for c in calls) and "send" in calls


# ----------------------------- sin datos personales -----------------------------


def test_messages_carry_no_personal_data_and_are_in_spanish(db_session, smtp):
    _run(db_session, 3, status="failed", error=f"fallo con {PII_MAIL} y {PII_RUT}")
    _run(db_session, 2, status="failed", error=f"fallo con {PII_MAIL}")
    _webhook(db_session, "failed", 2)
    _cancellation(db_session, "requires_reconciliation", 5, sub=PII_RUT)
    _billing(db_session, "requiere_conciliacion", 5, sub=PII_MAIL)
    assert _check(db_session).sent == 4
    assert len(smtp.messages) == 4
    for msg in smtp.messages:
        everything = msg["Subject"] + _text(msg) + msg["From"] + msg["To"]
        assert PII_RUT not in everything and PII_MAIL not in everything and "juan" not in everything.lower()
        assert "Canal" in _text(msg) and "Condición" in _text(msg)
        assert "http" not in _text(msg)  # solo enlaces relativos al panel


def test_state_is_stored_in_source_records_with_counters_only(db_session, smtp):
    _run(db_session, 3, status="failed")
    _run(db_session, 2, status="failed")
    _check(db_session)
    rows = db_session.scalars(select(SourceRecord).where(SourceRecord.source == "alert_state")).all()
    assert len(rows) == 1 and rows[0].external_id == "sync_fail:toku"
    assert set(rows[0].payload) <= {"active", "since", "last_sent_at", "last_resolved_at"}


# ----------------------------- job y scheduler -----------------------------


def _factory(session):
    class _S:
        def __call__(self):
            return self

        def __getattr__(self, name):
            return getattr(session, name)

        def close(self):
            pass

    return _S()


def test_job_runs_the_check_and_never_raises(db_session, smtp, monkeypatch):
    monkeypatch.setattr(alert_jobs, "SessionLocal", _factory(db_session))
    _run(db_session, 3, status="failed")
    _run(db_session, 2, status="failed")
    asyncio.run(alert_jobs.check_alerts())
    assert len(smtp.messages) == 1

    def boom(*a, **k):
        raise RuntimeError("fallo inesperado")

    monkeypatch.setattr(alert_jobs.alerts, "run_alert_check", boom)
    asyncio.run(alert_jobs.check_alerts())  # no propaga


def test_job_is_a_noop_when_disabled(db_session, smtp, monkeypatch):
    monkeypatch.setattr(settings, "alerts_enabled", False)
    monkeypatch.setattr(alert_jobs, "SessionLocal", lambda: pytest.fail("no debe abrir sesion"))
    asyncio.run(alert_jobs.check_alerts())


def test_job_registered_every_15_minutes_and_idempotent():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from app.scheduler import engine as sched_engine

    sched = AsyncIOScheduler(timezone="America/Santiago")
    sched_engine.register_jobs(sched)
    jobs = {j.id: j for j in sched.get_jobs()}
    assert alert_jobs.JOB_ALERTS in jobs
    assert "minute='2,17,32,47'" in str(jobs[alert_jobs.JOB_ALERTS].trigger)
    n_jobs = len(sched.get_jobs())
    sched_engine.register_jobs(sched)
    assert len(sched.get_jobs()) == n_jobs
