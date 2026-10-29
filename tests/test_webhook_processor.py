"""RT-05 / RT-07: procesador asincrono de `webhook_events`. Sin red: `refresh_subscription` se reemplaza por un falso o se
usa el real con los clientes falsos de MGT-06. Datos 100% sinteticos."""

import asyncio
import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.models.crm import Subscription
from app.models.payku_channel import PaykuTransaction
from app.models.status_change import StatusChangeEvent
from app.models.toku_channel import (
    TokuInvoice,
    TokuPaymentMethod,
    TokuSubscription,
    TokuTransaction,
)
from app.models.vp import VpCharge, VpPayment, VpSubscription
from app.models.webhook_event import WebhookEvent
from app.services import subscription_refresh as sr
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
def _empty_committed_queue():
    """Filas confirmadas por otros tests (receptores) no deben colarse en el lote de estos."""
    with SessionLocal() as s:
        s.execute(delete(WebhookEvent))
        s.commit()
    yield


class Recorder:
    """refresh falso: registra las llamadas; `fail` = {(source, id): excepcion}."""

    def __init__(self, fail: dict | None = None) -> None:
        self.calls: list[tuple[str, str, uuid.UUID]] = []
        self.fail = fail or {}

    async def __call__(self, db, source, external_id, *, run_id=None):
        self.calls.append((source, external_id, run_id))
        exc = self.fail.get((source, external_id))
        if exc is not None:
            raise exc
        return object()


def _add(db, source, event_type, resource=None, sub=None, payload=None, **over) -> WebhookEvent:
    fields = {"next_attempt_at": NOW - timedelta(seconds=5), "received_at": NOW - timedelta(seconds=10), **over}
    ev = WebhookEvent(
        source=source, event_type=event_type, resource_type=event_type.split(".")[0],
        resource_external_id=resource, subscription_external_id=sub, payload_masked=payload or {},
        dedupe_key=uuid.uuid4().hex + uuid.uuid4().hex, **fields)
    db.add(ev)
    db.flush()
    return ev


def _run(db, refresh, **kw):
    return asyncio.run(wp.process_pending(db, refresh=refresh, now=NOW, **kw))


def _reload(db, ev) -> WebhookEvent:
    db.expire_all()
    return db.get(WebhookEvent, ev.id)


# ----------------------------- reglas por evento: Toku -----------------------------


@pytest.mark.parametrize("event_type", ["subscription.created", "subscription.updated", "subscription.deleted"])
def test_toku_subscription_events_refresh_that_subscription(db_session, event_type) -> None:
    ev = _add(db_session, "toku", event_type, resource="sub_a", sub="sub_a")
    rec = Recorder()
    summary = _run(db_session, rec)
    assert [(c[0], c[1]) for c in rec.calls] == [("toku", "sub_a")]
    assert rec.calls[0][2] is not None  # run_id propio
    got = _reload(db_session, ev)
    assert (got.status, got.attempts, got.last_error_code) == ("done", 1, None) and got.processed_at is not None
    assert (summary.claimed, summary.done, summary.refreshes) == (1, 1, 1)


def test_toku_invoice_paid_resolves_subscription_from_local_invoice(db_session) -> None:
    db_session.add(TokuInvoice(external_id="in_1", subscription_id="sub_b", raw_payload={}))
    ev = _add(db_session, "toku", "invoice.paid", resource="in_1")
    rec = Recorder()
    _run(db_session, rec)
    assert [(c[0], c[1]) for c in rec.calls] == [("toku", "sub_b")]
    assert _reload(db_session, ev).status == "done"


def test_toku_transaction_success_uses_subscription_named_in_payload(db_session) -> None:
    _add(db_session, "toku", "transaction.success", resource="tx_1", sub="sub_c")
    rec = Recorder()
    _run(db_session, rec)
    assert [(c[0], c[1]) for c in rec.calls] == [("toku", "sub_c")]


