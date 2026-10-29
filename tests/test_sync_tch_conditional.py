"""SYNC-O-03: TCH solo se consolida tras una carga de Excel efectiva, no en cada corrida nocturna.

Hecho verificado por codigo: la importacion TCH (`scripts/etl_tch.py`) escribe SOLO en las tablas `tch_*`; las
tablas centralizadas (`clients`, `subscriptions`, `charges`) las alimenta unicamente `channel_consolidation`.
Por eso la consolidacion TCH no se apaga: se condiciona a que el registro de reportes (`tch_report_registry`) tenga
algun reporte nuevo desde la ultima consolidacion TCH exitosa. Estos tests demuestran que el resultado final en
`charges`/`subscriptions`/`clients` es el mismo que con la pasada incondicional.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.models.crm import Charge, Client, Subscription
from app.models.etl_run import EtlRun
from app.models.source_record import SourceRecord
from app.models.tch import TchCliente, TchSuscripcion, TchTransaccion
from app.scheduler.jobs import sync_all
from app.services import tch_report_registry as registry
from app.services.channel_consolidation import consolidate_to_centralized


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


def _sha() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex


# --- registro: marca de consolidacion ---------------------------------------------------------------


def test_without_a_mark_the_first_night_consolidates(db_session) -> None:
    snapshot = registry.consolidation_snapshot(db_session)
    assert registry.needs_consolidation(db_session, snapshot) is True  # base sin marca: se consolida una vez


def test_after_marking_nothing_new_means_no_consolidation(db_session) -> None:
    registry.register(db_session, _sha(), "a.xlsx", 10)
    snap = registry.consolidation_snapshot(db_session)
    registry.mark_consolidated(db_session, snap)
    assert registry.needs_consolidation(db_session, registry.consolidation_snapshot(db_session)) is False


def test_a_new_registered_report_triggers_consolidation(db_session) -> None:
    registry.register(db_session, _sha(), "a.xlsx", 10)
    registry.mark_consolidated(db_session, registry.consolidation_snapshot(db_session))
    registry.register(db_session, _sha(), "b.xlsx", 10)
    assert registry.needs_consolidation(db_session, registry.consolidation_snapshot(db_session)) is True


def test_the_mark_is_a_pre_consolidation_snapshot_so_a_late_report_is_not_lost(db_session) -> None:
    registry.register(db_session, _sha(), "a.xlsx", 10)
    snapshot_before = registry.consolidation_snapshot(db_session)  # tomado ANTES de consolidar
    registry.register(db_session, _sha(), "late.xlsx", 10)  # llega mientras se consolidaba
    registry.mark_consolidated(db_session, snapshot_before)
    assert registry.needs_consolidation(db_session, registry.consolidation_snapshot(db_session)) is True


def test_a_full_reload_of_the_same_files_triggers_consolidation(db_session) -> None:
    sha = _sha()
    registry.register(db_session, sha, "a.xlsx", 10)
    registry.mark_consolidated(db_session, registry.consolidation_snapshot(db_session))
    registry.clear(db_session)  # carga completa: reinicia el registro y vuelve a cargar los mismos archivos
    db_session.add(
        SourceRecord(source=registry.SOURCE, resource_type=registry.RESOURCE_TYPE, external_id=sha,
                     payload={"filename": "a.xlsx", "size_bytes": 10},
                     first_seen_at=datetime.now(UTC) + timedelta(seconds=5))  # otro instante de carga
    )
    db_session.flush()
    assert registry.needs_consolidation(db_session, registry.consolidation_snapshot(db_session)) is True


def test_the_mark_does_not_pollute_the_report_registry(db_session) -> None:
    sha = _sha()
    registry.register(db_session, sha, "a.xlsx", 10)
    registry.mark_consolidated(db_session, registry.consolidation_snapshot(db_session))
    assert registry.is_registered(db_session, sha) is True
    assert len(registry.consolidation_snapshot(db_session)["sha256s"]) >= 1
    assert registry.consolidation_snapshot(db_session)["sha256s"].count(sha) == 1  # la marca no es un reporte


# --- equivalencia del resultado final -----------------------------------------------------------------


def _canonical_tch(db: Session, ficha_numbers: set[str], dedupe: set[str]) -> dict:
    subs = sorted(
        (s.external_id, s.status, s.amount) for s in db.scalars(select(Subscription).where(Subscription.source == "tch"))
        if s.external_id in ficha_numbers
    )
    charges = sorted(
        (c.external_id, c.status, c.amount, c.subscription_external_id)
        for c in db.scalars(select(Charge).where(Charge.source == "tch")) if c.external_id in dedupe
    )
    clients = sorted(
        (c.external_id, c.first_name) for c in db.scalars(select(Client).where(Client.source == "tch"))
        if c.external_id.startswith("EQ-")
    )
    return {"subs": subs, "charges": charges, "clients": clients}


def _load_report(db: Session, n: int, ficha_base: int) -> tuple[set[str], set[str]]:
    """Simula una carga de Excel: filas en tch_* y el reporte registrado (lo que deja `import_incremental_file`)."""
    fichas, keys = set(), set()
    for i in range(n):
        ficha = ficha_base + i
        db.add(TchCliente(rut=f"EQ-{ficha}", nombre=f"Socio {ficha}"))
        db.add(TchSuscripcion(numero_ficha=ficha, cliente_rut=f"EQ-{ficha}", estado="VIGENTE", monto="5000"))
        key = f"eq-{ficha}-2026-09"
        db.add(TchTransaccion(numero_ficha=ficha, periodo="2026-09", estado="ACEPTADA", monto="5000",
                              dedupe_key=key, archivo_origen=f"r{ficha_base}.xlsx"))
        fichas.add(str(ficha))
        keys.add(key)
    registry.register(db, _sha(), f"r{ficha_base}.xlsx", 100)
    db.flush()
    return fichas, keys


def _conditional_night(db: Session) -> bool:
    """La decision de la corrida nocturna, tal como la toma el orquestador. Devuelve si consolido TCH."""
    snap = registry.consolidation_snapshot(db)
    if not registry.needs_consolidation(db, snap):
        return False
    failures: list[str] = []
    consolidate_to_centralized(db, ["tch"], failures=failures)
    if not failures:
        registry.mark_consolidated(db, snap)
    return True


def test_final_canonical_state_equals_the_unconditional_nightly_pass(db_session) -> None:
    registry.mark_consolidated(db_session, registry.consolidation_snapshot(db_session))  # estado estable previo
    fichas1, keys1 = _load_report(db_session, 3, 9_100_000)
    assert _conditional_night(db_session) is True  # noche tras la carga: consolida
    assert _conditional_night(db_session) is False  # noche siguiente sin carga: omite TCH
    fichas2, keys2 = _load_report(db_session, 2, 9_200_000)  # segunda carga
    assert _canonical_tch(db_session, fichas1 | fichas2, keys1 | keys2)["charges"] == sorted(
        (k, "ACEPTADA", "5000", k.split("-")[1]) for k in keys1
    )  # antes de la noche solo esta lo primero (la segunda carga aun no se consolida)
    assert _conditional_night(db_session) is True
    assert _conditional_night(db_session) is False

    conditional = _canonical_tch(db_session, fichas1 | fichas2, keys1 | keys2)
    consolidate_to_centralized(db_session, ["tch"])  # pasada incondicional de referencia
    always = _canonical_tch(db_session, fichas1 | fichas2, keys1 | keys2)
    assert conditional == always
    assert len(always["subs"]) == 5 and len(always["charges"]) == 5 and len(always["clients"]) == 5


# --- orquestador ----------------------------------------------------------------------------------


def _patch_orchestrator(monkeypatch, *, needs: bool, failures: list[str] | None = None):
    events: list[tuple] = []
    run = EtlRun(status="running")
    run.id = uuid.uuid4()

    class FakeDb:
        def scalar(self, *_a, **_k):
            return None

        def add(self, *_a):
            pass

        def commit(self):
            pass

        def close(self):
            pass

        def get(self, *_a):
            return run

    monkeypatch.setattr(sync_all, "SessionLocal", FakeDb)
    monkeypatch.setattr(sync_all, "start_exclusive_run", lambda _db, **_f: run)
    monkeypatch.setattr(sync_all, "skip_disabled_channel", lambda _c: False)

    async def vp(_db, platform, _cb=None, **_k):
        return SimpleNamespace(id=uuid.uuid4(), records_processed=1)

    async def ok(_db, _cb=None):
        return SimpleNamespace(id=uuid.uuid4(), records_processed=1)

    def consolidate(_db, sources, failures=None, **_k):
        events.append(("consolidate", tuple(sources) if sources else None))
        for f in (failures_to_report or []):
            failures.append(f)
        return 0

    failures_to_report = failures
    monkeypatch.setattr(sync_all, "sync_virtualpos", vp)
    monkeypatch.setattr(sync_all, "sync_toku", ok)
    monkeypatch.setattr(sync_all, "sync_payku", ok)
    monkeypatch.setattr(sync_all, "consolidate_to_centralized", consolidate)
    monkeypatch.setattr(sync_all, "reconcile_charge_recoveries", lambda *_a, **_k: None)
    monkeypatch.setattr(registry, "consolidation_snapshot", lambda _db: {"sha256s": ["x"], "latest_load_at": None})
    monkeypatch.setattr(registry, "needs_consolidation", lambda _db, _snap: needs)
    monkeypatch.setattr(registry, "mark_consolidated", lambda _db, _snap: events.append(("mark",)))
    return events, run


_NIGHTLY_WITHOUT_TCH = ("virtualpos", "toku", "payku")


def test_nightly_without_a_new_load_skips_tch_and_keeps_the_other_channels(monkeypatch) -> None:
    events, run = _patch_orchestrator(monkeypatch, needs=False)
    asyncio.run(sync_all.sync_all_channels())
    assert ("consolidate", _NIGHTLY_WITHOUT_TCH) in events
    assert not any(e[0] == "consolidate" and e[1] and "tch" in e[1] for e in events)
    assert ("mark",) not in events
    assert run.status == "completed" and "tch" in run.channels_processed  # la salud de TCH se conserva


def test_nightly_with_a_new_load_consolidates_tch_and_marks(monkeypatch) -> None:
    events, _ = _patch_orchestrator(monkeypatch, needs=True)
    asyncio.run(sync_all.sync_all_channels())
    assert ("consolidate", ("virtualpos", "toku", "payku", "tch")) in events
    assert ("mark",) in events


def test_a_failed_tch_consolidation_is_not_marked(monkeypatch) -> None:
    events, run = _patch_orchestrator(monkeypatch, needs=True, failures=["tch.transactions"])
    asyncio.run(sync_all.sync_all_channels())
    assert ("mark",) not in events
    assert run.status == "partial" or run.status == "failed"


def test_explicit_tch_request_always_consolidates(monkeypatch) -> None:
    events, _ = _patch_orchestrator(monkeypatch, needs=False)
    asyncio.run(sync_all.sync_all_channels(channels=["tch"]))
    assert ("consolidate", ("tch",)) in events


def test_the_skip_can_be_turned_off_by_setting(monkeypatch) -> None:
    monkeypatch.setattr(settings, "sync_tch_consolidate_only_after_load", False)
    events, _ = _patch_orchestrator(monkeypatch, needs=False)
    asyncio.run(sync_all.sync_all_channels())
    assert any(e[0] == "consolidate" and e[1] and "tch" in e[1] for e in events)
