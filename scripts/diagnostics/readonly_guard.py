"""Guarda comun de los scripts de diagnostico (parity_check, vp_parity_check, coverage_report).

1. Por defecto solo corren contra una base cuyo nombre termina en `_test`. Contra cualquier otra (`crm`, `crm_sandbox`)
   abortan, salvo que se pase EXPLICITAMENTE `--read-only`.
2. La sesion siempre es `READ ONLY` (PostgreSQL rechaza escrituras) y, ademas, un filtro de sentencias deja pasar solo
   `SELECT`/`WITH` (y el `SET TRANSACTION READ ONLY` inicial): cualquier otra cosa lanza antes de llegar a la base.
"""

from __future__ import annotations

import re
import sys
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal

TEST_SUFFIX = "_test"
_ALLOWED = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
_READ_ONLY_PREAMBLE = "SET TRANSACTION READ ONLY"


class ReadOnlyViolation(RuntimeError):
    """Un script de diagnostico intento ejecutar algo que no es un SELECT."""


class UnsafeDatabaseError(SystemExit):
    """La base no es `_test` y no se pidio `--read-only`."""


def current_database_name() -> str:
    return make_url(settings.database_url).database or ""


def enforce_database_guard(read_only: bool, db_name: str | None = None) -> str:
    """Devuelve el nombre de la base si se puede seguir; si no, aborta con codigo 2 (sin imprimir la URL)."""
    name = current_database_name() if db_name is None else db_name
    if name.endswith(TEST_SUFFIX) or read_only:
        return name
    print(
        f"Abortado: la base '{name}' no termina en '{TEST_SUFFIX}'. Para leerla igual (solo SELECT) pase --read-only.",
        file=sys.stderr,
    )
    raise UnsafeDatabaseError(2)


def add_read_only_argument(parser: Any) -> None:
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Permite una base que no termina en _test; solo se ejecutan SELECT dentro de una transaccion READ ONLY.",
    )


def _only_selects(conn, cursor, statement, parameters, context, executemany) -> None:
    if statement.strip().upper() == _READ_ONLY_PREAMBLE:
        return
    if not _ALLOWED.match(statement):
        raise ReadOnlyViolation(f"Sentencia no permitida en un diagnostico de solo lectura: {statement.split()[0] if statement.split() else ''!r}")


def guard_select_only(db: Session) -> Session:
    """Engancha el filtro de sentencias a la conexion de la sesion (solo a esa conexion, no al engine)."""
    event.listen(db.connection(), "before_cursor_execute", _only_selects)
    return db


def open_readonly_session() -> Session:
    """Sesion cuya transaccion es READ ONLY y que solo admite SELECT/WITH."""
    db = SessionLocal()
    db.execute(text(_READ_ONLY_PREAMBLE))
    return guard_select_only(db)
