"""EXP-02: permiso `export.pii`, su migracion y que no haya permisos fantasma."""

import importlib.util
import re
import uuid
from pathlib import Path

from sqlalchemy import select, text

from app.db.session import SessionLocal, engine
from app.models.auth import Permission, Role
from app.services.rbac import (
    PERMISSIONS,
    executive_permission_codes,
    seed_default_roles,
    support_permission_codes,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "alembic" / "versions" / "20261029_0044_export_pii_permission.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_0044", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_export_pii_is_in_catalog_with_spanish_description() -> None:
    assert "export.pii" in PERMISSIONS
    assert "datos personales" in PERMISSIONS["export.pii"].lower()


def test_support_and_executive_do_not_get_export_pii() -> None:
    assert "export.pii" not in support_permission_codes()
    assert "export.pii" not in executive_permission_codes()


def test_seed_default_roles_does_not_grant_export_pii_to_soporte_or_ejecutivo() -> None:
    db = SessionLocal()
    try:
        seed_default_roles(db)
        db.commit()
        for name in ("soporte", "ejecutivo"):
            role = db.scalar(select(Role).where(Role.name == name))
            assert role is not None and "export.pii" not in {p.code for p in role.permissions}
    finally:
        db.close()


def test_no_phantom_permissions_every_required_code_is_seeded() -> None:
    pattern = re.compile(r"require_(?:any_)?permissions?\(([^)]*)\)")
    required: dict[str, str] = {}
    for path in (ROOT / "app").rglob("*.py"):
        text_ = path.read_text(encoding="utf-8")
        for call in pattern.findall(text_):
            for code in re.findall(r"""["']([a-z_]+(?:\.[a-z_]+)+)["']""", call):
                required[code] = path.name
    assert required, "el escaneo no encontro ninguna ruta protegida"
    phantom = {code: where for code, where in required.items() if code not in PERMISSIONS}
    # Fantasmas PREEXISTENTES (rutas de escritura de writes.py que nadie puede usar, ni admin): decision del usuario
    # pendiente. Se fijan aqui para que cualquier fantasma NUEVO falle; si se siembran o se quitan, actualizar.
    known = {"virtualpos.payments.cancel", "toku.invoices.update", "toku.invoices.delete"}
    assert set(phantom) == known & set(phantom), f"permisos exigidos en rutas pero no sembrados: {phantom}"
    assert known >= set(phantom)
    assert "export.pii" in PERMISSIONS


def test_migration_0044_chain_and_seeded_in_test_database() -> None:
    module = _load_migration()
    assert module.revision == "20261029_0044" and module.down_revision == "20261029_0043"
    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from permissions where code='export.pii'")).scalar() == 1


def test_migration_grants_only_admin_and_jefatura_and_tolerates_missing_roles() -> None:
    module = _load_migration()
    suffix = uuid.uuid4().hex[:6]
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            # Sin ningun rol: no falla.
            conn.execute(text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code='export.pii')"))
            for name in ("admin", "jefatura", "soporte", "ejecutivo", "coordinador"):
                conn.execute(text("DELETE FROM role_permissions WHERE role_id IN (SELECT id FROM roles WHERE name=:n)"), {"n": name})
                conn.execute(text("DELETE FROM roles WHERE name=:n"), {"n": name})
            module.grant(conn)
            # Con roles: solo admin y jefatura reciben el permiso.
            for name in ("jefatura", "soporte", "ejecutivo", "coordinador"):
                conn.execute(text("INSERT INTO roles (id, name, description) VALUES (:i, :n, :d)"), {"i": uuid.uuid4(), "n": name, "d": f"t{suffix}"})
            conn.execute(text("INSERT INTO roles (id, name, description) VALUES (:i, 'admin', 't')"), {"i": uuid.uuid4()})
            module.grant(conn)
            module.grant(conn)  # idempotente
            holders = {
                r[0] for r in conn.execute(text(
                    "SELECT roles.name FROM roles JOIN role_permissions rp ON rp.role_id=roles.id "
                    "JOIN permissions p ON p.id=rp.permission_id WHERE p.code='export.pii'"))
            }
            assert holders == {"admin", "jefatura"}
        finally:
            trans.rollback()
    db = SessionLocal()
    try:
        assert db.scalar(select(Permission).where(Permission.code == "export.pii")) is not None
    finally:
        db.close()
