"""SYNC-O-13 / SYNC-D-11: plan y reanudacion de la carga historica (proveedor falso, datos sinteticos)."""

import asyncio
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.sync_cursor import SyncCursor
from app.services import sync_history
from app.services.sync_history import ChannelSpec
from scripts import sync_history as script

NOON_UTC = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)  # 12:00 en Chile


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    session.execute(delete(SyncCursor))
    session.flush()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


class FakeProvider:
    """Proveedor falso: `pages` paginas por ventana, 2 registros por pagina, con fecha dentro de la ventana."""

    def __init__(self, pages: int = 3, fail_on: tuple | None = None, outside: bool = False) -> None:
        self.pages = pages
        self.fail_on = fail_on
        self.outside = outside
        self.calls: list[tuple[date, int]] = []
        self.stored: list[str] = []

    def spec(self) -> ChannelSpec:
        provider = self

        class Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_a):
                return False

        async def read_page(_client, start: date, _end: date, page: int):
            provider.calls.append((start, page))
            if provider.fail_on == (start, page):
                raise TimeoutError("simulado")
            created = "2001-01-01" if provider.outside else start.isoformat()
            data = [{"id": f"{start}-{page}-{i}", "created_at": created} for i in range(2)]
            return {"data": data, "next": page < provider.pages}

        def store(_db, records):
            provider.stored.extend(r["id"] for r in records)
            return len(records)

        return ChannelSpec(
            resource="transaction", splitter=sync_history._days30, read_page=read_page,
            records=lambda r: r["data"], has_next=lambda r, _recs, _p: r["next"], store=store,
            date_fields=("created_at",), client_factory=Client,
        )


async def _no_sleep(_s: float) -> None:
    return None


def _run(db, provider, **kwargs):
    kwargs.setdefault("now_fn", lambda: NOON_UTC)
    return asyncio.run(sync_history.run_plan(db, "payku", spec=provider.spec(), sleep=_no_sleep, **kwargs))


def _statuses(db) -> list[tuple]:
    return [(c.window_start, c.status, c.page) for c in sync_history.load_plan(db, "payku")]


# ── Plan ───────────────────────────────────────────────────────────────────────────────────────────────


def test_plan_windows_per_channel() -> None:
    assert sync_history.plan_windows("toku", date(2024, 1, 15), date(2024, 3, 10)) == [
        (date(2024, 1, 15), date(2024, 1, 31)), (date(2024, 2, 1), date(2024, 2, 29)),
        (date(2024, 3, 1), date(2024, 3, 10)),
    ]
    weeks = sync_history.plan_windows("virtualpos1", date(2025, 1, 1), date(2025, 1, 20))
    assert weeks[0] == (date(2025, 1, 1), date(2025, 1, 7)) and weeks[-1] == (date(2025, 1, 15), date(2025, 1, 20))
    payku = sync_history.plan_windows("payku", date(2020, 1, 1), date(2020, 3, 1))
    assert payku == [(date(2020, 1, 1), date(2020, 1, 30)), (date(2020, 1, 31), date(2020, 2, 29)),
                     (date(2020, 3, 1), date(2020, 3, 1))]
    with pytest.raises(ValueError):
        sync_history.plan_windows("tch", date(2020, 1, 1), date(2020, 2, 1))


def test_save_plan_is_idempotent_and_keeps_progress(db_session: Session) -> None:
    plan = sync_history.save_plan(db_session, "payku", date(2020, 1, 1), date(2020, 3, 1))
    assert [(c.status, c.page, c.mode) for c in plan] == [("pending", 1, "history")] * 3
    plan[0].status, plan[0].page = "done", 7
    db_session.commit()
    again = sync_history.save_plan(db_session, "payku", date(2020, 1, 1), date(2020, 4, 15))
    assert len(again) == 4 and (again[0].status, again[0].page) == ("done", 7)
    # Las marcas de la sync diaria (window_start NULL) no se mezclan con el plan.
    assert db_session.scalar(select(SyncCursor).where(SyncCursor.window_start.is_(None))) is None


# ── Ejecucion y reanudacion ────────────────────────────────────────────────────────────────────────────


