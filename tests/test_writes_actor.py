# ruff: noqa: F811  (fixtures importadas de billing_requests_support: db_session/env)
"""MGT-01: todo `write_runs` creado por las rutas `/api/v1/writes/*` guarda `requested_by_user_id` con el usuario del
token (antes solo lo llenaba la Opcion A). Autenticacion real (JWT + cookie + CSRF) y proveedores falsos: ninguna red.
"""

from billing_requests_support import (  # noqa: F401 - fixtures autouse/importadas
    client_for,
    db_session,
    env,
    make_role,
    make_user,
)
from sqlalchemy import select

from app.core.config import settings
from app.models.crm import Client, Subscription
from app.models.write_run import WriteRun
from app.services import subscription_refresh, write_payku, write_toku, write_virtualpos

BASE = "/api/v1/writes"


class _CM:
    """Cliente de proveedor falso: contexto asincrono sin red."""

    def __init__(self, *_: object, **__: object) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class FakeVPActor(_CM):
    async def cancel_subscription(self, subscription_id):
        return {}

    async def get_subscription(self, subscription_id):
        return {"id": subscription_id, "status": "CANCELADA"}

    async def update_client(self, client_id, changes):
        return {"uuid": client_id, **changes}

    async def list_charges(self, subscription_id, page=1, limit=100, status=None):
        return {"charges": [], "pagination": {"pages": 1, "page": page}}


class FakeTokuActor(_CM):
    def precheck_writes(self, operations):
        return None

    async def list_subscription_invoices(self, subscription_id, general_statuses=None, page_size=100):
        return {"invoices": []}

    async def delete_subscription(self, subscription_id):
        return {}

    async def change_subscription_status(self, subscription_id, data):
        return {}

    async def get_subscription(self, subscription_id):
        return {"id": subscription_id, "status": "PAUSED"}


class FakePaykuActor(_CM):
    async def delete_subscription(self, subscription_id):
        return {}

    async def update_client(self, client_id, changes):
        return {}

    async def get_client(self, client_id):
        return {"id": client_id, "name": "Despues"}


def _actor(db, *codes, admin=False):
    """`admin=True` agrega el rol `admin`: los botones directos de BAJA de /writes/* quedaron restringidos a admin."""
    roles = [make_role(db, "actor-writes-t", set(codes))]
    if admin:
        roles.append(make_role(db, "admin", set(codes)))
    user = make_user(db, *roles)
    client, headers = client_for(db, user)
    return user, client, headers


def _runs(db, operation):
    return list(db.scalars(select(WriteRun).where(WriteRun.operation == operation)))


def test_virtualpos_cancel_subscription_records_actor(monkeypatch, db_session) -> None:
    monkeypatch.setattr(write_virtualpos, "VirtualPOSClient", FakeVPActor)
    monkeypatch.setattr(subscription_refresh, "VirtualPOSClient", FakeVPActor)
    db_session.add(Subscription(source="virtualpos1", external_id="sub-actor-vp", status="ACTIVA"))
    db_session.commit()
    user, client, h = _actor(db_session, "virtualpos.subscriptions.cancel", admin=True)
    r = client.delete(f"{BASE}/virtualpos/subscriptions/sub-actor-vp", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert (body["external_id"], body["status"]) == ("sub-actor-vp", "CANCELADA")  # campos previos intactos
    assert body["requires_reconciliation"] is False  # campos nuevos de la verificacion (aditivos)
    runs = _runs(db_session, "cancel_subscription")
    assert len(runs) == 1 and runs[0].requested_by_user_id == user.id


def test_virtualpos_update_client_records_actor(monkeypatch, db_session) -> None:
    monkeypatch.setattr(write_virtualpos, "VirtualPOSClient", FakeVPActor)
    db_session.add(Client(source="virtualpos1", external_id="cli-actor-vp", first_name="Antes"))
    db_session.commit()
    user, client, h = _actor(db_session, "virtualpos.clients.update")
    r = client.put(f"{BASE}/virtualpos/clients/cli-actor-vp", json={"first_name": "Despues"}, headers=h)
    assert r.status_code == 200
    runs = _runs(db_session, "update_client")
    assert len(runs) == 1 and runs[0].requested_by_user_id == user.id


def test_toku_delete_subscription_and_status_record_actor(monkeypatch, db_session) -> None:
    monkeypatch.setattr(write_toku, "TokuClient", FakeTokuActor)
    monkeypatch.setattr(settings, "toku_writes_enabled", True)
    db_session.add_all([
        Subscription(source="toku", external_id="sub-actor-tk-1", raw_payload={}),
        Subscription(source="toku", external_id="sub-actor-tk-2", raw_payload={}),
    ])
    db_session.commit()
    user, client, h = _actor(db_session, "toku.subscriptions.manage", admin=True)
    assert client.delete(f"{BASE}/toku/subscriptions/sub-actor-tk-1", headers=h).status_code == 200
    r = client.post(f"{BASE}/toku/subscriptions/sub-actor-tk-2/status", json={"status": "PAUSED"}, headers=h)
    assert r.status_code == 200
    for op in ("delete_subscription", "change_subscription_status"):
        runs = _runs(db_session, op)
        assert len(runs) == 1 and runs[0].requested_by_user_id == user.id, op


def test_payku_delete_subscription_and_update_client_record_actor(monkeypatch, db_session) -> None:
    monkeypatch.setattr(write_payku, "PaykuClient", FakePaykuActor)
    monkeypatch.setattr(settings, "payku_writes_enabled", True)
    db_session.add_all([
        Subscription(source="payku", external_id="sub-actor-pk", raw_payload={}),
        Client(source="payku", external_id="cli-actor-pk", first_name="Antes"),
    ])
    db_session.commit()
    user, client, h = _actor(db_session, "payku.subscriptions.cancel", "payku.clients.update", admin=True)
    assert client.delete(f"{BASE}/payku/subscriptions/sub-actor-pk", headers=h).status_code == 200
    assert client.put(f"{BASE}/payku/clients/cli-actor-pk", json={"name": "Despues"}, headers=h).status_code == 200
    for op in ("delete_subscription", "update_client"):
        runs = _runs(db_session, op)
        assert len(runs) == 1 and runs[0].requested_by_user_id == user.id, op


def test_service_default_keeps_actor_null(monkeypatch, db_session) -> None:
    """Sin pasar el argumento (scripts, otros servicios) el comportamiento anterior no cambia."""
    import asyncio

    monkeypatch.setattr(write_virtualpos, "VirtualPOSClient", FakeVPActor)
    monkeypatch.setattr(subscription_refresh, "VirtualPOSClient", FakeVPActor)
    db_session.add(Subscription(source="virtualpos1", external_id="sub-actor-null", status="ACTIVA"))
    db_session.commit()
    asyncio.run(write_virtualpos.cancel_subscription(db_session, "sub-actor-null"))
    assert _runs(db_session, "cancel_subscription")[0].requested_by_user_id is None
