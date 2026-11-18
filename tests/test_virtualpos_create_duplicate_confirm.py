"""BUG-VP-03c: el alta de suscripcion avisa (409) si ya hay una activa en el plan y crea si se confirma."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db
from app.core.config import settings
from app.core.security import ACCESS_COOKIE, create_access_token, get_current_user
from app.db.session import engine
from app.main import app
from app.models.auth import User
from app.models.vp import VpSubscription
from app.models.write_run import WriteRun
from app.services import write_virtualpos as svc

URL = "/api/v1/writes/virtualpos/subscriptions"
RUT = "11111111-1"  # relleno
PLAN = "zz03c-plan"
EXISTING = "zz03c-existing"
NEW_ID = "zz03c-new"
SENT: list[dict] = []


class FakeVP:
    def __init__(self, platform: str = "virtualpos1") -> None:
        self.platform = platform

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def create_subscription(self, data):
        SENT.append(dict(data))
        return {"suscription": {"id": NEW_ID, "plan_id": data["plan_id"], "status": "ACTIVA"}}


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


@pytest.fixture
def client(monkeypatch, db_session):
    SENT.clear()
    monkeypatch.setattr(settings, "virtualpos_writes_enabled", True)
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    monkeypatch.setattr(svc, "VirtualPOSClient", FakeVP)
    user = SimpleNamespace(
        id=uuid.uuid4(), is_active=True,
        roles=[SimpleNamespace(name="r", permissions=[SimpleNamespace(code="virtualpos.subscriptions.create")])],
    )
    db_session.add(User(id=user.id, username=f"u-{user.id.hex[:10]}", password_hash="x", is_active=True))
    db_session.add(VpSubscription(external_id=EXISTING, platform="virtualpos1", plan_external_id=PLAN,
                                  client_social_id=RUT, status="ACTIVA"))
    db_session.flush()
    token, csrf = create_access_token(user)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app, base_url="https://testserver")
    c.cookies.set(ACCESS_COOKIE, token)
    c.headers.update({"X-CSRF-Token": csrf})
    yield c
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db, None)


def _body(**extra) -> dict:
    return {"plan_id": PLAN, "email": "alta@example.com", "first_name": "Prueba", "last_name": "Relleno",
            "social_id": RUT, **extra}


def test_duplicate_without_flag_returns_409_with_new_code(client) -> None:
    r = client.post(URL, json=_body())
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "duplicate_active_subscription"
    assert detail["existing_external_id"] == EXISTING and detail["existing_status"] == "ACTIVA"
    assert RUT not in detail["message"] and "11111111" not in detail["message"]
    assert SENT == []


def test_duplicate_with_flag_creates_and_marks_write_run(client, db_session) -> None:
    r = client.post(URL, json=_body(confirm_duplicate=True))
    assert r.status_code == 200, r.text
    assert r.json()["external_id"] == NEW_ID
    run = db_session.scalar(select(WriteRun).where(WriteRun.operation == "create_subscription", WriteRun.external_id == NEW_ID))
    assert run.status == "completed"
    assert run.request_payload["duplicate_confirmed"] is True


def test_flag_is_not_sent_to_provider(client) -> None:
    assert client.post(URL, json=_body(confirm_duplicate=True)).status_code == 200
    assert len(SENT) == 1 and "confirm_duplicate" not in SENT[0]


def test_no_existing_active_creates_without_flag(client) -> None:
    r = client.post(URL, json=_body(plan_id="zz03c-other-plan"))
    assert r.status_code == 200, r.text
    assert "confirm_duplicate" not in SENT[0]
