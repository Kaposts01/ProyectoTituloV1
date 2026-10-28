"""Soporte compartido de tests_billing_requests_{service,api}: FakeVP en memoria, usuarios/roles reales y cliente HTTP.

Ninguna llamada de red: `VirtualPOSClient` se reemplaza por `FakeVP` (estado en memoria con CALLS/STATE).
Los usuarios son filas reales (rol + permisos) dentro de una transaccion que se revierte al terminar cada test.
"""

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db as crm_get_db
from app.core.config import settings
from app.core.security import ACCESS_COOKIE, create_access_token
from app.core.security import get_db as security_get_db
from app.db.session import engine
from app.integrations.virtualpos.client import VirtualPOSAPIError
from app.main import app
from app.models.auth import Permission, Role, User
from app.models.billing import BillingPolicy, VpCalendarMark, VpManagedCharge
from app.models.crm import Plan, Subscription
from app.services import billing_apply as ba
from app.services import write_virtualpos as wv
from app.services.rbac import (
    PERMISSIONS,
    executive_permission_codes,
    seed_permissions,
    support_permission_codes,
)

SUB = "sub-req-1"
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=ZoneInfo("America/Santiago"))
CALLS: list[tuple] = []
STATE: dict = {}
HORIZON = [f"2026-{m:02d}" for m in (11, 12)] + [f"2027-{m:02d}" for m in range(1, 11)]

P_REQUEST = "virtualpos.billing_changes.request"
P_APPROVE = "virtualpos.billing_changes.approve"
P_VIEW = "virtualpos.billing_changes.view"
P_MANAGE = "virtualpos.billing_policy.manage"


def api_error(code: str) -> VirtualPOSAPIError:
    return VirtualPOSAPIError(code, "nok", 400, 200)


class FakeVP:
    def __init__(self, platform: str = "virtualpos1") -> None:
        self.platform = platform

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def _by_id(self, charge_id):
        return next(c for c in STATE["charges"] if c["id"] == charge_id)

    async def list_charges(self, subscription_id, page=1, limit=100, status=None):
        CALLS.append(("list_charges", status))
        if STATE.get("list_error") is not None:
            raise STATE["list_error"]
        rows = [c for c in STATE["charges"] if status is None or c["status"] == status]
        return {"charges": [dict(c) for c in rows], "pagination": {"pages": 1, "page": page}}

    async def delete_subscription_charges(self, subscription_id):
        CALLS.append(("delete_plural", subscription_id))
        pend = [c for c in STATE["charges"] if c["status"] == "pendiente"]
        for c in pend:
            c["status"] = "cancelado"
        return {"cancel_charges": [dict(c) for c in pend]}

    async def delete_charge(self, charge_id):
        CALLS.append(("delete_charge", charge_id))
        fails = STATE.setdefault("delete_fail", {})
        if fails.get(charge_id, 0) > 0:
            fails[charge_id] -= 1
            raise httpx.ConnectError("boom")
        self._by_id(charge_id)["status"] = "cancelado"
        return {}

    async def create_charge(self, data):
        STATE["n_create"] += 1
        n = STATE["n_create"]
        CALLS.append(("create_charge", data["internal_code"]))
        fail = STATE.get("create_fail") or {}
        if fail.get("at") == n:
            raise api_error("E-113")
        charge = {"id": f"new-{n}", "charge_date": data["charge_date"], "amount": data["amount"],
                  "status": "pendiente", "internal_code": data["internal_code"]}
        STATE["charges"].append(charge)
        return {**charge, "suscription_id": data["suscription_id"]}

    async def get_charge(self, charge_id):
        return dict(self._by_id(charge_id))


def autos(amount: int = 9900) -> list[dict]:
    rows = [{"id": f"auto-{i:02d}", "charge_date": f"{m}-05", "amount": amount, "status": "pendiente"}
            for i, m in enumerate(HORIZON, start=1)]
    rows += [{"id": "auto-13", "charge_date": "2027-11-05", "amount": amount, "status": "pendiente"},
             {"id": "auto-14", "charge_date": "2027-12-05", "amount": amount, "status": "pendiente"},
             {"id": "paid-0", "charge_date": "2026-10-05", "amount": amount, "status": "pagado"}]
    return rows


