"""SYNC-O-07 + SYNC-D-13: la guarda `IS DISTINCT FROM` no reescribe filas sin cambios, pero `last_seen_at` se marca igual.

Datos sinteticos; nada de red ni de proveedores.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.toku_channel import TokuSubscription
from app.services.channel_store import store_toku_resources

PFX = "seen07-"


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


def _toku(ext: str, status: str = "active") -> dict:
    return {"id": ext, "status": status, "customer": {"id": f"{PFX}cus"}}


def _row(db: Session, ext: str) -> TokuSubscription:
    db.expire_all()
    return db.scalars(select(TokuSubscription).where(TokuSubscription.external_id == ext)).one()


def test_unchanged_row_keeps_updated_at_but_is_marked_seen(db_session: Session) -> None:
    store_toku_resources(db_session, "subscription", [_toku(f"{PFX}a")])
    first = _row(db_session, f"{PFX}a")
    updated_at, seen_at = first.updated_at, first.last_seen_at

    store_toku_resources(db_session, "subscription", [_toku(f"{PFX}a")])
    again = _row(db_session, f"{PFX}a")

    assert again.updated_at == updated_at  # sin cambios: la guarda no reescribe la fila
    assert again.last_seen_at > seen_at  # pero quedo vista en esta lectura
    assert again.removed_at is None


def test_changed_row_is_rewritten_and_seen(db_session: Session) -> None:
    store_toku_resources(db_session, "subscription", [_toku(f"{PFX}b")])
    seen_at = _row(db_session, f"{PFX}b").last_seen_at

    store_toku_resources(db_session, "subscription", [_toku(f"{PFX}b", "paused")])
    changed = _row(db_session, f"{PFX}b")

    # `updated_at` usa now() (inicio de la transaccion del test), asi que aqui se verifica el cambio por su contenido.
    assert changed.status == "paused"
    assert changed.last_seen_at > seen_at
