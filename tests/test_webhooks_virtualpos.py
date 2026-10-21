"""Tests para el receptor de webhooks de VirtualPOS (EPIC-D3)."""

import base64
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.api.v1.routes.webhooks_virtualpos import (
    _normalize_payout_payload,
    _verify_payout_signature,
)
from app.main import app

_SECRET = "vpos_webhook_secret_test_xyz"


def _make_payout_signature(raw_body: bytes, secret: str = _SECRET, encoding: str = "hex") -> str:
    mac = hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()
    return mac.hex() if encoding == "hex" else base64.b64encode(mac).decode()


def _payment_body() -> dict:
    return {"uuid": "pay_abc123"}


def _payout_body() -> dict:
    return {
        "status": "OK",
        "code": 200,
        "payout": {
            "id": "po_59653837fa4c43d",
            "status": "PROCESSING",
            "create_at": "2023-10-24 06:10:42",
            "update_at": "2023-10-24 09:10:46",
            "tef": {"amount": 12500},
        },
    }


# ── unit: _verify_payout_signature ──────────────────────────────────────────


def test_verify_payout_signature_hex() -> None:
    body = b'{"test": "data"}'
    sig = _make_payout_signature(body, encoding="hex")
    assert _verify_payout_signature(body, sig, _SECRET) is True


def test_verify_payout_signature_base64() -> None:
    body = b'{"test": "data"}'
    sig = _make_payout_signature(body, encoding="base64")
    assert _verify_payout_signature(body, sig, _SECRET) is True


def test_verify_payout_signature_wrong_secret() -> None:
    body = b'{"test": "data"}'
    sig = _make_payout_signature(body, secret="wrong_secret")
    assert _verify_payout_signature(body, sig, _SECRET) is False


def test_verify_payout_signature_tampered_body() -> None:
    body = b'{"test": "data"}'
    sig = _make_payout_signature(body)
    tampered = b'{"test": "hacked"}'
    assert _verify_payout_signature(tampered, sig, _SECRET) is False


# ── unit: _normalize_payout_payload ─────────────────────────────────────────


def test_normalize_renames_create_at_and_update_at() -> None:
    payload = _payout_body()
    result = _normalize_payout_payload(payload)
    payout = result["payout"]
    assert "created_at" in payout
    assert "create_at" not in payout
    assert "updated_at" in payout
    assert "update_at" not in payout


def test_normalize_preserves_existing_created_at() -> None:
    payload = {"payout": {"id": "po_1", "created_at": "existing", "create_at": "duplicate"}}
    result = _normalize_payout_payload(payload)
    assert result["payout"]["created_at"] == "existing"
    assert "create_at" not in result["payout"]


# ── integration: HTTP ────────────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.api.v1.routes.webhooks_virtualpos.settings.virtualpos_payout_webhook_secret", _SECRET)
    with TestClient(app) as c:
        yield c


def test_payment_webhook_no_auth_returns_200(client) -> None:
    resp = client.post(
        "/api/v1/webhooks/virtualpos/payment",
        json=_payment_body(),
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_subscription_webhook_no_auth_returns_200(client) -> None:
    resp = client.post(
        "/api/v1/webhooks/virtualpos/subscription",
        json={"id": "sus_abc123", "status": "active"},
    )
    assert resp.status_code == 200


def test_payout_webhook_valid_signature_returns_200(client) -> None:
    body = json.dumps(_payout_body()).encode()
    sig = _make_payout_signature(body)
    resp = client.post(
        "/api/v1/webhooks/virtualpos/payout",
        content=body,
        headers={"Content-Type": "application/json", "Signature": sig},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_payout_webhook_invalid_signature_returns_401(client) -> None:
    body = json.dumps(_payout_body()).encode()
    resp = client.post(
        "/api/v1/webhooks/virtualpos/payout",
        content=body,
        headers={"Content-Type": "application/json", "Signature": "deadbeef" * 8},
    )
    assert resp.status_code == 401


def test_payout_webhook_missing_signature_returns_401(client) -> None:
    resp = client.post(
        "/api/v1/webhooks/virtualpos/payout",
        json=_payout_body(),
    )
    assert resp.status_code == 401


def test_payout_webhook_not_configured_returns_503(monkeypatch) -> None:
    monkeypatch.setattr("app.api.v1.routes.webhooks_virtualpos.settings.virtualpos_payout_webhook_secret", "")
    with TestClient(app) as c:
        body = json.dumps(_payout_body()).encode()
        sig = _make_payout_signature(body)
        resp = c.post(
            "/api/v1/webhooks/virtualpos/payout",
            content=body,
            headers={"Content-Type": "application/json", "Signature": sig},
        )
    assert resp.status_code == 503


def test_unknown_kind_returns_404(client) -> None:
    resp = client.post("/api/v1/webhooks/virtualpos/unknown", json={"uuid": "x"})
    assert resp.status_code == 404


def test_payout_base64_signature_accepted(client) -> None:
    body = json.dumps(_payout_body()).encode()
    sig = _make_payout_signature(body, encoding="base64")
    resp = client.post(
        "/api/v1/webhooks/virtualpos/payout",
        content=body,
        headers={"Content-Type": "application/json", "Signature": sig},
    )
    assert resp.status_code == 200
