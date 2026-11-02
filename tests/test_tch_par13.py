"""TCH-PAR-13: consolidacion TCH incremental (solo cuotas nuevas o cambiadas). Datos sinteticos, sin PII."""

import uuid

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.crm import Charge
from app.models.status_change import StatusChangeEvent
from app.models.tch import TchSubscription, TchTransaction
from app.services import channel_consolidation
from app.services.channel_consolidation import _consolidate_tch_transactions, consolidate_to_centralized


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


def _seed(db: Session, n: int = 7) -> None:
    db.add(TchSubscription(file_number=880001, client_rut="22222222-2", status="ACTIVA", amount="4000"))
    db.add(TchSubscription(file_number=880002, client_rut="33333333-3", status="ACTIVA", amount="5000"))
    for i in range(n):
        db.add(TchTransaction(
            file_number=880001 if i % 2 == 0 else 880002, period=f"2026-{i + 1:02d}", installment_number="1",
            dedupe_key=f"t13|{i}", status="ACEPTADA", amount="4000", charge_date=f"2026-{i + 1:02d}-05",
            raw_payload={"fila": i},
        ))
    db.flush()


def _tch_charges(db: Session) -> dict[str, tuple]:
    return {
        c.external_id: (c.subscription_external_id, c.client_external_id, c.amount, c.currency, c.status,
                        c.charge_date, c.raw_payload)
        for c in db.scalars(select(Charge).where(Charge.source == "tch"))
    }


def _events(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(StatusChangeEvent).where(StatusChangeEvent.source == "tch"))


def _tch_timing(db: Session) -> dict:
    timings: list[dict] = []
    consolidate_to_centralized(db, ["tch"], timings=timings, run_id=uuid.uuid4())
    return next(t for t in timings if t["fn"] == "tch_transactions")


def test_second_tch_consolidation_reads_and_writes_nothing(db_session: Session,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(channel_consolidation, "_CHUNK", 3)  # varias paginas por clave
    _seed(db_session)
    first = _tch_timing(db_session)
    assert first["records"] == 7 and first["written"] == 7
    charges = _tch_charges(db_session)
    assert len(charges) == 7
    assert charges["t13|1"] == ("880002", "33333333-3", "4000", "CLP", "ACEPTADA", "2026-02-05", {"fila": 1})
    events = _events(db_session)

    second = _tch_timing(db_session)
    assert second["records"] == 0 and second["written"] == 0
    assert _events(db_session) == events
    assert _tch_charges(db_session) == charges


def test_only_changed_installments_are_read(db_session: Session) -> None:
    _seed(db_session)
    _tch_timing(db_session)
    base_events = _events(db_session)

    db_session.execute(update(TchTransaction).where(TchTransaction.dedupe_key == "t13|3").values(status="RECHAZADA"))
    timing = _tch_timing(db_session)
    assert timing["records"] == 1 and timing["written"] == 1
    changed = list(db_session.scalars(select(StatusChangeEvent).where(StatusChangeEvent.event_kind == "status_changed")))
    assert [(e.external_id, e.from_value, e.to_value) for e in changed] == [("t13|3", "ACEPTADA", "RECHAZADA")]
    assert _events(db_session) == base_events + 1


def test_subscription_client_change_rereads_its_installments(db_session: Session) -> None:
    _seed(db_session)
    _tch_timing(db_session)
    db_session.execute(
        update(TchSubscription).where(TchSubscription.file_number == 880002).values(client_rut="44444444-4")
    )
    timing = _tch_timing(db_session)
    assert timing["records"] == 3  # las cuotas 1, 3 y 5 son de la ficha 880002
    assert {v[1] for k, v in _tch_charges(db_session).items() if v[0] == "880002"} == {"44444444-4"}


def test_drifted_canonical_row_is_repaired(db_session: Session) -> None:
    _seed(db_session)
    _tch_timing(db_session)
    db_session.execute(update(Charge).where(Charge.source == "tch", Charge.external_id == "t13|0").values(amount="1"))
    db_session.execute(update(Charge).where(Charge.source == "tch", Charge.external_id == "t13|2").values(raw_payload=None))
    timing = _tch_timing(db_session)
    assert timing["records"] == 2
    charges = _tch_charges(db_session)
    assert charges["t13|0"][2] == "4000" and charges["t13|2"][6] == {"fila": 2}


def test_incremental_result_equals_full_projection(db_session: Session) -> None:
    """Lo consolidado por diferencias coincide con lo que arma la funcion fila a fila (sin perder columnas)."""
    _seed(db_session)
    _consolidate_tch_transactions(db_session)
    db_session.execute(update(TchTransaction).where(TchTransaction.dedupe_key == "t13|4").values(amount="9000"))
    assert _consolidate_tch_transactions(db_session) == 1
    expected = {}
    client = dict(db_session.execute(select(TchSubscription.file_number, TchSubscription.client_rut)).all())
    for t in db_session.scalars(select(TchTransaction).where(TchTransaction.dedupe_key.like("t13|%"))):
        expected[t.dedupe_key] = (str(t.file_number), client[t.file_number], t.amount, "CLP", t.status,
                                  t.charge_date, t.raw_payload)
    assert _tch_charges(db_session) == expected
