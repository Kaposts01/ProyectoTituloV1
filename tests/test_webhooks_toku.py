"""Tests para el receptor de webhooks de Toku (EPIC-D2)."""

import hashlib
import hmac
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.v1.routes.webhooks_toku import _verify_toku_signature
from app.db.session import SessionLocal
from app.main import app
from app.models.webhook_event import WebhookEvent
from app.services import webhook_intake as intake

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
    return TestClient(app, base_url="https://testserver")


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
    c = TestClient(app, base_url="https://testserver")
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


# ── RT-16: replay y desorden en el receptor ──────────────────────────────────


def _rows_for(event_ids: list[str]) -> list[WebhookEvent]:
    with SessionLocal() as s:
        return list(s.scalars(select(WebhookEvent).where(WebhookEvent.provider_event_id.in_(event_ids))
                              .order_by(WebhookEvent.received_at, WebhookEvent.id)))


@pytest.fixture
def clean_rows():
    """Borra las filas que cada prueba encola (la cola no es append-only) y reinicia el rate limit."""
    created: list[str] = []
    intake.reset_rate_limits()
    yield created
    with SessionLocal() as s:
        s.execute(delete(WebhookEvent).where(WebhookEvent.provider_event_id.in_(created)))
        s.commit()
    intake.reset_rate_limits()


def _post(client, body: dict, signature: str):
    return client.post("/api/v1/webhooks/toku", content=json.dumps(body),
                       headers={"Content-Type": "application/json", "Toku-Signature": signature})


def test_replay_of_captured_request_after_window_is_rejected_and_not_queued(client, clean_rows) -> None:
    """Un atacante que reenvia una peticion capturada (firma de hace mas de 5 min) no encola nada."""
    body = _invoice_paid_body()
    clean_rows.append(body["id"])
    old_signature = _make_signature(body["id"], ts=int(time.time()) - 301)
    assert _post(client, body, old_signature).status_code == 401
    assert _rows_for([body["id"]]) == []


def test_signature_cannot_be_reused_for_another_event_id(client, clean_rows) -> None:
    original = _invoice_paid_body()
    forged = _invoice_paid_body()
    clean_rows.extend([original["id"], forged["id"]])
    signature = _make_signature(original["id"])
    assert _post(client, original, signature).status_code == 200
    assert _post(client, forged, signature).status_code == 401  # la firma cubre t + id del evento
    assert [r.provider_event_id for r in _rows_for([original["id"], forged["id"]])] == [original["id"]]


def test_provider_retry_with_fresh_signature_queues_once(client, clean_rows) -> None:
    """Los reintentos de Toku (+1 min, +10 min...) traen firma nueva pero el mismo id: una sola fila en la cola."""
    body = _invoice_paid_body()
    clean_rows.append(body["id"])
    now = int(time.time())
    assert _post(client, body, _make_signature(body["id"], ts=now - 60)).status_code == 200
    assert _post(client, body, _make_signature(body["id"], ts=now)).status_code == 200
    rows = _rows_for([body["id"]])
    assert len(rows) == 1 and rows[0].status == "pending"


def test_out_of_order_deliveries_are_all_queued(client, clean_rows) -> None:
    """El receptor no descarta un aviso por llegar despues de uno mas nuevo: el procesador relee el estado actual."""
    sub = f"sub_{uuid.uuid4().hex[:8]}"
    newer = {"id": f"wheve_{uuid.uuid4().hex[:8]}", "event_type": "subscription.deleted", "subscription": {"id": sub}}
    older = {"id": f"wheve_{uuid.uuid4().hex[:8]}", "event_type": "subscription.updated", "subscription": {"id": sub}}
    clean_rows.extend([newer["id"], older["id"]])
    now = int(time.time())
    assert _post(client, newer, _make_signature(newer["id"], ts=now)).status_code == 200
    assert _post(client, older, _make_signature(older["id"], ts=now - 120)).status_code == 200
    rows = _rows_for([newer["id"], older["id"]])
    assert [(r.event_type, r.subscription_external_id, r.status) for r in rows] == [
        ("subscription.deleted", sub, "pending"), ("subscription.updated", sub, "pending")]
