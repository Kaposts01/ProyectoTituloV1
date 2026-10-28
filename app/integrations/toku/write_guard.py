"""Guardas duras de escritura de Toku para ambientes NO productivos (sandbox/qa).

Toku no tiene sandbox documentado: el "sandbox" del CRM usa la MISMA URL base que produccion
(api.trytoku.com) y solo cambia la llave `x-api-key`. Nadie ha verificado que esa llave vea datos
aislados, asi que una escritura "de sandbox" podria afectar datos reales. Por eso el cliente invoca
`assert_sandbox_write_allowed` antes de cualquier POST/PUT/DELETE cuando `settings.is_production`
es falso. En produccion esta funcion NO se invoca (comportamiento sin cambios).

Funcion pura (sin red ni BD). Los mensajes de error nombran campos y codigos, nunca valores, llaves
ni PII. Todo lo no contemplado queda bloqueado (lista blanca de endpoints).

Variables de PROCESO (no dejar nunca en .env; el .env no las alimenta, se leen de os.environ):
- TOKU_SANDBOX_ALLOW_WRITES_ARMED=1  segunda llave (la primera es TOKU_SANDBOX_WRITES_ENABLED).
  No se reutiliza CONTRACT_WRITES para no armar Toku por accidente al probar VirtualPOS.
- TOKU_SANDBOX_ALLOWED_IDS           lista separada por comas de IDs (cus_/sub_/in_/pm_ o claves de
  negocio) que se pueden modificar/borrar aunque no empiecen por TEST-. Vacia por defecto.
- TOKU_SANDBOX_MAX_WRITES            tope de escrituras por proceso (default 25).

Nota (g): el DELETE de un recurso `in_progress` no se puede verificar aqui; write_toku.delete_subscription
ya omite las invoices `in_progress` antes de borrar.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.core.config import TOKU_HOST

TEST_PREFIX = "TEST-"
ENV_ARMED = "TOKU_SANDBOX_ALLOW_WRITES_ARMED"
ENV_ALLOWED_IDS = "TOKU_SANDBOX_ALLOWED_IDS"
ENV_MAX_WRITES = "TOKU_SANDBOX_MAX_WRITES"
DEFAULT_MAX_WRITES = 25


class TokuWriteBlockedError(Exception):
    """Escritura de Toku bloqueada por una guarda dura. `code` es estable; `message` no lleva PII ni llaves."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class WriteGuardState:
    """Estado en memoria del proceso: contador de escrituras permitidas y entorno de proceso."""

    writes: int = 0
    env: Mapping[str, str] | None = field(default=None, repr=False)

    def environ(self) -> Mapping[str, str]:
        return os.environ if self.env is None else self.env


PROCESS_STATE = WriteGuardState()


@dataclass(frozen=True)
class _Rule:
    method: str
    pattern: re.Pattern[str]
    label: str
    path_id: bool = False  # el id del path debe ser TEST- o estar en la allowlist
    prefixed: tuple[str, ...] = ()  # campos de negocio obligatorios con prefijo TEST-
    required_true: tuple[str, ...] = ()  # banderas que deben ser exactamente true
    id_refs_required: tuple[str, ...] = ()  # referencias a otros recursos (TEST- o allowlist), obligatorias
    id_refs_optional: tuple[str, ...] = ()  # idem, solo si vienen en el body


def _r(method: str, regex: str, label: str, **kw: Any) -> _Rule:
    return _Rule(method, re.compile(regex), label, **kw)


_SEG = r"[^/]+"
_RULES: tuple[_Rule, ...] = (
    _r("POST", r"^/customers$", "/customers", prefixed=("external_id",)),
    _r("POST", r"^/subscriptions$", "/subscriptions", prefixed=("product_id",), id_refs_required=("customer",)),
    _r(
        "POST", r"^/invoices$", "/invoices",
        prefixed=("product_id", "invoice_external_id"),
        required_true=("disable_automatic_payment",),
        id_refs_optional=("customer",),
    ),
    _r("POST", r"^/payment-methods$", "/payment-methods", prefixed=("external_id",), id_refs_optional=("customer",)),
    _r(
        "POST", r"^/cl/checkout-sessions$", "/cl/checkout-sessions",
        prefixed=("unique_external_id",),
        required_true=("skip_message_trigger",),
        id_refs_required=("billing_data.id_customer", "billing_data.ids_subscription"),
    ),
    _r("POST", rf"^/invoices/{_SEG}/void$", "/invoices/{id}/void", path_id=True),
    _r("POST", rf"^/subscriptions/{_SEG}/status$", "/subscriptions/{id}/status", path_id=True),
    *(
        _r(method, rf"^/{res}/{_SEG}$", f"/{res}/{{id}}", path_id=True)
        for method in ("PUT", "DELETE")
        for res in ("customers", "invoices", "payment-methods", "subscriptions")
    ),
)

_BULK_RE = re.compile(r"batch|bulk", re.IGNORECASE)


def _blocked(code: str, message: str) -> TokuWriteBlockedError:
    return TokuWriteBlockedError(code, message)


