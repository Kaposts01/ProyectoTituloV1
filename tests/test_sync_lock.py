"""SYNC-O-11 / SYNC-D-06: lock atomico contra ejecuciones simultaneas de sync / ETL.

Cubre el guardian (`app.scheduler.run_lock`) y los cinco puntos de entrada: job nocturno y reintento
(`sync_all_channels`), /etl/full-sync, /etl/core/* e importacion TCH. Usa la base `crm_test` real (el lock es
de PostgreSQL), por eso cada test deja la tabla `etl_runs` como la encontro.
"""

import asyncio
import threading
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.v1.routes import etl as etl_routes
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import Permission, Role, User
from app.models.etl_run import EtlRun
from app.scheduler import run_lock
from app.scheduler.jobs import sync_all
from app.services.rbac import seed_permissions


@pytest.fixture
def clean_runs():
    """Deja `etl_runs` vacia antes y despues (la base de test se recrea por sesion; nadie mas depende de estas filas)."""

    def wipe() -> None:
        db = SessionLocal()
        try:
            db.execute(delete(EtlRun))
            db.commit()
        finally:
            db.close()

    wipe()
    yield
    wipe()


def _running_ids() -> list[uuid.UUID]:
    db = SessionLocal()
    try:
        return list(db.scalars(select(EtlRun.id).where(EtlRun.status == "running")))
    finally:
        db.close()


def _client(monkeypatch, codes: list[str]) -> tuple[TestClient, dict[str, str]]:
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    suffix = uuid.uuid4().hex[:10]
    db = SessionLocal()
    try:
        seed_permissions(db)
        perms = db.scalars(select(Permission).where(Permission.code.in_(codes))).all()
        role = Role(name=f"lock-role-{suffix}", permissions=list(perms))
        db.add_all([role, User(username=f"lock-{suffix}", password_hash=hash_password("pw-lock-test"), roles=[role])])
        db.commit()
    finally:
        db.close()
    client = TestClient(app, base_url="https://testserver")
    login = client.post("/api/v1/auth/login", json={"username": f"lock-{suffix}", "password": "pw-lock-test"})
    assert login.status_code == 200
    return client, {"X-CSRF-Token": login.json()["csrf_token"]}


# --- guardian ------------------------------------------------------------------------------------


def test_two_concurrent_starts_only_one_wins(clean_runs) -> None:
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def attempt() -> None:
        db = SessionLocal()
        try:
            barrier.wait(timeout=10)
            run_lock.start_exclusive_run(db, phase="t")
            outcomes.append("started")
        except run_lock.ActiveRunError:
            outcomes.append("busy")
        finally:
            db.close()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(outcomes) == ["busy", "started"]
    assert len(_running_ids()) == 1


