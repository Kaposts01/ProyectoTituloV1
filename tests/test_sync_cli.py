import asyncio
import importlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.parametrize('module_name', ['scripts.sync_toku', 'scripts.sync_virtualpos'])
def test_sync_cli_calls_current_consolidation(monkeypatch, module_name):
    module = importlib.import_module(module_name)
    db = MagicMock()
    monkeypatch.setattr(module, 'SessionLocal', lambda: db)
    channel = 'toku' if module_name.endswith('toku') else 'virtualpos'
    monkeypatch.setattr(module, 'sync_' + channel, AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4(), records_processed=3)))
    consolidate = MagicMock(return_value=3)
    monkeypatch.setattr(module, 'consolidate_to_centralized', consolidate)
    monkeypatch.setattr(module.sys, 'argv', [module_name] + (['virtualpos1'] if channel == 'virtualpos' else []))
    asyncio.run(module.main())
    consolidate.assert_called_once_with(db.__enter__.return_value, [channel])
