import pytest
from pydantic import ValidationError

from app.core.config import Settings

DB = "postgresql+psycopg://u:p@localhost/crm"


def make(**kw) -> Settings:
    base = {
        "database_url": DB,
        "virtualpos_base_url": "https://api.virtualpos.cl",
        "virtualpos_api_key": "k",
        "virtualpos_secret_key": "s",
    }
    base.update(kw)
    return Settings(_env_file=None, **base)


def sandbox(**kw) -> Settings:
    base = {
        "app_env": "sandbox",
        "database_url": DB + "_sandbox",
        "virtualpos_base_url": "https://api.virtualpos-sandbox.com",
        "virtualpos_api_key": "k",
        "virtualpos_secret_key": "s",
    }
    base.update(kw)
    return Settings(_env_file=None, **base)


def test_production_default_unchanged() -> None:
    s = make(toku_base_url="https://api.trytoku.com", payku_base_url="https://app.payku.cl")
    assert s.app_env == "production" and s.is_production


def test_legacy_development_is_production() -> None:
    assert make(app_env="development").is_production


def test_invalid_env_rejected() -> None:
    with pytest.raises(ValidationError, match="APP_ENV"):
        make(app_env="staging")


def test_production_rejects_sandbox_url_naming_variable() -> None:
    with pytest.raises(ValidationError, match="VIRTUALPOS2_BASE_URL") as e:
        make(virtualpos2_base_url="https://api.virtualpos-sandbox.com")
    assert "virtualpos-sandbox" not in str(e.value)


@pytest.mark.parametrize(
    ("field", "url"),
    [
        ("virtualpos_base_url", "https://api.virtualpos.cl"),
        ("virtualpos2_base_url", "https://api.virtualpos.cl"),
        ("toku_base_url", "https://api.trytoku.com"),
        ("payku_base_url", "https://app.payku.cl"),
    ],
)
@pytest.mark.parametrize("env", ["sandbox", "qa"])
def test_non_production_rejects_production_urls(env: str, field: str, url: str) -> None:
    with pytest.raises(ValidationError, match=field.upper()) as e:
        sandbox(app_env=env, database_url=DB + f"_{env}", **{field: url})
    assert "trytoku.com" not in str(e.value) and "api.virtualpos.cl" not in str(e.value)


def test_sandbox_ok_and_db_name_guard() -> None:
    assert sandbox().env_mode == "sandbox"
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        sandbox(database_url=DB)


def test_missing_sandbox_url_disables_channel_and_writes() -> None:
    s = sandbox(toku_writes_enabled=True, payku_writes_enabled=True)
    assert not s.channel_enabled("toku") and not s.channel_enabled("payku")
    assert s.channel_enabled("virtualpos")
    assert s.toku_writes_enabled is False and s.payku_writes_enabled is False


def test_writes_default_false() -> None:
    s = sandbox()
    assert not (s.virtualpos_writes_enabled or s.toku_writes_enabled or s.payku_writes_enabled)
    p = make()
    assert not (p.virtualpos_writes_enabled or p.toku_writes_enabled or p.payku_writes_enabled)
