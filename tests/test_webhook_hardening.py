"""RT-08: receptores endurecidos. Payloads 100% sinteticos; el receptor solo valida y encola en `webhook_events`.

Cubre: firma Toku valida/invalida/vencida, tope de body, rate limit, duplicado idempotente, sin PII persistida y sin
PII/secretos en logs, canales sin firma (solo ids) y redaccion de `?k=` en el access log.
"""

import hashlib
import hmac
import json
import logging
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

import app.api.v1.routes.webhooks_payku as wh_payku
import app.api.v1.routes.webhooks_toku as wh_toku
import app.api.v1.routes.webhooks_virtualpos as wh_vp
from app.core.log_redaction import RedactQuerySecretsFilter, redact_query_secrets
from app.db.session import SessionLocal
from app.main import app
from app.models.webhook_event import WebhookEvent
from app.services import webhook_intake as intake

TOKU_SECRET = "whesec_synthetic_secret_for_tests"
PAYKU_SECRET = "payku_synthetic_token_for_tests"
VP_PAYOUT_SECRET = "vp_synthetic_payout_secret"

# Datos personales SINTETICOS que NUNCA deben persistirse ni loguearse.
PII_EMAIL = "persona.ficticia@example.invalid"
PII_RUT = "11.111.111-1"
PII_PHONE = "+56911112222"
PII_NAME = "Fulana Ficticia Prueba"
PII_VALUES = (PII_EMAIL, PII_RUT, PII_PHONE, PII_NAME)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(wh_toku.settings, "toku_webhook_secret", TOKU_SECRET)
    monkeypatch.setattr(wh_payku.settings, "payku_webhook_secret", PAYKU_SECRET)
    monkeypatch.setattr(wh_vp.settings, "virtualpos_payout_webhook_secret", VP_PAYOUT_SECRET)
    intake.reset_rate_limits()
    _wipe()
    yield
    _wipe()
    intake.reset_rate_limits()


def _wipe() -> None:
    with SessionLocal() as db:
        db.execute(delete(WebhookEvent))
        db.commit()


def _rows() -> list[WebhookEvent]:
    with SessionLocal() as db:
        return list(db.scalars(select(WebhookEvent).order_by(WebhookEvent.received_at)))


@pytest.fixture
def client():
    return TestClient(app, base_url="https://testserver")


def _sig(event_id: str, secret: str = TOKU_SECRET, ts: int | None = None) -> str:
    t = str(ts or int(time.time()))
    s = hmac.new(secret.encode(), f"{t}.{event_id}".encode(), hashlib.sha256).hexdigest()
    return f"t={t},s={s}"


def _toku_body(event_id: str = "wheve_t0001", event_type: str = "subscription.updated") -> dict:
    return {
        "id": event_id,
        "event_type": event_type,
        "subscription": {
            "id": "sub_syn_1",
            "status": "active",
            "customer": {"id": "cus_syn_1", "email": PII_EMAIL, "name": PII_NAME, "government_id": PII_RUT},
            "payment_instrument": {"phone": PII_PHONE, "last4": "4242"},
            "note": f"contacto {PII_EMAIL} {PII_RUT}",
        },
    }


def _post_toku(client, body: dict, sig: str | None = None, raw: bytes | None = None):
    headers = {"Content-Type": "application/json"}
    headers["Toku-Signature"] = sig if sig is not None else _sig(body["id"])
    return client.post("/api/v1/webhooks/toku", content=raw if raw is not None else json.dumps(body), headers=headers)


# ----------------------------- Toku -----------------------------


def test_toku_valid_signature_enqueues_pending_event(client) -> None:
    r = _post_toku(client, _toku_body())
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    (row,) = _rows()
    assert (row.source, row.event_type, row.status, row.attempts) == ("toku", "subscription.updated", "pending", 0)
    assert row.provider_event_id == "wheve_t0001"
    assert row.resource_type == "subscription" and row.resource_external_id == "sub_syn_1"
    assert row.subscription_external_id == "sub_syn_1"
    assert row.last_error_code is None and row.processed_at is None


