"""Receptor de webhooks de Payku.

Tipos soportados (kind):
  subscription  -> {id, status}
  payment       -> {transaction_id, verification_key, order, status, subscriptions{...}}
  transaction   -> {transaction_id, payment_key, transaction_key, verification_key, order, status}
  nullification -> {id, id_transaction, ordencompra, fecha, monto, status}
  payout        -> {id, identifier_payout, order, status, update_at, customer{...}}

Autenticación: token secreto en query string `?k=<PAYKU_WEBHOOK_SECRET>`. Payku no firma el body (no documentado):
el contenido NUNCA se confia; solo se guardan ids/estado y el procesador relee por API. El token no se loguea (ni aqui
ni en el access log de uvicorn, ver `app/core/log_redaction.py`).

Pipeline (docs/data/webhooks.md):
  POST /{kind}?k=token -> rate limit -> validar token -> tope de body -> INSERT idempotente en `webhook_events` -> 200.
Acepta JSON y application/x-www-form-urlencoded.
"""

import hmac
import json
import logging
import urllib.parse
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.webhook_intake import (
    check_rate_limit,
    dedupe_key,
    enqueue_event,
    minimal_payload,
    read_body_limited,
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


logger = logging.getLogger(__name__)

router = APIRouter(tags=["Webhooks"])

_VALID_KINDS = frozenset({"subscription", "payment", "transaction", "nullification", "payout"})


def _parse_body(raw_body: bytes, content_type: str) -> dict[str, Any]:
    """Parsea el body como JSON o form-encoded (Payku no documenta el Content-Type)."""
    text = raw_body.decode("utf-8", errors="replace")
    ct = content_type.lower()
    if "application/json" in ct:
        return json.loads(text)
    if "application/x-www-form-urlencoded" in ct:
        return dict(urllib.parse.parse_qsl(text, keep_blank_values=True))
    # Intento automático: JSON primero, luego form
    try:
        return json.loads(text)
    except (ValueError, UnicodeDecodeError):
        return dict(urllib.parse.parse_qsl(text, keep_blank_values=True))


def _extract_resource_id(payload: dict[str, Any], kind: str) -> str | None:
    if kind == "subscription":
        return str(payload.get("id", "")) or None
    if kind in ("payment", "transaction"):
        return str(payload.get("transaction_id", "") or payload.get("payment_key", "")) or None
    if kind == "nullification":
        return str(payload.get("id_transaction", "") or payload.get("id", "")) or None
    if kind == "payout":
        return str(payload.get("id", "") or payload.get("identifier_payout", "")) or None
    return None


def _extract_subscription_id(payload: dict[str, Any], kind: str) -> str | None:
    if kind == "subscription":
        return str(payload.get("id", "")) or None
    subs = payload.get("subscriptions")
    if isinstance(subs, dict) and subs.get("id"):
        return str(subs["id"])
    return None


@router.post("/webhooks/payku/{kind}")
async def receive_payku_webhook(
    kind: str,
    request: Request,
    k: str = Query(default=""),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Receptor de webhooks de Payku. Valida, encola y responde 200 (sin trabajo pesado)."""
    if kind not in _VALID_KINDS:
        raise HTTPException(status_code=404, detail=f"Unknown webhook kind: {kind}")

    secret = settings.payku_webhook_secret
    if not secret:
        logger.error("PAYKU_WEBHOOK_SECRET no configurado; rechazando webhook entrante.")
        raise HTTPException(status_code=503, detail="Webhook receiver not configured.")

    check_rate_limit(request, f"payku:{kind}")

    if not hmac.compare_digest(k.encode(), secret.encode()):
        logger.warning("Payku webhook con token inválido kind=%s", kind)
        raise HTTPException(status_code=401, detail="Invalid webhook token.")

    raw_body = await read_body_limited(request)
    try:
        payload = _parse_body(raw_body, request.headers.get("content-type", ""))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Could not parse body as JSON or form.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Could not parse body as JSON or form.")

    stored = minimal_payload(payload)  # sin firma: solo ids/estado; el contenido no se confia
    resource_id = _extract_resource_id(payload, kind)
    inserted = enqueue_event(
        db,
        source="payku",
        event_type=kind,
        key=dedupe_key("payku", kind, resource_id, str(stored.get("status") or ""), bucket=True),
        payload_masked=stored,
        resource_type=kind,
        resource_external_id=resource_id,
        subscription_external_id=_extract_subscription_id(payload, kind),
    )
    logger.info("Payku webhook %s kind=%s resource_id=%s", "encolado" if inserted else "duplicado", kind, resource_id)
    return {"status": "ok"}
