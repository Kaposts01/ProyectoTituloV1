"""Tests para el receptor de webhooks de Payku (EPIC-D4)."""

import urllib.parse

import pytest
from fastapi.testclient import TestClient

from app.main import app

_SECRET = "payku_webhook_token_test_abc"


def _subscription_body() -> dict:
    return {"id": "su74866857980c7d2b4306", "status": "active"}


def _payment_body() -> dict:
    return {
        "transaction_id": 9123123,
        "verification_key": "2ba83615f863e72sdca5dfd0a6df2782",
        "order": 1568041684,
        "status": "success",
        "subscriptions": {"id": "su3ce571420e90b600eafb", "client": "cl795704ece0a3690baaf"},
    }


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("app.api.v1.routes.webhooks_payku.settings.payku_webhook_secret", _SECRET)
    with TestClient(app) as c:
        yield c


# ── integration: HTTP ─────────────────────────────────────────────────────────


def test_subscription_webhook_valid_token_returns_200(client) -> None:
    resp = client.post(
        f"/api/v1/webhooks/payku/subscription?k={_SECRET}",
        json=_subscription_body(),
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_payment_webhook_valid_token_returns_200(client) -> None:
    resp = client.post(
        f"/api/v1/webhooks/payku/payment?k={_SECRET}",
        json=_payment_body(),
    )
    assert resp.status_code == 200


def test_transaction_webhook_returns_200(client) -> None:
    body = {
        "transaction_id": "9916587765599311",
        "payment_key": "trx32cb779c0a777fc68",
        "verification_key": "8b3e2202fb086a7de93777ae34d5e18c",
        "order": "199",
        "status": "success",
    }
    resp = client.post(f"/api/v1/webhooks/payku/transaction?k={_SECRET}", json=body)
    assert resp.status_code == 200


def test_invalid_token_returns_401(client) -> None:
    resp = client.post(
        "/api/v1/webhooks/payku/subscription?k=wrong_token",
        json=_subscription_body(),
    )
    assert resp.status_code == 401


def test_missing_token_returns_401(client) -> None:
    resp = client.post(
        "/api/v1/webhooks/payku/subscription",
        json=_subscription_body(),
    )
    assert resp.status_code == 401


def test_not_configured_returns_503(monkeypatch) -> None:
    monkeypatch.setattr("app.api.v1.routes.webhooks_payku.settings.payku_webhook_secret", "")
    with TestClient(app) as c:
        resp = c.post(
            f"/api/v1/webhooks/payku/subscription?k={_SECRET}",
            json=_subscription_body(),
        )
    assert resp.status_code == 503


def test_unknown_kind_returns_404(client) -> None:
    resp = client.post(f"/api/v1/webhooks/payku/unknown?k={_SECRET}", json={"id": "x"})
    assert resp.status_code == 404


def test_form_encoded_body_accepted(client) -> None:
    body = urllib.parse.urlencode({"id": "su74866857980c7d2b4306", "status": "active"})
    resp = client.post(
        f"/api/v1/webhooks/payku/subscription?k={_SECRET}",
        content=body.encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200


def test_nullification_webhook_returns_200(client) -> None:
    body = {
        "id": "morexxzxxx",
        "id_transaction": "morexxzxxx",
        "ordencompra": "367734544",
        "fecha": "24-08-2023 12:29:35",
        "monto": 7000,
        "status": "complete",
    }
    resp = client.post(f"/api/v1/webhooks/payku/nullification?k={_SECRET}", json=body)
    assert resp.status_code == 200


def test_payout_webhook_returns_200(client) -> None:
    body = {
        "id": "morexzxxxx",
        "identifier_payout": "morexzxxxx",
        "order": "367734544",
        "status": "success",
        "update_at": "2023-08-24 12:29:35",
        "customer": {"name": "Jhon Doe", "phone": "978456879"},
    }
    resp = client.post(f"/api/v1/webhooks/payku/payout?k={_SECRET}", json=body)
    assert resp.status_code == 200
