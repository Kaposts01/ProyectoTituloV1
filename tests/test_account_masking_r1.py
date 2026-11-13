"""d199 (R1 del inventario SEC-01): la cuenta bancaria de TCH nunca sale completa, solo los ultimos 4 digitos.

La base no cambia (sin migraciones): `tch_suscripciones.numero_cuenta` sigue guardada; se enmascara al leer en la API
(ficha TCH, registros `crm`, fichas de staging y source records). Las exportaciones no tienen columna de cuenta.
Datos sinteticos.
"""

from __future__ import annotations

import csv
import io
import random
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.api.v1.routes.staging import _cstg
from app.api.v1.routes.staging import _serialize as serialize_source_record
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import Permission, Role, User
from app.models.crm import Subscription
from app.models.source_record import SourceRecord
from app.models.tch import TchSubscription
from app.services import rbac
from app.services.account_masking import (
    is_account_number_key,
    mask_account_fields,
    mask_account_number,
)
from app.services.export_queries import ENTITY_COLUMNS

ACCOUNT = "000123456789"


@pytest.mark.parametrize("key", ["numero_cuenta", "Número Cuenta", "NUMERO CUENTA", "N° Cuenta", "Nº de cuenta", "Nro. Cuenta",
                                 "num_cuenta", "account_number", "bank_account_number", "Cuenta Bancaria"])
def test_account_number_keys_are_detected(key) -> None:
    assert is_account_number_key(key)


@pytest.mark.parametrize("key", ["tipo_cuenta", "Tipo Cuenta", "cuenta", "account", "numero_ficha", "numero_mandato", "banco_nombre"])
def test_other_keys_are_not_masked(key) -> None:
    assert not is_account_number_key(key)


def test_mask_keeps_only_the_last_four_digits() -> None:
    assert mask_account_number(ACCOUNT) == "••••6789"
    assert mask_account_number("12-345-678 9") == "••••6789"
    assert mask_account_number("1234") == "••••"  # una cuenta corta nunca se muestra completa
    assert mask_account_number(None) is None and mask_account_number("  ") is None


def test_mask_fields_is_recursive_and_does_not_mutate() -> None:
    payload = {"Número Cuenta": ACCOUNT, "Tipo Cuenta": "CORRIENTE", "nested": [{"N° Cuenta": "987654321"}], "cuenta": "virtualpos1"}
    masked = mask_account_fields(payload)
    assert masked == {"Número Cuenta": "••••6789", "Tipo Cuenta": "CORRIENTE", "nested": [{"N° Cuenta": "••••4321"}],
                      "cuenta": "virtualpos1"}
    assert payload["Número Cuenta"] == ACCOUNT
    assert ACCOUNT not in str(masked)


def test_staging_serializers_mask_the_payload() -> None:
    sub = Subscription(id=uuid.uuid4(), source="tch", external_id="DEMO-r1", raw_payload={"Número Cuenta": ACCOUNT, "Banco": "X"})
    data = _cstg(sub, "subscription")
    assert data["payload"]["Número Cuenta"] == "••••6789" and data["payload"]["Banco"] == "X"
    record = SourceRecord(id=uuid.uuid4(), source="tch", resource_type="subscription", external_id="DEMO-r1",
                          payload={"numero_cuenta": ACCOUNT})
    assert serialize_source_record(record)["payload"] == {"numero_cuenta": "••••6789"}


def test_exports_have_no_account_column() -> None:
    for columns in ENTITY_COLUMNS.values():
        assert not [c for c in columns if is_account_number_key(c.key) or "cuenta" in c.header.lower()]


# ----------------------------------------------------------------------------- API (contra crm_test)

_FILE = random.randint(900_000_000, 999_999_999)
_TAG = "r1z[0-9a-f]{8}"


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM tch_suscripciones WHERE numero_ficha = :f"), {"f": _FILE})
        db.execute(text("DELETE FROM subscriptions WHERE source = 'tch' AND external_id = :e"), {"e": f"DEMO-R1-{_FILE}"})
        for stmt in (
            "DELETE FROM write_runs WHERE requested_by_user_id IN (SELECT id FROM users WHERE username ~ ('^' || :tag))",
            "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username ~ ('^' || :tag))",
            "DELETE FROM users WHERE username ~ ('^' || :tag)",
            "DELETE FROM roles WHERE name ~ ('^' || :tag)",
        ):
            db.execute(text(stmt), {"tag": _TAG})
        db.commit()
    finally:
        db.close()


def _login(monkeypatch, perms: list[str]) -> TestClient:
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    name = "r1z" + uuid.uuid4().hex[:8]
    db = SessionLocal()
    try:
        rbac.seed_permissions(db)
        plist = [db.scalar(select(Permission).where(Permission.code == p)) for p in perms]
        assert all(plist), perms
        role = Role(name=name, permissions=plist)
        db.add_all([role, User(username=name, password_hash=hash_password("Pw-r1-12345"), is_active=True, roles=[role])])
        db.commit()
    finally:
        db.close()
    client = TestClient(app, base_url="https://testserver")
    assert client.post("/api/v1/auth/login", json={"username": name, "password": "Pw-r1-12345"}).status_code == 200
    return client


def _seed() -> uuid.UUID:
    db = SessionLocal()
    try:
        db.add(TchSubscription(file_number=_FILE, client_rut="40000001-0", bank_name="Banco DEMO", account_type="CORRIENTE",
                               account_number=ACCOUNT, status="VIGENTE", raw_payload={"Número Cuenta": ACCOUNT}))
        sub = Subscription(source="tch", external_id=f"DEMO-R1-{_FILE}", status="VIGENTE",
                           raw_payload={"Número Cuenta": ACCOUNT, "Tipo Cuenta": "CORRIENTE"})
        db.add(sub)
        db.commit()
        return sub.id
    finally:
        db.close()


def test_tch_subscription_detail_shows_only_last_four(monkeypatch) -> None:
    _seed()
    client = _login(monkeypatch, ["tch.suscripciones.view"])
    resp = client.get(f"/api/v1/tch/suscripciones/{_FILE}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["numero_cuenta"] == "••••6789"
    assert ACCOUNT not in resp.text and "123456789" not in resp.text
    listing = client.get("/api/v1/tch/suscripciones", params={"limit": 200})
    assert listing.status_code == 200 and ACCOUNT not in listing.text


def test_crm_record_raw_payload_is_masked(monkeypatch) -> None:
    sub_id = _seed()
    client = _login(monkeypatch, ["virtualpos.subscriptions.view"])
    resp = client.get(f"/api/v1/subscriptions/{sub_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["raw_payload"]["Número Cuenta"] == "••••6789"
    assert ACCOUNT not in resp.text


def test_tch_subscription_export_never_includes_the_account(monkeypatch) -> None:
    _seed()
    client = _login(monkeypatch, ["tch.suscripciones.view", "export.pii"])
    resp = client.get("/api/v1/export/suscripciones", params={"canal": "tch", "filter_field": "id", "query": str(_FILE)})
    assert resp.status_code == 200, resp.text
    rows = list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))
    assert len(rows) == 1 and ACCOUNT not in resp.content.decode("utf-8-sig")