def test_many_concurrent_starts_leave_exactly_one_running(clean_runs) -> None:
    n = 6
    barrier = threading.Barrier(n)
    outcomes: list[str] = []

    def attempt() -> None:
        db = SessionLocal()
        try:
            barrier.wait(timeout=10)
            run_lock.start_exclusive_run(db, phase="t")
            outcomes.append("started")
        except run_lock.ActiveRunError:
            outcomes.append("busy")
        finally:
            db.close()

    threads = [threading.Thread(target=attempt) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert outcomes.count("started") == 1 and outcomes.count("busy") == n - 1
    assert len(_running_ids()) == 1


def test_a_finished_run_does_not_block(clean_runs) -> None:
    db = SessionLocal()
    try:
        first = run_lock.start_exclusive_run(db, phase="t")
        first.status, first.finished_at = "completed", datetime.now(timezone.utc)
        db.commit()
        second = run_lock.start_exclusive_run(db, phase="t")
        assert second.id != first.id and second.status == "running"
    finally:
        db.close()


def test_a_stale_running_run_expires_and_a_fresh_one_blocks(clean_runs, monkeypatch) -> None:
    monkeypatch.setattr(settings, "sync_run_stale_hours", 6)
    db = SessionLocal()
    try:
        fresh = EtlRun(status="running", started_at=datetime.now(timezone.utc) - timedelta(hours=1), phase="x")
        db.add(fresh)
        db.commit()
        with pytest.raises(run_lock.ActiveRunError) as busy:
            run_lock.start_exclusive_run(db, phase="t")
        assert busy.value.run_id == fresh.id

        fresh.started_at = datetime.now(timezone.utc) - timedelta(hours=7)
        db.commit()
        new = run_lock.start_exclusive_run(db, phase="t")
        assert new.status == "running"
        db.refresh(fresh)
        assert fresh.status == "failed" and fresh.finished_at is not None and "abandonada" in fresh.error_message
    finally:
        db.close()


def test_stale_limit_is_configurable(clean_runs, monkeypatch) -> None:
    monkeypatch.setattr(settings, "sync_run_stale_hours", 0.5)
    db = SessionLocal()
    try:
        db.add(EtlRun(status="running", started_at=datetime.now(timezone.utc) - timedelta(hours=1)))
        db.commit()
        assert run_lock.start_exclusive_run(db, phase="t").status == "running"
    finally:
        db.close()


def test_start_exclusive_runs_creates_all_rows_atomically_and_refuses_a_second_batch(clean_runs) -> None:
    db = SessionLocal()
    try:
        runs = run_lock.start_exclusive_runs(db, [{"phase": f"core_{p}"} for p in ("a", "b", "c")])
        assert len(runs) == 3 and len(_running_ids()) == 3
        with pytest.raises(run_lock.ActiveRunError):
            run_lock.start_exclusive_runs(db, [{"phase": "core_d"}])
        assert len(_running_ids()) == 3
    finally:
        db.close()


# --- job nocturno / reintento: sync_all_channels --------------------------------------------------


def _patch_sync_all(monkeypatch, calls: list[str], gate: threading.Event | None = None):
    monkeypatch.setattr(sync_all, "skip_disabled_channel", lambda _c: False)
    monkeypatch.setattr(sync_all, "consolidate_to_centralized", lambda *_a, **_k: 0)

    async def toku(_db, _cb=None):
        calls.append("toku")
        await asyncio.sleep(0.2)  # la corrida sigue `running` mientras el otro intento llega
        return SimpleNamespace(records_processed=1)

    monkeypatch.setattr(sync_all, "sync_toku", toku)


def test_two_simultaneous_nightly_runs_execute_the_sync_once(clean_runs, monkeypatch) -> None:
    calls: list[str] = []
    _patch_sync_all(monkeypatch, calls)

    async def both() -> None:
        await asyncio.gather(
            sync_all.sync_all_channels(channels=["toku"]), sync_all.sync_all_channels(channels=["toku"])
        )

    asyncio.run(both())
    assert calls == ["toku"]
    db = SessionLocal()
    try:
        assert db.scalar(select(EtlRun.status).where(EtlRun.status == "running")) is None
    finally:
        db.close()


def test_sync_all_is_blocked_by_a_core_etl_run_and_skips_silently(clean_runs, monkeypatch) -> None:
    calls: list[str] = []
    _patch_sync_all(monkeypatch, calls)
    db = SessionLocal()
    try:
        db.add(EtlRun(status="running", phase="core_toku"))
        db.commit()
    finally:
        db.close()
    asyncio.run(sync_all.sync_all_channels(channels=["toku"]))
    assert calls == []


def test_sync_all_adopts_the_run_reserved_by_the_endpoint(clean_runs, monkeypatch) -> None:
    calls: list[str] = []
    _patch_sync_all(monkeypatch, calls)
    reserved = uuid.uuid4()
    db = SessionLocal()
    try:
        run_lock.start_exclusive_run(db, id=reserved, phase="starting")
    finally:
        db.close()
    asyncio.run(sync_all.sync_all_channels(str(reserved), ["toku"]))
    assert calls == ["toku"]
    db = SessionLocal()
    try:
        row = db.get(EtlRun, reserved)
        assert row.status == "completed" and db.scalar(select(EtlRun.id).where(EtlRun.id != reserved)) is None
    finally:
        db.close()


# --- /etl/full-sync y /etl/core/* ------------------------------------------------------------------


def _noop_background(monkeypatch) -> None:
    async def noop(*_a, **_k) -> None:
        return None

    monkeypatch.setattr(etl_routes, "_run_full_sync_background", noop)
    monkeypatch.setattr(etl_routes, "_run_core_etl_background", lambda *_a, **_k: None)


def test_full_sync_returns_409_while_another_run_is_active(clean_runs, monkeypatch) -> None:
    _noop_background(monkeypatch)
    client, headers = _client(monkeypatch, ["etl.run"])
    first = client.post("/api/v1/etl/full-sync", json={"providers": ["toku"]}, headers=headers)
    second = client.post("/api/v1/etl/full-sync", json={"providers": ["toku"]}, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 409
    assert len(_running_ids()) == 1


def test_core_etl_endpoints_are_blocked_by_an_active_run(clean_runs, monkeypatch) -> None:
    _noop_background(monkeypatch)
    client, headers = _client(monkeypatch, ["etl.run"])
    db = SessionLocal()
    try:
        db.add(EtlRun(status="running", phase="sync_toku"))
        db.commit()
    finally:
        db.close()
    assert client.post("/api/v1/etl/core/toku", headers=headers).status_code == 409
    assert client.post("/api/v1/etl/core/all", headers=headers).status_code == 409
    assert len(_running_ids()) == 1  # no se crearon filas nuevas


def test_core_all_reserves_its_four_runs_at_once_and_then_blocks_everything(clean_runs, monkeypatch) -> None:
    _noop_background(monkeypatch)
    client, headers = _client(monkeypatch, ["etl.run"])
    first = client.post("/api/v1/etl/core/all", headers=headers)
    assert first.status_code == 200 and len(first.json()["run_ids"]) == 4
    assert len(_running_ids()) == 4
    assert client.post("/api/v1/etl/core/payku", headers=headers).status_code == 409


def test_concurrent_core_requests_only_one_is_accepted(clean_runs, monkeypatch) -> None:
    _noop_background(monkeypatch)
    client, headers = _client(monkeypatch, ["etl.run"])
    barrier = threading.Barrier(2)
    codes: list[int] = []

    def hit() -> None:
        barrier.wait(timeout=10)
        codes.append(client.post("/api/v1/etl/core/toku", headers=headers).status_code)

    threads = [threading.Thread(target=hit) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(codes) == [200, 409]
    assert len(_running_ids()) == 1


def test_scheduler_trigger_reserves_the_run_atomically_and_second_request_is_409(clean_runs, monkeypatch) -> None:
    from app.api.v1.routes import scheduler as sched_routes

    ran: list = []

    async def fake_sync(run_id, channels):
        ran.append(run_id)

    monkeypatch.setattr(sched_routes, "sync_all_channels", fake_sync)
    monkeypatch.setattr(sched_routes, "get_scheduler", lambda: SimpleNamespace(get_job=lambda _id: object()))
    client, headers = _client(monkeypatch, ["sync.run"])
    url = "/api/v1/scheduler/jobs/sync_all_channels/run"
    first = client.post(url, json={}, headers=headers)
    second = client.post(url, json={}, headers=headers)
    assert first.status_code == 202 and second.status_code == 409
    assert ran == [first.json()["run_id"]]  # el run_id devuelto es el de la fila reservada
    assert [str(i) for i in _running_ids()] == [first.json()["run_id"]]
