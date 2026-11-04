"""Guardas de la base de pruebas (`tests/db_guard.py`): CRM_TEST_DB_NAME y CRM_DOTENV_PATH.

Funciones puras: no abren conexiones ni leen el `.env` real.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.db_guard import (
    DEFAULT_TEST_DB_NAME,
    TestDbGuardError,
    resolve_dotenv_path,
    resolve_test_db_name,
    validate_test_db_name,
)


def test_default_name_is_crm_test():
    assert resolve_test_db_name({}) == DEFAULT_TEST_DB_NAME == "crm_test"


@pytest.mark.parametrize("name", ["crm_test", "crm_l0_test", "crm_lote3_test", "a_test"])
def test_valid_names_pass(name):
    assert resolve_test_db_name({"CRM_TEST_DB_NAME": name}) == name


@pytest.mark.parametrize("name", ["crm_l0", "crm_testing", "crm_test_x", "test", "crm-l0_test_"])
def test_name_without_test_suffix_fails(name):
    with pytest.raises(TestDbGuardError):
        resolve_test_db_name({"CRM_TEST_DB_NAME": name})


@pytest.mark.parametrize("name", ["crm", "crm_sandbox", "CRM", "CRM_SANDBOX", "postgres"])
def test_app_and_sandbox_databases_fail(name):
    with pytest.raises(TestDbGuardError):
        resolve_test_db_name({"CRM_TEST_DB_NAME": name})


@pytest.mark.parametrize(
    "name",
    [
        "",
        "   ",
        "Crm_test",  # mayusculas: PostgreSQL las pliega y el nombre deja de ser el validado
        "1crm_test",
        "crm-l0_test",
        'crm"; DROP DATABASE crm; --_test',
        "crm test",
        "crm_l0_test\n",
        "x" * 60 + "_test",  # > 63 caracteres (limite de identificadores PostgreSQL)
    ],
)
def test_unsafe_sql_names_fail(name):
    with pytest.raises(TestDbGuardError):
        validate_test_db_name(name)


def test_empty_env_value_fails_closed():
    with pytest.raises(TestDbGuardError):
        resolve_test_db_name({"CRM_TEST_DB_NAME": ""})


def test_name_matching_protected_database_fails():
    with pytest.raises(TestDbGuardError):
        validate_test_db_name("crm_l0_test", {"crm_l0_test"})


def test_dotenv_path_defaults_to_repo_root(tmp_path):
    assert resolve_dotenv_path(tmp_path, {}) == tmp_path / ".env"


def test_dotenv_path_uses_env_var(tmp_path):
    f = tmp_path / "otro.env"
    f.write_text("X=1\n", encoding="utf-8")
    assert resolve_dotenv_path(Path("ignorado"), {"CRM_DOTENV_PATH": str(f)}) == f.resolve()


@pytest.mark.parametrize("value", ["", "no/existe/.env"])
def test_dotenv_path_missing_fails_closed(tmp_path, value):
    with pytest.raises(TestDbGuardError):
        resolve_dotenv_path(tmp_path, {"CRM_DOTENV_PATH": value})


def test_dotenv_path_directory_fails_closed(tmp_path):
    with pytest.raises(TestDbGuardError):
        resolve_dotenv_path(tmp_path, {"CRM_DOTENV_PATH": str(tmp_path)})


@pytest.mark.parametrize("name", ["crm", "crm_sandbox", "crm_l0"])
def test_conftest_aborts_session_before_touching_database(name):
    """Extremo a extremo: una sesion de pytest con un nombre prohibido aborta (codigo 2) en
    pytest_configure, antes de abrir conexiones (la guarda del nombre va antes de cualquier engine)."""
    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "CRM_TEST_DB_NAME": name, "PYTHONPATH": str(root)}
    env.pop("TEST_DATABASE_URL", None)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only", "-p", "no:cacheprovider", __file__],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 2
    assert "[guarda de BD de tests]" in (proc.stdout + proc.stderr)
