import logging
from functools import lru_cache
from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Ambientes validos. "development" y similares son alias historicos de produccion
# (el .env actual usa APP_ENV=development con credenciales reales).
NON_PRODUCTION_ENVS = ("sandbox", "qa")
LEGACY_PRODUCTION_ALIASES = ("production", "prod", "development", "dev", "local")

# Hosts por proveedor (docs/integrations/...). Toku usa el mismo host en sandbox y produccion
# (se distingue solo por las llaves); Payku aun no tiene sandbox confirmado.
VP_PRODUCTION_HOST = "api.virtualpos.cl"
VP_SANDBOX_HOST = "api.virtualpos-sandbox.com"
PAYKU_PRODUCTION_HOST = "app.payku.cl"
TOKU_HOST = "api.trytoku.com"  # mismo host en sandbox y produccion
PRODUCTION_HOSTS: dict[str, tuple[str, ...]] = {
    "virtualpos_base_url": (VP_PRODUCTION_HOST,),
    "virtualpos2_base_url": (VP_PRODUCTION_HOST,),
    "payku_base_url": (PAYKU_PRODUCTION_HOST,),
}
# Hosts de sandbox conocidos que una URL de produccion nunca debe usar.
SANDBOX_HOSTS: dict[str, tuple[str, ...]] = {
    "virtualpos_base_url": (VP_SANDBOX_HOST,),
    "virtualpos2_base_url": (VP_SANDBOX_HOST,),
    "toku_base_url": (),
    "payku_base_url": ("des.payku.cl",),
}


log = logging.getLogger(__name__)


