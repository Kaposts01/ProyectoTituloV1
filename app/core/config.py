from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "CRM Suscripciones"
    app_env: str = "development"
    debug: bool = False
    database_url: str
    virtualpos_base_url: str
    virtualpos_api_key: str
    virtualpos_secret_key: str
    virtualpos_timeout_seconds: float = 30
    toku_base_url: str = ""
    toku_api_key: str = ""
    toku_timeout_seconds: float = 30
    payku_base_url: str = ""
    payku_api_key: str = ""
    payku_secret_key: str = ""
    payku_timeout_seconds: float = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
