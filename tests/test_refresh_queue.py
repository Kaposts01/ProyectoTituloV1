"""SYNC-O-15: cola `refresh_queue` (webhook fallido -> reconciliacion dirigida). Fakes: nada de red ni de proveedores."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.models.refresh_queue import RefreshQueueItem
from app.models.webhook_event import WebhookEvent
from app.services import refresh_queue as rq
from app.services import targeted_reconcile as tr
from app.services import webhook_processor as wp
from app.services.subscription_refresh import RefreshError

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


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
def _clean(monkeypatch):
    """Sin filas confirmadas de otros tests y sin sync activa ni ventana de riesgo (se prueba solo la cola)."""
    with SessionLocal() as s:
        s.execute(delete(RefreshQueueItem))
        s.execute(delete(WebhookEvent))
        s.commit()
    monkeypatch.setattr(tr, "find_active_run", lambda db: None)
    yield


class Recorder:
    def __init__(self, fail: dict | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail = fail or {}

    async def __call__(self, db, source, external_id, *, run_id=None):
        self.calls.append((source, external_id))
        exc = self.fail.get((source, external_id))
        if exc is not None:
            raise exc


async def _nosleep(_seconds):
    return None


def _items(db: Session, sub: str | None = None) -> list[RefreshQueueItem]:
    db.expire_all()
    stmt = select(RefreshQueueItem).order_by(RefreshQueueItem.created_at)
    if sub:
        stmt = stmt.where(RefreshQueueItem.subscription_external_id == sub)
    return list(db.scalars(stmt))


def _reconcile(db, rec, risk=(), **kw):
    kw.setdefault("limit", 10)
    original = tr.select_risk_subscriptions
    tr.select_risk_subscriptions = lambda db, limit, today=None: list(risk)[:limit]
    try:
        return asyncio.run(tr.run_targeted_reconcile(db, refresh=rec, sleep=_nosleep, pause_seconds=0, **kw))
    finally:
        tr.select_risk_subscriptions = original


def test_enqueue_is_deduplicated_while_live(db_session) -> None:
    assert rq.enqueue_refresh(db_session, "toku", "rq-a", "webhook_failed", NOW) is True
    assert rq.enqueue_refresh(db_session, "toku", "rq-a", "manual", NOW) is False  # ya hay una viva
    assert rq.enqueue_refresh(db_session, "payku", "rq-a", "manual", NOW) is True  # otro canal, otra orden
    assert len(_items(db_session, "rq-a")) == 2
    with pytest.raises(ValueError):
        rq.enqueue_refresh(db_session, "toku", "rq-a", "inventada", NOW)


def test_failed_webhook_enqueues_its_subscription_once(db_session) -> None:
    ev = WebhookEvent(source="toku", event_type="subscription.updated", resource_type="subscription",
                      resource_external_id="rq-sub", subscription_external_id="rq-sub", payload_masked={},
                      dedupe_key=uuid.uuid4().hex + uuid.uuid4().hex, next_attempt_at=NOW - timedelta(seconds=5),
                      received_at=NOW - timedelta(seconds=10))
    db_session.add(ev)
    db_session.flush()
    rec = Recorder(fail={("toku", "rq-sub"): RefreshError("PROVIDER_READ_FAILED")})
    for i in range(settings.webhook_max_attempts):
        asyncio.run(wp.process_pending(db_session, refresh=rec, now=NOW))
        if i < settings.webhook_max_attempts - 1:
            assert _items(db_session, "rq-sub") == []  # solo se encola al agotar los intentos
        db_session.expire_all()
        got = db_session.get(WebhookEvent, ev.id)
        got.next_attempt_at = NOW - timedelta(seconds=1)
        db_session.flush()
    assert db_session.get(WebhookEvent, ev.id).status == "failed"
    items = _items(db_session, "rq-sub")
    assert [(i.source, i.reason, i.state) for i in items] == [("toku", "webhook_failed", "pending")]


def test_reconcile_refreshes_queue_first_and_is_idempotent(db_session) -> None:
    rq.enqueue_refresh(db_session, "toku", "rq-q1", "webhook_failed")
    db_session.commit()
    rec = Recorder()
    summary = _reconcile(db_session, rec, risk=[("toku", "rq-q1"), ("payku", "rq-r1")])
    assert rec.calls == [("toku", "rq-q1"), ("payku", "rq-r1")]  # la cola primero; sin repetir la de la ventana
    assert (summary.selected, summary.queued, summary.refreshed) == (2, 1, 2)
    assert [i.state for i in _items(db_session, "rq-q1")] == ["done"]

    rec2 = Recorder()
    summary2 = _reconcile(db_session, rec2)
    assert rec2.calls == [] and summary2.queued == 0  # una orden `done` no se reprocesa
    assert len(_items(db_session, "rq-q1")) == 1


def test_queue_failures_back_off_then_fail(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "refresh_queue_max_attempts", 2)
    rq.enqueue_refresh(db_session, "toku", "rq-f", "webhook_failed")
    db_session.commit()
    rec = Recorder(fail={("toku", "rq-f"): RefreshError("PROVIDER_READ_FAILED")})
    _reconcile(db_session, rec)
    (item,) = _items(db_session, "rq-f")
    assert (item.state, item.attempts, item.last_error_code) == ("pending", 1, "PROVIDER_READ_FAILED")
    assert item.not_before > datetime.now(UTC)  # backoff: no se toma en la pasada siguiente
    assert rq.claim_due(db_session, 10) == []
    item.not_before = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    _reconcile(db_session, rec)
    (item,) = _items(db_session, "rq-f")
    assert (item.state, item.attempts) == ("failed", 2) and item.finished_at is not None
    assert rq.enqueue_refresh(db_session, "toku", "rq-f", "manual") is True  # tras `failed` se puede volver a pedir


def test_cut_pass_releases_unprocessed_items(db_session) -> None:
    ids = [f"rq-c{i}" for i in range(tr.MAX_CONSECUTIVE_FAILURES + 2)]
    for sid in ids:
        rq.enqueue_refresh(db_session, "toku", sid, "webhook_failed")
    db_session.commit()
    rec = Recorder(fail={("toku", sid): RefreshError("PROVIDER_READ_FAILED") for sid in ids})
    summary = _reconcile(db_session, rec)
    assert summary.skipped_reason == "provider_failing"
    states = {i.subscription_external_id: (i.state, i.attempts) for i in _items(db_session)}
    untouched = [sid for sid in ids if sid not in {c[1] for c in rec.calls}]
    assert untouched and all(states[sid] == ("pending", 0) for sid in untouched)  # sin gastar intento


def test_stale_running_goes_back_to_pending(db_session) -> None:
    rq.enqueue_refresh(db_session, "toku", "rq-s", "manual", NOW)
    db_session.commit()
    (claimed,) = rq.claim_due(db_session, 10, NOW)
    assert claimed.attempts == 1 and rq.claim_due(db_session, 10, NOW) == []  # reclamada: nadie mas la toma
    again = rq.claim_due(db_session, 10, NOW + rq.CLAIM_LEASE + timedelta(seconds=1))
    assert [i.id for i in again] == [claimed.id]
