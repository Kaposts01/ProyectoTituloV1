import asyncio

import pytest
from pydantic import ValidationError

from app.core.config import Settings

DB = "postgresql+psycopg://u:p@localhost/crm"
SDB = "postgresql+psycopg://u:p@localhost/crm_sandbox"
PROD = {
    "database_url": DB,
    "virtualpos_base_url": "https://api.virtualpos.cl",
    "virtualpos_api_key": "prod-vk",
    "virtualpos_secret_key": "prod-vs",
    "virtualpos2_base_url": "https://api.virtualpos.cl",
    "virtualpos2_api_key": "prod-v2k",
    "virtualpos2_secret_key": "prod-v2s",
    "toku_base_url": "https://api.trytoku.com",
    "toku_api_key": "prod-tk",
    "toku_account_key": "prod-ta",
    "toku_writes_enabled": True,
    "payku_base_url": "https://app.payku.cl",
    "payku_public_token": "prod-pp",
    "payku_private_token": "prod-pq",
}
SBX = {
    "sandbox_database_url": SDB,
    "virtualpos_sandbox_base_url": "https://api.virtualpos-sandbox.com",
    "virtualpos_sandbox_api_key": "sbx-vk",
    "virtualpos_sandbox_secret_key": "sbx-vs",
    "toku_base_sandbox_url": "https://api.trytoku.com",
    "toku_sandbox_api_key": "sbx-tk",
    "toku_sandbox_account_key": "sbx-ta",
}


def make(**kw) -> Settings:
    return Settings(_env_file=None, **{**PROD, **kw})


def sandbox(env: str = "sandbox", drop: tuple[str, ...] = (), **kw) -> Settings:
    base = {k: v for k, v in {**PROD, **SBX, "app_env": env}.items() if k not in drop}
    return Settings(_env_file=None, **{**base, **kw})


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)


def test_production_default_ignores_sandbox_vars() -> None:
    s = make(**SBX, virtualpos_sandbox_writes_enabled=True)
    assert s.is_production and s.database_url == DB
    assert s.virtualpos_api_key == "prod-vk" and s.virtualpos2_api_key == "prod-v2k"
    assert s.toku_api_key == "prod-tk" and s.toku_writes_enabled is True
    assert s.virtualpos_writes_enabled is False and s.channel_enabled("virtualpos2")


def test_legacy_development_is_production() -> None:
    assert make(app_env="development").is_production


def test_invalid_env_rejected() -> None:
    with pytest.raises(ValidationError, match="APP_ENV"):
        make(app_env="staging")


def test_production_rejects_sandbox_url_naming_variable() -> None:
    with pytest.raises(ValidationError, match="VIRTUALPOS2_BASE_URL") as e:
        make(virtualpos2_base_url="https://api.virtualpos-sandbox.com")
    assert "virtualpos-sandbox" not in str(e.value)


@pytest.mark.parametrize("env", ["sandbox", "qa"])
def test_sandbox_takes_only_sandbox_vars(env: str) -> None:
    s = sandbox(env, virtualpos_sandbox_writes_enabled=True)
    assert s.env_mode == env and s.database_url == SDB
    assert s.virtualpos_base_url == SBX["virtualpos_sandbox_base_url"]
    assert s.virtualpos_api_key == "sbx-vk" and s.virtualpos_secret_key == "sbx-vs"
    assert s.toku_api_key == "sbx-tk" and s.toku_account_key == "sbx-ta"
    assert s.virtualpos_writes_enabled is True
    assert s.channel_enabled("virtualpos") and s.channel_enabled("toku")


def test_virtualpos2_always_disabled_in_sandbox() -> None:
    s = sandbox()
    assert not s.channel_enabled("virtualpos2")
    assert s.virtualpos2_base_url == s.virtualpos2_api_key == s.virtualpos2_secret_key == ""


def test_channel_without_sandbox_vars_disabled_and_writes_false() -> None:
    s = sandbox(
        payku_sandbox_writes_enabled=True,
        toku_sandbox_writes_enabled=True,
        drop=("toku_base_sandbox_url", "toku_sandbox_api_key"),
    )
    assert not s.channel_enabled("payku") and not s.channel_enabled("toku")
    assert s.payku_writes_enabled is False and s.toku_writes_enabled is False
    assert s.payku_base_url == "" and s.toku_api_key == ""  # sin fallback a produccion


