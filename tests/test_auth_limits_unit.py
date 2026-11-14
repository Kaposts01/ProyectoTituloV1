"""CRM-16A/16D: piezas puras (politica de claves, IP truncada, seudonimo, bloqueo progresivo, ventana fija)."""

import pytest

from app.core import rate_limit
from app.core.config import settings
from app.core.password_policy import PasswordPolicyError, validate_new_password
from app.core.rate_limit import (
    FixedWindowLimiter,
    LoginThrottle,
    client_ip_from,
    truncate_ip,
    username_ref,
)


@pytest.mark.parametrize(
    ("password", "fragment"),
    [
        ("corta-123", "al menos 12"),
        ("password1234", "común"),
        ("Contraseña123", "común"),
        ("  QWERTY123456 ", "común"),
        ("aaaaaaaaaaaaaaa", "repetir"),
        ("abababababababab", "repetir"),
        ("xx-operador.sintetico-99", "nombre de usuario"),
    ],
)
def test_password_policy_rejects_weak_new_passwords(password: str, fragment: str) -> None:
    with pytest.raises(PasswordPolicyError, match=fragment):
        validate_new_password(password, "operador.sintetico")


def test_password_policy_accepts_long_uncommon_password_and_respects_config(monkeypatch) -> None:
    validate_new_password("marea-lenta-azul-47", "operador.sintetico")
    monkeypatch.setattr(settings, "auth_password_min_length", 20)
    with pytest.raises(PasswordPolicyError, match="al menos 20"):
        validate_new_password("marea-lenta-azul-47", "operador.sintetico")
    monkeypatch.setattr(settings, "auth_password_min_length", 3)  # nunca baja de 8
    with pytest.raises(PasswordPolicyError, match="al menos 8"):
        validate_new_password("ab-12", None)


def test_truncate_ip_never_returns_full_address() -> None:
    assert truncate_ip("203.0.113.77") == "203.0.113.0/24"
    assert truncate_ip("2001:db8:abcd:12:1:2:3:4") == "2001:db8:abcd::/48"
    assert truncate_ip("testclient") == "unknown"


def test_username_ref_is_stable_case_insensitive_and_opaque() -> None:
    ref = username_ref("Operador.Sintetico")
    assert ref == username_ref(" operador.sintetico ")
    assert len(ref) == 16
    assert "operador" not in ref
    assert ref != username_ref("otro.usuario")


def test_forwarded_for_only_when_trusted(monkeypatch) -> None:
    assert client_ip_from("10.0.0.1", "198.51.100.9, 10.0.0.1") == "10.0.0.1"
    # Un proxy propio delante: la IP real es la ultima que agrego (posicion 1 desde la derecha).
    monkeypatch.setattr(settings, "api_trusted_proxy_count", 1)
    assert client_ip_from("10.0.0.1", "198.51.100.9") == "198.51.100.9"
    # Un cliente que antepone una IP falsa no la puede imponer.
    assert client_ip_from("10.0.0.1", "1.2.3.4, 198.51.100.9") == "198.51.100.9"
    # Dos proxies propios.
    monkeypatch.setattr(settings, "api_trusted_proxy_count", 2)
    assert client_ip_from("10.0.0.1", "1.2.3.4, 198.51.100.9, 10.0.0.2") == "198.51.100.9"
    # Menos entradas que proxies declarados: se usa la IP del socket.
    assert client_ip_from("10.0.0.1", "198.51.100.9") == "10.0.0.1"
    assert client_ip_from(None, None) == "unknown"


def test_login_throttle_locks_progressively_with_cap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_login_failure_window_seconds", 900)
    monkeypatch.setattr(settings, "auth_login_lockout_base_seconds", 60)
    monkeypatch.setattr(settings, "auth_login_lockout_max_seconds", 200)
    throttle = LoginThrottle()
    key = ("user", "abc")

    assert not throttle.register_failure(key, 3, at=0)
    assert not throttle.register_failure(key, 3, at=1)
    assert throttle.retry_after([key], at=1) == 0
    assert throttle.register_failure(key, 3, at=2)  # tercer fallo: bloqueo de 60 s
    assert throttle.retry_after([key], at=2) == 60
    assert throttle.retry_after([key, ("ip", "x")], at=50) == 12
    assert throttle.retry_after([key], at=62) == 0

    for t in (70, 71, 72):
        locked = throttle.register_failure(key, 3, at=t)
    assert locked and throttle.retry_after([key], at=72) == 120  # segundo bloqueo: el doble
    for t in (300, 301, 302):
        throttle.register_failure(key, 3, at=t)
    assert throttle.retry_after([key], at=302) == 200  # tercero: 240 recortado al tope

    throttle.clear(key)
    assert throttle.retry_after([key], at=303) == 0


def test_login_throttle_failures_outside_window_do_not_count(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_login_failure_window_seconds", 10)
    throttle = LoginThrottle()
    key = ("ip", "203.0.113.5")
    throttle.register_failure(key, 2, at=0)
    assert not throttle.register_failure(key, 2, at=20)
    assert throttle.register_failure(key, 2, at=21)


def test_fixed_window_limiter_returns_retry_after_and_resets() -> None:
    limiter = FixedWindowLimiter()
    key = ("ip", "203.0.113.5")
    assert limiter.hit(key, 2, at=100.0) == 0
    assert limiter.hit(key, 2, at=110.0) == 0
    assert limiter.hit(key, 2, at=115.5) == 45
    assert limiter.hit(("ip", "otra"), 2, at=115.5) == 0
    assert limiter.hit(key, 2, at=160.0) == 0  # ventana nueva
    assert limiter.hit(key, 0, at=160.0) == 0  # 0 = sin limite


def test_module_clock_is_patchable(monkeypatch) -> None:
    monkeypatch.setattr(rate_limit, "now", lambda: 5.0)
    limiter = FixedWindowLimiter()
    assert limiter.hit(("ip", "a"), 1) == 0
    assert limiter.hit(("ip", "a"), 1) == 60