def test_toku_transaction_failed_resolves_through_invoice_in_payload(db_session) -> None:
    db_session.add(TokuInvoice(external_id="in_9", subscription_id="sub_d", raw_payload={}))
    _add(db_session, "toku", "transaction.failed", resource="tx_2", payload={"transaction": {"invoice_id": "in_9"}})
    rec = Recorder()
    _run(db_session, rec)
    assert [(c[0], c[1]) for c in rec.calls] == [("toku", "sub_d")]


def test_toku_transaction_resolves_through_payment_method_customer(db_session) -> None:
    db_session.add_all([
        TokuTransaction(external_id="tx_3", payment_method_id="pm_1", raw_payload={}),
        TokuPaymentMethod(external_id="pm_1", customer_id="cus_1", raw_payload={}),
        TokuSubscription(external_id="sub_e", customer_id="cus_1", status="ACTIVE", raw_payload={}),
    ])
    _add(db_session, "toku", "transaction.status_update", resource="tx_3")
    rec = Recorder()
    _run(db_session, rec)
    assert [(c[0], c[1]) for c in rec.calls] == [("toku", "sub_e")]


def test_toku_payment_method_event_refreshes_all_customer_subscriptions(db_session) -> None:
    db_session.add_all([
        TokuPaymentMethod(external_id="pm_2", customer_id="cus_2", raw_payload={}),
        TokuSubscription(external_id="sub_f1", customer_id="cus_2", raw_payload={}),
        TokuSubscription(external_id="sub_f2", customer_id="cus_2", raw_payload={}),
    ])
    ev = _add(db_session, "toku", "payment_method.status_update", resource="pm_2")
    rec = Recorder()
    _run(db_session, rec)
    assert sorted(c[1] for c in rec.calls) == ["sub_f1", "sub_f2"]
    assert _reload(db_session, ev).status == "done"


@pytest.mark.parametrize(("event_type", "resource", "sub", "code"), [
    ("transaction.bulk_success", "tx_x", None, "BULK_EVENT"),
    ("transaction.bulk_failed", "tx_x", None, "BULK_EVENT"),
    ("customer.created", "cus_x", None, "UNKNOWN_EVENT"),
    ("subscription.updated", None, None, "NO_RESOURCE"),
    ("invoice.paid", "in_desconocida", None, "NO_RESOURCE"),
    ("transaction.success", "tx_sin_datos", None, "NO_RESOURCE"),
    ("payment_method.deleted", "pm_desconocido", None, "NO_RESOURCE"),
])
def test_toku_unknown_or_unresolvable_events_are_ignored(db_session, event_type, resource, sub, code) -> None:
    ev = _add(db_session, "toku", event_type, resource=resource, sub=sub)
    rec = Recorder()
    summary = _run(db_session, rec)
    got = _reload(db_session, ev)
    assert (got.status, got.last_error_code) == ("ignored", code) and rec.calls == []
    assert summary.ignored == 1


# ----------------------------- reglas por evento: VirtualPOS y Payku -----------------------------


def test_virtualpos_payment_resolves_subscription_by_uuid(db_session) -> None:
    db_session.add_all([
        VpPayment(platform="virtualpos2", external_id="pay-uuid-1", charge_external_id="ch-1", raw_payload={}),
        VpCharge(platform="virtualpos2", external_id="ch-1", subscription_external_id="vp-sub-1", raw_payload={}),
    ])
    ev = _add(db_session, "virtualpos", "payment", resource="pay-uuid-1")
    rec = Recorder()
    _run(db_session, rec)
    assert [(c[0], c[1]) for c in rec.calls] == [("virtualpos2", "vp-sub-1")]
    assert _reload(db_session, ev).status == "done"


def test_virtualpos_subscription_callback_and_unknowns(db_session) -> None:
    db_session.add(VpSubscription(platform="virtualpos1", external_id="vp-sub-2", status="ACTIVA", raw_payload={}))
    sub_ev = _add(db_session, "virtualpos", "subscription", resource="vp-sub-2", sub="vp-sub-2")
    unknown = _add(db_session, "virtualpos", "payment", resource="no-existe")
    payout = _add(db_session, "virtualpos", "payout", resource="po_1")
    rec = Recorder()
    _run(db_session, rec)
    assert [(c[0], c[1]) for c in rec.calls] == [("virtualpos1", "vp-sub-2")]
    assert _reload(db_session, sub_ev).status == "done"
    assert (_reload(db_session, unknown).status, _reload(db_session, unknown).last_error_code) == ("ignored", "NO_RESOURCE")
    assert (_reload(db_session, payout).status, _reload(db_session, payout).last_error_code) == ("ignored", "IGNORED_KIND")


