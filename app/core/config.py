import logging
import os
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


# `.env` a leer: `CRM_DOTENV_PATH` (variable de proceso) si esta definida, p. ej. para correr la suite
# desde un git worktree que no tiene `.env`; si no, `.env` del directorio actual. Las variables de proceso
# siguen teniendo prioridad sobre el archivo.
DOTENV_PATH = os.environ.get("CRM_DOTENV_PATH") or ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=DOTENV_PATH,
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
    # SYNC-O-11: un etl_run `running` mas viejo que esto se considera abandonado (proceso caido) y deja de bloquear.
    sync_run_stale_hours: float = 6
    # SYNC-O-03: la corrida nocturna consolida TCH solo si llego un reporte Excel nuevo (False = siempre, como antes).
    sync_tch_consolidate_only_after_load: bool = True
    # SYNC-O-16: el ETL Core de Toku/Payku/VirtualPOS corre dentro del sync, tras consolidar (False = solo manual).
    sync_core_etl_enabled: bool = False
    # SYNC-O-02/05: lectura por ventana de fecha (Toku transacciones; VirtualPOS pagos y clientes). APAGADA por defecto:
    # se enciende tras las pruebas de contrato en sandbox (DEC-03). Solape de la ventana y relectura completa periodica.
    sync_windowed_reads_enabled: bool = False
    sync_window_overlap_hours: float = 48
    sync_window_full_refresh_days: int = 7
    # SYNC-D-02/03: historial de cambios de estado/monto en la consolidacion. `baseline` marca los eventos de la corrida
    # como linea base (no cuentan como novedad); usar en la primera consolidacion de un canal vacio o de una carga historica.
    status_events_enabled: bool = True
    status_events_baseline: bool = False
    # RJ-06: captura diaria de la glosa de rechazo de VirtualPOS (1 peticion por suscripcion con rechazos sin detalle).
    # APAGADA por defecto: la enciende el usuario tras revisar. Tope de suscripciones por corrida y por cuenta VP.
    vp_rejection_capture_enabled: bool = False
    vp_rejection_capture_max_subscriptions: int = 500
    vp_rejection_capture_pause_seconds: float = 0.3
    vp_rejection_capture_recheck_days: int = 30  # cobros consultados sin glosa se reconsultan pasado este plazo
    vp_rejection_capture_max_retries: int = 3  # reintentos con backoff ante 429/5xx
    # RT-04..08: webhooks en tiempo casi real. Receptores (tope de body, rate limit por IP+ruta) y procesador asincrono.
    # El procesador esta APAGADO por defecto: sin la bandera la cola `webhook_events` solo acumula.
    webhook_max_body_bytes: int = 262144
    webhook_rate_limit_per_minute: int = 120
    webhook_trust_forwarded_for: bool = False  # solo detras de un proxy/tunel propio (X-Forwarded-For es falsificable)
    webhook_processor_enabled: bool = False
    webhook_processor_batch_size: int = 50
    webhook_max_attempts: int = 5
    webhook_backoff_base_seconds: float = 30  # espera = base * 2**(intentos-1), tope 1 h
    webhook_processing_stale_minutes: float = 10  # un evento `processing` abandonado vuelve a `pending`
    # RT-06: reconciliacion dirigida (sin webhooks) de suscripciones con ventana de riesgo. APAGADA por defecto.
    targeted_reconcile_enabled: bool = False
    targeted_reconcile_max_per_run: int = 200
    targeted_reconcile_pause_seconds: float = 1.0
    targeted_reconcile_due_days: int = 5  # cobro programado en los ultimos N dias
    targeted_reconcile_rejection_days: int = 15  # rechazo reciente = cobro rechazado de los ultimos N dias
    # SYNC-D-08: alertas de fallos de sincronizacion por correo (job cada 15 min). APAGADA por defecto. Todo se define SOLO
    # por variable de entorno; `ALERT_EMAIL_TO` (lista separada por comas) es obligatorio: si falta, no se envia nada.
    alerts_enabled: bool = False
    alert_email_to: str = ""
    alert_email_from: str = ""
    alert_smtp_host: str = ""
    alert_smtp_port: int = 587
    alert_smtp_user: str = ""
    alert_smtp_password: str = ""
    alert_smtp_starttls: bool = True
    # RJ-15: materializa los intentos FAILED de Toku como core_payments (source_status='FAILED'). APAGADA por defecto.
    toku_materialize_failed_payments: bool = False
    # TK-20: senales de suscripcion desde los reportes (activa efectiva, racha por cuotas, tarjeta bloqueada/vencida)
    # y estado reporte > API. Apagada por defecto: el recuperador todavia no las lee (REC-04).
    toku_report_signals_enabled: bool = False
    toku_report_firm_unpaid_days: int = 7  # dias sin intento para que una cuota fallida quede «en firme» (DEC-16)
    # SYNC-D-10: reintentos de lectura (red, 429, 5xx) con `Retry-After`; ninguna espera supera este tope (segundos).
    http_retry_max_delay_seconds: float = 30
    # SYNC-D-10: reintento del job `retry_failed_channels`. Tope de corridas fallidas por canal y dia (Chile) antes de rendirse;
    # si la sync principal sigue corriendo, se pospone `sync_retry_defer_minutes` hasta `sync_retry_max_deferrals` veces.
    sync_retry_max_failures_per_day: int = 3
    sync_retry_defer_minutes: int = 30
    sync_retry_max_deferrals: int = 6
    # VP-PAR-11: paridad diaria reportes PAT vs base (solo lectura, resultado al log). APAGADA por defecto.
    vp_parity_check_enabled: bool = False
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
    toku_report_hash_pepper: str = ""  # HMAC de `ID Producto` de los reportes (TK-18); vacio = importador cerrado
    vp_report_hash_pepper: str = ""  # HMAC del codigo de vendedor de los reportes PAT de VirtualPOS; vacio = no se guarda el hash
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
            self._apply_production_aliases()
            return self
        self._guard_sandbox()
        self._apply_sandbox()
        return self

    def _apply_production_aliases(self) -> None:
        """Alias de variables en produccion (como ya hace `_apply_sandbox`), sin pisar valores explicitos.

        - Payku: la doc usa PAYKU_PUBLIC_TOKEN (Bearer) y PAYKU_PRIVATE_TOKEN (firma); el codigo lee
          payku_api_key/payku_secret_key. Si estas quedan vacias se usan los tokens.
        - VirtualPOS cuenta 2: si tiene credenciales pero no URL propia, usa la URL de la cuenta 1
          (es el mismo servicio VirtualPOS de produccion).
        """
        if not self.payku_api_key.strip() and self.payku_public_token.strip():
            self.payku_api_key = self.payku_public_token
        if not self.payku_secret_key.strip() and self.payku_private_token.strip():
            self.payku_secret_key = self.payku_private_token
        if not self.virtualpos2_base_url.strip() and self.virtualpos2_api_key.strip() and self.virtualpos2_secret_key.strip():
            self.virtualpos2_base_url = self.virtualpos_base_url

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


