"""Receptor VirtualPOS: eventos PAT (charge_paid, charge_reject, card_change), cuerpo POS de suscripcion y variante
application/x-www-form-urlencoded. Sin base de datos: `enqueue_event` y `get_db` se reemplazan por falsos. Datos 100%
sinteticos."""

import json
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.api.v1.routes.webhooks_virtualpos as wh_vp
from app.main import app
from app.services.webhook_intake import reset_rate_limits

PII_EMAIL = "persona.sintetica@example.com"


def _charge_body(status: str = "pagado") -> dict:
    return {
        "suscription_uuid": "sus-syn-1",
        "id": "chg-syn-1",
        "charge_date": "2026-10-09",
        "amount": 15000,
        "status": status,
        "description": "Cuota mensual",
        "payment": {
            "client": {"email": PII_EMAIL, "first_name": "Ana", "last_name": "Sintetica", "social_id": "", "phone": ""},
            "order": {"uuid": "pay-syn-1", "card_number": "1234", "auth_code": "123456", "deposits": []},
        },
    }


# ── unit: extraccion de ids ─────────────────────────────────────────────────


@pytest.mark.parametrize("kind", ["charge_paid", "charge_reject"])
def test_charge_events_take_charge_id_and_subscription_uuid(kind) -> None:
    assert wh_vp._extract_ids(_charge_body(), kind) == ("chg-syn-1", "sus-syn-1")


def test_charge_without_subscription_keeps_charge_id() -> None:
    assert wh_vp._extract_ids({"id": 987}, "charge_paid") == ("987", None)


def test_card_change_takes_subscription_uuid() -> None:
    assert wh_vp._extract_ids({"uuid": "sus-syn-2"}, "card_change") == ("sus-syn-2", "sus-syn-2")


def test_subscription_from_api_callback_uuid() -> None:
    assert wh_vp._extract_ids({"uuid": "sus-syn-3"}, "subscription") == ("sus-syn-3", "sus-syn-3")


def test_subscription_from_pos_body_nested_suscription_uuid() -> None:
    body = {"status": "OK", "code": 200, "suscription": {"uuid": "sus-syn-4"}}
    assert wh_vp._extract_ids(body, "subscription") == ("sus-syn-4", "sus-syn-4")


def test_subscription_legacy_id_still_works() -> None:
    assert wh_vp._extract_ids({"id": "sus_abc123", "status": "active"}, "subscription") == ("sus_abc123", "sus_abc123")


def test_payment_and_payout_ids_unchanged() -> None:
    assert wh_vp._extract_ids({"uuid": "pay-1"}, "payment") == ("pay-1", None)
    assert wh_vp._extract_ids({"payout": {"id": "po_1"}}, "payout") == ("po_1", None)


def test_bool_or_object_ids_are_ignored() -> None:
    assert wh_vp._extract_ids({"uuid": True}, "card_change") == (None, None)
    assert wh_vp._extract_ids({"id": {"x": 1}}, "charge_paid") == (None, None)


def test_resource_type_by_kind() -> None:
    assert wh_vp._resource_type("charge_paid") == "charge"
    assert wh_vp._resource_type("charge_reject") == "charge"
    assert wh_vp._resource_type("card_change") == "subscription"
    assert wh_vp._resource_type("payment") == "payment"


# ── unit: parseo del cuerpo ─────────────────────────────────────────────────

_FORM = "application/x-www-form-urlencoded"


def test_parse_json_default() -> None:
    assert wh_vp._parse_body(b'{"uuid": "x"}', "application/json") == {"uuid": "x"}
    assert wh_vp._parse_body(b'{"uuid": "x"}', None) == {"uuid": "x"}


def test_parse_form_flat_fields() -> None:
    raw = urlencode({"uuid": "sus-syn-5"}).encode()
    assert wh_vp._parse_body(raw, _FORM) == {"uuid": "sus-syn-5"}


def test_parse_form_bracket_fields_become_nested() -> None:
    raw = urlencode({"status": "OK", "code": "200", "suscription[uuid]": "sus-syn-6"}).encode()
    payload = wh_vp._parse_body(raw, _FORM + "; charset=UTF-8")
    assert payload["suscription"] == {"uuid": "sus-syn-6"}
    assert wh_vp._extract_ids(payload, "subscription") == ("sus-syn-6", "sus-syn-6")


def test_parse_form_with_json_in_single_field() -> None:
    raw = urlencode({"data": json.dumps(_charge_body())}).encode()
    assert wh_vp._extract_ids(wh_vp._parse_body(raw, _FORM), "charge_paid") == ("chg-syn-1", "sus-syn-1")


