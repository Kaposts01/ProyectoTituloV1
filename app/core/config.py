import os
from functools import lru_cache
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Ambientes validos. "development" y similares son alias historicos de produccion
# (el .env actual usa APP_ENV=development con credenciales reales).
NON_PRODUCTION_ENVS = ("sandbox", "qa")
LEGACY_PRODUCTION_ALIASES = ("production", "prod", "development", "dev", "local")

# Hosts documentados por proveedor (docs/integrations/...). Toku y Payku no tienen
# host de sandbox documentado para Toku; Payku usa des.payku.cl en su coleccion Postman.
PRODUCTION_HOSTS: dict[str, tuple[str, ...]] = {
    "virtualpos_base_url": ("api.virtualpos.cl",),
    "virtualpos2_base_url": ("api.virtualpos.cl",),
    "toku_base_url": ("api.trytoku.com",),
    "payku_base_url": ("app.payku.cl",),
}
SANDBOX_HOSTS: dict[str, tuple[str, ...]] = {
    "virtualpos_base_url": ("api.virtualpos-sandbox.com",),
    "virtualpos2_base_url": ("api.virtualpos-sandbox.com",),
    "toku_base_url": (),
    "payku_base_url": ("des.payku.cl",),
}


def _active_env_files() -> tuple[str, ...]:
    """`.env` siempre; `.env.<APP_ENV>` encima cuando APP_ENV es sandbox/qa (variable de proceso)."""
    mode = os.environ.get("APP_ENV", "").strip().lower()
    if mode in NON_PRODUCTION_ENVS:
        return (".env", f".env.{mode}")
    return (".env",)


def _host(url: str) -> str:
    return (urlparse(url.strip()).hostname or "").lower()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_active_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = "CRM Suscripciones"
    app_env: str = "production"
    debug: bool = False
    auth_jwt_secret: str = ""
    auth_access_token_minutes: int = 60
    initial_admin_username: str = ""
    initial_admin_password: str = ""
    database_url: str
    # VirtualPOS cuenta 1 (sandbox/producción)
    virtualpos_base_url: str = ""
    virtualpos_api_key: str = ""
    virtualpos_secret_key: str = ""
    virtualpos_timeout_seconds: float = 30
    virtualpos_read_retries: int = 2
    virtualpos_writes_enabled: bool = False
    # WR-VP-05: POST /v3/charge sobre planes MONTO_FIJO falla (E-113) segun la doc; no validado en sandbox.
    virtualpos_allow_charge_on_fixed_plan: bool = False
    virtualpos_payout_webhook_secret: str = ""
    # VirtualPOS cuenta 2 (producción)
    virtualpos2_base_url: str = ""
    virtualpos2_api_key: str = ""
    virtualpos2_secret_key: str = ""
    # Toku
    toku_base_url: str = ""
    toku_api_key: str = ""
    toku_account_key: str = ""
    toku_timeout_seconds: float = 30
    toku_read_retries: int = 2
    toku_writes_enabled: bool = False
    toku_webhook_secret: str = ""
    # Payku
    payku_base_url: str = ""
    payku_api_key: str = ""
    payku_secret_key: str = ""
    payku_public_token: str = ""
    payku_private_token: str = ""
    payku_date_init: str = "2025-01-01"
    payku_date_end: str = ""
    payku_timeout_seconds: float = 30
    payku_read_retries: int = 2
    payku_writes_enabled: bool = False
    payku_webhook_secret: str = ""

    @property
    def env_mode(self) -> str:
        """`production`, `sandbox` o `qa` (los alias historicos cuentan como production)."""
        mode = self.app_env.strip().lower()
        return mode if mode in NON_PRODUCTION_ENVS else "production"

    @property
    def is_production(self) -> bool:
        return self.env_mode == "production"

    def channel_enabled(self, channel: str) -> bool:
        """En sandbox/qa un canal sin URL propia queda deshabilitado (nunca cae a produccion)."""
        return bool(getattr(self, f"{channel}_base_url", "").strip())

    @model_validator(mode="after")
    def _guard_environment(self) -> "Settings":
        mode = self.app_env.strip().lower()
        if mode not in NON_PRODUCTION_ENVS and mode not in LEGACY_PRODUCTION_ALIASES:
            raise ValueError("APP_ENV invalido: use production, sandbox o qa")
        for field, hosts in PRODUCTION_HOSTS.items():
            host = _host(getattr(self, field))
            if not host:
                continue
            if self.is_production and host in SANDBOX_HOSTS[field]:
                raise ValueError(f"{field.upper()} apunta a sandbox pero APP_ENV es production")
            if not self.is_production and host in hosts:
                raise ValueError(
                    f"{field.upper()} apunta a produccion pero APP_ENV es {self.env_mode}"
                )
        if self.is_production:
            if not (self.virtualpos_base_url and self.virtualpos_api_key and self.virtualpos_secret_key):
                raise ValueError("VIRTUALPOS_BASE_URL/API_KEY/SECRET_KEY son obligatorias en production")
        else:
            db_name = (urlparse(self.database_url).path or "").lstrip("/").lower()
            if self.env_mode not in db_name:
                raise ValueError(
                    f"DATABASE_URL debe apuntar a una base cuyo nombre contenga '{self.env_mode}'"
                )
            # Canal sin URL de sandbox: deshabilitado, sin escrituras.
            for channel in ("virtualpos", "virtualpos2", "toku", "payku"):
                flag = f"{channel}_writes_enabled"
                if not self.channel_enabled(channel) and hasattr(self, flag):
                    setattr(self, flag, False)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
