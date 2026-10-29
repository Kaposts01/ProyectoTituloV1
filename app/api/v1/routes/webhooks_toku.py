"""Receptor de webhooks de Toku.

Pipeline (docs/data/webhooks.md):
  POST -> rate limit -> tope de body -> verificar firma (HMAC en tiempo constante, ventana de 5 min)
  -> enmascarar PII -> INSERT idempotente en `webhook_events` -> 200 inmediato.
  El procesador asincrono (`webhook_processor`) relee el recurso por API; aqui no se hace trabajo pesado.

La firma Toku cubre solo t + event_id, no el body. Los datos del payload nunca se aplican directamente a la base
central; son solo un aviso (el procesador siempre relee por API). El payload NO se loguea ni se persiste sin enmascarar.
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.webhook_intake import (
    check_rate_limit,
    dedupe_key,
    enqueue_event,
    masked_payload,
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

# Ventana de tolerancia para el timestamp de la firma (segundos)
_SIGNATURE_MAX_AGE_SECONDS = 300  # 5 minutos


def _verify_toku_signature(header: str, event_id: str, secret: str) -> tuple[bool, str | None]:
    """Verifica la firma HMAC-SHA256 de Toku.

    Returns (valid, signature_t). signature_t es None si el header es inválido.
    Formato: Toku-Signature: t=<unix_timestamp>,s=<hex_digest>
    Mensaje firmado: "{t}.{event_id}"
    """
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
    except ValueError:
        return False, None

    t = parts.get("t")
    s = parts.get("s")
    if not t or not s:
        return False, None

    # Rechazar si el timestamp es demasiado antiguo
    try:
        ts = int(t)
        if abs(time.time() - ts) > _SIGNATURE_MAX_AGE_SECONDS:
            return False, t
    except ValueError:
        return False, None

    expected = hmac.new(secret.encode(), f"{t}.{event_id}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, s), t


def _extract_resource_id(body: dict[str, Any], event_type: str) -> str | None:
    """Extrae el ID del recurso principal del payload según el tipo de evento."""
    if event_type.startswith("invoice."):
        return (body.get("invoice") or {}).get("id")
    if event_type.startswith("transaction."):
        return (body.get("transaction") or {}).get("id")
    if event_type.startswith("subscription."):
        return (body.get("subscription") or {}).get("id")
    if event_type.startswith("customer."):
        return (body.get("customer") or {}).get("id")
    if event_type.startswith("payment_method."):
        pm = body.get("payment_method") or {}
        return pm.get("id") or pm.get("payment_method_id")
    return None


def _extract_subscription_id(body: dict[str, Any], event_type: str) -> str | None:
    """Suscripcion afectada cuando el propio payload la nombra (si no, el procesador la resuelve con la base local)."""
    if event_type.startswith("subscription."):
        return (body.get("subscription") or {}).get("id")
    obj = body.get(event_type.split(".", 1)[0]) or {}
    if isinstance(obj, dict):
        sub = obj.get("subscription_id") or obj.get("subscription")
        if isinstance(sub, dict):
            sub = sub.get("id")
        if isinstance(sub, str):
            return sub
    return None


def _resource_type(event_type: str) -> str | None:
    head = event_type.split(".", 1)[0]
    return head if head and head != event_type else None


@router.post("/webhooks/toku")
async def receive_toku_webhook(
    request: Request,
    toku_signature: str | None = Header(default=None, alias="Toku-Signature"),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Receptor de webhooks de Toku. Valida, encola y responde 200 (sin trabajo pesado)."""
    secret = settings.toku_webhook_secret
    if not secret:
        # Sin secret configurado no podemos verificar — rechazar para no acumular datos no autenticados
        logger.error("TOKU_WEBHOOK_SECRET no configurado; rechazando webhook entrante.")
        raise HTTPException(status_code=503, detail="Webhook receiver not configured.")

    check_rate_limit(request, "toku")
    raw_body = await read_body_limited(request)
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body.") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    event_id = body.get("id")
    if not isinstance(event_id, str) or not event_id:
        raise HTTPException(status_code=400, detail="Missing event id.")

    if not toku_signature:
        logger.warning("Toku webhook recibido sin cabecera Toku-Signature; rechazando.")
        raise HTTPException(status_code=401, detail="Missing Toku-Signature header.")

    valid, _signature_t = _verify_toku_signature(toku_signature, event_id, secret)
    if not valid:
        logger.warning("Toku webhook con firma inválida o expirada event_id=%s", event_id)
        raise HTTPException(status_code=401, detail="Invalid or expired signature.")

    event_type = str(body.get("event_type") or "unknown")
    inserted = enqueue_event(
        db,
        source="toku",
        event_type=event_type,
        key=dedupe_key("toku", event_id),
        payload_masked=masked_payload(body),
        provider_event_id=event_id,
        resource_type=_resource_type(event_type),
        resource_external_id=_extract_resource_id(body, event_type),
        subscription_external_id=_extract_subscription_id(body, event_type),
    )
    logger.info("Toku webhook %s event_id=%s event_type=%s", "encolado" if inserted else "duplicado", event_id, event_type)
    return {"status": "ok"}
