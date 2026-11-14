"""Guardas duras de escritura de Payku para ambientes NO productivos (sandbox/qa).

Analogas a las de Toku (app/integrations/toku/write_guard.py). El sandbox de Payku aun no esta confirmado
ni tiene credenciales cargadas; estas guardas existen ANTES de habilitar cualquier escritura (d165).
`PaykuClient` invoca `assert_sandbox_write_allowed` antes de cada POST/PUT/DELETE cuando
`settings.is_production` es falso. En produccion esta funcion NO se invoca (comportamiento sin cambios:
las escrituras de produccion siguen gobernadas solo por PAYKU_WRITES_ENABLED en app/services/write_payku.py).

Funcion pura (sin red ni BD). Los mensajes de error nombran campos y codigos, nunca valores, llaves ni PII.
Todo lo no contemplado queda bloqueado (lista blanca de endpoints): en particular cualquier endpoint que
mueva dinero (transacciones, cobros de consumo, tarjetas, wallet/payout, mall, anulaciones, escrow,
marketplace, eventos) y tambien POST /api/conciliation aunque sea una consulta.

Reglas:
- Llave 1: PAYKU_SANDBOX_WRITES_ENABLED=true (en sandbox/qa se vuelca a `settings.payku_writes_enabled`).
- Host: https, sin credenciales en la URL, puerto 443, host en la lista de hosts de sandbox conocidos
  (`SANDBOX_HOSTS["payku_base_url"]` de app.core.config) y nunca el host de produccion. Un host nuevo exige
  cambio de codigo revisado.
- Llave 2: PAYKU_SANDBOX_ALLOW_WRITES_ARMED=1 (variable de PROCESO).
- Creaciones con datos sinteticos: `name` con prefijo TEST- y `email` en el dominio example.test.
- PUT/DELETE sobre un recurso existente: el id del path debe empezar por TEST- o estar en
  PAYKU_SANDBOX_ALLOWED_IDS (los ids que genera Payku, p. ej. cl.../su.../pl..., no llevan TEST-). Lo mismo
  para las referencias `client` y `plan` al crear una suscripcion.
- Tope PAYKU_SANDBOX_MAX_WRITES por proceso.

Variables de PROCESO (no dejar nunca en .env; el .env no las alimenta, se leen de os.environ):
- PAYKU_SANDBOX_ALLOW_WRITES_ARMED=1  segunda llave (la primera es PAYKU_SANDBOX_WRITES_ENABLED).
- PAYKU_SANDBOX_ALLOWED_IDS           lista separada por comas de IDs de Payku que se pueden modificar,
  borrar o referenciar aunque no empiecen por TEST-. Vacia por defecto.
- PAYKU_SANDBOX_MAX_WRITES            tope de escrituras por proceso (default 25, maximo 500: valores
  mayores se recortan; negativos o no numericos vuelven al default; 0 bloquea todo). El cupo es POR
  PROCESO: se reinicia al reiniciar y se multiplica con N workers. Es una red de seguridad, no un limite
  global.

Aviso: con APP_ENV=development/dev/local `settings.is_production` es True (alias historicos), las variables
PAYKU_SANDBOX_* se ignoran y estas guardas NO corren.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.core.config import PAYKU_PRODUCTION_HOST, SANDBOX_HOSTS

TEST_PREFIX = "TEST-"
TEST_EMAIL_DOMAIN = "example.test"
ENV_ARMED = "PAYKU_SANDBOX_ALLOW_WRITES_ARMED"
ENV_ALLOWED_IDS = "PAYKU_SANDBOX_ALLOWED_IDS"
ENV_MAX_WRITES = "PAYKU_SANDBOX_MAX_WRITES"
DEFAULT_MAX_WRITES = 25
MAX_WRITES_CEILING = 500  # tope superior del cupo: un valor enorme no puede anularlo


class PaykuWriteBlockedError(Exception):
    """Escritura de Payku bloqueada por una guarda dura. `code` es estable; `message` no lleva PII ni llaves."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class WriteGuardState:
    """Estado en memoria del proceso: contador de escrituras permitidas y entorno de proceso."""

    writes: int = 0
    env: Mapping[str, str] | None = field(default=None, repr=False)
    lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    def environ(self) -> Mapping[str, str]:
        return os.environ if self.env is None else self.env