_DEV_ALIASES = ("development", "dev", "local")
_dev_alias_warning_emitted = False


def warn_unguarded_dev_writes(cfg: "Settings") -> None:
    """AVISO INFORMATIVO (no cambia ningun comportamiento), una sola vez por proceso.

    Con APP_ENV=development/dev/local `is_production` es True (alias historicos): las variables
    TOKU_SANDBOX_* se ignoran y las guardas de escritura de Toku NO corren, asi que una maquina de
    desarrollo con llaves reales y TOKU_WRITES_ENABLED=true escribe en Toku sin guarda. El mensaje solo
    nombra variables, nunca valores. Se invoca en el arranque de la app (lifespan); solo cubre Toku
    porque no existe un patron analogo para otros proveedores.
    """
    global _dev_alias_warning_emitted
    if _dev_alias_warning_emitted:
        return
    if cfg.app_env.strip().lower() in _DEV_ALIASES and cfg.toku_writes_enabled:
        _dev_alias_warning_emitted = True
        log.warning(
            "APP_ENV es un alias de produccion (development/dev/local) y TOKU_WRITES_ENABLED esta activo: "
            "las variables TOKU_SANDBOX_* se ignoran y las guardas de escritura de Toku NO se aplican; "
            "las escrituras iran a Toku con las llaves TOKU_* configuradas. Use APP_ENV=sandbox o qa para "
            "probar con guardas, o desactive TOKU_WRITES_ENABLED."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