def test_toku_invalid_signature_401_and_nothing_stored(client) -> None:
    body = _toku_body()
    assert _post_toku(client, body, sig=_sig(body["id"], secret="otro")).status_code == 401
    assert _rows() == []


def test_toku_expired_signature_401_and_nothing_stored(client) -> None:
    body = _toku_body()
    assert _post_toku(client, body, sig=_sig(body["id"], ts=int(time.time()) - 400)).status_code == 401
    assert _rows() == []


def test_toku_signature_just_inside_window_is_accepted(client) -> None:
    body = _toku_body()
    assert _post_toku(client, body, sig=_sig(body["id"], ts=int(time.time()) - 250)).status_code == 200


def test_toku_uses_constant_time_comparison() -> None:
    import inspect

    assert "compare_digest" in inspect.getsource(wh_toku._verify_toku_signature)
    assert wh_toku._SIGNATURE_MAX_AGE_SECONDS == 300


def test_toku_missing_secret_503_and_nothing_stored(client, monkeypatch) -> None:
    monkeypatch.setattr(wh_toku.settings, "toku_webhook_secret", "")
    assert _post_toku(client, _toku_body()).status_code == 503
    assert _rows() == []


def test_toku_duplicate_event_is_idempotent(client) -> None:
    body = _toku_body()
    assert _post_toku(client, body).status_code == 200
    assert _post_toku(client, body).status_code == 200
    assert len(_rows()) == 1


def test_toku_oversized_body_413_and_nothing_stored(client, monkeypatch) -> None:
    monkeypatch.setattr(intake.settings, "webhook_max_body_bytes", 1024)
    body = _toku_body()
    body["padding"] = "x" * 5000
    assert _post_toku(client, body).status_code == 413
    assert _rows() == []


def test_toku_invalid_json_400(client) -> None:
    assert _post_toku(client, {"id": "wheve_x"}, raw=b"{no es json").status_code == 400


def test_toku_no_pii_persisted(client) -> None:
    _post_toku(client, _toku_body())
    (row,) = _rows()
    dumped = json.dumps(row.payload_masked)
    for value in PII_VALUES:
        assert value not in dumped
    assert row.payload_masked["subscription"]["customer"] == {"id": "cus_syn_1"}  # el id externo se conserva
    assert row.payload_masked["subscription"]["id"] == "sub_syn_1"


