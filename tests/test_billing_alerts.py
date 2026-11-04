"""BILL-22: alertas de la cola de conciliacion y del barrido de la Opcion A. SOLO con un SMTP falso en memoria.

Ninguna prueba abre un socket ni envia un correo real; el destinatario es ficticio (`alerts@example.test`).
"""

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
from app.models.billing import (
    BillingChangeRequest,
    BillingChangeRequestEvent,
    VpManagedCharge,
)
from app.models.source_record import SourceRecord
from app.models.sync_run import SyncRun
from app.models.webhook_event import WebhookEvent
from app.services import alerts, billing_alerts

NOW = datetime(2099, 6, 1, 12, 0, tzinfo=UTC)
TO = "alerts@example.test"
SUB = "sub-bill22-secreta"
CHARGE = "chg-bill22-secreto"


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    session.execute(delete(SyncRun))
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
    instances: ClassVar[list["FakeSMTP"]] = []
    messages: ClassVar[list] = []

    def __init__(self, host, port=0, timeout=None, **kw):
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        pass

    def starttls(self, **kw):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg, **kw):
        FakeSMTP.messages.append(msg)


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.instances, FakeSMTP.messages = [], []
    monkeypatch.setattr(alerts.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(alerts.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(settings, "alerts_enabled", True)
    monkeypatch.setattr(settings, "alert_email_to", TO)
    monkeypatch.setattr(settings, "alert_email_from", "crm@example.test")
    monkeypatch.setattr(settings, "alert_smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "alert_smtp_port", 587)
    monkeypatch.setattr(settings, "alert_smtp_user", "")
    monkeypatch.setattr(settings, "alert_smtp_password", "")
    monkeypatch.setattr(settings, "webhook_processor_enabled", False)
    monkeypatch.setattr(settings, "alert_webhook_silence_hours", 0)
    return FakeSMTP


def _request(db, status, updated_ago_min=0, sub=SUB) -> BillingChangeRequest:
    user = User(username=f"u-{uuid.uuid4().hex[:10]}", password_hash="x")
    db.add(user)
    db.flush()
    row = BillingChangeRequest(
        request_type="change_amount", platform="virtualpos1", subscription_external_id=sub,
        requested_by_user_id=user.id, new_amount=Decimal("7000"), previous_amount=Decimal("9990"), status=status,
        rules_snapshot={"self_approval_enabled": True, "dual_approval_enabled": False},
        plan_preview={"create": [], "cancel": [], "covered": [], "manual_review": []},
        updated_at=NOW - timedelta(minutes=updated_ago_min))
    db.add(row)
    db.flush()
    return row


def _managed(db, request_id, updated_ago_min=0) -> None:
    db.add(VpManagedCharge(platform="virtualpos1", charge_id=CHARGE, subscription_external_id=SUB,
                           internal_code="CRM-X", month="2099-07", amount=Decimal("7000"), request_id=request_id,
                           status="requiere_conciliacion", updated_at=NOW - timedelta(minutes=updated_ago_min)))
    db.flush()


def _swept_event(db, request_id, ago=timedelta(hours=1)) -> None:
    db.add(BillingChangeRequestEvent(request_id=request_id, event_type="requiere_conciliacion", actor_user_id=None,
                                     detail={"reason": "stuck_applying", "older_than_minutes": 30},
                                     created_at=NOW - ago))
    db.flush()


def _billing_keys(db) -> set[str]:
    return {c.key for c in alerts.evaluate_conditions(db, NOW) if c.key.startswith("billing")}


def _all_text() -> str:
    return "\n".join(m["Subject"] + "\n" + m.get_body(preferencelist=("plain",)).get_content() for m in FakeSMTP.messages)


def test_provider_is_registered():
    assert billing_alerts.KIND in alerts.registered_kinds()


def test_request_in_requiere_conciliacion_alerts_once(db_session, smtp):
    req = _request(db_session, "requiere_conciliacion", updated_ago_min=5)
    _managed(db_session, req.id, updated_ago_min=5)  # su cobro va con la solicitud: no duplica el aviso
    assert _billing_keys(db_session) == {"billing_stuck"}
    result = alerts.run_alert_check(db_session, now=NOW)
    assert result.sent == 1 and "cobro" in smtp.messages[0]["Subject"].lower()


def test_orphan_charge_in_reconciliation_alerts_without_pii(db_session, smtp):
    req = _request(db_session, "aprobada")  # reabierta, pero su cobro sigue sin conciliar
    _managed(db_session, req.id, updated_ago_min=10)
    assert _billing_keys(db_session) == {"billing_reconciliation:queue"}
    assert alerts.run_alert_check(db_session, now=NOW).sent == 1
    body = _all_text()
    assert "cobros del CRM: 1" in body
    assert SUB not in body and CHARGE not in body and str(req.id) not in body


def test_stale_queue_over_24h_alerts_pilot_abort(db_session, smtp):
    _request(db_session, "requiere_conciliacion", updated_ago_min=25 * 60)
    assert _billing_keys(db_session) == {"billing_stuck", "billing_reconciliation:stale"}
    alerts.run_alert_check(db_session, now=NOW)
    assert "PI-05" in _all_text()


def test_swept_requests_alert_and_recover(db_session, smtp):
    req = _request(db_session, "requiere_conciliacion", updated_ago_min=60)
    _swept_event(db_session, req.id)
    assert "billing_reconciliation:swept" in _billing_keys(db_session)
    alerts.run_alert_check(db_session, now=NOW)
    assert any("barridas" in m["Subject"] for m in smtp.messages)
    # fuera de la ventana de 24 h y con la solicitud ya reabierta: aviso de recuperacion
    req.status = "aprobada"
    db_session.flush()
    later = NOW + timedelta(hours=25)
    assert billing_alerts.swept_count(db_session, later) == 0
    smtp.messages.clear()
    alerts.run_alert_check(db_session, now=later)
    assert any("solicitudes barridas a conciliación" in m["Subject"] for m in smtp.messages)


def test_human_reconciliation_event_is_not_counted_as_swept(db_session):
    req = _request(db_session, "requiere_conciliacion")
    db_session.add(BillingChangeRequestEvent(request_id=req.id, event_type="requiere_conciliacion",
                                             actor_user_id=None, detail={"reason": "cancel_failed"},
                                             created_at=NOW - timedelta(hours=1)))
    db_session.flush()
    assert billing_alerts.swept_count(db_session, NOW) == 0


@pytest.mark.parametrize("missing", ["alerts_enabled", "alert_email_to", "alert_smtp_host"])
def test_nothing_is_sent_without_alert_configuration(db_session, smtp, monkeypatch, missing):
    req = _request(db_session, "requiere_conciliacion", updated_ago_min=25 * 60)
    _swept_event(db_session, req.id)
    _managed(db_session, _request(db_session, "aprobada", sub="sub-bill22-otra").id)
    monkeypatch.setattr(settings, missing, False if missing == "alerts_enabled" else "")
    result = alerts.run_alert_check(db_session, now=NOW)
    assert result.sent == 0 and result.skipped is not None
    assert smtp.instances == [] and smtp.messages == []
    assert db_session.scalar(select(SourceRecord).where(SourceRecord.source == "alert_state")) is None
