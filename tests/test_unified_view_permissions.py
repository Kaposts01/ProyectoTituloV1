"""d124 (opcion c): permisos generales de las vistas unificadas y ciclos de Payku como cobros. Datos SINTETICOS.

* `general.subscriptions.view` / `general.charges.view` (migracion 0064, regla por datos como la 0052).
* Compatibilidad: sin el permiso general, cada canal sigue exigiendo su permiso de vista.
* Payku: los ciclos (`p_cycles`, PK-06) aparecen en `/general/charges` cuando existen.
"""

import importlib.util
import random
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal, engine
from app.main import app
from app.models.auth import Permission, Role, User
from app.models.payku_channel import PaykuCycle
from app.services import rbac
from app.services.export_queries import effective_permissions, select_specs

ROOT = Path(__file__).resolve().parents[1]
_TAG = "zv[0-9a-f]{8}"
NEW_CODES = {rbac.GENERAL_SUBSCRIPTIONS_VIEW, rbac.GENERAL_CHARGES_VIEW}


def _sfx() -> str:
    return "zv" + "".join(random.choice("0123456789abcdef") for _ in range(8))


def _migration():
    path = ROOT / "alembic" / "versions" / "20261102_0064_seed_unified_view_permissions.py"
    spec = importlib.util.spec_from_file_location("mig_0064", path)
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


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    db = SessionLocal()
    try:
        params = {"tag": _TAG}
        for stmt in (
            "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username ~ ('^uv-' || :tag))",
            "DELETE FROM users WHERE username ~ ('^uv-' || :tag)",
            "DELETE FROM roles WHERE name ~ ('^uv-' || :tag)",
            "DELETE FROM p_cycles WHERE external_id ~ :tag",
        ):
            db.execute(text(stmt), params)
        db.commit()
    finally:
        db.close()


def _login(monkeypatch, suffix: str, perms: list[str]) -> TestClient:
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    db = SessionLocal()
    try:
        rbac.seed_permissions(db)
        plist = [db.scalar(select(Permission).where(Permission.code == p)) for p in perms]
        assert all(plist), perms
        role = Role(name=f"uv-{suffix}", permissions=plist)
        db.add_all([role, User(username=f"uv-{suffix}", password_hash=hash_password("Pw-uv-12345"), is_active=True, roles=[role])])
        db.commit()
    finally:
        db.close()
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/v1/auth/login", json={"username": f"uv-{suffix}", "password": "Pw-uv-12345"}).status_code == 200
    return client


# --- migracion 0064 ---------------------------------------------------------------------------------------------------


def test_migration_0064_chain_and_rules_match_rbac() -> None:
    mig = _migration()
    assert mig.revision == "20261102_0064" and mig.down_revision == "20261102_0066"
    assert mig.GRANT_RULES == rbac.UNIFIED_VIEW_GRANT_RULES
    assert {code: rbac.PERMISSIONS[code] for code in mig.PERMISSIONS} == mig.PERMISSIONS
    assert set(mig.PERMISSIONS) == NEW_CODES


def _role(db: Session, codes: list[str]) -> Role:
    perms = [db.scalar(select(Permission).where(Permission.code == c)) for c in codes]
    role = Role(name=f"mig64-{uuid.uuid4().hex[:8]}", permissions=perms)
    db.add(role)
    db.flush()
    return role


def _new_codes(db: Session, role: Role) -> set[str]:
    db.expire(role)
    return {p.code for p in role.permissions if p.code in NEW_CODES}


def test_migration_0064_grants_by_data_and_downgrade_removes(db_session: Session) -> None:
    mig = _migration()
    rbac.seed_permissions(db_session)
    db_session.flush()
    mig.revoke(db_session.connection())  # como una base en 0066
    subs = list(rbac.UNIFIED_VIEW_GRANT_RULES[rbac.GENERAL_SUBSCRIPTIONS_VIEW])
    charges = list(rbac.UNIFIED_VIEW_GRANT_RULES[rbac.GENERAL_CHARGES_VIEW])
    full = _role(db_session, subs + charges)
    subs_only = _role(db_session, subs)
    partial = _role(db_session, subs[:2] + charges[:3])

    mig.grant(db_session.connection())
    mig.grant(db_session.connection())  # idempotente
    assert _new_codes(db_session, full) == NEW_CODES
    assert _new_codes(db_session, subs_only) == {rbac.GENERAL_SUBSCRIPTIONS_VIEW}
    assert _new_codes(db_session, partial) == set()  # nadie gana acceso a canales que no veia

    mig.revoke(db_session.connection())
    assert _new_codes(db_session, full) == set()
    assert not db_session.scalars(select(Permission).where(Permission.code.in_(NEW_CODES))).all()
    mig.grant(db_session.connection())  # deja la base como la dejo alembic


