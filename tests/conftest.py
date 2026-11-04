"""Configuracion global de pytest: la suite corre SIEMPRE contra su propia base `*_test`.

Como correr: `PYTHONPATH=. .venv/Scripts/pytest.exe -q` (crea/limpia la base de test, por defecto
`crm_test`, y aplica `alembic upgrade head` al inicio de cada sesion; nunca toca la base de la app ni la sandbox).

Variables de proceso (ver `tests/db_guard.py` y docs/engineering/calidad/12-plan-pruebas.md):
- `CRM_TEST_DB_NAME`: nombre de la base de test (por defecto `crm_test`). Debe terminar en `_test` y calzar
  con una regex segura para SQL; nunca `crm` ni `crm_sandbox`. Permite correr pytest en paralelo desde
  varios worktrees, cada uno con su base.
- `CRM_DOTENV_PATH`: `.env` a usar (p. ej. el del repo principal desde un worktree, que no tiene `.env`).
  La app lo lee via `Settings` (`app/core/config.py`); nunca se copia ni se imprime.

La URL de test sale de `TEST_DATABASE_URL` (variable de proceso) o de `DATABASE_URL` (entorno/.env)
cambiando SOLO el nombre de la base. Se fija en `os.environ["DATABASE_URL"]` en `pytest_configure`, antes
de que se importe cualquier modulo de `app` (los tests se importan despues, durante la recoleccion).
Guarda dura: si la base no pasa `validate_test_db_name` o coincide con la de
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
from tests.db_guard import (
    DOTENV_PATH_ENV,
    TEST_DB_NAME_ENV,
    TEST_DB_NAME_RE,
    TestDbGuardError,
    resolve_dotenv_path,
    resolve_test_db_name,
    validate_test_db_name,
)

ROOT = Path(__file__).resolve().parent.parent


def _abort(msg: str) -> None:
    pytest.exit(f"[guarda de BD de tests] {msg}", returncode=2)


def _dotenv_path() -> Path:
    try:
        return resolve_dotenv_path(ROOT)
    except TestDbGuardError as exc:
        _abort(str(exc))
        raise  # inalcanzable: pytest.exit lanza


def _protected_db_names() -> set[str]:
    """Nombres de base de DATABASE_URL / SANDBOX_DATABASE_URL (proceso y .env). Nunca se imprimen URLs."""
    file_values = dotenv_values(_dotenv_path())
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
    try:
        name = resolve_test_db_name()
    except TestDbGuardError as exc:
        _abort(f"{TEST_DB_NAME_ENV}: {exc}")
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        url = make_url(explicit)
        if TEST_DB_NAME_ENV in os.environ and url.database != name:
            _abort(f"TEST_DATABASE_URL y {TEST_DB_NAME_ENV} apuntan a bases distintas.")
        return url
    base = os.environ.get("DATABASE_URL") or dotenv_values(_dotenv_path()).get("DATABASE_URL")
    if not base:
        _abort(
            "No hay DATABASE_URL (entorno/.env) ni TEST_DATABASE_URL para derivar la base de test "
            f"(desde un worktree, define {DOTENV_PATH_ENV})."
        )
    return make_url(base).set(database=name)


def _guard(url: URL, protected: set[str]) -> None:
    try:
        validate_test_db_name(url.database, protected)
    except TestDbGuardError as exc:
        _abort(f"Base de test resuelta (TEST_DATABASE_URL/{TEST_DB_NAME_ENV}/DATABASE_URL): {exc}")


def _reset_test_database(url: URL) -> None:
    """Crea la base si falta, deja `public` limpio y aplica las migraciones. Solo tras pasar la guarda."""
    name = url.database
    # Segunda barrera antes de interpolar el nombre en SQL (CREATE DATABASE).
    assert name and TEST_DB_NAME_RE.fullmatch(name)
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
    _dotenv_path()  # falla cerrado si CRM_DOTENV_PATH esta definida y no existe
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
    expected = make_url(os.environ["DATABASE_URL"]).database
    if not TEST_DB_NAME_RE.fullmatch(str(current)) or current != expected:
        pytest.exit("[guarda de BD de tests] el engine de la app no apunta a la base '*_test' esperada.", returncode=2)
    yield


@pytest.fixture(autouse=True)
def _billing_pilot_allowlist_open(request, monkeypatch):
    """BILL-09: la allowlist del piloto (vacia = todo bloqueado) se abre para los tests que no la prueban.

    Los tests de la allowlist piden el fixture `real_pilot_allowlist` y ven el comportamiento real
    (`BILLING_PILOT_ALLOWLIST` fijada por el propio test con monkeypatch)."""
    if "real_pilot_allowlist" in request.fixturenames:
        yield
        return
    from app.services import billing_requests

    monkeypatch.setattr(billing_requests, "is_pilot_allowlisted", lambda platform, subscription_external_id: True)
    yield


@pytest.fixture
def real_pilot_allowlist(monkeypatch):
    """Usa la allowlist real; parte vacia (todo bloqueado) salvo que el test la fije."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "billing_pilot_allowlist", "")
    yield
