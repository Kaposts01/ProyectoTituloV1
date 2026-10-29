"""RT-04: cola `webhook_events` (migracion 20261029_0049). Esquema, restricciones e indices. Datos sinteticos."""

import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.webhook_event import WEBHOOK_EVENT_STATUSES, WebhookEvent

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "alembic" / "versions" / "20261029_0049_webhook_events_queue.py"


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


def _event(**over) -> WebhookEvent:
    base = {
        "source": "toku",
        "event_type": "subscription.updated",
        "provider_event_id": f"wheve_{uuid.uuid4().hex[:8]}",
        "resource_type": "subscription",
        "resource_external_id": "sub_1",
        "payload_masked": {"id": "x"},
        "dedupe_key": uuid.uuid4().hex + uuid.uuid4().hex,
    }
    return WebhookEvent(**{**base, **over})


def test_table_has_expected_columns() -> None:
    cols = {c["name"]: c for c in inspect(engine).get_columns("webhook_events")}
    expected = {
        "id", "source", "event_type", "provider_event_id", "resource_type", "resource_external_id",
        "subscription_external_id", "status", "attempts", "next_attempt_at", "locked_at", "last_error_code",
        "received_at", "processed_at", "payload_masked", "dedupe_key",
    }
    assert expected <= set(cols)
    assert cols["payload_masked"]["nullable"] is False
    assert cols["dedupe_key"]["nullable"] is False


def test_indexes_for_queue_and_lookup() -> None:
    idx = {i["name"]: i["column_names"] for i in inspect(engine).get_indexes("webhook_events")}
    assert idx["ix_webhook_events_status_next_attempt"] == ["status", "next_attempt_at"]
    assert idx["ix_webhook_events_source_resource"] == ["source", "resource_external_id"]


def test_defaults_and_status_values(db_session) -> None:
    ev = _event()
    db_session.add(ev)
    db_session.flush()
    db_session.refresh(ev)
    assert ev.status == "pending" and ev.attempts == 0
    assert ev.next_attempt_at is not None and ev.received_at is not None
    assert set(WEBHOOK_EVENT_STATUSES) == {"pending", "processing", "done", "failed", "ignored"}


def test_dedupe_key_is_unique(db_session) -> None:
    db_session.add(_event(dedupe_key="k" * 64))
    db_session.flush()
    db_session.add(_event(dedupe_key="k" * 64))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_invalid_status_rejected(db_session) -> None:
    db_session.add(_event(status="weird"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_no_personal_columns_in_table() -> None:
    names = {c["name"] for c in inspect(engine).get_columns("webhook_events")}
    assert not names & {"email", "phone", "rut", "name", "payload", "raw_body", "headers", "source_ip"}


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_0049", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_chain_single_head_and_real_downgrade() -> None:
    mod = _load_migration()
    assert mod.revision == "20261029_0049" and mod.down_revision == "20261029_0048"
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1
    source = MIGRATION.read_text(encoding="utf-8")
    assert "def downgrade" in source and "drop_table" in source


def test_migration_is_only_additive() -> None:
    """No toca datos existentes: no hay DELETE/UPDATE/ALTER sobre tablas previas."""
    source = MIGRATION.read_text(encoding="utf-8").lower()
    body = source.split("def upgrade", 1)[1]
    assert "op.execute" not in body and "alter_table" not in body and "add_column" not in body
    assert "stg_" not in body


def test_unique_constraint_present_in_database() -> None:
    with engine.connect() as conn:
        n = conn.execute(text(
            "SELECT count(*) FROM pg_constraint WHERE conname = 'uq_webhook_events_dedupe_key'")).scalar()
    assert n == 1