def test_run_reads_every_window_to_the_end(db_session: Session) -> None:
    sync_history.save_plan(db_session, "payku", date(2020, 1, 1), date(2020, 2, 29))
    provider = FakeProvider(pages=3)
    summary = _run(db_session, provider)
    assert (summary.windows_done, summary.requests, summary.records) == (2, 6, 12)
    assert [s[1] for s in _statuses(db_session)] == ["done", "done"]
    done = sync_history.load_plan(db_session, "payku")[0]
    assert (done.records_seen, done.requests_made, done.locked_by) == (6, 3, None)
    assert done.last_success_at is not None
    assert _run(db_session, provider).stopped_reason == "sin ventanas pendientes"  # nada que repetir


def test_request_cap_stops_and_resume_continues_from_saved_page(db_session: Session) -> None:
    sync_history.save_plan(db_session, "payku", date(2020, 1, 1), date(2020, 2, 29))
    provider = FakeProvider(pages=3)
    first = _run(db_session, provider, max_requests=4)
    assert first.requests == 4 and "tope" in first.stopped_reason
    assert _statuses(db_session) == [(date(2020, 1, 1), "done", 3), (date(2020, 1, 31), "pending", 2)]

    second = _run(db_session, provider)
    assert second.windows_done == 1 and second.requests == 2
    # Cada pagina se leyo una sola vez: la reanudacion empezo en la pagina 2 de la segunda ventana.
    assert provider.calls == [(date(2020, 1, 1), 1), (date(2020, 1, 1), 2), (date(2020, 1, 1), 3),
                              (date(2020, 1, 31), 1), (date(2020, 1, 31), 2), (date(2020, 1, 31), 3)]
    assert len(provider.stored) == len(set(provider.stored)) == 12


def test_failure_marks_window_failed_and_is_retried_only_on_request(db_session: Session) -> None:
    sync_history.save_plan(db_session, "payku", date(2020, 1, 1), date(2020, 2, 29))
    provider = FakeProvider(pages=2, fail_on=(date(2020, 1, 1), 2))
    summary = _run(db_session, provider)
    assert summary.windows_failed == 1 and "TimeoutError" in summary.stopped_reason
    failed = sync_history.load_plan(db_session, "payku")[0]
    assert (failed.status, failed.page, failed.last_error, failed.locked_by) == ("failed", 2, "TimeoutError", None)

    provider.fail_on = None
    skipped = _run(db_session, provider)  # la fallida se salta: sigue la siguiente
    assert [s[1] for s in _statuses(db_session)] == ["failed", "done"] and skipped.windows_done == 1
    retried = _run(db_session, provider, retry_failed=True)
    assert retried.windows_done == 1 and [s[1] for s in _statuses(db_session)] == ["done", "done"]


def test_ignored_date_filter_fails_the_window(db_session: Session) -> None:
    sync_history.save_plan(db_session, "payku", date(2020, 1, 1), date(2020, 1, 20))
    provider = FakeProvider(outside=True)
    summary = _run(db_session, provider)
    assert summary.windows_failed == 1 and provider.stored == []
    assert sync_history.load_plan(db_session, "payku")[0].last_error == "filtro de fecha ignorado por el proveedor"


def test_allowed_hours_block_requests_outside_the_slot(db_session: Session) -> None:
    sync_history.save_plan(db_session, "payku", date(2020, 1, 1), date(2020, 1, 20))
    provider = FakeProvider()
    summary = _run(db_session, provider, allowed_hours=sync_history.parse_hours("22-6"))  # 12:00 en Chile
    assert summary.requests == 0 and "franja" in summary.stopped_reason
    assert _statuses(db_session) == [(date(2020, 1, 1), "pending", 1)]
    assert sync_history.within_hours((22, 6), datetime(2026, 11, 2, 4, 0, tzinfo=UTC))  # 01:00 en Chile


def test_window_taken_by_another_run_is_skipped(db_session: Session) -> None:
    plan = sync_history.save_plan(db_session, "payku", date(2020, 1, 1), date(2020, 1, 20))
    plan[0].status, plan[0].locked_by = "running", "otra"
    plan[0].locked_until = datetime(2030, 1, 1, tzinfo=UTC)
    db_session.commit()
    assert _run(db_session, FakeProvider()).requests == 0


