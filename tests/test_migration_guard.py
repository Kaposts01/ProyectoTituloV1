"""Guarda anti-downgrade de Alembic (incidente 2026-10-28). Tests puros salvo el round-trip en crm_test."""

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy.engine import make_url

from alembic import command
from app.db.migration_guard import (
    ALLOW_DOWNGRADE_ENV,
    DowngradeBlockedError,
    check_downgrade_allowed,
    is_downgrade_command,
)

ROOT = Path(__file__).resolve().parent.parent


def test_downgrade_sobre_crm_bloqueado():
    with pytest.raises(DowngradeBlockedError):
        check_downgrade_allowed("crm", True, {})


@pytest.mark.parametrize("name", ["crm_sandbox", "crm_test", "crm_qa", "qa_crm", "sandbox_x"])
def test_downgrade_permitido_en_bases_seguras(name):
    check_downgrade_allowed(name, True, {})


def test_upgrade_sobre_crm_permitido():
    check_downgrade_allowed("crm", False, {})


def test_downgrade_crm_con_confirmacion_explicita():
    check_downgrade_allowed("crm", True, {ALLOW_DOWNGRADE_ENV: "1"})


@pytest.mark.parametrize("value", ["0", "true", "yes", "", "11", " 1"])
def test_downgrade_crm_con_valor_distinto_de_1_bloqueado(value):
    with pytest.raises(DowngradeBlockedError):
        check_downgrade_allowed("crm", True, {ALLOW_DOWNGRADE_ENV: value})


def test_mensaje_sin_credenciales_y_con_nombre_y_variable():
    with pytest.raises(DowngradeBlockedError) as exc:
        check_downgrade_allowed("crm", True, {"DATABASE_URL": "postgresql://user:s3cr3t@host/crm"})
    msg = str(exc.value)
    assert "'crm'" in msg and ALLOW_DOWNGRADE_ENV in msg
    assert "s3cr3t" not in msg and "postgresql://" not in msg and "@" not in msg


def test_deteccion_de_direccion():
    def downgrade(rev, context): ...

    def upgrade(rev, context): ...

    assert is_downgrade_command({"fn": downgrade}) is True
    assert is_downgrade_command({"fn": upgrade}) is False
    assert is_downgrade_command({}) is True  # falla cerrado
    assert is_downgrade_command(None) is True


def test_env_py_llama_a_la_guarda():
    text = (ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "check_downgrade_allowed(" in text
    assert "is_downgrade_command(" in text
    assert "os.environ" in text
    # La guarda debe ir antes de abrir cualquier conexion.
    assert text.index("check_downgrade_allowed(") < text.index("run_migrations_online()")


def test_downgrade_programatico_roundtrip_en_crm_test():
    """API `alembic.command.downgrade` real, solo contra la base de la suite (conftest la fija a *_test)."""
    from app.core.config import settings

    db = make_url(settings.database_url).database or ""
    if not db.endswith("_test"):
        pytest.skip("settings no apunta a una base *_test; no se ejecuta por seguridad.")
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    try:
        command.downgrade(cfg, "-1")
    finally:
        command.upgrade(cfg, "head")
