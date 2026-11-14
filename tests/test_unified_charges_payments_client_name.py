"""13C (d205 a): nombre del socio en Cobros y Pagos de VirtualPOS (vista unificada y su exportacion).

VirtualPOS no entrega el ID del cliente en el cargo ni en el pago (`client_external_id` vacio), asi que el join al cliente
del canal no resolvia y la columna Socio quedaba vacia. Mismo orden de respaldo que la cartera de suscripciones:

* Cobros: cliente enlazado por ID > cliente embebido en el payload del cargo o de su suscripcion > cliente centralizado
  vinculado a la suscripcion, con el nombre observado en la misma fuente.
* Pagos: cliente enlazado por ID > cliente embebido en el payload del pago > cliente centralizado de la suscripcion
  vinculada al pago en `core_payments` (misma fuente).

Nunca se cruza por RUT contra otros clientes (ADR-001). La exportacion sigue exigiendo `export.pii`. Datos sinteticos
(prefijo DEMO), solo en la base de pruebas.
"""

from __future__ import annotations

import csv
import io
import random
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import Permission, Role, User
from app.models.core import (
    CoreClient,
    CoreClientAttribute,
    CorePayment,
    CoreSubscription,
)
from app.models.crm import Charge as CCharge
from app.models.crm import Client as CClient
from app.models.crm import Payment as CPayment
from app.models.crm import Subscription as CSub
from app.services import rbac

_TAG = "zq[0-9a-f]{8}"
VP = "virtualpos1"
_CORE_IDS: list[uuid.UUID] = []


def _sfx() -> str:
    return "zq" + "".join(random.choice("0123456789abcdef") for _ in range(8))


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    db = SessionLocal()
    try:
        params = {"tag": _TAG}
        for stmt in (
            "DELETE FROM core_payments WHERE external_id ~ :tag",
            "DELETE FROM core_client_attributes WHERE attribute_value ~ :tag",
            "DELETE FROM core_subscriptions WHERE external_id ~ :tag",
            "DELETE FROM payments WHERE external_id ~ :tag",
            "DELETE FROM charges WHERE external_id ~ :tag",
            "DELETE FROM subscriptions WHERE external_id ~ :tag",
            "DELETE FROM clients WHERE external_id ~ :tag",
            "DELETE FROM write_runs WHERE requested_by_user_id IN (SELECT id FROM users WHERE username ~ ('^uq-' || :tag))",
            "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username ~ ('^uq-' || :tag))",
            "DELETE FROM users WHERE username ~ ('^uq-' || :tag)",
            "DELETE FROM roles WHERE name ~ ('^uq-' || :tag)",
        ):
            db.execute(text(stmt), params)
        for core_id in _CORE_IDS:
            db.execute(text("DELETE FROM core_clients WHERE id = :id"), {"id": core_id})
        _CORE_IDS.clear()
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
        role = Role(name=f"uq-{suffix}", permissions=plist)
        db.add_all([role, User(username=f"uq-{suffix}", password_hash=hash_password("Pw-uq-12345"), is_active=True, roles=[role])])
        db.commit()
    finally:
        db.close()
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/v1/auth/login", json={"username": f"uq-{suffix}", "password": "Pw-uq-12345"}).status_code == 200
    return client


def _sub(sfx: str, key: str, *, client_ext: str | None = None, rut: str | None = None, payload_client: dict | None = None) -> CSub:
    return CSub(
        source=VP, external_id=f"{sfx}-s{key}", client_external_id=client_ext, client_social_id=rut, status="ACTIVA",
        suscription_date="2026-01-10", amount="5000", currency="CLP",
        raw_payload={"id": f"{sfx}-s{key}", "client": payload_client} if payload_client is not None else {"id": f"{sfx}-s{key}"},
    )


def _charge(sfx: str, key: str, sub_key: str | None, *, client_ext: str | None = None) -> CCharge:
    return CCharge(
        source=VP, external_id=f"{sfx}-c{key}", subscription_external_id=f"{sfx}-s{sub_key}" if sub_key else None,
        client_external_id=client_ext, amount="5000", currency="CLP", status="pagado", charge_date="2026-02-10",
        raw_payload={"id": f"{sfx}-c{key}", "status": "pagado"},
    )


def _payment(sfx: str, key: str, *, client_ext: str | None = None, payload_client: dict | None = None) -> CPayment:
    payload = {"order": {"uuid": f"{sfx}-p{key}"}}
    if payload_client is not None:
        payload["client"] = payload_client
    return CPayment(
        source=VP, external_id=f"{sfx}-p{key}", client_external_id=client_ext, amount="5000", currency="CLP",
        status="pagado", payment_date="2026-02-10", raw_payload=payload,
    )