def test_ensure_general_grants_includes_unified_views(db_session: Session) -> None:
    rbac.seed_permissions(db_session)
    role = _role(db_session, list(rbac.UNIFIED_VIEW_GRANT_RULES[rbac.GENERAL_CHARGES_VIEW]))
    rbac.ensure_general_grants(db_session)
    assert _new_codes(db_session, role) == {rbac.GENERAL_CHARGES_VIEW}


# --- resolucion de permisos -------------------------------------------------------------------------------------------


def test_general_permission_covers_every_channel_and_channel_permissions_still_work() -> None:
    items, denied = select_specs("suscripciones", None, {rbac.GENERAL_SUBSCRIPTIONS_VIEW})
    assert not denied and {spec.provider for spec, _ in items} == {"virtualpos", "toku", "payku", "tch"}
    items, _ = select_specs("cobros", None, {rbac.GENERAL_CHARGES_VIEW})
    assert {spec.provider for spec, _ in items} == {"virtualpos", "toku", "payku", "tch"}
    items, _ = select_specs("pagos", "payku", {rbac.GENERAL_CHARGES_VIEW})
    assert [spec.provider for spec, _ in items] == ["payku"]
    # compatibilidad: sin el general, solo los canales con permiso propio
    items, denied = select_specs("suscripciones", None, {"toku.subscriptions.view"})
    assert [spec.provider for spec, _ in items] == ["toku"] and not denied
    _, denied = select_specs("suscripciones", "tch", {"toku.subscriptions.view"})
    assert denied
    # el permiso general de suscripciones no abre cobros (ni clientes)
    assert effective_permissions("cobros", {rbac.GENERAL_SUBSCRIPTIONS_VIEW}) == {rbac.GENERAL_SUBSCRIPTIONS_VIEW}
    assert effective_permissions("clientes", {rbac.GENERAL_CHARGES_VIEW}) == {rbac.GENERAL_CHARGES_VIEW}


def test_routes_accept_general_permission_alone(monkeypatch) -> None:
    client = _login(monkeypatch, _sfx(), [rbac.GENERAL_SUBSCRIPTIONS_VIEW, rbac.GENERAL_CHARGES_VIEW])
    subs = client.get("/api/v1/general/subscriptions", params={"limit": 1})
    assert subs.status_code == 200, subs.text
    assert set(subs.json()["canales"]) == {"virtualpos1", "virtualpos2", "toku", "payku", "tch"}
    charges = client.get("/api/v1/general/charges", params={"limit": 1})
    assert charges.status_code == 200 and "payku" in charges.json()["canales"]
    assert client.get("/api/v1/general/payments", params={"limit": 1}).status_code == 200


def test_routes_without_any_permission_are_forbidden(monkeypatch) -> None:
    client = _login(monkeypatch, _sfx(), ["dashboard.view"])
    assert client.get("/api/v1/general/subscriptions").status_code == 403
    assert client.get("/api/v1/general/charges").status_code == 403


# --- Payku: ciclos como cobros (d124 b) -------------------------------------------------------------------------------


def test_payku_cycles_show_as_charges(monkeypatch) -> None:
    sfx = _sfx()
    db = SessionLocal()
    try:
        db.add_all([
            PaykuCycle(external_id=f"{sfx}:2011-08-05", subscription_id=f"sub-{sfx}", cycle_day="2011-08-05",
                       status="success", status_normalized="paid", amount_paid="7000", try_number=1),
            PaykuCycle(external_id=f"{sfx}:2011-09-05", subscription_id=f"sub-{sfx}", cycle_day="2011-09-05",
                       status="maximum attempt limit", status_normalized="rejected", amount_paid="0", try_number=3),
        ])
        db.commit()
    finally:
        db.close()
    client = _login(monkeypatch, sfx, ["payku.transactions.view"])
    params = {"canal": "payku", "date_from": "2011-08-01", "date_to": "2011-09-30"}
    body = client.get("/api/v1/general/charges", params=params).json()
    assert body["total"] == 2 and body["by_channel"] == {"payku": 2}
    first = body["items"][0]
    assert (first["channel"], first["charge_id"], first["status"], first["period"], first["rut"]) == (
        "payku", f"{sfx}:2011-08-05", "paid", "2011-08", None,
    )
    rejected = client.get("/api/v1/general/charges", params={**params, "outcome": "rejected"}).json()
    assert [row["charge_id"] for row in rejected["items"]] == [f"{sfx}:2011-09-05"]
    statuses = client.get("/api/v1/general/charges/statuses", params={"canal": "payku", **params}).json()
    assert {s["status"] for s in statuses["statuses"]} >= {"paid", "rejected"}
