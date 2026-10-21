"""Tests para la API de revisión de candidatos de identidad (CORE-04)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db
from app.core.security import get_current_user
from app.db.session import engine
from app.main import app
from app.models.auth import Permission, Role, User
from app.models.core import ClientMatchCandidate, CoreClient, ExternalIdentity

client = TestClient(app, raise_server_exceptions=False)

_CANDIDATE_URL = "/api/v1/core/identity/match-candidates"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_db():
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
def identity_client(isolated_db):
    """TestClient con DB aislada y usuario con permisos core.identity.read/review."""
    perm_read = Permission(code="core.identity.read", description="")
    perm_review = Permission(code="core.identity.review", description="")
    role = Role(name="identity-reviewer-test", permissions=[perm_read, perm_review])
    fake_user = User(
        username="identity-reviewer-test",
        password_hash="unused",
        is_active=True,
        roles=[role],
    )

    def override_db():
        yield isolated_db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: fake_user

    yield TestClient(app)

    del app.dependency_overrides[get_db]
    del app.dependency_overrides[get_current_user]


@pytest.fixture
def candidate(isolated_db):
    """Par de CoreClients con identidades externas y un ClientMatchCandidate pendiente."""
    client_a = CoreClient()
    client_b = CoreClient()
    isolated_db.add_all([client_a, client_b])
    isolated_db.flush()

    ext_a = ExternalIdentity(
        client_id=client_a.id,
        source="virtualpos1",
        resource_type="client",
        external_id=f"ext-{uuid.uuid4().hex[:8]}",
    )
    cand = ClientMatchCandidate(
        client_id_a=client_a.id,
        client_id_b=client_b.id,
        match_level="A",
        match_signals={"rut": True},
    )
    isolated_db.add_all([ext_a, cand])
    isolated_db.flush()
    return cand


# ---------------------------------------------------------------------------
# Auth barriers (originales)
# ---------------------------------------------------------------------------


def test_list_requires_auth():
    resp = client.get(_CANDIDATE_URL)
    assert resp.status_code in (401, 403)


def test_get_requires_auth():
    resp = client.get(f"{_CANDIDATE_URL}/{uuid.uuid4()}")
    assert resp.status_code in (401, 403)


def test_review_requires_auth():
    resp = client.post(
        f"{_CANDIDATE_URL}/{uuid.uuid4()}/review",
        json={"decision": "confirmed"},
    )
    assert resp.status_code in (401, 403)


def test_review_endpoint_registered():
    """Verifica que la ruta review existe en el schema OpenAPI."""
    paths = set(app.openapi()["paths"])
    assert "/api/v1/core/identity/match-candidates" in paths
    assert "/api/v1/core/identity/match-candidates/{candidate_id}" in paths
    assert "/api/v1/core/identity/match-candidates/{candidate_id}/review" in paths


# ---------------------------------------------------------------------------
# Lógica de negocio
# ---------------------------------------------------------------------------


def test_list_returns_candidate(identity_client, candidate):
    resp = identity_client.get(_CANDIDATE_URL)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    ids = [item["id"] for item in data["items"]]
    assert str(candidate.id) in ids


def test_list_includes_external_identities(identity_client, candidate, isolated_db):
    resp = identity_client.get(_CANDIDATE_URL)
    assert resp.status_code == 200
    items = resp.json()["items"]
    match = next(i for i in items if i["id"] == str(candidate.id))
    # client_a tiene una ExternalIdentity; client_b no tiene
    assert len(match["identities_a"]) == 1
    assert match["identities_a"][0]["source"] == "virtualpos1"
    assert match["identities_b"] == []


def test_get_returns_candidate(identity_client, candidate):
    resp = identity_client.get(f"{_CANDIDATE_URL}/{candidate.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(candidate.id)
    assert data["status"] == "pending"


def test_get_not_found(identity_client):
    resp = identity_client.get(f"{_CANDIDATE_URL}/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_review_success(identity_client, candidate, isolated_db):
    resp = identity_client.post(
        f"{_CANDIDATE_URL}/{candidate.id}/review",
        json={"decision": "confirmed", "notes": "mismo RUT verificado"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "confirmed"
    assert data["reviewed_by"] == "identity-reviewer-test"
    assert data["reviewed_at"] is not None
    assert data["notes"] == "mismo RUT verificado"

    isolated_db.expire(candidate)
    assert candidate.status == "confirmed"
    assert candidate.reviewed_by == "identity-reviewer-test"


def test_review_invalid_decision(identity_client, candidate):
    resp = identity_client.post(
        f"{_CANDIDATE_URL}/{candidate.id}/review",
        json={"decision": "invalid"},
    )
    assert resp.status_code == 422


def test_review_not_found(identity_client):
    resp = identity_client.post(
        f"{_CANDIDATE_URL}/{uuid.uuid4()}/review",
        json={"decision": "confirmed"},
    )
    assert resp.status_code == 404


def test_review_is_reversible(identity_client, candidate, isolated_db):
    """Un candidato ya confirmado puede ser rechazado (reversibilidad ADR-001)."""
    identity_client.post(
        f"{_CANDIDATE_URL}/{candidate.id}/review",
        json={"decision": "confirmed"},
    )
    resp = identity_client.post(
        f"{_CANDIDATE_URL}/{candidate.id}/review",
        json={"decision": "rejected", "notes": "revisión adicional"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
