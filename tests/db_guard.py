"""Guardas puras de la base de pruebas (sin efectos): las usa `tests/conftest.py` y las prueba
`tests/test_db_guard.py`. Ninguna funcion imprime ni devuelve URLs ni valores del `.env`.

- `CRM_TEST_DB_NAME` (variable de proceso): nombre de la base de pruebas. Por defecto `crm_test`.
  Debe cumplir `TEST_DB_NAME_RE` (minusculas, digitos y `_`, terminado en `_test`, <= 63 chars),
  asi es seguro interpolarlo como identificador SQL. Nunca puede ser `crm` ni `crm_sandbox`.
- `CRM_DOTENV_PATH` (variable de proceso): ruta al `.env` a usar (p. ej. el del repo principal
  cuando se corre desde un worktree). Si se define, el archivo debe existir; si no, se usa `<repo>/.env`.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

DEFAULT_TEST_DB_NAME = "crm_test"
TEST_DB_NAME_ENV = "CRM_TEST_DB_NAME"
DOTENV_PATH_ENV = "CRM_DOTENV_PATH"
# Bases de la app y de la sandbox: prohibidas siempre, aunque el .env no las nombre.
FORBIDDEN_DB_NAMES = frozenset({"crm", "crm_sandbox", "postgres", "template0", "template1"})
# Identificador PostgreSQL sin comillas raras: empieza con letra, solo [a-z0-9_], termina en `_test`.
TEST_DB_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,57}_test$")


class TestDbGuardError(Exception):
    """La configuracion de la base de pruebas no es segura; la sesion debe abortar."""

    __test__ = False  # que pytest no intente recolectarla


def validate_test_db_name(name: str | None, protected: set[str] | frozenset[str] = frozenset()) -> str:
    """Devuelve `name` si es una base de pruebas segura; si no, lanza `TestDbGuardError`."""
    if not name:
        raise TestDbGuardError("El nombre de la base de test esta vacio.")
    if name in FORBIDDEN_DB_NAMES or name.lower() in FORBIDDEN_DB_NAMES:
        raise TestDbGuardError("La base de test no puede ser crm, crm_sandbox ni una base del sistema.")
    if not TEST_DB_NAME_RE.fullmatch(name):
        raise TestDbGuardError(
            "El nombre de la base de test debe calzar con ^[a-z][a-z0-9_]{0,57}_test$ (terminar en '_test')."
        )
    if name in protected:
        raise TestDbGuardError("La base de test coincide con la de DATABASE_URL/SANDBOX_DATABASE_URL.")
    return name


def resolve_test_db_name(environ: Mapping[str, str] | None = None) -> str:
    """Lee `CRM_TEST_DB_NAME` (por defecto `crm_test`) y lo valida. Definida pero vacia: falla cerrado."""
    env = os.environ if environ is None else environ
    raw = env.get(TEST_DB_NAME_ENV)
    name = DEFAULT_TEST_DB_NAME if raw is None else raw.strip()
    return validate_test_db_name(name)


def resolve_dotenv_path(root: Path, environ: Mapping[str, str] | None = None) -> Path:
    """Ruta del `.env`: `CRM_DOTENV_PATH` si esta definida (debe existir), si no `<root>/.env`."""
    env = os.environ if environ is None else environ
    raw = env.get(DOTENV_PATH_ENV)
    if raw is None:
        return root / ".env"
    path = Path(raw.strip()).expanduser()
    if not raw.strip() or not path.is_file():
        raise TestDbGuardError("CRM_DOTENV_PATH esta definida pero no apunta a un archivo existente.")
    return path.resolve()