def test_toku_no_pii_nor_signature_in_logs(client, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    body = _toku_body()
    sig = _sig(body["id"])
    _post_toku(client, body, sig=sig)
    _post_toku(client, body, sig=sig)  # tambien la ruta del duplicado
    _post_toku(client, body, sig=_sig(body["id"], secret="otro"))  # y la de firma invalida
    text = caplog.text
    for value in (*PII_VALUES, sig, TOKU_SECRET):
        assert value not in text


def test_toku_rate_limit_429(client, monkeypatch) -> None:
    monkeypatch.setattr(intake.settings, "webhook_rate_limit_per_minute", 3)
    codes = [_post_toku(client, _toku_body(f"wheve_r{i}")).status_code for i in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    assert len(_rows()) == 3


def test_rate_limit_is_per_route_and_window_slides(client, monkeypatch) -> None:
    monkeypatch.setattr(intake.settings, "webhook_rate_limit_per_minute", 2)

    class _Req:
        client = type("C", (), {"host": "10.0.0.9"})()
        headers: dict = {}  # noqa: RUF012

    intake.check_rate_limit(_Req(), "a", now=0.0)
    intake.check_rate_limit(_Req(), "a", now=1.0)
    intake.check_rate_limit(_Req(), "b", now=1.0)  # otra ruta: cuenta aparte
    with pytest.raises(Exception, match="429"):
        intake.check_rate_limit(_Req(), "a", now=2.0)
    intake.check_rate_limit(_Req(), "a", now=62.0)  # la ventana de 60 s ya paso


def test_forwarded_for_is_ignored_unless_trusted(monkeypatch) -> None:
    class _Req:
        client = type("C", (), {"host": "127.0.0.1"})()
        headers = {"x-forwarded-for": "9.9.9.9, 1.1.1.1"}  # noqa: RUF012

    assert intake.client_ip(_Req()) == "127.0.0.1"
    monkeypatch.setattr(intake.settings, "webhook_trust_forwarded_for", True)
    assert intake.client_ip(_Req()) == "9.9.9.9"


# ----------------------------- VirtualPOS -----------------------------


def test_vp_payment_stores_only_the_id_and_dedupes(client) -> None:
    body = {"uuid": "pay_syn_1", "status": "PAGADO", "client": {"email": PII_EMAIL, "name": PII_NAME}, "rut": PII_RUT}
    assert client.post("/api/v1/webhooks/virtualpos/payment", json=body).status_code == 200
    assert client.post("/api/v1/webhooks/virtualpos/payment", json=body).status_code == 200
    (row,) = _rows()
    assert (row.source, row.event_type, row.resource_type, row.resource_external_id) == (
        "virtualpos", "payment", "payment", "pay_syn_1")
    assert row.payload_masked == {"uuid": "pay_syn_1", "status": "PAGADO"}  # el contenido nunca se confia ni se guarda
    assert not any(v in json.dumps(row.payload_masked) for v in PII_VALUES)


def test_vp_oversized_body_413(client, monkeypatch) -> None:
    monkeypatch.setattr(intake.settings, "webhook_max_body_bytes", 512)
    r = client.post("/api/v1/webhooks/virtualpos/payment", json={"uuid": "p", "pad": "x" * 2000})
    assert r.status_code == 413 and _rows() == []


def test_vp_payout_still_requires_valid_signature(client) -> None:
    raw = json.dumps({"payout": {"id": "po_syn_1", "status": "OK"}}).encode()
    assert client.post("/api/v1/webhooks/virtualpos/payout", content=raw).status_code == 401
    mac = hmac.new(VP_PAYOUT_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    ok = client.post("/api/v1/webhooks/virtualpos/payout", content=raw, headers={"Signature": mac})
    assert ok.status_code == 200
    (row,) = _rows()
    assert row.event_type == "payout" and row.resource_external_id == "po_syn_1"


def test_vp_unknown_kind_404(client) -> None:
    assert client.post("/api/v1/webhooks/virtualpos/otro", json={}).status_code == 404


def test_vp_logs_have_no_pii(client, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    client.post("/api/v1/webhooks/virtualpos/payment", json={"uuid": "pay_syn_2", "client": {"email": PII_EMAIL}})
    assert PII_EMAIL not in caplog.text


# ----------------------------- Payku -----------------------------


def test_payku_payment_stores_only_ids(client) -> None:
    body = {
        "transaction_id": 9123123,
        "verification_key": "clave-que-no-debe-guardarse",
        "status": "success",
        "subscriptions": {"id": "su_syn_1", "client": "cl_syn_1"},
        "customer": {"email": PII_EMAIL, "name": PII_NAME},
    }
    r = client.post(f"/api/v1/webhooks/payku/payment?k={PAYKU_SECRET}", json=body)
    assert r.status_code == 200
    (row,) = _rows()
    assert (row.source, row.event_type, row.resource_type, row.resource_external_id) == (
        "payku", "payment", "payment", "9123123")
    assert row.subscription_external_id == "su_syn_1"
    dumped = json.dumps(row.payload_masked)
    assert "clave-que-no-debe-guardarse" not in dumped and PII_EMAIL not in dumped and PII_NAME not in dumped
    assert row.payload_masked["status"] == "success"


def test_payku_form_encoded_body_and_duplicate(client) -> None:
    data = {"id": "su_syn_2", "status": "active"}
    for _ in range(2):
        assert client.post(f"/api/v1/webhooks/payku/subscription?k={PAYKU_SECRET}", data=data).status_code == 200
    (row,) = _rows()
    assert row.resource_type == "subscription" and row.resource_external_id == "su_syn_2"
    assert row.subscription_external_id == "su_syn_2"


def test_payku_invalid_token_401_and_missing_secret_503(client, monkeypatch) -> None:
    assert client.post("/api/v1/webhooks/payku/subscription?k=mal", json={"id": "x"}).status_code == 401
    assert _rows() == []
    monkeypatch.setattr(wh_payku.settings, "payku_webhook_secret", "")
    assert client.post("/api/v1/webhooks/payku/subscription?k=mal", json={"id": "x"}).status_code == 503


def test_payku_token_never_logged(client, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    client.post(f"/api/v1/webhooks/payku/subscription?k={PAYKU_SECRET}", json={"id": "su_syn_3", "status": "active"})
    client.post("/api/v1/webhooks/payku/subscription?k=token-equivocado", json={"id": "su_syn_3"})
    # Solo los logs del servidor (el cliente de pruebas, httpx, imprime su propia URL de salida).
    server_logs = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith(("app", "uvicorn")))
    assert PAYKU_SECRET not in server_logs and "token-equivocado" not in server_logs
    assert "encolado" in server_logs


def test_payku_oversized_body_413(client, monkeypatch) -> None:
    monkeypatch.setattr(intake.settings, "webhook_max_body_bytes", 512)
    r = client.post(f"/api/v1/webhooks/payku/subscription?k={PAYKU_SECRET}", json={"id": "x", "pad": "y" * 2000})
    assert r.status_code == 413 and _rows() == []


def test_receivers_do_not_write_legacy_staging_tables(client) -> None:
    from sqlalchemy import func

    from app.models.stg_payku_webhook_event import StgPaykuWebhookEvent
    from app.models.stg_toku_webhook_event import StgTokuWebhookEvent
    from app.models.stg_vpos_webhook_event import StgVposWebhookEvent

    def total() -> int:
        with SessionLocal() as db:
            return sum(db.scalar(select(func.count()).select_from(m)) for m in
                       (StgTokuWebhookEvent, StgVposWebhookEvent, StgPaykuWebhookEvent))

    before = total()
    _post_toku(client, _toku_body("wheve_legacy"))
    client.post("/api/v1/webhooks/virtualpos/payment", json={"uuid": "pay_legacy"})
    client.post(f"/api/v1/webhooks/payku/subscription?k={PAYKU_SECRET}", json={"id": "su_legacy"})
    assert total() == before


# ----------------------------- utilidades -----------------------------


def test_access_log_filter_redacts_query_token() -> None:
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "POST", f"/api/v1/webhooks/payku/payment?k={PAYKU_SECRET}&x=1", "1.1", 200), None)
    assert RedactQuerySecretsFilter().filter(record) is True
    rendered = record.getMessage()
    assert PAYKU_SECRET not in rendered and "k=[redacted]" in rendered and "x=1" in rendered
    assert redact_query_secrets("/a?b=1") == "/a?b=1"


def test_access_log_filter_is_installed_on_uvicorn_logger() -> None:
    assert any(isinstance(f, RedactQuerySecretsFilter) for f in logging.getLogger("uvicorn.access").filters)


def test_mask_pii_unit() -> None:
    out = intake.mask_pii({
        "email": PII_EMAIL, "customer": {"id": "cus_1", "email": PII_EMAIL}, "ok": 5,
        "list": [{"phone": PII_PHONE}, f"hola {PII_RUT}"], "client": "cl_9",
    })
    dumped = json.dumps(out)
    assert PII_EMAIL not in dumped and PII_PHONE not in dumped and PII_RUT not in dumped
    assert out["customer"] == {"id": "cus_1"} and out["ok"] == 5 and out["client"] == "cl_9"


def test_masked_payload_drops_credentials() -> None:
    out = intake.masked_payload({"card_number": "4111111111111111", "cvv": "123", "id": "x"})
    assert out == {"id": "x"}
