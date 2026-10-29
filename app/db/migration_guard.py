"""Guarda contra `alembic downgrade` accidentales sobre bases no seguras.

Por que existe (incidente 2026-10-28): un agente corrio comandos de Alembic (3 `downgrade -1` y un
`upgrade head`) contra la base real `crm` porque su script fijo `DATABASE_URL` en `os.environ`
DESPUES de importar `settings`, y `alembic/env.py` usa `settings.database_url`. La base quedo en una
revision que el usuario no decidio y faltaron filas de `core_charges` que hubo que reconstruir con el
ETL de Core. Esta guarda hace que ningun downgrade se ejecute, ni por la CLI ni por la API
programatica `alembic.command.downgrade`, salvo que la base de destino sea segura o exista una
confirmacion explicita en el proceso.

Reglas:
- Base segura: el nombre termina en `_test` o contiene `sandbox` o `qa`.
- Confirmacion explicita: variable de PROCESO `ALEMBIC_ALLOW_DOWNGRADE=1` (nunca se lee del `.env`).
- Los `upgrade` (y cualquier comando que no sea downgrade) no se ven afectados.

La logica es pura (sin E/S ni conexiones) para poder probarla sin tocar bases reales. Los mensajes
solo incluyen el NOMBRE de la base, nunca la URL ni credenciales.
"""

from collections.abc import Mapping

ALLOW_DOWNGRADE_ENV = "ALEMBIC_ALLOW_DOWNGRADE"


class DowngradeBlockedError(RuntimeError):
    """Se intento un downgrade sobre una base no segura sin confirmacion explicita."""


def is_safe_database(db_name: str) -> bool:
    name = (db_name or "").lower()
    return name.endswith("_test") or "sandbox" in name or "qa" in name


def check_downgrade_allowed(db_name: str, is_downgrade: bool, env: Mapping[str, str]) -> None:
    """Lanza `DowngradeBlockedError` si un downgrade apunta a una base no segura sin confirmacion."""
    if not is_downgrade or is_safe_database(db_name):
        return
    if env.get(ALLOW_DOWNGRADE_ENV) == "1":
        return
    raise DowngradeBlockedError(
        f"Downgrade de Alembic bloqueado: la base '{db_name or '(sin nombre)'}' no es segura "
        "(solo se permiten bases que terminen en '_test' o contengan 'sandbox' o 'qa'). "
        f"Si de verdad quieres bajar la version de esa base, define {ALLOW_DOWNGRADE_ENV}=1 "
        "en el proceso (no en el .env) solo para ese comando y quitala despues."
    )


def is_downgrade_command(context_opts: Mapping[str, object] | None) -> bool:
    """Detecta la direccion desde `EnvironmentContext.context_opts` (alembic 1.19.1).

    `alembic.command.downgrade` (usada por la CLI y por la API programatica) pasa
    `fn=<funcion interna llamada 'downgrade'>`. Si no se puede leer `fn`, se asume downgrade
    (falla cerrado).
    """
    if context_opts is None:
        return True
    fn = context_opts.get("fn")
    if fn is None:
        return True
    return getattr(fn, "__name__", "") == "downgrade"