def test_payku_rules(db_session) -> None:
    db_session.add(PaykuTransaction(external_id="trx-1", subscription_id="su-from-db", raw_payload={}))
    sub = _add(db_session, "payku", "subscription", resource="su-1", sub="su-1")
    pay_named = _add(db_session, "payku", "payment", resource="trx-9", sub="su-2")
    pay_db = _add(db_session, "payku", "transaction", resource="trx-1")
    nullif = _add(db_session, "payku", "nullification", resource="trx-1")
    lost = _add(db_session, "payku", "payment", resource="trx-sin-suscripcion")
    payout = _add(db_session, "payku", "payout", resource="po-1")
    rec = Recorder()
    _run(db_session, rec)
    assert sorted((c[0], c[1]) for c in rec.calls) == [("payku", "su-1"), ("payku", "su-2"), ("payku", "su-from-db")]
    for ev in (sub, pay_named, pay_db, nullif):
        assert _reload(db_session, ev).status == "done"
    assert _reload(db_session, lost).last_error_code == "NO_RESOURCE"
    assert _reload(db_session, payout).last_error_code == "IGNORED_KIND"


def test_unknown_source_is_ignored(db_session) -> None:
    ev = _add(db_session, "otro", "x.y", resource="r")
    _run(db_session, Recorder())
    assert _reload(db_session, ev).status == "ignored"


# ----------------------------- coalescencia y fallo parcial -----------------------------


def test_events_of_same_subscription_share_one_refresh(db_session) -> None:
    evs = [_add(db_session, "toku", t, resource="sub_g", sub="sub_g")
           for t in ("subscription.updated", "transaction.success", "invoice.paid")]
    rec = Recorder()
    summary = _run(db_session, rec)
    assert len(rec.calls) == 1 and summary.done == 3
    assert all(_reload(db_session, e).status == "done" for e in evs)


def test_partial_failure_does_not_block_the_rest_of_the_batch(db_session) -> None:
    ok = _add(db_session, "toku", "subscription.updated", resource="sub_ok", sub="sub_ok")
    bad = _add(db_session, "toku", "subscription.updated", resource="sub_bad", sub="sub_bad")
    rec = Recorder(fail={("toku", "sub_bad"): RefreshError("PROVIDER_READ_FAILED")})
    summary = _run(db_session, rec)
    assert _reload(db_session, ok).status == "done"
    got = _reload(db_session, bad)
    assert (got.status, got.last_error_code, got.attempts) == ("pending", "PROVIDER_READ_FAILED", 1)
    assert got.next_attempt_at > datetime.now(UTC) + timedelta(seconds=20)
    assert (summary.done, summary.retried, summary.failed) == (1, 1, 0)


def test_event_with_several_targets_is_done_only_if_all_succeed(db_session) -> None:
    db_session.add_all([
        TokuPaymentMethod(external_id="pm_3", customer_id="cus_3", raw_payload={}),
        TokuSubscription(external_id="sub_h1", customer_id="cus_3", raw_payload={}),
        TokuSubscription(external_id="sub_h2", customer_id="cus_3", raw_payload={}),
    ])
    ev = _add(db_session, "toku", "payment_method.updated", resource="pm_3")
    rec = Recorder(fail={("toku", "sub_h2"): RefreshError("LOCAL_WRITE_FAILED")})
    _run(db_session, rec)
    got = _reload(db_session, ev)
    assert (got.status, got.last_error_code) == ("pending", "LOCAL_WRITE_FAILED")


# ----------------------------- backoff y reintentos -----------------------------