def _host(url: str) -> str:
    return (urlparse(url.strip()).hostname or "").lower()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
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
    # Solo con APP_ENV=sandbox/qa: reemplazan a las variables de produccion (nunca fallback).
    sandbox_database_url: str = ""
    # URLs del selector de ambiente (solo navegacion) y scheduler en sandbox/qa.
    sandbox_app_url: str = ""
    production_app_url: str = ""
    sandbox_scheduler_enabled: bool = False
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
    virtualpos_sandbox_base_url: str = ""
    virtualpos_sandbox_api_key: str = ""
    virtualpos_sandbox_secret_key: str = ""
    virtualpos_sandbox_writes_enabled: bool = False
    # VirtualPOS cuenta 2 (solo produccion; en sandbox siempre vacia)
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
    toku_base_sandbox_url: str = ""
    toku_sandbox_api_key: str = ""
    toku_sandbox_account_key: str = ""
    toku_sandbox_writes_enabled: bool = False
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
    payku_sandbox_base_url: str = ""
    payku_sandbox_public_token: str = ""
    payku_sandbox_private_token: str = ""
    payku_sandbox_writes_enabled: bool = False

    @property
    def env_mode(self) -> str:
        """`production`, `sandbox` o `qa` (los alias historicos cuentan como production)."""
        mode = self.app_env.strip().lower()
        return mode if mode in NON_PRODUCTION_ENVS else "production"

    @property
    def is_production(self) -> bool:
        return self.env_mode == "production"

    def channel_enabled(self, channel: str) -> bool:
        """Produccion: siempre habilitado. Sandbox/qa: solo si el canal tiene sus variables sandbox."""
        if self.is_production:
            return True
        if channel == "virtualpos":
            return bool(self.virtualpos_base_url and self.virtualpos_api_key and self.virtualpos_secret_key)
        if channel == "toku":
            return bool(self.toku_base_url and self.toku_api_key)
        if channel == "payku":
            return bool(self.payku_base_url and self.payku_api_key and self.payku_secret_key)
        return False  # virtualpos2 y cualquier otro: no existen en sandbox

    @model_validator(mode="after")
    def _guard_environment(self) -> "Settings":
        mode = self.app_env.strip().lower()
        if mode not in NON_PRODUCTION_ENVS and mode not in LEGACY_PRODUCTION_ALIASES:
            raise ValueError("APP_ENV invalido: use production, sandbox o qa")
        if self.is_production:
            for field, hosts in SANDBOX_HOSTS.items():
                if _host(getattr(self, field)) in hosts:
                    raise ValueError(f"{field.upper()} apunta a sandbox pero APP_ENV es production")
            if not (self.virtualpos_base_url and self.virtualpos_api_key and self.virtualpos_secret_key):
                raise ValueError("VIRTUALPOS_BASE_URL/API_KEY/SECRET_KEY son obligatorias en production")
            return self
        self._guard_sandbox()
        self._apply_sandbox()
        return self

    def _guard_sandbox(self) -> None:
        env = self.env_mode
        if not self.sandbox_database_url.strip():
            raise ValueError("SANDBOX_DATABASE_URL es obligatoria cuando APP_ENV es sandbox o qa")
        db_name = (urlparse(self.sandbox_database_url).path or "").lstrip("/").lower()
        if "sandbox" not in db_name and "qa" not in db_name:
            raise ValueError("SANDBOX_DATABASE_URL debe apuntar a una base cuyo nombre contenga 'sandbox' o 'qa'")
        if self.sandbox_database_url.strip() == self.database_url.strip():
            raise ValueError("SANDBOX_DATABASE_URL no puede ser igual a DATABASE_URL")
        if _host(self.virtualpos_sandbox_base_url) == VP_PRODUCTION_HOST:
            raise ValueError(f"VIRTUALPOS_SANDBOX_BASE_URL apunta a produccion pero APP_ENV es {env}")
        if _host(self.payku_sandbox_base_url) == PAYKU_PRODUCTION_HOST:
            raise ValueError(f"PAYKU_SANDBOX_BASE_URL apunta a produccion pero APP_ENV es {env}")
        # Toku comparte host con produccion: se distingue solo por las llaves. El host debe ser EXACTAMENTE
        # el de Toku (https, sin credenciales en la URL) para que ninguna URL ajena reciba la llave.
        if self.toku_base_sandbox_url.strip():
            parsed = urlparse(self.toku_base_sandbox_url.strip())
            if (
                parsed.scheme != "https"
                or (parsed.hostname or "").lower() != TOKU_HOST
                or parsed.username is not None
                or parsed.port not in (None, 443)
            ):
                raise ValueError(f"TOKU_BASE_SANDBOX_URL debe ser https con el host exacto de Toku ({TOKU_HOST})")
            log.warning(
                "Toku comparte host con produccion (%s): el sandbox se distingue solo por llaves "
                "y no hay aislamiento verificado; las escrituras estan protegidas por guardas duras.",
                TOKU_HOST,
            )
        pairs = (
            ("VIRTUALPOS_SANDBOX_API_KEY", self.virtualpos_sandbox_api_key, self.virtualpos_api_key),
            ("VIRTUALPOS_SANDBOX_SECRET_KEY", self.virtualpos_sandbox_secret_key, self.virtualpos_secret_key),
            ("TOKU_SANDBOX_API_KEY", self.toku_sandbox_api_key, self.toku_api_key),
            ("TOKU_SANDBOX_ACCOUNT_KEY", self.toku_sandbox_account_key, self.toku_account_key),
            ("PAYKU_SANDBOX_PUBLIC_TOKEN", self.payku_sandbox_public_token, self.payku_public_token),
            ("PAYKU_SANDBOX_PRIVATE_TOKEN", self.payku_sandbox_private_token, self.payku_private_token),
        )
        for name, sandbox_value, prod_value in pairs:
            if sandbox_value.strip() and sandbox_value.strip() == prod_value.strip():
                raise ValueError(f"{name} es igual a su equivalente de produccion")

    def _apply_sandbox(self) -> None:
        """Reemplaza los campos efectivos solo con variables *_SANDBOX_* (sin fallback a produccion)."""
        self.database_url = self.sandbox_database_url.strip()
        self.virtualpos_base_url = self.virtualpos_sandbox_base_url
        self.virtualpos_api_key = self.virtualpos_sandbox_api_key
        self.virtualpos_secret_key = self.virtualpos_sandbox_secret_key
        self.virtualpos_writes_enabled = self.virtualpos_sandbox_writes_enabled
        self.virtualpos_allow_charge_on_fixed_plan = (
            self.virtualpos_allow_charge_on_fixed_plan and self.virtualpos_sandbox_writes_enabled
        )
        self.virtualpos2_base_url = self.virtualpos2_api_key = self.virtualpos2_secret_key = ""
        self.toku_base_url = self.toku_base_sandbox_url
        self.toku_api_key = self.toku_sandbox_api_key
        self.toku_account_key = self.toku_sandbox_account_key
        self.toku_writes_enabled = self.toku_sandbox_writes_enabled
        self.payku_base_url = self.payku_sandbox_base_url
        self.payku_api_key = self.payku_public_token = self.payku_sandbox_public_token
        self.payku_secret_key = self.payku_private_token = self.payku_sandbox_private_token
        self.payku_writes_enabled = self.payku_sandbox_writes_enabled
        for channel in ("virtualpos", "toku", "payku"):
            if not self.channel_enabled(channel):
                setattr(self, f"{channel}_writes_enabled", False)
        if not self.channel_enabled("virtualpos"):
            self.virtualpos_allow_charge_on_fixed_plan = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
