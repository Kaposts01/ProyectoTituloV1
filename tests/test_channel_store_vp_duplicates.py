"""store_vp_resources / sync_virtualpos resistentes a duplicados activos (uq_vp_sub_active_plan_client)."""
import asyncio
import logging
from typing import Self

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.sync_run import SyncRun  # noqa: F401
from app.models.vp import VpSubscription
from app.models.write_run import WriteRun  # noqa: F401
from app.services import virtualpos_sync
from app.services.channel_store import store_vp_resources

RUT = "11111111-1"


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


def _sub(ext: str, date: str, plan: str = "dup-plan", rut: str = RUT, status: str = "ACTIVA") -> dict:
    return {"id": ext, "plan_id": plan, "client": {"social_id": rut}, "status": status, "suscription_date": date}


def _ids(db: Session, prefix: str = "dup-") -> set[str]:
    rows = db.scalars(select(VpSubscription.external_id).where(VpSubscription.external_id.like(f"{prefix}%")))
    return set(rows)


def test_duplicate_active_in_batch_is_skipped_deterministically(db_session, caplog) -> None:
    batch = [
        _sub("dup-old", "2026-01-01"),
        _sub("dup-new", "2026-06-01"),
        _sub("dup-other", "2026-02-01", plan="dup-plan-2"),
        _sub("dup-canceled", "2026-01-01", status="CANCELADA"),
    ]
    skipped: list[str] = []
    with caplog.at_level(logging.WARNING):
        written = store_vp_resources(db_session, "subscription", batch, platform="virtualpos1", skipped_subscriptions=skipped)

    assert written == 3
    assert skipped == ["dup-old"]
    assert _ids(db_session) == {"dup-new", "dup-other", "dup-canceled"}
    assert "1 suscripciones omitidas" in caplog.text
    assert RUT not in caplog.text and "11111111" not in caplog.text
    # la sesion sigue usable
    store_vp_resources(db_session, "subscription", [_sub("dup-after", "2026-03-01", plan="dup-plan-3")], platform="virtualpos1")
    assert "dup-after" in _ids(db_session)


def test_tie_on_date_keeps_greatest_external_id(db_session) -> None:
    skipped: list[str] = []
    store_vp_resources(
        db_session, "subscription", [_sub("dup-a", "2026-01-01"), _sub("dup-b", "2026-01-01")],
        platform="virtualpos1", skipped_subscriptions=skipped,
    )
    assert skipped == ["dup-a"]
    assert _ids(db_session) == {"dup-b"}


def test_batch_without_duplicates_unchanged(db_session) -> None:
    skipped: list[str] = []
    written = store_vp_resources(
        db_session, "subscription", [_sub("dup-1", "2026-01-01"), _sub("dup-2", "2026-01-01", plan="dup-plan-2")],
        platform="virtualpos1", skipped_subscriptions=skipped,
    )
    assert written == 2 and skipped == []
    assert _ids(db_session) == {"dup-1", "dup-2"}


def test_existing_row_update_is_not_lost_or_deleted(db_session) -> None:
    store_vp_resources(db_session, "subscription", [_sub("dup-x", "2026-01-01")], platform="virtualpos1")
    skipped: list[str] = []
    # dup-x se actualiza (CANCELADA) y dup-y activa nueva con mismo cliente/plan: ambas caben
    store_vp_resources(
        db_session, "subscription",
        [_sub("dup-x", "2026-01-01", status="CANCELADA"), _sub("dup-y", "2026-07-01")],
        platform="virtualpos1", skipped_subscriptions=skipped,
    )
    assert skipped == []
    rows = {r.external_id: r.status for r in db_session.scalars(select(VpSubscription).where(VpSubscription.external_id.like("dup-%")))}
    assert rows == {"dup-x": "CANCELADA", "dup-y": "ACTIVA"}

    # una activa existente colisiona con una nueva mas antigua: la nueva se omite, la existente intacta
    store_vp_resources(db_session, "subscription", [_sub("dup-z", "2026-02-01")], platform="virtualpos1", skipped_subscriptions=skipped)
    assert skipped == ["dup-z"]
    assert _ids(db_session) == {"dup-x", "dup-y"}


class _FakeVp:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def list_clients(self, page: int = 1, limit: int = 100):
        return {"clients": []}

    async def list_payments(self, page: int = 1, limit: int = 100):
        return {"payments": []}

    async def list_plans(self):
        return {"plans": []}

    async def list_subscriptions(self, page: int = 1, limit: int = 100):
        return {
            "suscriptions": [_sub("dup-s1", "2026-01-01"), _sub("dup-s2", "2026-05-01"), _sub("dup-s3", "2026-01-01", plan="dup-p9")],
            "pagination": {"page": page, "pages": 1, "limit": limit, "total": 3},
        }


def test_sync_virtualpos_completes_with_note(monkeypatch, db_session) -> None:
    monkeypatch.setattr(virtualpos_sync, "VirtualPOSClient", lambda: _FakeVp())

    run = asyncio.run(virtualpos_sync.sync_virtualpos(db_session))

    assert run.status == "completed"
    assert run.error_message == "1 suscripciones omitidas por duplicado activo"
    assert _ids(db_session) == {"dup-s2", "dup-s3"}