def _allowed_ids(env: Mapping[str, str]) -> frozenset[str]:
    return frozenset(i.strip() for i in env.get(ENV_ALLOWED_IDS, "").split(",") if i.strip())


def _max_writes(env: Mapping[str, str]) -> int:
    raw = env.get(ENV_MAX_WRITES, "").strip()
    if not raw:
        return DEFAULT_MAX_WRITES
    try:
        return max(int(raw), 0)
    except ValueError:
        return DEFAULT_MAX_WRITES


def _id_ok(value: Any, allowed: frozenset[str]) -> bool:
    return isinstance(value, str) and bool(value) and (value.startswith(TEST_PREFIX) or value in allowed)


def _values(body: Mapping[str, Any], dotted: str) -> list[Any] | None:
    """Valores del campo (admite 'a.b' y listas). None si el campo no existe."""
    node: Any = body
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return list(node) if isinstance(node, list) else [node]


def _host_ok(base_url: str) -> bool:
    parsed = urlparse((base_url or "").strip())
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() == TOKU_HOST
        and parsed.username is None
        and parsed.port in (None, 443)
    )


def assert_sandbox_write_allowed(
    method: str,
    path: str,
    body: Any,
    settings: Any,
    session_state: WriteGuardState,
) -> None:
    """Lanza TokuWriteBlockedError si la escritura no cumple TODAS las guardas; si pasa, cuenta la operacion."""
    method = method.upper()
    env = session_state.environ()

    # (a) llave 1: flag de config, ademas host exacto (defensa en profundidad).
    if not settings.toku_writes_enabled:
        raise _blocked("WRITES_DISABLED", "las escrituras de Toku estan deshabilitadas en este ambiente")
    if not _host_ok(settings.toku_base_url):
        raise _blocked("HOST_NOT_ALLOWED", "la URL base de Toku no es https con el host esperado")
    # (b) llave 2: interruptor de proceso.
    if env.get(ENV_ARMED) != "1":
        raise _blocked("NOT_ARMED", f"falta {ENV_ARMED}=1 en el entorno del proceso")

    # (f) escrituras masivas, antes que la lista blanca para dar un codigo claro.
    if _BULK_RE.search(path) or isinstance(body, list):
        raise _blocked("BULK_BLOCKED", "las escrituras masivas (batch/bulk) estan bloqueadas fuera de produccion")

    if not path.startswith("/") or any(t in path for t in ("..", "?", "#", "%", "\\", "//")):
        raise _blocked("PATH_INVALID", "ruta de escritura no valida")

    # Lista blanca de endpoints.
    rule = next((r for r in _RULES if r.method == method and r.pattern.match(path)), None)
    if rule is None:
        raise _blocked("ENDPOINT_NOT_ALLOWED", f"{method} sobre un endpoint no contemplado esta bloqueado")

    allowed = _allowed_ids(env)

    # (d) PUT/DELETE/void/status: id del path.
    if rule.path_id:
        resource_id = path.strip("/").split("/")[1]
        if not _id_ok(resource_id, allowed):
            raise _blocked(
                "ID_NOT_ALLOWED",
                f"{method} {rule.label}: el id no empieza por {TEST_PREFIX} ni esta en {ENV_ALLOWED_IDS}",
            )

    if method in ("POST", "PUT"):
        if rule.prefixed or rule.required_true or rule.id_refs_required or rule.id_refs_optional:
            if not isinstance(body, Mapping):
                raise _blocked("BODY_INVALID", f"{method} {rule.label}: el body debe ser un objeto JSON")
            _check_body(rule, method, body, allowed)

    # (e) tope de operaciones por proceso (solo cuenta las que pasaron todo lo anterior).
    if session_state.writes >= _max_writes(env):
        raise _blocked("CAP_REACHED", f"se alcanzo el tope de escrituras por proceso ({ENV_MAX_WRITES})")
    session_state.writes += 1


def _check_body(rule: _Rule, method: str, body: Mapping[str, Any], allowed: frozenset[str]) -> None:
    where = f"{method} {rule.label}"
    # (c) prefijo TEST- en claves de negocio.
    for name in rule.prefixed:
        vals = _values(body, name)
        if not vals:
            raise _blocked("FIELD_MISSING", f"{where}: falta el campo '{name}'")
        if not all(isinstance(v, str) and v.startswith(TEST_PREFIX) for v in vals):
            raise _blocked("PREFIX_REQUIRED", f"{where}: '{name}' debe empezar por {TEST_PREFIX}")
    for name in rule.required_true:
        if body.get(name) is not True:
            raise _blocked("FLAG_REQUIRED", f"{where}: '{name}' debe ser true")
    for names, required in ((rule.id_refs_required, True), (rule.id_refs_optional, False)):
        for name in names:
            vals = _values(body, name)
            if vals is None:
                if required:
                    raise _blocked("FIELD_MISSING", f"{where}: falta el campo '{name}'")
                continue
            if not vals or not all(_id_ok(v, allowed) for v in vals):
                raise _blocked(
                    "ID_NOT_ALLOWED",
                    f"{where}: '{name}' no empieza por {TEST_PREFIX} ni esta en {ENV_ALLOWED_IDS}",
                )