def test_parse_form_declared_but_json_sent() -> None:
    raw = json.dumps({"uuid": "sus-syn-7"}).encode()
    assert wh_vp._parse_body(raw, _FORM) == {"uuid": "sus-syn-7"}


@pytest.mark.parametrize("raw,ctype", [(b"[1, 2]", "application/json"), (b"no es json", "application/json"),
                                       (b"\xff\xfe", _FORM)])
def test_parse_invalid_bodies_are_400(raw, ctype) -> None:
    with pytest.raises(HTTPException) as exc:
        wh_vp._parse_body(raw, ctype)
    assert exc.value.status_code == 400


# ── HTTP (cola falsa, sin base) ─────────────────────────────────────────────


class FakeQueue:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, db, **kwargs) -> bool:
        self.calls.append(kwargs)
        return True


@pytest.fixture
def queue(monkeypatch):
    fake = FakeQueue()
    monkeypatch.setattr(wh_vp, "enqueue_event", fake)
    app.dependency_overrides[wh_vp.get_db] = lambda: None
    reset_rate_limits()
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(wh_vp.get_db, None)


@pytest.fixture
def client(queue):
    return TestClient(app, base_url="https://testserver")  # sin `with`: no arranca el ciclo de vida (scheduler, BD)


@pytest.mark.parametrize("kind", ["charge_paid", "charge_reject"])
def test_charge_route_enqueues_only_ids_and_status(client, queue, kind) -> None:
    status = "pagado" if kind == "charge_paid" else "rechazado"
    resp = client.post(f"/api/v1/webhooks/virtualpos/{kind}", json=_charge_body(status))
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}
    (call,) = queue.calls
    assert call["source"] == "virtualpos" and call["event_type"] == kind
    assert call["resource_type"] == "charge"
    assert call["resource_external_id"] == "chg-syn-1"
    assert call["subscription_external_id"] == "sus-syn-1"
    assert call["payload_masked"] == {"id": "chg-syn-1", "status": status, "subscription_id": "sus-syn-1"}
    stored = json.dumps(call["payload_masked"])
    for leaked in (PII_EMAIL, "Ana", "1234", "123456", "pay-syn-1", "15000"):
        assert leaked not in stored


def test_card_change_route_enqueues_subscription(client, queue) -> None:
    assert client.post("/api/v1/webhooks/virtualpos/card_change", json={"uuid": "sus-syn-8"}).status_code == 200
    (call,) = queue.calls
    assert (call["event_type"], call["resource_type"]) == ("card_change", "subscription")
    assert call["resource_external_id"] == call["subscription_external_id"] == "sus-syn-8"


def test_pos_subscription_body_enqueues_nested_uuid(client, queue) -> None:
    body = {"status": "OK", "code": 200, "suscription": {"uuid": "sus-syn-9"}}
    assert client.post("/api/v1/webhooks/virtualpos/subscription", json=body).status_code == 200
    (call,) = queue.calls
    assert call["subscription_external_id"] == "sus-syn-9"
    assert call["payload_masked"] == {"status": "OK", "subscription_id": "sus-syn-9"}


def test_form_urlencoded_charge_is_accepted(client, queue) -> None:
    raw = urlencode({"id": "chg-syn-2", "suscription_uuid": "sus-syn-10", "status": "pagado",
                     "payment[client]": PII_EMAIL})
    resp = client.post("/api/v1/webhooks/virtualpos/charge_paid", content=raw,
                       headers={"Content-Type": _FORM})
    assert resp.status_code == 200
    (call,) = queue.calls
    assert (call["resource_external_id"], call["subscription_external_id"]) == ("chg-syn-2", "sus-syn-10")
    assert PII_EMAIL not in json.dumps(call["payload_masked"])


def test_form_urlencoded_card_change_is_accepted(client, queue) -> None:
    resp = client.post("/api/v1/webhooks/virtualpos/card_change", content="uuid=sus-syn-11",
                       headers={"Content-Type": _FORM})
    assert resp.status_code == 200
    assert queue.calls[0]["subscription_external_id"] == "sus-syn-11"


@pytest.mark.parametrize("kind", ["suscription_activated", "charge", "otro"])
def test_unknown_routes_still_404(client, queue, kind) -> None:
    assert client.post(f"/api/v1/webhooks/virtualpos/{kind}", json={"uuid": "x"}).status_code == 404
    assert queue.calls == []


def test_invalid_body_is_400_and_not_enqueued(client, queue) -> None:
    resp = client.post("/api/v1/webhooks/virtualpos/charge_paid", content=b"[]",
                       headers={"Content-Type": "application/json"})
    assert resp.status_code == 400
    assert queue.calls == []