def _seed(sfx: str) -> None:
    """Cobros y pagos VirtualPOS sinteticos, uno por caso del orden de respaldo."""
    db = SessionLocal()
    try:
        core_id = uuid.uuid4()
        _CORE_IDS.append(core_id)
        db.add(CoreClient(id=core_id))
        db.flush()
        core_sub = CoreSubscription(client_id=core_id, source=VP, external_id=f"{sfx}-sc", status="ACTIVA")
        db.add_all([
            CClient(source=VP, external_id=f"{sfx}-cli-a", first_name="DEMO Ana", last_name="Enlazada", social_id=f"DEMO-{sfx}-A"),
            CClient(source=VP, external_id=f"{sfx}-cli-d", first_name="DEMO Dora", last_name="PorRut", social_id=f"DEMO-{sfx}-D"),
            # a) cliente enlazado por ID (en la suscripcion): manda sobre el payload
            _sub(sfx, "a", client_ext=f"{sfx}-cli-a", rut=f"DEMO-{sfx}-A", payload_client={"first_name": "DEMO Otro", "last_name": "Payload"}),
            # b) caso real de VirtualPOS: sin ID, nombre embebido en la suscripcion
            _sub(sfx, "b", rut=f"DEMO-{sfx}-B", payload_client={"first_name": "DEMO Bruno", "last_name": "Embebido"}),
            # c) sin ID ni nombre: cliente centralizado vinculado, nombre de la MISMA fuente
            _sub(sfx, "c", rut=f"DEMO-{sfx}-C", payload_client={"first_name": " "}),
            core_sub,
            CoreClientAttribute(client_id=core_id, source=VP, attribute_type="name", attribute_value=f"DEMO Carla Central {sfx}"),
            CoreClientAttribute(client_id=core_id, source="toku", attribute_type="name", attribute_value=f"DEMO Otra Fuente {sfx}"),
            # d) solo RUT compartido con un cliente del canal sin enlace: NO se cruza por RUT
            _sub(sfx, "d", rut=f"DEMO-{sfx}-D"),
            _charge(sfx, "a", "a"), _charge(sfx, "b", "b"), _charge(sfx, "c", "c"), _charge(sfx, "d", "d"),
            _charge(sfx, "e", None),  # cargo sin suscripcion: sin nombre
            # pagos
            _payment(sfx, "a", client_ext=f"{sfx}-cli-a", payload_client={"first_name": "DEMO Otro", "last_name": "Payload"}),
            _payment(sfx, "b", payload_client={"first_name": "DEMO Bruno", "last_name": "Embebido", "social_id": f"DEMO-{sfx}-B"}),
            _payment(sfx, "c", payload_client={"first_name": "", "social_id": f"DEMO-{sfx}-C"}),
            _payment(sfx, "d", payload_client={"social_id": f"DEMO-{sfx}-D"}),
        ])
        db.flush()
        db.add(CorePayment(subscription_id=core_sub.id, source=VP, external_id=f"{sfx}-pc", source_status="pagado"))
        db.commit()
    finally:
        db.close()


def _rows(client: TestClient, path: str, key: str, sfx: str) -> dict[str, dict]:
    resp = client.get(f"/api/v1/general/{path}", params={"canal": "virtualpos", "filter_field": "id", "query": sfx})
    assert resp.status_code == 200, resp.text
    return {row[key].removeprefix(f"{sfx}-"): row for row in resp.json()["items"]}


def test_vp_charge_name_follows_fallback_order(monkeypatch) -> None:
    sfx = _sfx()
    _seed(sfx)
    client = _login(monkeypatch, sfx, ["virtualpos.charges.view"])
    rows = _rows(client, "charges", "charge_id", sfx)
    assert list(rows) == ["ca", "cb", "cc", "cd", "ce"]
    assert rows["ca"]["name"] == "DEMO Ana Enlazada"
    assert rows["cb"]["name"] == "DEMO Bruno Embebido" and rows["cb"]["rut"] == f"DEMO-{sfx}-B"
    assert rows["cc"]["name"] == f"DEMO Carla Central {sfx}"
    assert rows["cd"]["name"] is None and rows["cd"]["rut"] == f"DEMO-{sfx}-D"
    assert rows["ce"]["name"] is None


def test_vp_payment_name_follows_fallback_order(monkeypatch) -> None:
    sfx = _sfx()
    _seed(sfx)
    client = _login(monkeypatch, sfx, ["virtualpos.payments.view"])
    rows = _rows(client, "payments", "payment_id", sfx)
    assert list(rows) == ["pa", "pb", "pc", "pd"]
    assert rows["pa"]["name"] == "DEMO Ana Enlazada"
    assert rows["pb"]["name"] == "DEMO Bruno Embebido" and rows["pb"]["rut"] == f"DEMO-{sfx}-B"
    assert rows["pc"]["name"] == f"DEMO Carla Central {sfx}"
    assert rows["pd"]["name"] is None and rows["pd"]["rut"] == f"DEMO-{sfx}-D"


def _export(client: TestClient, entity: str, sfx: str) -> list[dict[str, str]]:
    resp = client.get(f"/api/v1/export/{entity}", params={"canal": "virtualpos", "filter_field": "id", "query": sfx})
    assert resp.status_code == 200, resp.text
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))


def test_export_includes_names_only_with_export_pii(monkeypatch) -> None:
    sfx = _sfx()
    _seed(sfx)
    perms = ["virtualpos.charges.view", "virtualpos.payments.view"]
    with_pii = _login(monkeypatch, sfx, [*perms, "export.pii"])
    assert [r["Nombre del cliente"] for r in _export(with_pii, "cobros", sfx)] == [
        "DEMO Ana Enlazada", "DEMO Bruno Embebido", f"DEMO Carla Central {sfx}", "", "",
    ]
    assert [r["Nombre del cliente"] for r in _export(with_pii, "pagos", sfx)] == [
        "DEMO Ana Enlazada", "DEMO Bruno Embebido", f"DEMO Carla Central {sfx}", "",
    ]
    without_pii = _login(monkeypatch, _sfx(), perms)
    for entity, count in (("cobros", 5), ("pagos", 4)):
        rows = _export(without_pii, entity, sfx)
        assert len(rows) == count
        assert "Nombre del cliente" not in rows[0] and "RUT del cliente" not in rows[0]
