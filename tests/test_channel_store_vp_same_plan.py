"""BUG-VP-03b: store_vp_resources / sync_virtualpos guardan varias activas con mismo RUT y plan (sin omisiones)."""
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


def test_same_plan_active_in_batch_are_all_stored(db_session, caplog) -> None:
    batch = [
        _sub("dup-old", "2026-01-01"),
        _sub("dup-new", "2026-06-01"),
        _sub("dup-other", "2026-02-01", plan="dup-plan-2"),
        _sub("dup-canceled", "2026-01-01", status="CANCELADA"),
    ]
    with caplog.at_level(logging.WARNING):
        written = store_vp_resources(db_session, "subscription", batch, platform="virtualpos1")

    assert written == 4
    assert _ids(db_session) == {"dup-old", "dup-new", "dup-other", "dup-canceled"}
    assert "omitidas" not in caplog.text
    assert RUT not in caplog.text and "11111111" not in caplog.text


def test_existing_active_plus_new_active_same_plan_both_kept(db_session) -> None:
    store_vp_resources(db_session, "subscription", [_sub("dup-x", "2026-01-01")], platform="virtualpos1")
    written = store_vp_resources(db_session, "subscription", [_sub("dup-y", "2026-07-01")], platform="virtualpos1")

    assert written == 1
    rows = {r.external_id: r.status for r in db_session.scalars(select(VpSubscription).where(VpSubscription.external_id.like("dup-%")))}
    assert rows == {"dup-x": "ACTIVA", "dup-y": "ACTIVA"}


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


def test_sync_virtualpos_completes_without_note_and_stores_all(monkeypatch, db_session, caplog) -> None:
    monkeypatch.setattr(virtualpos_sync, "VirtualPOSClient", lambda: _FakeVp())

    with caplog.at_level(logging.INFO):
        run = asyncio.run(virtualpos_sync.sync_virtualpos(db_session))

    assert run.status == "completed"
    assert run.error_message is None
    assert _ids(db_session) == {"dup-s1", "dup-s2", "dup-s3"}
    assert RUT not in caplog.text and "11111111" not in caplog.text