PROCESS_STATE = WriteGuardState()


@dataclass(frozen=True)
class _Rule:
    method: str
    pattern: re.Pattern[str]
    label: str
    path_id: bool = False  # el id del path debe ser TEST- o estar en la allowlist
    prefixed: tuple[str, ...] = ()  # campos obligatorios con prefijo TEST-
    test_emails: tuple[str, ...] = ()  # campos obligatorios con email @example.test
    id_refs_required: tuple[
        str, ...
    ] = ()  # referencias a otros recursos (TEST- o allowlist), obligatorias
    put_synthetic: bool = False  # PUT: si vienen name/email, deben ser sinteticos


def _r(method: str, regex: str, label: str, **kw: Any) -> _Rule:
    return _Rule(method, re.compile(regex), label, **kw)


# Segmento de id: solo caracteres de ids de Payku (cl.../su.../pl...) y claves TEST-...
_SEG = r"[A-Za-z0-9_.:-]+"
_RULES: tuple[_Rule, ...] = (
    _r(
        "POST",
        r"^/api/suclient$",
        "/api/suclient",
        prefixed=("name",),
        test_emails=("email",),
    ),
    _r(
        "PUT",
        rf"^/api/suclient/{_SEG}$",
        "/api/suclient/{id}",
        path_id=True,
        put_synthetic=True,
    ),
    _r("DELETE", rf"^/api/suclient/{_SEG}$", "/api/suclient/{id}", path_id=True),
    _r("POST", r"^/api/suplan$", "/api/suplan", prefixed=("name",)),
    _r(
        "POST",
        r"^/api/sususcription$",
        "/api/sususcription",
        id_refs_required=("client", "plan"),
    ),
    _r(
        "DELETE",
        rf"^/api/sususcription/{_SEG}$",
        "/api/sususcription/{id}",
        path_id=True,
    ),
)


def _blocked(code: str, message: str) -> PaykuWriteBlockedError:
    return PaykuWriteBlockedError(code, message)


def _allowed_ids(env: Mapping[str, str]) -> frozenset[str]:
    return frozenset(
        i.strip() for i in env.get(ENV_ALLOWED_IDS, "").split(",") if i.strip()
    )


def _max_writes(env: Mapping[str, str]) -> int:
    raw = env.get(ENV_MAX_WRITES, "").strip()
    if not raw:
        return DEFAULT_MAX_WRITES
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_WRITES
    if value < 0:
        return DEFAULT_MAX_WRITES
    return min(value, MAX_WRITES_CEILING)


def _id_ok(value: Any, allowed: frozenset[str]) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and (value.startswith(TEST_PREFIX) or value in allowed)
    )


def _is_test_email(value: Any) -> bool:
    if not isinstance(value, str) or value.count("@") != 1:
        return False
    local, domain = value.rsplit("@", 1)
    return bool(local) and domain.lower() == TEST_EMAIL_DOMAIN


def _host_ok(base_url: str) -> bool:
    parsed = urlparse((base_url or "").strip())
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and host != PAYKU_PRODUCTION_HOST
        and host in SANDBOX_HOSTS.get("payku_base_url", ())
        and parsed.username is None
        and parsed.port in (None, 443)
    )


