"""SYNC-GAP-01 (platform VirtualPOS) y SYNC-GAP-03 (source_record_id)."""
import asyncio
from typing import Self

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.crm import Charge, Client, Payment, Plan, Subscription
from app.models.source_record import SourceRecord
from app.models.sync_run import SyncRun  # noqa: F401 — registra la tabla en metadata
from app.models.vp import VpClient
from app.models.write_run import (
    WriteRun,  # noqa: F401 — registra la tabla en metadata antes de resolve FK
)
from app.services import virtualpos_sync
from app.services.channel_consolidation import (
    _consolidate_vp_clients,
    _source_record_ids,
    _upsert_centralized,
)
from app.services.channel_store import store_vp_resources


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


def _stage(db: Session, source: str, resource_type: str, external_id: str) -> SourceRecord:
    record = SourceRecord(source=source, resource_type=resource_type, external_id=external_id, payload={})
    db.add(record)
    db.flush()
    return record


def test_unknown_platform_is_rejected_on_store(db_session) -> None:
    written = store_vp_resources(db_session, "client", [{"uuid": "gap-unknown-1"}], platform="virtualpos9")

    assert written == 0
    assert db_session.scalars(select(VpClient).where(VpClient.external_id == "gap-unknown-1")).first() is None


def test_unknown_platform_is_skipped_on_consolidation(db_session) -> None:
    db_session.add_all([
        VpClient(platform="virtualpos9", external_id="gap-unknown-2", raw_payload={}),
        VpClient(platform="virtualpos2", external_id="gap-known-2", raw_payload={}),
    ])
    db_session.flush()

    _consolidate_vp_clients(db_session)

    assert db_session.scalars(select(Client).where(Client.external_id == "gap-unknown-2")).first() is None
    assert db_session.scalars(select(Client).where(Client.external_id == "gap-known-2")).one().source == "virtualpos2"


def test_source_record_ids_helper_returns_only_matches(db_session) -> None:
    record = _stage(db_session, "virtualpos1", "client", "gap-helper-1")

    mapping = _source_record_ids(db_session, "virtualpos1", "client", ["gap-helper-1", "gap-helper-missing"])

    assert mapping == {"gap-helper-1": record.id}


def test_consolidation_sets_source_record_id_and_second_pass_keeps_it(db_session) -> None:
    record = _stage(db_session, "virtualpos1", "client", "gap-link-1")
    db_session.add_all([
        VpClient(platform="virtualpos1", external_id="gap-link-1", raw_payload={}),
        VpClient(platform="virtualpos1", external_id="gap-nolink-1", raw_payload={}),
    ])
    db_session.flush()

    _consolidate_vp_clients(db_session)
    _consolidate_vp_clients(db_session)

    linked = db_session.scalars(select(Client).where(Client.external_id == "gap-link-1")).one()
    unlinked = db_session.scalars(select(Client).where(Client.external_id == "gap-nolink-1")).one()
    assert linked.source_record_id == record.id
    assert unlinked.source_record_id is None


def test_upsert_without_match_does_not_erase_existing_link(db_session) -> None:
    record = _stage(db_session, "virtualpos1", "client", "gap-keep-1")
    db_session.add(VpClient(platform="virtualpos1", external_id="gap-keep-1", raw_payload={}))
    db_session.flush()
    _consolidate_vp_clients(db_session)

    _upsert_centralized(
        db_session,
        Client,
        "uq_client_source_external_id",
        [{"source": "virtualpos1", "external_id": "gap-keep-1", "source_record_id": None, "first_name": "X", "cards": []}],
    )

    client = db_session.scalars(select(Client).where(Client.external_id == "gap-keep-1")).one()
    assert client.source_record_id == record.id
    assert client.first_name == "X"


def test_source_record_id_unique_constraint_is_not_violated(db_session) -> None:
    record = _stage(db_session, "virtualpos1", "client", "gap-uniq-1")
    db_session.add(Client(source="virtualpos1", external_id="gap-uniq-owner", source_record_id=record.id, cards=[]))
    db_session.flush()

    # Otra fila intenta reclamar el mismo source_record_id: debe quedar NULL, sin IntegrityError.
    _upsert_centralized(
        db_session,
        Client,
        "uq_client_source_external_id",
        [{"source": "virtualpos1", "external_id": "gap-uniq-other", "source_record_id": record.id, "cards": []}],
    )

    other = db_session.scalars(select(Client).where(Client.external_id == "gap-uniq-other")).one()
    assert other.source_record_id is None


class _FakeVpClient:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def list_clients(self, page: int = 1, limit: int = 100):
        return {"clients": [{"uuid": "gap-full-client", "first_name": "Test", "status": "ACTIVE"}]}

    async def list_plans(self):
        return {"plans": [{"id": "gap-full-plan", "name": "Plan"}]}

    async def list_payments(self, page: int = 1, limit: int = 100):
        return {"payments": [{"order": {"uuid": "gap-full-payment", "amount": 1000}}]}

    async def list_subscriptions(self, page: int = 1, limit: int = 100):
        return {
            "suscriptions": [{
                "id": "gap-full-sub",
                "plan_id": "gap-full-plan",
                "charge_program": [{"id": "gap-full-charge", "amount": 1000, "status": "PENDING"}],
            }],
            "pagination": {"page": page, "pages": 1, "limit": limit, "total": 1},
        }


def test_full_vp_sync_leaves_single_linked_version_per_row(monkeypatch, db_session) -> None:
    monkeypatch.setattr(virtualpos_sync, "VirtualPOSClient", lambda: _FakeVpClient())

    asyncio.run(virtualpos_sync.sync_virtualpos(db_session))
    asyncio.run(virtualpos_sync.sync_virtualpos(db_session))

    expected = {
        Client: "gap-full-client",
        Plan: "gap-full-plan",
        Subscription: "gap-full-sub",
        Charge: "gap-full-charge",
        Payment: "gap-full-payment",
    }
    for model, external_id in expected.items():
        count = db_session.scalar(
            select(func.count()).select_from(model).where(model.external_id == external_id)
        )
        assert count == 1, model.__name__
        row = db_session.scalars(select(model).where(model.external_id == external_id)).one()
        assert row.source == "virtualpos1"
        assert row.source_record_id is not None, model.__name__
