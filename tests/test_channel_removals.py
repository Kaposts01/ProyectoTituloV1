"""SYNC-D-13: bajas por desaparicion con `last_seen_at`. Datos sinteticos; nada de red ni de proveedores."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Self

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.models.source_record import SourceRecord
from app.models.status_change import StatusChangeEvent
from app.models.sync_run import SyncRun  # noqa: F401
from app.models.toku_channel import TokuSubscription
from app.models.vp import VpSubscription
from app.services import alerts, channel_removals, read_only_provider_sync
from app.services.channel_removals import (
    GUARD_RESOURCE,
    GUARD_SOURCE,
    STATUS_ABORTED,
    STATUS_APPLIED,
    STATUS_DISABLED,
    STATUS_NOTHING,
    STATUS_PARTIAL,
    detect_removals,
)
from app.services.channel_store import store_toku_resources, store_vp_resources

PFX = "rm13-"


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
def enabled(monkeypatch):
    """Bandera encendida y umbral holgado: las filas de otros tests en la base compartida no deben abortar."""
    monkeypatch.setattr(settings, "sync_removal_detection_enabled", True)
    monkeypatch.setattr(settings, "sync_removal_max_ratio", 1.0)
    monkeypatch.setattr(settings, "sync_removal_max_count", 1_000_000)


def _toku(ext: str, status: str = "active") -> dict:
    return {"id": ext, "status": status, "customer": {"id": f"{PFX}cus"}}


def _tk_rows(db: Session) -> dict[str, TokuSubscription]:
    db.expire_all()
    return {r.external_id: r for r in db.scalars(
        select(TokuSubscription).where(TokuSubscription.external_id.like(f"{PFX}%")))}


def _removed_events(db: Session, source: str) -> list[StatusChangeEvent]:
    return list(db.scalars(select(StatusChangeEvent).where(
        StatusChangeEvent.event_kind == "removed", StatusChangeEvent.source == source,
        StatusChangeEvent.external_id.like(f"{PFX}%"))))


def _guard(db: Session, source: str) -> SourceRecord | None:
    return db.scalar(select(SourceRecord).where(
        SourceRecord.source == GUARD_SOURCE, SourceRecord.resource_type == GUARD_RESOURCE,
        SourceRecord.external_id == source))


def _two_syncs(db: Session) -> datetime:
    """Primera sync con a, b, c; segunda (completa) solo con a, b. Devuelve el inicio de la segunda lectura."""
    store_toku_resources(db, "subscription", [_toku(f"{PFX}a"), _toku(f"{PFX}b"), _toku(f"{PFX}c", "paused")])
    started = datetime.now(UTC) + timedelta(milliseconds=1)
    store_toku_resources(db, "subscription", [_toku(f"{PFX}a"), _toku(f"{PFX}b")])
    return started - timedelta(milliseconds=1)


def test_upsert_sets_last_seen_and_clears_removed(db_session) -> None:
    store_toku_resources(db_session, "subscription", [_toku(f"{PFX}x")])
    row = _tk_rows(db_session)[f"{PFX}x"]
    assert row.last_seen_at is not None and row.removed_at is None
    row.removed_at = datetime.now(UTC)
    db_session.commit()
    store_toku_resources(db_session, "subscription", [_toku(f"{PFX}x")])
    assert _tk_rows(db_session)[f"{PFX}x"].removed_at is None  # reaparecio: se limpia la baja


def test_flag_off_does_nothing(db_session) -> None:
    started = _two_syncs(db_session)
    outcome = detect_removals(db_session, "toku", seen_since=started, complete=True)
    assert outcome.status == STATUS_DISABLED
    assert all(r.removed_at is None for r in _tk_rows(db_session).values())


def test_partial_sync_never_marks(db_session, enabled) -> None:
    started = _two_syncs(db_session)
    outcome = detect_removals(db_session, "toku", seen_since=started, complete=False)
    assert outcome.status == STATUS_PARTIAL
    assert all(r.removed_at is None for r in _tk_rows(db_session).values())
    assert _removed_events(db_session, "toku") == []


def test_complete_sync_marks_missing_and_is_idempotent(db_session, enabled) -> None:
    started = _two_syncs(db_session)
    outcome = detect_removals(db_session, "toku", seen_since=started, complete=True)
    assert outcome.status == STATUS_APPLIED
    rows = _tk_rows(db_session)
    assert rows[f"{PFX}c"].removed_at is not None
    assert rows[f"{PFX}a"].removed_at is None and rows[f"{PFX}b"].removed_at is None
    assert rows[f"{PFX}c"].status == "paused"  # el estado no se toca (decision de negocio pendiente)
    events = _removed_events(db_session, "toku")
    assert [(e.external_id, e.from_value, e.to_value, e.entity_type) for e in events] == [
        (f"{PFX}c", "paused", None, "subscription")]

    again = detect_removals(db_session, "toku", seen_since=started, complete=True)
    assert again.status == STATUS_NOTHING and again.marked == 0
    assert len(_removed_events(db_session, "toku")) == 1  # ya marcada: no vuelve a emitir


def test_threshold_exceeded_aborts_without_writing_and_alerts(db_session, enabled, monkeypatch) -> None:
    monkeypatch.setattr(settings, "sync_removal_max_count", 0)
    started = _two_syncs(db_session)
    outcome = detect_removals(db_session, "toku", seen_since=started, complete=True)
    assert outcome.status == STATUS_ABORTED and outcome.marked == 0 and outcome.missing >= 1
    assert all(r.removed_at is None for r in _tk_rows(db_session).values())
    assert _removed_events(db_session, "toku") == []
    guard = _guard(db_session, "toku")
    assert guard is not None and guard.payload["missing"] == outcome.missing

    conditions = [c for c in alerts.evaluate_conditions(db_session, datetime.now(UTC))
                  if c.key == "removal_aborted:toku"]
    assert len(conditions) == 1 and PFX not in conditions[0].text  # solo conteos, sin ids
    assert alerts._describe_key("removal_aborted:toku")[0] == "Toku"

    # Una corrida posterior que no aborta borra la marca (la alerta se recupera).
    monkeypatch.setattr(settings, "sync_removal_max_count", 1_000_000)
    assert detect_removals(db_session, "toku", seen_since=started, complete=True).status == STATUS_APPLIED
    assert _guard(db_session, "toku") is None


def test_ratio_threshold() -> None:
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(settings, "sync_removal_max_ratio", 0.05)
        mp.setattr(settings, "sync_removal_max_count", 100)
        assert channel_removals._exceeds_threshold(5, 100) is False
        assert channel_removals._exceeds_threshold(6, 100) is True
        assert channel_removals._exceeds_threshold(101, 1_000_000) is True
        assert channel_removals._exceeds_threshold(100, 0) is False  # sin conocidas no hay proporcion; manda la cantidad


def test_vp_removals_are_scoped_by_platform(db_session, enabled) -> None:
    def sub(ext, plan):
        return {"id": ext, "plan_id": plan, "client": {"social_id": f"{PFX}{plan}"}, "status": "CANCELADA"}

    store_vp_resources(db_session, "subscription", [sub(f"{PFX}v1", "p1")], platform="virtualpos1")
    store_vp_resources(db_session, "subscription", [sub(f"{PFX}v2", "p2")], platform="virtualpos2")
    started = datetime.now(UTC) + timedelta(seconds=1)
    detect_removals(db_session, "virtualpos2", seen_since=started, complete=True)
    db_session.expire_all()
    rows = {r.external_id: r for r in db_session.scalars(
        select(VpSubscription).where(VpSubscription.external_id.like(f"{PFX}%")))}
    assert rows[f"{PFX}v2"].removed_at is not None
    assert rows[f"{PFX}v1"].removed_at is None  # otra cuenta: no se toca


def test_vp_row_skipped_by_active_duplicate_still_counts_as_seen(db_session) -> None:
    def sub(ext, status, date):
        return {"id": ext, "plan_id": f"{PFX}dup", "client": {"social_id": f"{PFX}rut"}, "status": status,
                "suscription_date": date}

    store_vp_resources(db_session, "subscription", [sub(f"{PFX}old", "ACTIVA", "2026-01-01"),
                                                    sub(f"{PFX}new", "CANCELADA", "2026-06-01")], platform="virtualpos1")
    before = datetime.now(UTC)
    skipped: list[str] = []
    store_vp_resources(db_session, "subscription", [sub(f"{PFX}old", "ACTIVA", "2026-01-01"),
                                                    sub(f"{PFX}new", "ACTIVA", "2026-06-01")],
                       platform="virtualpos1", skipped_subscriptions=skipped)
    db_session.expire_all()
    rows = {r.external_id: r for r in db_session.scalars(
        select(VpSubscription).where(VpSubscription.external_id.like(f"{PFX}%")))}
    assert skipped == [f"{PFX}new"]  # la mas reciente choca con la activa existente
    omitted = rows[f"{PFX}new"]
    assert omitted.status == "CANCELADA"  # el upsert no la toco...
    assert omitted.last_seen_at >= before  # omitida por duplicado activo, pero vista: no es baja


# ----------------------------- enganche en la sync generica (Toku) -----------------------------


class _FakeClient:
    def __init__(self, pages: list[dict]) -> None:
        self.pages = pages

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc) -> None:
        return None


def _run_generic(db, monkeypatch, response: dict, page_size: int = 100) -> list[dict]:
    calls: list[dict] = []
    monkeypatch.setattr(read_only_provider_sync, "detect_removals",
                        lambda db, source, **kw: calls.append({"source": source, **kw}))

    async def read(client, page):
        return response

    asyncio.run(read_only_provider_sync.sync_read_only_provider(
        db, source="toku", client_factory=lambda: _FakeClient([]), secrets=(),
        resources=[("subscription", page_size, True, read)], channel_store_fn=store_toku_resources))
    return calls


def test_generic_sync_complete_read_calls_detection(db_session, monkeypatch) -> None:
    calls = _run_generic(db_session, monkeypatch, {"data": [_toku(f"{PFX}g1")], "next_cursor": None})
    assert len(calls) == 1 and calls[0]["source"] == "toku" and calls[0]["complete"] is True


def test_generic_sync_truncated_read_is_partial(db_session, monkeypatch) -> None:
    monkeypatch.setattr(read_only_provider_sync, "_MAX_PAGES", 1)
    calls = _run_generic(db_session, monkeypatch, {"data": [_toku(f"{PFX}g2")], "next_cursor": "more"})
    assert len(calls) == 1 and calls[0]["complete"] is False