def test_backoff_is_exponential_and_capped(monkeypatch) -> None:
    monkeypatch.setattr(settings, "webhook_backoff_base_seconds", 30)
    assert [wp.backoff_seconds(n) for n in (1, 2, 3, 4, 5)] == [30, 60, 120, 240, 480]
    assert wp.backoff_seconds(20) == 3600


def test_five_failures_end_in_failed_with_fixed_code(db_session) -> None:
    ev = _add(db_session, "toku", "subscription.updated", resource="sub_i", sub="sub_i")
    rec = Recorder(fail={("toku", "sub_i"): RefreshError("PROVIDER_READ_FAILED")})
    states = []
    for _ in range(5):
        _run(db_session, rec)
        got = _reload(db_session, ev)
        states.append((got.status, got.attempts))
        got.next_attempt_at = NOW - timedelta(seconds=1)  # el reloj avanza: vence el backoff
        db_session.flush()
    assert states == [("pending", 1), ("pending", 2), ("pending", 3), ("pending", 4), ("failed", 5)]
    got = _reload(db_session, ev)
    assert got.last_error_code == "PROVIDER_READ_FAILED" and got.processed_at is not None
    assert len(rec.calls) == 5
    _run(db_session, rec)  # un evento `failed` no se vuelve a tomar
    assert len(rec.calls) == 5


def test_event_not_due_yet_is_not_claimed(db_session) -> None:
    _add(db_session, "toku", "subscription.updated", resource="sub_j", sub="sub_j",
         next_attempt_at=NOW + timedelta(minutes=5))
    rec = Recorder()
    assert _run(db_session, rec).claimed == 0 and rec.calls == []


def test_unexpected_exception_stores_only_a_fixed_code(db_session) -> None:
    ev = _add(db_session, "toku", "subscription.updated", resource="sub_k", sub="sub_k")
    rec = Recorder(fail={("toku", "sub_k"): RuntimeError("detalle del proveedor con texto libre y datos")})
    _run(db_session, rec)
    got = _reload(db_session, ev)
    assert got.last_error_code == "UNEXPECTED"
    assert "proveedor" not in (got.last_error_code or "")


# ----------------------------- subscription.deleted = baja -----------------------------


class _Resp404:
    status_code = 404


class _Http404(Exception):
    response = _Resp404()


def _refresh_error_from_404() -> RefreshError:
    try:
        raise _Http404()
    except _Http404 as exc:
        err = RefreshError("PROVIDER_READ_FAILED")
        err.__cause__ = exc
        return err


def _seed_toku_sub(db, sid: str) -> None:
    db.add(TokuSubscription(external_id=sid, status="ACTIVE", amount="5000", raw_payload={}))
    db.add(Subscription(source="toku", external_id=sid, status="ACTIVE", amount="5000", raw_payload={}))
    db.flush()


def _status_events(db, sid: str):
    return list(db.scalars(select(StatusChangeEvent).where(
        StatusChangeEvent.entity_type == "subscription", StatusChangeEvent.external_id == sid)))


def test_toku_deleted_confirmed_by_404_marks_baja_once(db_session) -> None:
    _seed_toku_sub(db_session, "sub_del")
    ev = _add(db_session, "toku", "subscription.deleted", resource="sub_del", sub="sub_del")
    rec = Recorder(fail={("toku", "sub_del"): _refresh_error_from_404()})
    _run(db_session, rec)
    assert _reload(db_session, ev).status == "done"
    db_session.expire_all()
    assert db_session.scalar(select(Subscription.status).where(Subscription.external_id == "sub_del")) == "deleted"
    assert db_session.scalar(select(TokuSubscription.status).where(TokuSubscription.external_id == "sub_del")) == "deleted"
    events = _status_events(db_session, "sub_del")
    assert [(e.event_kind, e.from_value, e.to_value, e.is_baseline) for e in events] == [
        ("status_changed", "ACTIVE", "deleted", False)]
    assert events[0].run_id is not None
    # Un segundo aviso identico no duplica el evento de cambio.
    _add(db_session, "toku", "subscription.deleted", resource="sub_del", sub="sub_del")
    _run(db_session, rec)
    assert len(_status_events(db_session, "sub_del")) == 1


