"""SYNC-O-10: escritura en lotes de `source_records` (idempotente, con conteo de nuevas/actualizadas/sin cambio)."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.source_record import SourceRecord
from app.services.source_record_store import upsert_source_records
from app.services.virtualpos_sync import _store_records


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


def _source() -> str:
    return f"test_{uuid.uuid4().hex[:12]}"


def _ext(record):
    return str(record["id"])


def _rows(db, source):
    return {r.external_id: r for r in db.scalars(select(SourceRecord).where(SourceRecord.source == source))}


def test_batch_counts_inserted_then_is_idempotent(db_session) -> None:
    source = _source()
    records = [{"id": i, "v": i} for i in range(7)]
    first = upsert_source_records(db_session, source, "payment", records, external_id_fn=_ext, batch_size=3)
    assert (first.seen, first.inserted, first.updated, first.unchanged) == (7, 7, 0, 0)
    second = upsert_source_records(db_session, source, "payment", records, external_id_fn=_ext, batch_size=3)
    assert (second.inserted, second.updated, second.unchanged) == (0, 0, 7)  # misma guarda: nada se reescribe
    assert len(_rows(db_session, source)) == 7


def test_only_changed_payloads_count_as_updated(db_session) -> None:
    source = _source()
    upsert_source_records(db_session, source, "client", [{"id": 1, "v": "a"}, {"id": 2, "v": "b"}], external_id_fn=_ext)
    result = upsert_source_records(
        db_session, source, "client", [{"id": 1, "v": "a"}, {"id": 2, "v": "B"}, {"id": 3, "v": "c"}], external_id_fn=_ext
    )
    assert (result.inserted, result.updated, result.unchanged) == (1, 1, 1)
    assert _rows(db_session, source)["2"].payload == {"id": 2, "v": "B"}


def test_duplicate_external_id_in_one_batch_keeps_the_last(db_session) -> None:
    source = _source()
    result = upsert_source_records(
        db_session, source, "charge", [{"id": 1, "v": "old"}, {"id": 1, "v": "new"}], external_id_fn=_ext
    )
    assert result.inserted == 1 and result.seen == 2
    assert _rows(db_session, source)["1"].payload == {"id": 1, "v": "new"}


def test_vp_store_records_tracks_sync_context_per_record(db_session) -> None:
    source = _source()
    charges = [{"id": "c1", "amount": 1}, {"id": "c2", "amount": 2}]
    contexts = [{"subscription_external_id": "s1"}, {"subscription_external_id": "s2"}]
    assert _store_records(db_session, source, "charge", charges, contexts=contexts) == 2
    assert _store_records(db_session, source, "charge", charges, contexts=contexts) == 0  # idempotente
    contexts[1] = {"subscription_external_id": "s3"}
    assert _store_records(db_session, source, "charge", charges, contexts=contexts) == 1  # cambia solo el contexto
    rows = _rows(db_session, source)
    assert rows["c1"].sync_context == {"subscription_external_id": "s1"}
    assert rows["c2"].sync_context == {"subscription_external_id": "s3"}


def test_card_data_is_still_sanitized(db_session) -> None:
    source = _source()
    _store_records(db_session, source, "payment", [{"id": "p1", "card_number": "4111111111111111", "amount": 5}])
    assert "card_number" not in _rows(db_session, source)["p1"].payload or _rows(db_session, source)["p1"].payload[
        "card_number"
    ] != "4111111111111111"
