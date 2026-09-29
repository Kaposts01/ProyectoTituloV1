from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "CRM Suscripciones"
    app_env: str = "development"
    debug: bool = False
    auth_jwt_secret: str = ""
    auth_access_token_minutes: int = 60
    initial_admin_username: str = ""
    initial_admin_password: str = ""
    database_url: str
    # VirtualPOS cuenta 1 (sandbox/producción)
    virtualpos_base_url: str
    virtualpos_api_key: str
    virtualpos_secret_key: str
    virtualpos_timeout_seconds: float = 30
    virtualpos_read_retries: int = 2
    virtualpos_writes_enabled: bool = False
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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
