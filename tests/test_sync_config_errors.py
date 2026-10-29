"""SYNC-D-09 / VP-PAR-01 / PK-PAR-01: errores de configuracion, estado del run y reintentos."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.channel_errors import CONFIG_ERROR_PREFIX, ChannelConfigError
from app.core.config import Settings
from app.models.etl_run import EtlRun
from tests.test_config_environments import PROD, make

# --- config: alias de variables en produccion ---------------------------------------------------


def test_production_payku_falls_back_to_public_private_tokens() -> None:
    cfg = make()
    assert cfg.payku_api_key == "prod-pp"
    assert cfg.payku_secret_key == "prod-pq"


def test_production_payku_explicit_keys_win() -> None:
    cfg = make(payku_api_key="explicit-k", payku_secret_key="explicit-s")
    assert (cfg.payku_api_key, cfg.payku_secret_key) == ("explicit-k", "explicit-s")


def test_production_vp2_base_url_falls_back_to_account1_when_keys_present() -> None:
    values = {k: v for k, v in PROD.items() if k != "virtualpos2_base_url"}
    cfg = Settings(_env_file=None, **values)
    assert cfg.virtualpos2_base_url == cfg.virtualpos_base_url


def test_production_vp2_without_keys_stays_unconfigured() -> None:
    values = {k: v for k, v in PROD.items() if not k.startswith("virtualpos2")}
    cfg = Settings(_env_file=None, **values)
    assert cfg.virtualpos2_base_url == ""


# --- clientes: error de configuracion tipado ----------------------------------------------------


def test_vp_client_unconfigured_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.virtualpos import client as vp_client

    monkeypatch.setattr(
        vp_client,
        "settings",
        SimpleNamespace(
            virtualpos2_base_url="",
            virtualpos2_api_key="valor-secreto",
            virtualpos2_secret_key="otro-secreto",
            virtualpos_timeout_seconds=5,
        ),
    )
    with pytest.raises(ChannelConfigError) as exc:
        vp_client.VirtualPOSClient("virtualpos2")
    message = str(exc.value)
    assert message.startswith(CONFIG_ERROR_PREFIX)
    assert "VIRTUALPOS2_BASE_URL" in message
    assert "VIRTUALPOS2_API_KEY" not in message  # solo se listan las variables que faltan
    assert "valor-secreto" not in message and "otro-secreto" not in message


def test_payku_client_empty_key_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.payku import client as pk_client

    monkeypatch.setattr(
        pk_client,
        "settings",
        SimpleNamespace(
            is_production=True,
            payku_api_key="  ",
            payku_secret_key="",
            payku_base_url="https://app.payku.cl",
            payku_timeout_seconds=5,
        ),
    )
    with pytest.raises(ChannelConfigError) as exc:
        pk_client.PaykuClient()
    assert "PAYKU_API_KEY" in str(exc.value)


# --- sync_all: estado del run -------------------------------------------------------------------


def _fake_db_factory(store: dict):
    class FakeDb:
        def scalar(self, *_a, **_k):
            return None

        def add(self, obj):
            store["run"] = obj

        def commit(self):
            pass

        def close(self):
            pass

        def get(self, *_a):
            return store["run"]

    return FakeDb


def _patch_sync_all(monkeypatch, store, *, vp2_error):
    from app.scheduler.jobs import sync_all

    monkeypatch.setattr(sync_all, "SessionLocal", _fake_db_factory(store))
    monkeypatch.setattr(sync_all, "skip_disabled_channel", lambda _c: False)
    monkeypatch.setattr(sync_all, "consolidate_to_centralized", lambda *_a, **_k: 0)

    async def vp(_db, platform, _cb=None):
        if platform == "virtualpos2":
            raise vp2_error
        return SimpleNamespace(records_processed=3)

    async def ok(_db, _cb=None):
        return SimpleNamespace(records_processed=2)

    monkeypatch.setattr(sync_all, "sync_virtualpos", vp)
    monkeypatch.setattr(sync_all, "sync_toku", ok)
    monkeypatch.setattr(sync_all, "sync_payku", ok)
    return sync_all


def test_config_failure_marks_run_partial_and_keeps_other_channels(monkeypatch) -> None:
    store: dict = {}
    sync_all = _patch_sync_all(
        monkeypatch, store, vp2_error=ChannelConfigError("VirtualPOS virtualpos2 no configurado")
    )
    asyncio.run(sync_all.sync_all_channels(channels=["virtualpos1", "virtualpos2", "toku", "payku"]))
    run = store["run"]
    assert run.status == "partial"
    assert run.channels_failed == ["virtualpos2"]
    assert run.channels_processed == ["virtualpos1", "toku", "payku"]
    assert "virtualpos2" in run.error_message
    assert "configuracion" in run.error_message.lower()


def test_all_channels_failing_marks_run_failed(monkeypatch) -> None:
    store: dict = {}
    sync_all = _patch_sync_all(monkeypatch, store, vp2_error=RuntimeError("x"))
    asyncio.run(sync_all.sync_all_channels(channels=["virtualpos2"]))
    assert store["run"].status == "failed"
    assert store["run"].channels_failed == ["virtualpos2"]


def test_no_failures_stays_completed(monkeypatch) -> None:
    store: dict = {}
    sync_all = _patch_sync_all(monkeypatch, store, vp2_error=RuntimeError("no se usa"))
    asyncio.run(sync_all.sync_all_channels(channels=["virtualpos1", "toku"]))
    assert store["run"].status == "completed"
    assert not store["run"].channels_failed


# --- retry: no reintenta errores de configuracion -----------------------------------------------


def _retry_db(last: EtlRun, latest_errors: list[tuple[str, str]]):
    class Db:
        def __init__(self) -> None:
            self.queue = [None, last]

        def scalar(self, *_a, **_k):
            return self.queue.pop(0)

        def execute(self, *_a, **_k):
            return latest_errors

        def close(self):
            pass

    return Db()


def test_retry_skips_config_failed_channels() -> None:
    from app.scheduler.jobs import retry_failed

    last = EtlRun(status="partial")
    last.channels_failed = ["virtualpos2", "toku"]
    db = _retry_db(last, [("virtualpos2", f"{CONFIG_ERROR_PREFIX}: VIRTUALPOS2_BASE_URL"), ("toku", "ReadTimeout")])
    with patch.object(retry_failed, "SessionLocal", return_value=db):
        with patch("app.scheduler.jobs.sync_all.sync_all_channels", AsyncMock()) as m:
            asyncio.run(retry_failed.retry_failed_channels())
    m.assert_called_once_with(channels=["toku"])


def test_retry_does_nothing_if_only_config_failures() -> None:
    from app.scheduler.jobs import retry_failed

    last = EtlRun(status="partial")
    last.channels_failed = ["payku"]
    db = _retry_db(last, [("payku", f"{CONFIG_ERROR_PREFIX}: PAYKU_API_KEY")])
    with patch.object(retry_failed, "SessionLocal", return_value=db):
        with patch("app.scheduler.jobs.sync_all.sync_all_channels", AsyncMock()) as m:
            asyncio.run(retry_failed.retry_failed_channels())
    m.assert_not_called()
