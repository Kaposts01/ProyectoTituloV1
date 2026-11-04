"""d119 (opcion b): RUT y nombre en las pestañas Toku, TCH y Payku del Recuperador general, solo con el permiso de
datos personales del canal (ver clientes del canal), como las listas por canal y las vistas unificadas.

Datos SINTETICOS (RUT ficticios, nombres inventados, fechas en 2094). Las pruebas de servicio usan la sesion revertible;
las de API confirman sus filas y las borran al terminar.
"""

import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import Permission, Role, User
from app.models.core import CorePayment, CoreSubscription
from app.models.crm import Client, Subscription
from app.models.payku_channel import PaykuSubscription
from app.models.tch import TchClient, TchSubscription
from app.services import rbac, recovery_payku, recovery_pii, recovery_tch, recovery_toku
from tests.test_charge_recovery import db_session  # noqa: F401  (fixture)

WINDOW = (date(2094, 1, 1), date(2094, 12, 31))
ENDED = datetime(2094, 6, 1, tzinfo=UTC)
STARTED = datetime(2094, 1, 1, tzinfo=UTC)


def _seed(db: Session, tag: str, file_number: int) -> dict[str, str]:
    toku, payku, tch = f"tk-pii-{tag}", f"pk-pii-{tag}", str(file_number)
    db.add_all([
        CoreSubscription(source="toku", external_id=toku, status="deleted_at_source", started_at=STARTED, ended_at=ENDED),
        CoreSubscription(source="payku", external_id=payku, status="cancel", started_at=STARTED, ended_at=ENDED),
        CoreSubscription(source="tch", external_id=tch, status="ELIMINADO", started_at=STARTED, ended_at=ENDED),
        PaykuSubscription(external_id=payku, status="cancel", status_normalized="cancelled"),
        Subscription(source="toku", external_id=toku, client_external_id=f"cli-tk-{tag}"),
        Client(source="toku", external_id=f"cli-tk-{tag}", first_name="Ana", last_name="Prueba", social_id="11.111.111-1"),
        Subscription(source="payku", external_id=payku, client_external_id=f"cli-pk-{tag}", client_social_id="22.222.222-2"),
        Client(source="payku", external_id=f"cli-pk-{tag}", first_name="Beto", last_name="Ficticio"),
        TchSubscription(file_number=file_number, client_rut=f"9{file_number}-K", status="ELIMINADO"),
        TchClient(rut=f"9.{file_number}-k", name="Carla", last_name="Sintetica"),
    ])
    db.flush()
    tch_sub = db.scalar(select(CoreSubscription).where(CoreSubscription.source == "tch", CoreSubscription.external_id == tch))
    db.add(CorePayment(source="tch", external_id=f"{tch}|2094-02|1", subscription_id=tch_sub.id, source_status="RECHAZADA",
                       occurred_at=datetime(2094, 2, 10, tzinfo=UTC), amount=4000, rejection_code="05"))
    db.flush()
    return {"toku": toku, "payku": payku, "tch": tch}


def _row(result: dict, sub_id: str) -> dict:
    return next(r for r in result["items"] if r["subscription_id"] == sub_id)


def test_services_attach_rut_and_name_only_with_include_pii(db_session: Session) -> None:  # noqa: F811
    tag = uuid.uuid4().hex[:8]
    ids = _seed(db_session, tag, 70_000_000 + uuid.uuid4().int % 1_000_000)
    with_pii = {
        "toku": recovery_toku.cancelled(db_session, *WINDOW, 0, 500, include_pii=True),
        "payku": recovery_payku.cancelled(db_session, *WINDOW, 0, 500, include_pii=True),
        "tch": recovery_tch.deleted(db_session, *WINDOW, 0, 500, include_pii=True),
    }
    assert (_row(with_pii["toku"], ids["toku"])["rut"], _row(with_pii["toku"], ids["toku"])["name"]) == ("11.111.111-1", "Ana Prueba")
    assert (_row(with_pii["payku"], ids["payku"])["rut"], _row(with_pii["payku"], ids["payku"])["name"]) == ("22.222.222-2", "Beto Ficticio")
    tch_row = _row(with_pii["tch"], ids["tch"])
    assert tch_row["rut"] == f"9{ids['tch']}-K" and tch_row["name"] == "Carla Sintetica"  # nombre por RUT normalizado
    assert all(r["pii_included"] is True for r in with_pii.values())
    rejected = recovery_tch.rejected(db_session, *WINDOW, 0, 500, include_pii=True)
    assert _row(rejected, ids["tch"])["name"] == "Carla Sintetica"

    hidden = [
        recovery_toku.cancelled(db_session, *WINDOW, 0, 500),
        recovery_payku.cancelled(db_session, *WINDOW, 0, 500),
        recovery_tch.deleted(db_session, *WINDOW, 0, 500),
        recovery_tch.rejected(db_session, *WINDOW, 0, 500),
        recovery_toku.rejected(db_session, *WINDOW, 0, 500),
        recovery_payku.suspended(db_session, *WINDOW, 0, 500),
    ]
    for result in hidden:
        assert result["pii_included"] is False
        assert all(r["rut"] is None and r["name"] is None for r in result["items"])


