"""Configuracion global de pytest: la suite corre SIEMPRE contra su propia base `*_test`.

Como correr: `PYTHONPATH=. .venv/Scripts/pytest.exe -q` (crea/limpia `crm_test` y aplica
`alembic upgrade head` al inicio de cada sesion; nunca toca la base de la app ni la sandbox).

La URL de test sale de `TEST_DATABASE_URL` (variable de proceso) o de `DATABASE_URL` (.env/entorno)
cambiando SOLO el nombre de la base por `crm_test`. Se fija en `os.environ["DATABASE_URL"]` en
`pytest_configure`, antes de que se importe cualquier modulo de `app` (los tests se importan despues,
durante la recoleccion). Guarda dura: si la base no termina en `_test` o coincide con la de
`DATABASE_URL`/`SANDBOX_DATABASE_URL`, se aborta la sesion completa.
"""

import os
from pathlib import Path

import pytest
from alembic.config import Config
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from alembic import command

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEST_DB_NAME = "crm_test"


def _abort(msg: str) -> None:
    pytest.exit(f"[guarda de BD de tests] {msg}", returncode=2)


def _protected_db_names() -> set[str]:
    """Nombres de base de DATABASE_URL / SANDBOX_DATABASE_URL (proceso y .env). Nunca se imprimen URLs."""
    file_values = dotenv_values(ROOT / ".env")
    names: set[str] = set()
    for var in ("DATABASE_URL", "SANDBOX_DATABASE_URL"):
        for raw in (os.environ.get(var), file_values.get(var)):
            if raw:
                try:
                    db = make_url(raw).database
                except (ValueError, ArgumentError):
                    continue
                if db:
                    names.add(db)
    return names


def _resolve_test_url() -> URL:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return make_url(explicit)
    base = os.environ.get("DATABASE_URL") or dotenv_values(ROOT / ".env").get("DATABASE_URL")
    if not base:
        _abort("No hay DATABASE_URL (entorno/.env) ni TEST_DATABASE_URL para derivar la base de test.")
    return make_url(base).set(database=DEFAULT_TEST_DB_NAME)


def _guard(url: URL, protected: set[str]) -> None:
    name = url.database or ""
    if not name.endswith("_test"):
        _abort("La base de test resuelta (TEST_DATABASE_URL/DATABASE_URL) no termina en '_test'.")
    if name in protected:
        _abort("La base de test coincide con la de DATABASE_URL/SANDBOX_DATABASE_URL del .env.")


def _reset_test_database(url: URL) -> None:
    """Crea la base si falta, deja `public` limpio y aplica las migraciones. Solo tras pasar la guarda."""
    name = url.database
    assert name and name.endswith("_test")
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.execute(text("select 1 from pg_database where datname = :n"), {"n": name}).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        admin.dispose()

    eng = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with eng.connect() as conn:
            if conn.execute(text("select current_database()")).scalar() != name:
                _abort("current_database() no coincide con la base de test esperada.")
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    finally:
        eng.dispose()

    cfg = Config()  # sin alembic.ini: evita que fileConfig() reconfigure el logging de pytest
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, "head")


def pytest_configure(config):
    url = _resolve_test_url()
    _guard(url, _protected_db_names())
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)

    # Primera importacion de app, ya con la URL de test.
    from app.core.config import settings

    if make_url(settings.database_url).database != url.database:
        _abort("Settings no resolvio la base de test (DATABASE_URL del proceso fue ignorada).")
    _reset_test_database(url)


@pytest.fixture(scope="session", autouse=True)
def _assert_test_database():
    from app.db.session import engine

    with engine.connect() as conn:
        current = conn.execute(text("select current_database()")).scalar()
    if not str(current).endswith("_test"):
        pytest.exit("[guarda de BD de tests] el engine de la app no apunta a una base '*_test'.", returncode=2)
    yield
