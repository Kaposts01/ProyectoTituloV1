"""MGT-16: permisos y roles de la baja de suscripciones multicanal.

D12: jefatura solicita; admin o jefatura aprueban; ejecutivo solo lee. D28: los permisos «fantasma» no se siembran y el
flujo nuevo no depende de ellos. La migracion 0050 se ejecuta dentro de una transaccion que se revierte (nunca Alembic).
"""

import importlib.util
import re
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.auth import Permission, Role
from app.services import rbac

ROOT = Path(__file__).resolve().parent.parent
REQ, APPR, VIEW = rbac.CANCELLATION_REQUEST, rbac.CANCELLATION_APPROVE, rbac.CANCELLATION_VIEW
PHANTOMS = {"virtualpos.payments.cancel", "toku.invoices.update", "toku.invoices.delete"}


def _migration():
    path = ROOT / "alembic" / "versions" / "20261029_0050_seed_cancellation_permissions.py"
    spec = importlib.util.spec_from_file_location("mig_0050", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _grants(db, role_name):
    role = db.scalar(select(Role).where(Role.name == role_name))
    if role is None:
        return None
    return {p.code for p in role.permissions if p.code.startswith("subscriptions.cancellation.")}


def test_new_permissions_are_in_catalog_with_spanish_descriptions() -> None:
    for code in (REQ, APPR, VIEW):
        assert re.fullmatch(r"subscriptions\.cancellation\.(request|approve|view)", code)
        assert rbac.PERMISSIONS[code].strip()
    assert rbac.CANCELLATION_ROLE_GRANTS["jefatura"] == {REQ, APPR, VIEW}
    assert rbac.CANCELLATION_ROLE_GRANTS["admin"] == {REQ, APPR, VIEW}


def test_no_ghost_permissions_are_seeded_or_introduced() -> None:
    """D28: los tres fantasmas siguen sin sembrarse y todo permiso exigido por una ruta existe en el catalogo (salvo
    los tres fantasmas heredados de /writes/*, que siguen inalcanzables)."""
    assert not PHANTOMS & set(rbac.PERMISSIONS)
    used: set[str] = set()
    for path in (ROOT / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for call in re.findall(r"require_(?:any_)?permissions?\(([^)]*)\)", text):
            used |= set(re.findall(r'"([a-z_]+(?:\.[a-z_]+)+)"', call))
    assert used - set(rbac.PERMISSIONS) <= PHANTOMS, sorted(used - set(rbac.PERMISSIONS) - PHANTOMS)
    # El flujo de baja nuevo no usa ninguno de los fantasmas.
    for name in ("cancellations.py",):
        route = ROOT / "app" / "api" / "v1" / "routes" / name
        if route.exists():
            assert not any(p in route.read_text(encoding="utf-8") for p in PHANTOMS)
    for name in ("cancellation_requests.py", "cancellation_apply.py"):
        service = ROOT / "app" / "services" / name
        if service.exists():
            assert not any(p in service.read_text(encoding="utf-8") for p in PHANTOMS)


def test_read_only_roles_inherit_view_but_never_request_or_approve() -> None:
    for codes in (rbac.executive_permission_codes(), rbac.support_permission_codes()):
        assert VIEW in codes
        assert REQ not in codes and APPR not in codes


def test_migration_0050_role_matrix(db_session) -> None:
    existing = set(db_session.scalars(select(Role.name)))
    for name in ("admin", "jefatura", "soporte", "ejecutivo", "coordinador"):
        if name not in existing:
            db_session.add(Role(name=name))
    db_session.flush()
    mig = _migration()
    mig.grant(db_session.connection())
    db_session.expire_all()
    expected = {
        "admin": {REQ, APPR, VIEW},
        "jefatura": {REQ, APPR, VIEW},
        "soporte": {VIEW},
        "ejecutivo": {VIEW},
        "coordinador": {VIEW},
    }
    for role, codes in expected.items():
        assert _grants(db_session, role) == codes, role
    # la matriz de la migracion coincide con la del catalogo
    assert {r: set(c) for r, c in mig.ROLE_GRANTS.items()} == {
        r: set(c) for r, c in rbac.CANCELLATION_ROLE_GRANTS.items()
    }
    assert mig.PERMISSIONS == {c: rbac.PERMISSIONS[c] for c in (REQ, APPR, VIEW)}


def test_migration_0050_is_idempotent_and_does_not_create_missing_roles(db_session) -> None:
    roles_before = set(db_session.scalars(select(Role.name)))
    if "jefatura" not in roles_before:
        db_session.add(Role(name="jefatura"))
        db_session.flush()
    mig = _migration()
    conn = db_session.connection()
    mig.grant(conn)
    mig.grant(conn)  # segunda corrida: no duplica ni falla
    db_session.expire_all()
    assert _grants(db_session, "jefatura") == {REQ, APPR, VIEW}
    roles_after = set(db_session.scalars(select(Role.name)))
    assert roles_after - roles_before <= {"jefatura"}  # la migracion no crea ningun rol
    codes = [
        p.code for p in db_session.scalars(select(Permission).where(Permission.code.like("subscriptions.cancellation.%")))
    ]
    assert sorted(codes) == sorted({REQ, APPR, VIEW})
