"""Tests para el receptor de webhooks de Toku (EPIC-D2)."""

import hashlib
import hmac
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.v1.routes.webhooks_toku import _verify_toku_signature
from app.main import app

_SECRET = "whesec_test_secret_abc123"

# ── helpers ─────────────────────────────────────────────────────────────────


def _make_signature(event_id: str, secret: str = _SECRET, ts: int | None = None) -> str:
    t = str(ts or int(time.time()))
    sig = hmac.new(secret.encode(), f"{t}.{event_id}".encode(), hashlib.sha256).hexdigest()
    return f"t={t},s={sig}"


def _invoice_paid_body(event_id: str | None = None) -> dict:
    eid = event_id or f"wheve_{uuid.uuid4().hex[:8]}"
    return {
        "id": eid,
        "event_type": "invoice.paid",
        "invoice": {"id": "inv_abc123", "status": "paid", "amount": 10000},
    }


# ── unit: verify_toku_signature ──────────────────────────────────────────────


def test_verify_signature_valid() -> None:
    event_id = "wheve_123"
    header = _make_signature(event_id)
    valid, t = _verify_toku_signature(header, event_id, _SECRET)
    assert valid is True
    assert t is not None


def test_verify_signature_wrong_secret() -> None:
    event_id = "wheve_123"
    header = _make_signature(event_id, secret="wrong_secret")
    valid, _ = _verify_toku_signature(header, event_id, _SECRET)
    assert valid is False


def test_verify_signature_expired_timestamp() -> None:
    event_id = "wheve_123"
    old_ts = int(time.time()) - 400  # > 300 s → expirado
    header = _make_signature(event_id, ts=old_ts)
    valid, _ = _verify_toku_signature(header, event_id, _SECRET)
    assert valid is False


def test_verify_signature_malformed_header() -> None:
    valid, t = _verify_toku_signature("garbage", "wheve_123", _SECRET)
    assert valid is False
    assert t is None


def test_verify_signature_missing_fields() -> None:
    valid, _t = _verify_toku_signature("t=1234", "wheve_123", _SECRET)
    assert valid is False


# ── integration: POST /api/v1/webhooks/toku ──────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.toku_webhook_secret", _SECRET)
    # También parchear el acceso interno en el módulo del router
    import app.api.v1.routes.webhooks_toku as wh
    monkeypatch.setattr(wh.settings, "toku_webhook_secret", _SECRET)
    return TestClient(app)


def test_webhook_valid_signature_returns_200(client) -> None:
    body = _invoice_paid_body()
    sig = _make_signature(body["id"])
    response = client.post(
        "/api/v1/webhooks/toku",
        content=json.dumps(body),
        headers={"Content-Type": "application/json", "Toku-Signature": sig},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_webhook_invalid_signature_returns_401(client) -> None:
    body = _invoice_paid_body()
    sig = _make_signature(body["id"], secret="wrong_secret")
    response = client.post(
        "/api/v1/webhooks/toku",
        content=json.dumps(body),
        headers={"Content-Type": "application/json", "Toku-Signature": sig},
    )
    assert response.status_code == 401


def test_webhook_missing_signature_header_returns_401(client) -> None:
    body = _invoice_paid_body()
    response = client.post(
        "/api/v1/webhooks/toku",
        content=json.dumps(body),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 401


def test_webhook_expired_timestamp_returns_401(client) -> None:
    body = _invoice_paid_body()
    old_ts = int(time.time()) - 400
    sig = _make_signature(body["id"], ts=old_ts)
    response = client.post(
        "/api/v1/webhooks/toku",
        content=json.dumps(body),
        headers={"Content-Type": "application/json", "Toku-Signature": sig},
    )
    assert response.status_code == 401


def test_webhook_not_configured_returns_503(monkeypatch) -> None:
    import app.api.v1.routes.webhooks_toku as wh
    monkeypatch.setattr(wh.settings, "toku_webhook_secret", "")
    c = TestClient(app)
    body = _invoice_paid_body()
    sig = _make_signature(body["id"])
    response = c.post(
        "/api/v1/webhooks/toku",
        content=json.dumps(body),
        headers={"Content-Type": "application/json", "Toku-Signature": sig},
    )
    assert response.status_code == 503


def test_webhook_idempotent_duplicate_ignored(client) -> None:
    """El mismo toku_event_id recibido dos veces no rompe — el segundo se ignora."""
    body = _invoice_paid_body()
    sig = _make_signature(body["id"])
    headers = {"Content-Type": "application/json", "Toku-Signature": sig}
    r1 = client.post("/api/v1/webhooks/toku", content=json.dumps(body), headers=headers)
    r2 = client.post("/api/v1/webhooks/toku", content=json.dumps(body), headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 200