# ── Script: dry-run por defecto y confirmacion contra crm ──────────────────────────────────────────────


def _no_session():
    pytest.fail("el dry-run no debe abrir la base")


def test_script_dry_run_by_default_touches_nothing(capsys) -> None:
    code = script.main(["--channel", "toku", "--from", "2024-01-01", "--to", "2024-02-15"],
                       session_factory=_no_session, database_name=lambda: pytest.fail("no debe resolver la base"))
    out = capsys.readouterr().out
    assert code == 0 and "2 ventanas" in out and "DRY-RUN" in out


def test_script_aborts_against_crm_without_explicit_confirmation(capsys) -> None:
    for argv in (["--execute", "--from", "2020-01-01", "--to", "2020-02-01"], ["--resume"],
                 ["--execute", "--from", "2020-01-01", "--to", "2020-02-01", "--confirm-database", "crm_sandbox"]):
        code = script.main(["--channel", "payku", *argv], session_factory=_no_session, database_name=lambda: "crm")
        assert code == 2
    assert "PRODUCCION" in capsys.readouterr().err


def test_script_execute_and_resume_with_confirmation(db_session: Session, monkeypatch, capsys) -> None:
    provider = FakeProvider(pages=2)
    monkeypatch.setattr(db_session, "close", lambda: None)  # la sesion del test la cierra el fixture
    common = dict(session_factory=lambda: db_session, database_name=lambda: "crm_test_x",
                  spec_factory=lambda _c: provider.spec())
    monkeypatch.setattr(sync_history, "run_plan", _fixed_clock(sync_history.run_plan))
    code = script.main(["--channel", "payku", "--execute", "--from", "2020-01-01", "--to", "2020-02-29",
                        "--confirm-database", "crm_test_x", "--max-requests", "3", "--pause-seconds", "0"], **common)
    assert code == 0 and "Reanude con --resume" in capsys.readouterr().out
    code = script.main(["--channel", "payku", "--resume", "--confirm-database", "crm_test_x", "--pause-seconds", "0"],
                       **common)
    assert code == 0
    assert [s[1] for s in _statuses(db_session)] == ["done", "done"] and len(provider.calls) == 4
    assert script.main(["--channel", "payku", "--status"], **common) == 0
    assert "done" in capsys.readouterr().out


def _fixed_clock(run_plan):
    async def wrapped(*args, **kwargs):
        kwargs.setdefault("now_fn", lambda: NOON_UTC)
        kwargs.setdefault("sleep", _no_sleep)
        return await run_plan(*args, **kwargs)

    return wrapped


# ── Especificaciones reales (sin llamar al proveedor) ──────────────────────────────────────────────────


def test_real_specs_are_built_without_calling_providers() -> None:
    for channel, resource in (("virtualpos1", "payment"), ("virtualpos2", "payment"), ("toku", "transaction"),
                              ("payku", "transaction")):
        spec = sync_history.channel_spec(channel)
        assert spec.resource == resource and spec.date_fields


def test_payku_history_never_overwrites_known_transactions(db_session: Session) -> None:
    from app.models.payku_channel import PaykuTransaction

    db_session.add(PaykuTransaction(external_id="hist-pt1", subscription_id="hist-ps1", status="success",
                                    amount="3000", currency="CLP"))
    db_session.flush()
    spec = sync_history.channel_spec("payku")
    written = spec.store(db_session, [
        {"id": "hist-pt1", "status": "failed", "amount": 1, "created_at": "2020-01-02"},
        {"id": "hist-pt2", "status": "success", "amount": 2, "created_at": "2020-01-03"},
    ])
    assert written == 1
    known = db_session.scalars(select(PaykuTransaction).where(PaykuTransaction.external_id == "hist-pt1")).one()
    db_session.refresh(known)
    assert (known.subscription_id, known.status) == ("hist-ps1", "success")
    assert db_session.scalar(select(PaykuTransaction.id).where(PaykuTransaction.external_id == "hist-pt2"))