def _evaluate(
    method: str, path: str, body: Any, settings: Any, env: Mapping[str, str]
) -> None:
    """Todas las guardas salvo el cupo. Pura: no cuenta ni muta nada."""
    method = method.upper()

    # Falla cerrado ante dudas de ambiente: esta guarda solo tiene sentido fuera de produccion.
    if getattr(settings, "is_production", True):
        raise _blocked(
            "ENV_NOT_SANDBOX",
            "la guarda de sandbox de Payku se invoco con un ambiente productivo",
        )
    # Llave 1: flag de config, ademas host de sandbox conocido (defensa en profundidad).
    if not settings.payku_writes_enabled:
        raise _blocked(
            "WRITES_DISABLED",
            "las escrituras de Payku estan deshabilitadas en este ambiente",
        )
    if not _host_ok(settings.payku_base_url):
        raise _blocked(
            "HOST_NOT_ALLOWED",
            "la URL base de Payku no es https con un host de sandbox conocido",
        )
    # Llave 2: interruptor de proceso.
    if env.get(ENV_ARMED) != "1":
        raise _blocked("NOT_ARMED", f"falta {ENV_ARMED}=1 en el entorno del proceso")

    if isinstance(body, list):
        raise _blocked(
            "BULK_BLOCKED",
            "las escrituras masivas estan bloqueadas fuera de produccion",
        )
    if not path.startswith("/") or any(
        t in path for t in ("..", "?", "#", "%", "\\", "//")
    ):
        raise _blocked("PATH_INVALID", "ruta de escritura no valida")

    rule = next(
        (r for r in _RULES if r.method == method and r.pattern.fullmatch(path)), None
    )
    if rule is None:
        raise _blocked(
            "ENDPOINT_NOT_ALLOWED",
            f"{method} sobre un endpoint no contemplado esta bloqueado",
        )

    allowed = _allowed_ids(env)
    where = f"{method} {rule.label}"

    if rule.path_id:
        resource_id = path.rstrip("/").rsplit("/", 1)[1]
        if not _id_ok(resource_id, allowed):
            raise _blocked(
                "ID_NOT_ALLOWED",
                f"{where}: el id no empieza por {TEST_PREFIX} ni esta en {ENV_ALLOWED_IDS}",
            )

    if method in ("POST", "PUT"):
        if not isinstance(body, Mapping):
            raise _blocked("BODY_INVALID", f"{where}: el body debe ser un objeto JSON")
        _check_body(rule, where, body, allowed)


def _check_body(
    rule: _Rule, where: str, body: Mapping[str, Any], allowed: frozenset[str]
) -> None:
    for name in rule.prefixed:
        if name not in body:
            raise _blocked("FIELD_MISSING", f"{where}: falta el campo '{name}'")
        value = body[name]
        if not (isinstance(value, str) and value.startswith(TEST_PREFIX)):
            raise _blocked(
                "PREFIX_REQUIRED", f"{where}: '{name}' debe empezar por {TEST_PREFIX}"
            )
    for name in rule.test_emails:
        if name not in body:
            raise _blocked("FIELD_MISSING", f"{where}: falta el campo '{name}'")
        if not _is_test_email(body[name]):
            raise _blocked(
                "EMAIL_DOMAIN_REQUIRED",
                f"{where}: '{name}' debe ser del dominio {TEST_EMAIL_DOMAIN}",
            )
    for name in rule.id_refs_required:
        if name not in body:
            raise _blocked("FIELD_MISSING", f"{where}: falta el campo '{name}'")
        if not _id_ok(body[name], allowed):
            raise _blocked(
                "ID_NOT_ALLOWED",
                f"{where}: '{name}' no empieza por {TEST_PREFIX} ni esta en {ENV_ALLOWED_IDS}",
            )
    if rule.put_synthetic:
        if "name" in body and not (
            isinstance(body["name"], str) and body["name"].startswith(TEST_PREFIX)
        ):
            raise _blocked(
                "PREFIX_REQUIRED", f"{where}: 'name' debe empezar por {TEST_PREFIX}"
            )
        if "email" in body and not _is_test_email(body["email"]):
            raise _blocked(
                "EMAIL_DOMAIN_REQUIRED",
                f"{where}: 'email' debe ser del dominio {TEST_EMAIL_DOMAIN}",
            )


def assert_sandbox_write_allowed(
    method: str,
    path: str,
    body: Any,
    settings: Any,
    session_state: WriteGuardState,
) -> None:
    """Lanza PaykuWriteBlockedError si la escritura no cumple TODAS las guardas; si pasa, cuenta la operacion."""
    env = session_state.environ()
    _evaluate(method, path, body, settings, env)
    # Tope de operaciones por proceso (solo cuenta las que pasaron todo lo anterior). El candado hace
    # atomico comprobar+incrementar tambien entre hilos.
    with session_state.lock:
        if session_state.writes + 1 > _max_writes(env):
            raise _blocked(
                "CAP_REACHED",
                f"se alcanzo el tope de escrituras por proceso ({ENV_MAX_WRITES})",
            )
        session_state.writes += 1