def test_toku_deleted_with_transient_failure_is_retried_not_marked(db_session) -> None:
    _seed_toku_sub(db_session, "sub_del2")
    ev = _add(db_session, "toku", "subscription.deleted", resource="sub_del2", sub="sub_del2")
    rec = Recorder(fail={("toku", "sub_del2"): RefreshError("PROVIDER_READ_FAILED")})  # sin 404 de causa
    _run(db_session, rec)
    assert _reload(db_session, ev).status == "pending"
    assert db_session.scalar(select(Subscription.status).where(Subscription.external_id == "sub_del2")) == "ACTIVE"


def test_404_on_non_deleted_event_is_not_a_baja(db_session) -> None:
    _seed_toku_sub(db_session, "sub_upd")
    ev = _add(db_session, "toku", "subscription.updated", resource="sub_upd", sub="sub_upd")
    _run(db_session, Recorder(fail={("toku", "sub_upd"): _refresh_error_from_404()}))
    assert _reload(db_session, ev).status == "pending"
    assert db_session.scalar(select(Subscription.status).where(Subscription.external_id == "sub_upd")) == "ACTIVE"


# ----------------------------- integracion con refresh_subscription real (clientes falsos) -----------------------------


STATE: dict = {}


class _FakeTokuClient:
    def __init__(self, *_: object, **__: object) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get_subscription(self, subscription_id):
        return STATE["sub"]

    async def list_subscription_invoices(self, subscription_id, general_statuses=None, page_size=100):
        return {"invoices": [dict(i) for i in STATE["invoices"]]}


def test_real_refresh_writes_status_events_with_own_run_id_and_is_idempotent(db_session, monkeypatch) -> None:
    monkeypatch.setattr(sr, "TokuClient", _FakeTokuClient)
    _seed_toku_sub(db_session, "sub_rt")
    db_session.commit()
    STATE["sub"] = {"subscription": {"id": "sub_rt", "status": "CANCELLED", "amount": 5000}}
    STATE["invoices"] = [{"id": "sub_rt-in1", "status": "UNPAID", "general_status": "unpaid", "amount": 5000}]

    first = _add(db_session, "toku", "subscription.updated", resource="sub_rt", sub="sub_rt")
    summary = asyncio.run(wp.process_pending(db_session, now=NOW))
    assert (summary.done, summary.failed) == (1, 0)
    assert _reload(db_session, first).status == "done"
    changes = [e for e in _status_events(db_session, "sub_rt") if e.event_kind == "status_changed"]
    assert [(e.from_value, e.to_value) for e in changes] == [("ACTIVE", "CANCELLED")]
    assert changes[0].run_id is not None and changes[0].is_baseline is False

    n = db_session.scalar(select(func.count()).select_from(StatusChangeEvent).where(
        StatusChangeEvent.subscription_external_id == "sub_rt"))
    second = _add(db_session, "toku", "invoice.paid", resource="sub_rt-in1", sub="sub_rt")  # reproceso: mismo estado remoto
    asyncio.run(wp.process_pending(db_session, now=NOW))
    assert _reload(db_session, second).status == "done"
    assert db_session.scalar(select(func.count()).select_from(StatusChangeEvent).where(
        StatusChangeEvent.subscription_external_id == "sub_rt")) == n


# ----------------------------- recuperacion de `processing` abandonado -----------------------------


def test_stale_processing_goes_back_to_pending_or_failed(db_session) -> None:
    old = NOW - timedelta(minutes=settings.webhook_processing_stale_minutes + 5)
    again = _add(db_session, "toku", "subscription.updated", resource="s1", sub="s1",
                 status="processing", locked_at=old, attempts=1)
    spent = _add(db_session, "toku", "subscription.updated", resource="s2", sub="s2",
                 status="processing", locked_at=old, attempts=settings.webhook_max_attempts)
    fresh = _add(db_session, "toku", "subscription.updated", resource="s3", sub="s3",
                 status="processing", locked_at=NOW - timedelta(minutes=1), attempts=1)
    rec = Recorder()
    _run(db_session, rec)
    assert [c[1] for c in rec.calls] == ["s1"]
    assert _reload(db_session, again).attempts == 2 and _reload(db_session, again).status == "done"
    assert (_reload(db_session, spent).status, _reload(db_session, spent).last_error_code) == ("failed", "STALE_PROCESSING")
    assert _reload(db_session, fresh).status == "processing"


