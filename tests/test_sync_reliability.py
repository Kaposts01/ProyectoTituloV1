import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import etl
from app.db.session import SessionLocal
from app.models.etl_run import EtlRun
from app.scheduler import event_bus
from app.scheduler.jobs import sync_all


@pytest.mark.parametrize('path', ['/core/all', '/core/detect-matches', '/core/toku'])
def test_core_dispatches_static_and_provider_routes(monkeypatch, path):
    app = FastAPI()
    app.include_router(etl.router)
    for route in etl.router.routes:
        for dependency in route.dependencies:
            app.dependency_overrides[dependency.dependency] = lambda: None
    db = MagicMock()
    db.refresh.side_effect = lambda run: setattr(run, 'id', uuid.uuid4())
    monkeypatch.setattr(etl, '_get_db', lambda: db)
    task = MagicMock()
    monkeypatch.setattr(etl, '_run_core_etl_background', task)
    detector = MagicMock(return_value={'inserted': 0})
    monkeypatch.setattr(etl, 'detect_matches', detector)
    response = TestClient(app).post(path)
    assert response.status_code == 200
    if path == '/core/all':
        assert len(response.json()['run_ids']) == 4
        assert task.call_count == 4
    elif path.endswith('detect-matches'):
        detector.assert_called_once_with(db)
        task.assert_not_called()
    else:
        assert response.json()['provider'] == 'toku'
        assert task.call_count == 1


@pytest.mark.parametrize('orchestrator', ['scheduler', 'full_sync'])
@pytest.mark.parametrize('failure', [None, 'toku', 'consolidation'])
def test_orchestration_persists_honest_outcome(monkeypatch, caplog, orchestrator, failure):
    module = sync_all if orchestrator == 'scheduler' else etl
    good = AsyncMock(return_value=SimpleNamespace(records_processed=3))
    toku = AsyncMock(side_effect=RuntimeError('private-provider-secret')) if failure == 'toku' else good
    monkeypatch.setattr(sync_all, 'sync_toku', toku)
    monkeypatch.setattr(sync_all, 'sync_payku', good)
    monkeypatch.setattr(etl, '_SYNC_FN', {'toku': toku, 'payku': good})
    consolidate = MagicMock(side_effect=RuntimeError('private-provider-secret')) if failure == 'consolidation' else MagicMock(return_value=2)
    monkeypatch.setattr(module, 'consolidate_to_centralized', consolidate)
    run_id = uuid.uuid4()
    try:
        if orchestrator == 'full_sync':
            with SessionLocal() as db:
                db.add(EtlRun(id=run_id, status='running'))
                db.commit()
            asyncio.run(etl._run_full_sync_background(run_id, ['toku', 'payku']))
        else:
            asyncio.run(sync_all.sync_all_channels(str(run_id), ['toku', 'payku']))
        with SessionLocal() as db:
            run = db.get(EtlRun, run_id)
            assert run.status == ('failed' if failure else 'completed')
            assert run.finished_at is not None
            assert run.phase is None
            assert run.records_upserted == (5 if failure == 'toku' else 6 if failure == 'consolidation' else 8)
            assert run.channels_processed == (['payku'] if failure == 'toku' else ['toku', 'payku'])
            assert 'private-provider-secret' not in (run.error_message or '')
            if failure:
                assert run.error_message
        assert 'private-provider-secret' not in caplog.text
        if orchestrator == 'scheduler':
            bus = event_bus.get_bus(str(run_id))
            assert bus.done
            terminal = bus.events[-1]
            assert terminal['type'] == ('error' if failure else 'completed')
            if failure:
                assert terminal['phase'] == 'fatal'
            assert 'private-provider-secret' not in str(bus.events)
            if failure:
                intermediate = [e for e in bus.events[:-1] if e['type'] == 'error']
                assert intermediate and all(e['terminal'] is False for e in intermediate)
    finally:
        event_bus.cleanup_bus(str(run_id))
        with SessionLocal() as db:
            run = db.get(EtlRun, run_id)
            if run:
                db.delete(run)
                db.commit()


@pytest.mark.parametrize("path", ["/core/all", "/core/detect-matches", "/core/toku"])
def test_core_routes_require_authentication(path):
    app = FastAPI()
    app.include_router(etl.router)
    assert TestClient(app).post(path).status_code == 401


def test_full_sync_rejects_empty_provider_selection():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        etl.FullSyncRequest(providers=[])