@pytest.fixture(autouse=True)
def env(monkeypatch):
    CALLS.clear()
    STATE.clear()
    STATE.update(charges=autos(), n_create=0)
    monkeypatch.setattr(settings, "virtualpos_writes_enabled", True)
    monkeypatch.setattr(settings, "virtualpos_allow_charge_on_fixed_plan", True)
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    monkeypatch.setattr(wv, "VirtualPOSClient", FakeVP)
    monkeypatch.setattr(ba, "now_chile", lambda: NOW)  # "hoy" fijo en Chile para API y servicio
    yield
    app.dependency_overrides.pop(crm_get_db, None)
    app.dependency_overrides.pop(security_get_db, None)


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


# ----------------------------- datos -----------------------------


def make_role(db: Session, name: str, codes: set[str]) -> Role:
    seed_permissions(db)
    perms = {p.code: p for p in db.scalars(select(Permission))}
    role = db.scalar(select(Role).where(Role.name == name))
    if role is None:
        role = Role(name=name)
        db.add(role)
    role.permissions = [perms[c] for c in sorted(codes)]
    db.flush()
    return role


def make_user(db: Session, *roles: Role, active: bool = True) -> User:
    user = User(username=f"u-{uuid.uuid4().hex[:10]}", password_hash="x", is_active=active, roles=list(roles))
    db.add(user)
    db.flush()
    return user


def roles_kit(db: Session) -> dict[str, Role]:
    """admin (todos los permisos), ejecutivo/soporte (.view), solicitante (request+view), gestor_politica (manage)."""
    return {
        "admin": make_role(db, "admin", set(PERMISSIONS)),
        "ejecutivo": make_role(db, "ejecutivo", executive_permission_codes()),
        "soporte": make_role(db, "soporte", support_permission_codes()),
        "solicitante": make_role(db, "solicitante-t", {P_REQUEST, P_VIEW}),
        "gestor": make_role(db, "gestor-politica-t", {P_MANAGE, P_VIEW}),
        "aprobador": make_role(db, "aprobador-t", {P_APPROVE, P_VIEW}),
    }


def seed_sub(db: Session, status: str = "ACTIVA", plan_type: str = "MONTO_FIJO") -> None:
    db.add(Subscription(source="virtualpos1", external_id=SUB, plan_external_id="plan-1", status=status))
    db.add(Plan(source="virtualpos1", external_id="plan-1", plan_type=plan_type))
    db.commit()


def set_policy(db: Session, **values) -> BillingPolicy:
    from app.services import billing_requests as br

    policy = br.get_policy(db)
    for k, v in values.items():
        setattr(policy, k, v)
    db.commit()
    return policy


def seed_crm_calendar(db: Session, amount: int = 12000) -> None:
    """Calendario modificado por el CRM (12 pendientes del CRM + marca) y 2 automaticos posteriores al horizonte."""
    rows, months = [], HORIZON
    for i, m in enumerate(months, start=1):
        cid = f"m-{i:02d}"
        code = f"{SUB}-{m.replace('-', '')}-{amount}"
        rows.append({"id": cid, "charge_date": f"{m}-05", "amount": amount, "status": "pendiente", "internal_code": code})
        db.add(VpManagedCharge(platform="virtualpos1", charge_id=cid, subscription_external_id=SUB, internal_code=code,
                               month=m, charge_date=date.fromisoformat(f"{m}-05"), amount=amount, status="creado"))
    rows += [{"id": "auto-13", "charge_date": "2027-11-05", "amount": 9900, "status": "pendiente"},
             {"id": "auto-14", "charge_date": "2027-12-05", "amount": 9900, "status": "pendiente"},
             {"id": "paid-0", "charge_date": "2026-10-05", "amount": 9900, "status": "pagado"}]
    STATE["charges"] = rows
    db.add(VpCalendarMark(platform="virtualpos1", subscription_external_id=SUB, last_scheduled_month="2027-10",
                          last_scheduled_date=date(2027, 10, 5), scheduled_amount=amount, charge_day=5, is_active=True))
    db.commit()


def client_for(db: Session, user: User) -> tuple[TestClient, dict[str, str]]:
    """Cliente HTTP autenticado de verdad (JWT + cookie) contra la sesion de test; devuelve (cliente, cabecera CSRF)."""
    token, csrf = create_access_token(user)
    app.dependency_overrides[crm_get_db] = lambda: db
    app.dependency_overrides[security_get_db] = lambda: db
    client = TestClient(app)
    client.cookies.set(ACCESS_COOKIE, token)
    return client, {"X-CSRF-Token": csrf}


def names() -> list[str]:
    return [c[0] for c in CALLS]


def deleted() -> list[str]:
    return [c[1] for c in CALLS if c[0] == "delete_charge"]
