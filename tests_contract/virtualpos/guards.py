"""Guardas duras de la suite de contrato de VirtualPOS. Funciones puras: devuelven la lista de problemas.

Los mensajes nombran variables, nunca valores. La suite solo puede correr contra el sandbox.
"""

from __future__ import annotations

from urllib.parse import urlparse

from app.core.config import VP_PRODUCTION_HOST, VP_SANDBOX_HOST

ENV_CONTRACT_TESTS = "CONTRACT_TESTS"
ENV_CONTRACT_WRITES = "CONTRACT_WRITES"
ENV_SUB_FIXED = "CONTRACT_VP_SUB_FIXED"
ENV_SUB_VARIABLE = "CONTRACT_VP_SUB_VARIABLE"


def host_of(url: str) -> str:
    return (urlparse((url or "").strip()).hostname or "").lower()


def base_guard_problems(env_mode: str, base_url: str, contract_tests: str | None) -> list[str]:
    """Condiciones para cualquier prueba de contrato (lectura o escritura)."""
    problems: list[str] = []
    if env_mode != "sandbox":
        problems.append("APP_ENV debe ser 'sandbox' (settings.env_mode != sandbox).")
    host = host_of(base_url)
    if host == VP_PRODUCTION_HOST:
        problems.append("La URL base de VirtualPOS (settings.virtualpos_base_url) apunta al host de PRODUCCION: prohibido.")
    elif host != VP_SANDBOX_HOST:
        problems.append("El host de virtualpos_base_url no es exactamente el host de sandbox de VirtualPOS.")
    if contract_tests != "1":
        problems.append(f"Falta {ENV_CONTRACT_TESTS}=1 en el entorno del proceso.")
    return problems


def write_guard_problems(contract_writes: str | None, writes_enabled: bool) -> list[str]:
    """Condiciones adicionales para pruebas con marcador contract_write."""
    problems: list[str] = []
    if contract_writes != "1":
        problems.append(f"Falta {ENV_CONTRACT_WRITES}=1 en el entorno del proceso (pruebas contract_write).")
    if not writes_enabled:
        problems.append("settings.virtualpos_writes_enabled es falso (VIRTUALPOS_SANDBOX_WRITES_ENABLED=true).")
    return problems


def missing_sub_vars(fixed: str | None, variable: str | None, needed: tuple[str, ...]) -> list[str]:
    """Variables de suscripcion de prueba que faltan, entre las `needed`."""
    values = {ENV_SUB_FIXED: fixed, ENV_SUB_VARIABLE: variable}
    return [name for name in needed if not (values.get(name) or "").strip()]
