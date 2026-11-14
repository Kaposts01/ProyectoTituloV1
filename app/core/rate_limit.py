"""Limitadores en memoria (CRM-16A/16D): rate limit general de la API y bloqueo progresivo del login.

Sin dependencias nuevas. El estado es POR PROCESO y se pierde al reiniciar (igual que el rate limit de webhooks):
con varios workers el limite efectivo se multiplica. Ver docs/security/login-y-rate-limit.md.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import math
import threading
import time
from dataclasses import dataclass, field

from app.core.config import settings

_MAX_KEYS = 20000


def now() -> float:
    """Reloj monotono; los tests lo reemplazan con monkeypatch."""
    return time.monotonic()


# ----------------------------- IP del cliente -----------------------------


def client_ip_from(host: str | None, forwarded_for: str | None) -> str:
    """IP del cliente. `X-Forwarded-For` solo cuenta con API_TRUST_FORWARDED_FOR (detras de un proxy propio)."""
    if settings.api_trust_forwarded_for and forwarded_for:
        first = forwarded_for.split(",")[0].strip()[:45]
        if first:
            return first
    return host or "unknown"


def truncate_ip(ip: str) -> str:
    """IP truncada para registros: IPv4 a /24, IPv6 a /48. Nunca la IP completa."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "unknown"
    prefix = 24 if addr.version == 4 else 48
    return str(ipaddress.ip_network(f"{addr}/{prefix}", strict=False))


def username_ref(username: str) -> str:
    """Referencia seudonima del nombre de usuario (HMAC-SHA256 truncado). No permite recuperar el nombre."""
    key = (settings.auth_jwt_secret or "crm-login-ref").encode("utf-8")
    normalized = username.strip().casefold().encode("utf-8")
    return hmac.new(key, normalized, hashlib.sha256).hexdigest()[:16]


# ----------------------------- ventana fija (API) -----------------------------


class FixedWindowLimiter:
    """Contador por clave en ventanas fijas. `hit` devuelve segundos de espera (Retry-After) o 0 si se permite."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._windows: dict[tuple[str, str], tuple[float, int]] = {}

    def reset(self) -> None:
        with self._lock:
            self._windows.clear()

    def hit(self, key: tuple[str, str], limit: int, window: float = 60.0, at: float | None = None) -> int:
        if limit <= 0:
            return 0
        current = now() if at is None else at
        with self._lock:
            if len(self._windows) > _MAX_KEYS:
                for stale in [k for k, (start, _) in self._windows.items() if current - start >= window]:
                    del self._windows[stale]
            start, count = self._windows.get(key, (current, 0))
            if current - start >= window:
                start, count = current, 0
            if count >= limit:
                return max(1, math.ceil(start + window - current))
            self._windows[key] = (start, count + 1)
            return 0


api_limiter = FixedWindowLimiter()


# ----------------------------- bloqueo progresivo del login -----------------------------


@dataclass
class _LoginState:
    failures: list[float] = field(default_factory=list)
    locked_until: float = 0.0
    lockouts: int = 0
    last_event: float = 0.0


class LoginThrottle:
    """Fallos por clave (usuario seudonimo o IP) en una ventana; al llegar al umbral bloquea por un tiempo que se
    duplica en cada bloqueo seguido (tope configurable). Un login exitoso limpia la clave del usuario."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[tuple[str, str], _LoginState] = {}

    def reset(self) -> None:
        with self._lock:
            self._states.clear()

    def _prune(self, current: float) -> None:
        window = settings.auth_login_failure_window_seconds
        horizon = max(window, settings.auth_login_lockout_max_seconds) * 4
        for key in [k for k, s in self._states.items() if s.locked_until <= current and current - s.last_event > horizon]:
            del self._states[key]

    def retry_after(self, keys: list[tuple[str, str]], at: float | None = None) -> int:
        """Segundos que faltan del bloqueo mas largo entre las claves (0 = sin bloqueo)."""
        current = now() if at is None else at
        with self._lock:
            remaining = [s.locked_until - current for k in keys if (s := self._states.get(k)) is not None]
        longest = max(remaining, default=0.0)
        return math.ceil(longest) if longest > 0 else 0

    def register_failure(self, key: tuple[str, str], threshold: int, at: float | None = None) -> bool:
        """Anota un fallo. True si este fallo activo un bloqueo."""
        if threshold <= 0:
            return False
        current = now() if at is None else at
        window = settings.auth_login_failure_window_seconds
        with self._lock:
            if len(self._states) > _MAX_KEYS:
                self._prune(current)
            state = self._states.setdefault(key, _LoginState())
            # Tras un periodo largo sin fallos el escalamiento vuelve a empezar.
            if state.lockouts and current - state.last_event > max(window, settings.auth_login_lockout_max_seconds) * 4:
                state.lockouts = 0
            state.last_event = current
            state.failures = [t for t in state.failures if current - t < window]
            state.failures.append(current)
            if len(state.failures) < threshold:
                return False
            state.lockouts += 1
            duration = settings.auth_login_lockout_base_seconds * (2 ** (state.lockouts - 1))
            state.locked_until = current + min(duration, settings.auth_login_lockout_max_seconds)
            state.failures = []
            return True

    def clear(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._states.pop(key, None)


login_throttle = LoginThrottle()


def reset_all() -> None:
    """Limpia todos los contadores (tests)."""
    api_limiter.reset()
    login_throttle.reset()