def test_writes_default_false() -> None:
    s = sandbox()
    assert not (s.virtualpos_writes_enabled or s.toku_writes_enabled or s.payku_writes_enabled)


def test_guard_a_sandbox_database() -> None:
    with pytest.raises(ValidationError, match="SANDBOX_DATABASE_URL"):
        sandbox(drop=("sandbox_database_url",))
    with pytest.raises(ValidationError, match="SANDBOX_DATABASE_URL"):
        sandbox(sandbox_database_url="postgresql+psycopg://u:p@localhost/crm_prod")
    with pytest.raises(ValidationError, match="SANDBOX_DATABASE_URL"):
        sandbox(database_url=SDB)


def test_guard_b_virtualpos_sandbox_not_production_host() -> None:
    with pytest.raises(ValidationError, match="VIRTUALPOS_SANDBOX_BASE_URL") as e:
        sandbox(virtualpos_sandbox_base_url="https://api.virtualpos.cl")
    assert "api.virtualpos.cl" not in str(e.value)


def test_guard_c_toku_same_host_ok_with_sandbox_vars() -> None:
    s = sandbox()
    assert s.toku_base_url == "https://api.trytoku.com" and s.channel_enabled("toku")


@pytest.mark.parametrize(
    ("name", "sbx_field", "prod_field"),
    [
        ("VIRTUALPOS_SANDBOX_API_KEY", "virtualpos_sandbox_api_key", "virtualpos_api_key"),
        ("VIRTUALPOS_SANDBOX_SECRET_KEY", "virtualpos_sandbox_secret_key", "virtualpos_secret_key"),
        ("TOKU_SANDBOX_API_KEY", "toku_sandbox_api_key", "toku_api_key"),
        ("TOKU_SANDBOX_ACCOUNT_KEY", "toku_sandbox_account_key", "toku_account_key"),
        ("PAYKU_SANDBOX_PUBLIC_TOKEN", "payku_sandbox_public_token", "payku_public_token"),
        ("PAYKU_SANDBOX_PRIVATE_TOKEN", "payku_sandbox_private_token", "payku_private_token"),
    ],
)
def test_guard_c_sandbox_key_equal_to_production_rejected(name: str, sbx_field: str, prod_field: str) -> None:
    with pytest.raises(ValidationError, match=name) as e:
        sandbox(**{sbx_field: PROD[prod_field]})
    assert PROD[prod_field] not in str(e.value)


def test_guard_d_payku_sandbox_not_production_host() -> None:
    with pytest.raises(ValidationError, match="PAYKU_SANDBOX_BASE_URL"):
        sandbox(payku_sandbox_base_url="https://app.payku.cl")
    assert sandbox(payku_sandbox_base_url="https://des.payku.cl").payku_base_url == "https://des.payku.cl"


@pytest.mark.parametrize("field", ["virtualpos_base_url", "virtualpos2_base_url", "payku_base_url"])
def test_guard_e_production_rejects_sandbox_hosts(field: str) -> None:
    url = "https://des.payku.cl" if field == "payku_base_url" else "https://api.virtualpos-sandbox.com"
    with pytest.raises(ValidationError, match=field.upper()) as e:
        make(**{field: url})
    assert url.split("//")[1] not in str(e.value)


def test_sync_all_skips_disabled_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.scheduler.jobs import sync_all

    monkeypatch.setattr(sync_all, "settings", sandbox(drop=("toku_base_sandbox_url", "toku_sandbox_api_key")))
    assert sync_all.skip_disabled_channel("virtualpos2") is True
    assert sync_all.skip_disabled_channel("toku") is True
    assert sync_all.skip_disabled_channel("payku") is True
    assert sync_all.skip_disabled_channel("virtualpos1") is False

    calls: list[str] = []

    async def boom(*_a, **_k):
        calls.append("called")
        raise RuntimeError("no debe llamarse")

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
            return None

    monkeypatch.setattr(sync_all, "SessionLocal", FakeDb)
    monkeypatch.setattr(sync_all, "sync_toku", boom)
    monkeypatch.setattr(sync_all, "sync_payku", boom)
    monkeypatch.setattr(sync_all, "consolidate_to_centralized", lambda *_a, **_k: 0)
    asyncio.run(sync_all.sync_all_channels(channels=["toku", "payku", "virtualpos2"]))
    assert calls == []
