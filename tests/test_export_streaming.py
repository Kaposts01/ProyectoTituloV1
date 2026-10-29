"""EXP-05: streaming real (cursor del lado del servidor), paginacion repartida entre canales y volumen moderado."""

import random
import time
import tracemalloc
import uuid

from sqlalchemy import delete, insert

from app.db.session import SessionLocal
from app.models.tch import TchTransaction
from app.services.export_queries import (
    ENTITY_COLUMNS,
    ENTITY_SPECS,
    ExportFilters,
    iter_rows,
    page_plan,
    select_specs,
)
from app.services.exporter import BOM, csv_stream


def test_page_plan_splits_offset_and_limit_across_channels() -> None:
    assert page_plan([5, 3, 4], 0, 4) == [(0, 4), (0, 0), (0, 0)]
    assert page_plan([5, 3, 4], 3, 4) == [(3, 2), (0, 2), (0, 0)]
    assert page_plan([5, 3, 4], 8, 10) == [(0, 0), (0, 0), (0, 4)]
    assert page_plan([5, 3, 4], 100, 10) == [(0, 0), (0, 0), (0, 0)]
    assert page_plan([], 0, 10) == []


def test_select_specs_resolves_channels_and_permissions() -> None:
    all_perms = {s.permission for s in ENTITY_SPECS["cobros"]}
    items, denied = select_specs("cobros", None, all_perms)
    assert not denied and [src for _s, srcs in items for src in srcs] == ["virtualpos1", "virtualpos2", "toku", "tch"]
    items, denied = select_specs("cobros", "virtualpos2", all_perms)
    assert not denied and [srcs for _s, srcs in items] == [("virtualpos2",)]
    items, denied = select_specs("cobros", "toku", {"tch.transacciones.view"})
    assert denied and items == []
    items, denied = select_specs("cobros", None, {"tch.transacciones.view"})
    assert not denied and [s.provider for s, _ in items] == ["tch"]
    items, denied = select_specs("cobros", "payku", all_perms)  # payku no tiene cobros
    assert items == [] and not denied


def test_query_uses_server_side_cursor_and_closes_session(monkeypatch) -> None:
    seen: list[dict] = []
    sessions = []

    def factory():
        session = SessionLocal()
        original = session.execute

        def spy(stmt, *args, **kwargs):
            seen.append(dict(stmt.get_execution_options()) if hasattr(stmt, "get_execution_options") else {})
            return original(stmt, *args, **kwargs)

        session.execute = spy  # type: ignore[method-assign]
        sessions.append(session)
        return session

    items, _ = select_specs("cobros", "tch", {"tch.transacciones.view"})
    gen = iter_rows(factory, items, ExportFilters(query="no-existe-" + uuid.uuid4().hex, filter_field="id"), False)
    assert list(gen) == []
    assert any(o.get("stream_results") is True and o.get("yield_per", 0) >= 500 for o in seen), seen
    sfx = "cur" + uuid.uuid4().hex[:8]
    seed = SessionLocal()
    try:
        seed.execute(insert(TchTransaction), [
            {"file_number": 1, "status": "ACEPTADA", "dedupe_key": f"{sfx}-{i}", "source_file": sfx} for i in range(3)])
        seed.commit()
        gen2 = iter_rows(factory, items, ExportFilters(), False)
        next(gen2)
        gen2.close()  # el consumidor corta: la sesion y el cursor se liberan
        assert sessions[-1].in_transaction() is False
    finally:
        seed.execute(delete(TchTransaction).where(TchTransaction.source_file == sfx))
        seed.commit()
        seed.close()


def test_volume_50k_rows_streams_in_chunks_within_time_and_memory() -> None:
    sfx = "vol" + uuid.uuid4().hex[:8]
    file_number = random.randint(90_000_000, 99_999_999)
    total = 50_000
    db = SessionLocal()
    try:
        for start in range(0, total, 10_000):
            db.execute(insert(TchTransaction), [
                {"file_number": file_number, "period": "2026-01", "amount": "5000", "charge_date": "2026-01-15",
                 "status": "ACEPTADA" if i % 3 else "RECHAZADA", "dedupe_key": f"{sfx}-{i}", "source_file": sfx}
                for i in range(start, start + 10_000)
            ])
        db.commit()
        items, _ = select_specs("cobros", "tch", {"tch.transacciones.view"})
        filters = ExportFilters(query=str(file_number), filter_field="subscription_id")
        finished: list[tuple[int, bool]] = []
        tracemalloc.start()
        started = time.perf_counter()
        chunks = 0
        biggest = 0
        first = True
        lines = 0
        for chunk in csv_stream(ENTITY_COLUMNS["cobros"], False, iter_rows(SessionLocal, items, filters, False),
                                on_finish=lambda n, ok: finished.append((n, ok))):
            if first:
                assert chunk.startswith(BOM)
                first = False
            chunks += 1
            biggest = max(biggest, len(chunk))
            lines += chunk.count(b"\n")
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert finished == [(total, True)]
        assert lines == total + 1  # filas + cabecera
        assert chunks >= 40 and biggest < 400_000, (chunks, biggest)
        assert peak < 30 * 1024 * 1024, f"pico de memoria {peak / 1e6:.1f} MB: no deberia armar todo en memoria"
        assert elapsed < 60, f"50.000 filas tardaron {elapsed:.1f} s"
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        db.rollback()
        db.execute(delete(TchTransaction).where(TchTransaction.source_file == sfx))
        db.commit()
        db.close()