# ----------------------------- concurrencia (sesiones reales con commit) -----------------------------


@pytest.fixture
def real_queue():
    def wipe():
        with SessionLocal() as s:
            s.execute(delete(WebhookEvent))
            s.commit()

    wipe()
    yield
    wipe()


def _commit_events(n: int) -> list[uuid.UUID]:
    with SessionLocal() as s:
        evs = [WebhookEvent(
            source="toku", event_type="subscription.updated", resource_type="subscription",
            resource_external_id=f"sub_c{i}", subscription_external_id=f"sub_c{i}", payload_masked={},
            dedupe_key=uuid.uuid4().hex + uuid.uuid4().hex, next_attempt_at=datetime.now(UTC) - timedelta(seconds=5))
            for i in range(n)]
        s.add_all(evs)
        s.commit()
        return [e.id for e in evs]


def test_skip_locked_worker_does_not_take_rows_locked_by_another(real_queue) -> None:
    _commit_events(3)
    a, b = SessionLocal(), SessionLocal()
    try:
        locked = list(a.scalars(wp.select_due_events(a, 2, datetime.now(UTC))))  # A bloquea 2 filas sin confirmar
        assert len(locked) == 2
        claimed = wp.claim_events(b, 10)
        assert len(claimed) == 1 and claimed[0].id not in {r.id for r in locked}
    finally:
        a.rollback()
        a.close()
        b.close()


def test_two_workers_never_process_the_same_event(real_queue) -> None:
    ids = _commit_events(24)
    calls: list[str] = []
    lock = threading.Lock()

    async def fake_refresh(db, source, external_id, *, run_id=None):
        await asyncio.sleep(0.01)
        with lock:
            calls.append(external_id)

    def worker():
        async def loop():
            db = SessionLocal()
            try:
                while (await wp.process_pending(db, limit=5, refresh=fake_refresh)).claimed:
                    pass
            finally:
                db.close()
        asyncio.run(loop())

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(calls) == sorted(f"sub_c{i}" for i in range(24))  # cada suscripcion exactamente una vez
    with SessionLocal() as s:
        rows = list(s.scalars(select(WebhookEvent).where(WebhookEvent.id.in_(ids))))
    assert len(rows) == 24 and all(r.status == "done" and r.attempts == 1 for r in rows)


# ----------------------------- job del scheduler -----------------------------


def test_job_does_nothing_while_flag_is_off_and_drains_when_on(real_queue, monkeypatch) -> None:
    from app.scheduler.jobs.webhook_jobs import process_webhook_queue

    (event_id,) = _commit_events(1)
    rec = Recorder()
    monkeypatch.setattr(wp, "refresh_subscription", rec)
    monkeypatch.setattr(settings, "webhook_processor_enabled", False)
    asyncio.run(process_webhook_queue())
    assert rec.calls == []
    with SessionLocal() as s:
        assert s.get(WebhookEvent, event_id).status == "pending"
    monkeypatch.setattr(settings, "webhook_processor_enabled", True)
    asyncio.run(process_webhook_queue())
    assert len(rec.calls) == 1
    with SessionLocal() as s:
        assert s.get(WebhookEvent, event_id).status == "done"


def test_processor_job_is_registered_every_minute() -> None:
    from app.scheduler.engine import JOB_WEBHOOK_PROCESSOR, register_jobs

    class FakeScheduler:
        def __init__(self) -> None:
            self.jobs: dict[str, dict] = {}

        def get_job(self, _id):
            return None

        def add_job(self, func, **kw):
            self.jobs[kw["id"]] = {"func": func, **kw}

    sched = FakeScheduler()
    register_jobs(sched)
    job = sched.jobs[JOB_WEBHOOK_PROCESSOR]
    assert job["trigger"] == "interval" and job["minutes"] == 1
    assert job["func"].__name__ == "process_webhook_queue"
