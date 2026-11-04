"""REV-01: piezas de confiabilidad tomadas de origin/sprint-5/estabilizacion-dashboard (1005a26).

- Un error fatal de la orquestacion no copia el texto de la excepcion a la corrida ni al SSE y conserva lo avanzado.
- `/etl/full-sync` rechaza una lista vacia de proveedores.
- Las rutas fijas `/etl/core/all` y `/etl/core/detect-matches` no las captura `/etl/core/{provider}`.
- Los scripts de sync por consola llaman a la consolidacion vigente.

Lo que contradice decisiones posteriores (p. ej. `failed` en vez de `partial`, d139b) no se trajo.
"""

import asyncio
import importlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.routes import etl
from app.scheduler import event_bus
from tests.test_sync_config_errors import _patch_sync_all

SECRET = "private-provider-secret"


def test_scheduler_fatal_error_keeps_progress_and_never_stores_the_exception_text(monkeypatch) -> None:
    store: dict = {}
    sync_all = _patch_sync_all(monkeypatch, store, vp2_error=RuntimeError("no se usa"))

    def explode(channel: str) -> bool:
        if channel == "payku":
            raise RuntimeError(SECRET)
        return False

    monkeypatch.setattr(sync_all, "skip_disabled_channel", explode)
    events: list[dict] = []
    monkeypatch.setattr(sync_all.event_bus, "emit", lambda _rid, event: events.append(event))
    asyncio.run(sync_all.sync_all_channels(channels=["toku", "payku"]))
    run = store["run"]
    event_bus.cleanup_bus(str(run.id))
    assert run.status == "failed"
    assert run.channels_processed == ["toku"]
    assert run.records_upserted == 2
    assert run.error_message == "Error durante la sincronización."
    assert SECRET not in str(events)
    assert events[-1] == {"type": "error", "phase": "fatal", "msg": "Error durante la sincronización."}


def test_full_sync_fatal_error_keeps_progress(monkeypatch) -> None:
    updates: list[dict] = []
    monkeypatch.setattr(etl, "_update_run", lambda _run_id, **fields: updates.append(fields))
    monkeypatch.setattr(etl, "_SYNC_FN", {"toku": AsyncMock(return_value=SimpleNamespace(records_processed=4))})
    monkeypatch.setattr(etl, "settings", SimpleNamespace(channel_enabled=lambda _c: True, env_mode="test"))
    monkeypatch.setattr(etl, "SessionLocal", MagicMock())
    monkeypatch.setattr(etl, "consolidate_to_centralized", MagicMock(side_effect=RuntimeError(SECRET)))

    asyncio.run(etl._run_full_sync_background(uuid.uuid4(), ["toku"]))

    final = updates[-1]
    assert final["status"] == "failed"
    assert final["channels_processed"] == ["toku"]
    assert final["records_upserted"] == 4
    assert SECRET not in str(final)


def test_full_sync_rejects_empty_provider_selection() -> None:
    with pytest.raises(ValidationError):
        etl.FullSyncRequest(providers=[])
    assert etl.FullSyncRequest().providers  # por defecto, todos


@pytest.mark.parametrize(
    ("path", "endpoint"),
    [("/core/all", "trigger_core_etl_all"), ("/core/detect-matches", "trigger_detect_matches"), ("/core/toku", "trigger_core_etl")],
)
def test_core_static_routes_are_not_captured_by_the_provider_route(path, endpoint) -> None:
    from starlette.routing import Match

    scope = {"type": "http", "path": path, "method": "POST"}
    first = next(route for route in etl.router.routes if route.matches(scope)[0] == Match.FULL)
    assert first.endpoint.__name__ == endpoint


@pytest.mark.parametrize("path", ["/core/all", "/core/detect-matches", "/core/toku"])
def test_core_routes_require_authentication(path) -> None:
    app = FastAPI()
    app.include_router(etl.router)
    assert TestClient(app, base_url="https://testserver").post(path).status_code == 401


@pytest.mark.parametrize("module_name", ["scripts.sync_toku", "scripts.sync_virtualpos"])
def test_sync_cli_calls_current_consolidation(monkeypatch, module_name) -> None:
    module = importlib.import_module(module_name)
    db = MagicMock()
    monkeypatch.setattr(module, "SessionLocal", lambda: db)
    channel = "toku" if module_name.endswith("toku") else "virtualpos"
    monkeypatch.setattr(module, "sync_" + channel, AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4(), records_processed=3)))
    consolidate = MagicMock(return_value=3)
    monkeypatch.setattr(module, "consolidate_to_centralized", consolidate)
    monkeypatch.setattr(module.sys, "argv", [module_name] + (["virtualpos1"] if channel == "virtualpos" else []))
    asyncio.run(module.main())
    consolidate.assert_called_once_with(db.__enter__.return_value, [channel])
