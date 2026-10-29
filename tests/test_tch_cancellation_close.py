# ruff: noqa: F811  (fixtures importadas de cancellation_support: db_session)
"""MGT: la importacion del Excel de TCH cierra las bajas `pending_external` cuya ficha viene eliminada en el reporte."""

import pytest
from cancellation_support import (
    approved_request,
    db_session,  # noqa: F401 - fixture
    make_roles,
    make_user,
    seed_tch,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.cancellation import SubscriptionCancellationRequest
from app.models.tch import TchSubscription
from scripts import etl_tch


def _factory(db):
    return lambda: Session(bind=db.get_bind(), join_transaction_mode="create_savepoint")


def _pending_request(db, ficha: int):
    seed_tch(db, ficha)
    jefa = make_user(db, make_roles(db)["jefatura"])
    req = approved_request(db, jefa, "tch", str(ficha))
    req.status = "pending_external"
    db.commit()
    return req.id


def _status(db, req_id):
    db.expire_all()
    return db.get(SubscriptionCancellationRequest, req_id).status


@pytest.fixture
def importer(db_session, monkeypatch, tmp_path):
    """Importa un reporte sintetico: `_process_file` es falso y, si `eliminar`, marca la ficha como eliminada."""
    monkeypatch.setattr(etl_tch, "SessionLocal", _factory(db_session))
    monkeypatch.setattr(etl_tch, "_apply_implicit_cancellations", lambda db, fichas: 0)
    monkeypatch.setattr(etl_tch, "_has_legacy_dedupe_keys", lambda db: False)
    counter = {"n": 0}

    def run(ficha: int, eliminar: bool):
        def fake_process(path, db):
            if eliminar:
                row = db.scalar(select(TchSubscription).where(TchSubscription.file_number == ficha))
                row.deletion_date = "2026-11-03"
                db.flush()
            return {"sus_ins": 0, "sus_upd": 1, "trans": 0, "controles": 0, "fichas": set(), "err": 0}

        monkeypatch.setattr(etl_tch, "_process_file", fake_process)
        counter["n"] += 1
        xlsx = tmp_path / f"2026093{counter['n']} TCH IG SEPTIEMBRE 2026.xlsx"
        xlsx.write_bytes(f"sintetico-{counter['n']}".encode())
        return etl_tch.import_incremental_file(xlsx)

    return run


def test_import_closes_a_pending_external_request_when_the_ficha_is_eliminated(db_session, importer):
    req_id = _pending_request(db_session, 910201)
    importer(910201, eliminar=True)
    assert _status(db_session, req_id) == "completed"


def test_import_leaves_the_request_in_process_when_the_ficha_is_not_eliminated(db_session, importer):
    req_id = _pending_request(db_session, 910202)
    importer(910202, eliminar=False)
    assert _status(db_session, req_id) == "pending_external"


def test_a_failure_while_closing_does_not_undo_the_import(db_session, importer, monkeypatch):
    from app.services import cancellation_apply

    _pending_request(db_session, 910203)

    def boom(db, **kw):
        raise RuntimeError("fallo al cerrar")

    monkeypatch.setattr(cancellation_apply, "close_tch_cancellations_from_report", boom)
    assert importer(910203, eliminar=True) == 1  # la importacion termina bien (total = 1 suscripcion actualizada)
    row = db_session.scalar(select(TchSubscription).where(TchSubscription.file_number == 910203))
    assert row.deletion_date == "2026-11-03"


def test_script_main_incremental_calls_the_closer(monkeypatch):
    """El script (`main`, modo incremental) tambien llama al cierre tras cargar el archivo."""
    import inspect

    src = inspect.getsource(etl_tch.main)
    assert "_close_cancellations_from_report" in src
