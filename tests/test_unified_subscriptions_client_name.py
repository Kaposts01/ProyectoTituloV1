"""13C: nombre del socio en la cartera de suscripciones (vista unificada y su exportacion).

VirtualPOS no entrega el ID del cliente en la suscripcion (`client_external_id` vacio), asi que el join al cliente del
canal no resolvia y la fila mostraba el RUT pero no el nombre. Orden de respaldo (`export_queries._subs_client_name`):
cliente enlazado por ID > cliente embebido en el payload de la suscripcion (solo VirtualPOS) > cliente centralizado
vinculado a la suscripcion, con el nombre observado en la misma fuente. Nunca por RUT contra otros clientes (ADR-001).
Datos sinteticos (prefijo DEMO), solo en la base de pruebas.
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
from app.models.core import CoreClient, CoreClientAttribute, CoreSubscription
from app.models.crm import Client as CClient
from app.models.crm import Subscription as CSub
from app.services import rbac

_TAG = "zn[0-9a-f]{8}"
VP = "virtualpos1"


def _sfx() -> str:
    return "zn" + "".join(random.choice("0123456789abcdef") for _ in range(8))


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    db = SessionLocal()
    try:
        params = {"tag": _TAG}
        for stmt in (
            "DELETE FROM core_client_attributes WHERE attribute_value ~ :tag",
            "DELETE FROM core_subscriptions WHERE external_id ~ :tag",
            "DELETE FROM subscriptions WHERE external_id ~ :tag",
            "DELETE FROM clients WHERE external_id ~ :tag",
            "DELETE FROM write_runs WHERE requested_by_user_id IN (SELECT id FROM users WHERE username ~ ('^un-' || :tag))",
            "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username ~ ('^un-' || :tag))",
            "DELETE FROM users WHERE username ~ ('^un-' || :tag)",
            "DELETE FROM roles WHERE name ~ ('^un-' || :tag)",
        ):
            db.execute(text(stmt), params)
        for core_id in _CORE_IDS:
            db.execute(text("DELETE FROM core_clients WHERE id = :id"), {"id": core_id})
        _CORE_IDS.clear()
        db.commit()
    finally:
        db.close()


_CORE_IDS: list[uuid.UUID] = []


def _login(monkeypatch, suffix: str, perms: list[str]) -> TestClient:
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    db = SessionLocal()
    try:
        rbac.seed_permissions(db)
        plist = [db.scalar(select(Permission).where(Permission.code == p)) for p in perms]
        assert all(plist), perms
        role = Role(name=f"un-{suffix}", permissions=plist)
        db.add_all([role, User(username=f"un-{suffix}", password_hash=hash_password("Pw-un-12345"), is_active=True, roles=[role])])
        db.commit()
    finally:
        db.close()
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/v1/auth/login", json={"username": f"un-{suffix}", "password": "Pw-un-12345"}).status_code == 200
    return client


def _sub(sfx: str, key: str, *, client_ext: str | None = None, rut: str | None = None, payload_client: dict | None = None,
         source: str = VP) -> CSub:
    return CSub(
        source=source, external_id=f"{sfx}-{key}", client_external_id=client_ext, client_social_id=rut, status="ACTIVA",
        suscription_date="2026-01-10", amount="5000", currency="CLP",
        raw_payload={"id": f"{sfx}-{key}", "client": payload_client} if payload_client is not None else {"id": f"{sfx}-{key}"},
    )


def _seed(sfx: str) -> None:
    """Cinco suscripciones VirtualPOS sinteticas, una por caso del orden de respaldo."""
    db = SessionLocal()
    try:
        core_id = uuid.uuid4()
        _CORE_IDS.append(core_id)
        db.add(CoreClient(id=core_id))
        db.flush()
        db.add_all([
            # a) enlace por ID al cliente del canal: manda sobre el payload
            CClient(source=VP, external_id=f"{sfx}-cli-a", first_name="DEMO Ana", last_name="Enlazada", social_id=f"DEMO-{sfx}-A"),
            _sub(sfx, "a", client_ext=f"{sfx}-cli-a", rut=f"DEMO-{sfx}-A",
                 payload_client={"first_name": "DEMO Otro", "last_name": "Payload"}),
            # b) sin ID de cliente (caso real de VirtualPOS): nombre del cliente embebido en la suscripcion
            _sub(sfx, "b", rut=f"DEMO-{sfx}-B", payload_client={"first_name": "DEMO Bruno", "last_name": "Embebido",
                                                                 "social_id": f"DEMO-{sfx}-B"}),
            # c) sin ID ni nombre en el payload: cliente centralizado vinculado, nombre de la MISMA fuente
            _sub(sfx, "c", rut=f"DEMO-{sfx}-C", payload_client={"first_name": " ", "social_id": f"DEMO-{sfx}-C"}),
            CoreSubscription(client_id=core_id, source=VP, external_id=f"{sfx}-c", status="ACTIVA"),
            CoreClientAttribute(client_id=core_id, source=VP, attribute_type="name", attribute_value=f"DEMO Carla Central {sfx}"),
            CoreClientAttribute(client_id=core_id, source="toku", attribute_type="name", attribute_value=f"DEMO Otra Fuente {sfx}"),
            # d) solo RUT, compartido con un cliente del mismo canal sin enlace: NO se cruza por RUT (ADR-001)
            CClient(source=VP, external_id=f"{sfx}-cli-d", first_name="DEMO Dora", last_name="PorRut", social_id=f"DEMO-{sfx}-D"),
            _sub(sfx, "d", rut=f"DEMO-{sfx}-D"),
        ])
        db.commit()
    finally:
        db.close()


def _rows(client: TestClient, sfx: str, **params) -> dict[str, dict]:
    body = client.get("/api/v1/general/subscriptions",
                      params={"canal": "virtualpos", "filter_field": "id", "query": sfx, **params}).json()
    return {row["subscription_id"].removeprefix(f"{sfx}-"): row for row in body["items"]}


def test_vp_subscription_name_follows_fallback_order(monkeypatch) -> None:
    sfx = _sfx()
    _seed(sfx)
    client = _login(monkeypatch, sfx, ["virtualpos.subscriptions.view"])
    rows = _rows(client, sfx)
    assert list(rows) == ["a", "b", "c", "d"]  # orden intacto (canal, ID)
    assert rows["a"]["name"] == "DEMO Ana Enlazada"
    assert rows["b"]["name"] == "DEMO Bruno Embebido" and rows["b"]["rut"] == f"DEMO-{sfx}-B"
    assert rows["c"]["name"] == f"DEMO Carla Central {sfx}"
    assert rows["d"]["name"] is None and rows["d"]["rut"] == f"DEMO-{sfx}-D"


def test_client_filter_searches_the_resolved_name(monkeypatch) -> None:
    sfx = _sfx()
    _seed(sfx)
    client = _login(monkeypatch, sfx, ["virtualpos.subscriptions.view"])
    for needle, expected in (("Bruno Embebido", "b"), (f"Carla Central {sfx}", "c"), ("Ana Enlazada", "a")):
        body = client.get("/api/v1/general/subscriptions",
                          params={"canal": "virtualpos", "filter_field": "client", "query": needle}).json()
        ids = [row["subscription_id"] for row in body["items"] if row["subscription_id"].startswith(sfx)]
        assert ids == [f"{sfx}-{expected}"], needle
    # el nombre del payload que perdio contra el enlace por ID no hace match
    body = client.get("/api/v1/general/subscriptions",
                      params={"canal": "virtualpos", "filter_field": "client", "query": "Otro Payload"}).json()
    assert not [row for row in body["items"] if row["subscription_id"].startswith(sfx)]


def _export(client: TestClient, sfx: str) -> list[dict[str, str]]:
    resp = client.get("/api/v1/export/suscripciones", params={"canal": "virtualpos", "filter_field": "id", "query": sfx})
    assert resp.status_code == 200, resp.text
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))


def test_export_includes_name_only_with_export_pii(monkeypatch) -> None:
    sfx = _sfx()
    _seed(sfx)
    with_pii = _login(monkeypatch, sfx, ["virtualpos.subscriptions.view", "export.pii"])
    rows = _export(with_pii, sfx)
    assert [row["Nombre del cliente"] for row in rows] == [
        "DEMO Ana Enlazada", "DEMO Bruno Embebido", f"DEMO Carla Central {sfx}", "",
    ]
    sfx2 = _sfx()
    without_pii = _login(monkeypatch, sfx2, ["virtualpos.subscriptions.view"])
    rows = _export(without_pii, sfx)
    assert len(rows) == 4 and "Nombre del cliente" not in rows[0] and "RUT del cliente" not in rows[0]
