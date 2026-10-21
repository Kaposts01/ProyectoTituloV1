"""Tests para la API de revisión de candidatos de identidad (CORE-04)."""

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

_CANDIDATE_URL = "/api/v1/core/identity/match-candidates"


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
