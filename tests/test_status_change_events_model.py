"""SYNC-D-01: esquema de status_change_events y rejection_reason_catalog (solo sobre crm_test)."""

import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.status_change import RejectionReasonCatalog, StatusChangeEvent

ROOT = Path(__file__).resolve().parent.parent


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


def _event(**overrides) -> StatusChangeEvent:
    values = dict(
        entity_type="charge",
        source="toku",
        external_id="in_1",
        event_kind="status_changed",
        field="status",
        from_value="pending",
        to_value="paid",
        dedupe_key=uuid.uuid4().hex + uuid.uuid4().hex,
    )
    values.update(overrides)
    return StatusChangeEvent(**values)


def test_unico_head_de_alembic():
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1


def test_tablas_e_indices_existen():
    insp = inspect(engine)
    assert {"status_change_events", "rejection_reason_catalog"} <= set(insp.get_table_names())
    cols = {c["name"] for c in insp.get_columns("status_change_events")}
    assert cols == {
        "id", "entity_type", "source", "external_id", "subscription_external_id", "event_kind", "field",
        "from_value", "to_value", "amount", "provider_event_at", "detected_at", "run_id", "is_baseline",
        "dedupe_key",
    }
    index_cols = {tuple(i["column_names"]) for i in insp.get_indexes("status_change_events")}
    assert ("detected_at",) in index_cols
    assert ("entity_type", "source", "external_id") in index_cols
    assert ("event_kind", "detected_at") in index_cols
    uniques = [u["column_names"] for u in insp.get_unique_constraints("status_change_events")]
    assert ["dedupe_key"] in uniques
    cat_cols = {c["name"] for c in insp.get_columns("rejection_reason_catalog")}
    assert cat_cols == {"id", "source", "code", "reason", "first_seen_at", "last_seen_at", "occurrences"}


def test_inserta_con_defaults(db_session: Session) -> None:
    ev = _event()
    db_session.add(ev)
    db_session.flush()
    assert ev.id is not None and ev.detected_at is not None and ev.is_baseline is False


def test_dedupe_key_unico(db_session: Session) -> None:
    key = "a" * 64
    db_session.add(_event(dedupe_key=key))
    db_session.flush()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(_event(dedupe_key=key, external_id="otro"))
            db_session.flush()


@pytest.mark.parametrize("overrides", [{"entity_type": "plan"}, {"event_kind": "borrado"}])
def test_check_constraints(db_session: Session, overrides: dict) -> None:
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(_event(**overrides))
            db_session.flush()


def test_eventos_son_inmutables(db_session: Session) -> None:
    ev = _event()
    db_session.add(ev)
    db_session.flush()
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("UPDATE status_change_events SET to_value = 'x' WHERE id = :i"), {"i": ev.id})
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM status_change_events WHERE id = :i"), {"i": ev.id})


def test_catalogo_unico_y_actualizable(db_session: Session) -> None:
    cat = RejectionReasonCatalog(source="toku", code="2070", reason="Fondos insuficientes")
    db_session.add(cat)
    db_session.flush()
    assert cat.occurrences == 1 and cat.first_seen_at is not None
    cat.occurrences = 5
    db_session.flush()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(RejectionReasonCatalog(source="toku", code="2070", reason="Fondos insuficientes"))
            db_session.flush()
    assert db_session.scalars(select(RejectionReasonCatalog)).one().occurrences == 5