def test_pii_permission_is_the_channel_client_view_permission() -> None:
    assert recovery_pii.PII_PERMISSIONS == {"toku": "toku.customers.view", "payku": "payku.clients.view",
                                            "tch": "tch.clientes.view"}
    for code in recovery_pii.PII_PERMISSIONS.values():
        assert code in rbac.PERMISSIONS
    assert recovery_pii.can_view_pii(None, "toku") is False


# ----------------------------- API (RBAC con y sin el permiso) -----------------------------


@pytest.fixture
def seeded():
    db = SessionLocal()
    tag = uuid.uuid4().hex[:8]
    file_number = 71_000_000 + uuid.uuid4().int % 1_000_000
    try:
        ids = _seed(db, tag, file_number)
        db.commit()
        yield ids
    finally:
        db.rollback()
        db.execute(delete(CorePayment).where(CorePayment.external_id == f"{ids['tch']}|2094-02|1"))
        db.execute(delete(CoreSubscription).where(CoreSubscription.external_id.in_(list(ids.values()))))
        db.execute(delete(PaykuSubscription).where(PaykuSubscription.external_id == ids["payku"]))
        db.execute(delete(Subscription).where(Subscription.external_id.in_([ids["toku"], ids["payku"]])))
        db.execute(delete(Client).where(Client.external_id.in_([f"cli-tk-{tag}", f"cli-pk-{tag}"])))
        db.execute(delete(TchSubscription).where(TchSubscription.file_number == file_number))
        db.execute(delete(TchClient).where(TchClient.rut == f"9.{file_number}-k"))
        db.commit()
        db.close()


def _login(monkeypatch, perms: list[str]) -> TestClient:
    suffix = uuid.uuid4().hex[:10]
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    db = SessionLocal()
    try:
        rbac.seed_permissions(db)
        plist = [db.scalar(select(Permission).where(Permission.code == p)) for p in perms]
        role = Role(name=f"pii-{suffix}", permissions=plist)
        db.add_all([role, User(username=f"pii-{suffix}", password_hash=hash_password("Pw-pii-12345"), is_active=True, roles=[role])])
        db.commit()
    finally:
        db.close()
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/v1/auth/login", json={"username": f"pii-{suffix}", "password": "Pw-pii-12345"}).status_code == 200
    return client


CASES = [
    ("toku", rbac.RECOVERY_TOKU_VIEW, "/api/v1/recovery/toku/cancelled", "Ana Prueba"),
    ("payku", rbac.RECOVERY_PAYKU_VIEW, "/api/v1/recovery/payku/cancelled", "Beto Ficticio"),
    ("tch", rbac.RECOVERY_TCH_VIEW, "/api/v1/recovery/tch/deleted", "Carla Sintetica"),
]


@pytest.mark.parametrize(("source", "tab_perm", "path", "name"), CASES)
def test_api_shows_rut_and_name_only_with_personal_data_permission(monkeypatch, seeded, source, tab_perm, path, name) -> None:
    params = {"date_from": "2094-01-01", "date_to": "2094-12-31", "limit": 500}
    without = _login(monkeypatch, [rbac.GENERAL_RECOVERY_VIEW, tab_perm]).get(path, params=params)
    assert without.status_code == 200
    body = without.json()
    row = _row(body, seeded[source])
    assert body["pii_included"] is False and row["rut"] is None and row["name"] is None
    assert name not in without.text

    with_perm = _login(monkeypatch, [rbac.GENERAL_RECOVERY_VIEW, tab_perm, recovery_pii.PII_PERMISSIONS[source]]).get(path, params=params)
    assert with_perm.status_code == 200
    body = with_perm.json()
    row = _row(body, seeded[source])
    assert body["pii_included"] is True and row["name"] == name and row["rut"]


@pytest.mark.parametrize(("source", "tab_perm", "path", "name"), CASES)
def test_personal_data_permission_alone_does_not_open_the_tab(monkeypatch, source, tab_perm, path, name) -> None:
    client = _login(monkeypatch, [rbac.GENERAL_RECOVERY_VIEW, recovery_pii.PII_PERMISSIONS[source]])
    assert client.get(path).status_code == 403
