"""SYNC-D-16: source_record_id para TCH (registro en cada carga y backfill idempotente). Excel sinteticos, sin PII."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.crm import Charge, Client, Subscription
from app.models.source_record import SourceRecord
from app.models.tch import TchClient, TchSubscription, TchTransaction
from app.services import channel_consolidation
from app.services.tch_source_records import (
    missing_tch_source_records,
    sync_tch_source_records,
)
from scripts import etl_tch
from tests.tch_synthetic import write_report

F1, F2 = 953001, 953002


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
        session.close()
    finally:
        transaction.rollback()
        connection.close()


def _report(tmp_path):
    return write_report(
        tmp_path / "20260131 TCH IG ENERO 2026.xlsx",
        active=[
            {"ficha": F1, "rut": "11111111-1", "historial": {(2025, 12): (1, "Pagada", 10000)}},
            {"ficha": F2, "rut": "22222222-2"},
        ],
        aceptados=[{"ficha": F1, "cuota": 2, "mes": "ENE 26", "fecha": date(2026, 1, 5)}],
        rechazados=[{"ficha": F2, "cuota": 1, "mes": "ENE 26", "fecha": date(2026, 1, 6), "motivo": "Cuenta cerrada"}],
        control=[("DICIEMBRE 2025", 1, 0), ("ENERO 2026", 1, 1)],
    )


def _tch_records(db) -> dict[tuple[str, str], SourceRecord]:
    return {(r.resource_type, r.external_id): r for r in db.scalars(select(SourceRecord).where(SourceRecord.source == "tch"))}


def _seed_without_records(db) -> None:
    """Simula lo ya cargado en `crm` antes de SYNC-D-16: filas tch_* sin source_records."""
    db.add(TchClient(rut="11.111.111-1"))
    db.add(TchSubscription(file_number=F1, client_rut="11.111.111-1", status="VIGENTE"))
    db.add(TchTransaction(file_number=F1, period="2026-01", installment_number="2", status="ACEPTADA", dedupe_key=f"{F1}|2026-01|2"))
    db.add(TchTransaction(file_number=F1, status="ACEPTADA", dedupe_key=None))  # sin clave: no se registra
    db.commit()


def test_backfill_registers_every_tch_row_once_and_is_idempotent(db_session) -> None:
    _seed_without_records(db_session)
    assert missing_tch_source_records(db_session) == {"client": 1, "subscription": 1, "transaction": 1}

    first = sync_tch_source_records(db_session)
    second = sync_tch_source_records(db_session)

    assert first == {"client": 1, "subscription": 1, "transaction": 1}
    assert second == {"client": 0, "subscription": 0, "transaction": 0}
    assert missing_tch_source_records(db_session) == {"client": 0, "subscription": 0, "transaction": 0}
    records = _tch_records(db_session)
    assert set(records) == {("client", "11.111.111-1"), ("subscription", str(F1)), ("transaction", f"{F1}|2026-01|2")}
    # Payload minimo: solo la tabla de origen, ningun dato personal.
    assert {r.payload["tabla"] for r in records.values()} == {"tch_clientes", "tch_suscripciones", "tch_transacciones"}
    assert all(set(r.payload) == {"tabla"} for r in records.values())


def test_backfill_dry_run_rolls_back(db_session) -> None:
    _seed_without_records(db_session)
    created = etl_tch.backfill_source_records(db_session, apply=False)
    assert created["transaction"] == 1
    assert _tch_records(db_session) == {}
    etl_tch.backfill_source_records(db_session, apply=True)
    assert len(_tch_records(db_session)) == 3


def test_each_load_registers_source_records_and_consolidation_links_them(db_session, tmp_path) -> None:
    path = _report(tmp_path)
    etl_tch._process_file(path, db_session)
    etl_tch._register_source_records(db_session)
    etl_tch._process_file(path, db_session)  # la misma carga dos veces
    assert etl_tch._register_source_records(db_session) == {"client": 0, "subscription": 0, "transaction": 0}

    channel_consolidation._consolidate_tch_clients(db_session)
    channel_consolidation._consolidate_tch_subscriptions(db_session)
    channel_consolidation._consolidate_tch_transactions(db_session)

    records = _tch_records(db_session)
    clients = db_session.scalars(select(Client).where(Client.source == "tch", Client.external_id.in_(["11.111.111-1", "22.222.222-2"]))).all()
    subs = db_session.scalars(select(Subscription).where(Subscription.source == "tch", Subscription.external_id.in_([str(F1), str(F2)]))).all()
    charges = db_session.scalars(select(Charge).where(Charge.source == "tch", Charge.subscription_external_id.in_([str(F1), str(F2)]))).all()
    assert len(clients) == 2 and len(subs) == 2 and len(charges) == 3
    for row, kind in [*((c, "client") for c in clients), *((s, "subscription") for s in subs), *((c, "transaction") for c in charges)]:
        assert row.source_record_id == records[(kind, row.external_id)].id


def test_full_reload_reuses_the_same_source_records(db_session, tmp_path) -> None:
    path = _report(tmp_path)
    etl_tch.reload_full(db_session, [path], apply=True, tolerance_month=1, tolerance_total=1)
    first = {key: record.id for key, record in _tch_records(db_session).items()}
    assert ("transaction", f"{F1}|2026-01|2") in first

    etl_tch.reload_full(db_session, [path], apply=True, tolerance_month=1, tolerance_total=1)

    assert {key: record.id for key, record in _tch_records(db_session).items()} == first
    assert missing_tch_source_records(db_session) == {"client": 0, "subscription": 0, "transaction": 0}


def test_cli_backfill_apply_requires_the_exact_database_name() -> None:
    with pytest.raises(SystemExit) as exc:
        etl_tch.main(["--backfill-source-records", "--apply"])
    assert exc.value.code == 2
