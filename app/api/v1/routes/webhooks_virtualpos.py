"""Receptor de webhooks de VirtualPOS.

Tipos soportados (kind):
  payment      -> POST con uuid; sin firma documentada. SOLO se guarda el id: el procesador relee por API.
  subscription -> POST con id/uuid; sin firma documentada. SOLO se guarda el id.
  payout       -> POST con objeto payout; HMAC-SHA256 del body en header `Signature` (hex o base64).

Pipeline (docs/data/webhooks.md):
  POST -> rate limit -> tope de body -> [payout: verificar HMAC] -> INSERT idempotente en `webhook_events` -> 200.
Para payout la firma se calcula sobre el body crudo exacto (no re-serializar). El payload no se loguea; el contenido de
payment/subscription nunca se confia ni se persiste (solo ids/estado).
"""

import base64
import hashlib
import hmac
import json
import logging
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

_VALID_KINDS = frozenset({"payment", "subscription", "payout"})


def _verify_payout_signature(raw_body: bytes, received: str, secret: str) -> bool:
    """Verifica HMAC-SHA256 del body crudo. Acepta hex o base64 (no documentado cuál)."""
    mac = hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()
    candidates = [mac.hex(), base64.b64encode(mac).decode()]
    return any(
        len(c) == len(received) and hmac.compare_digest(c, received)
        for c in candidates
    )


def _normalize_payout_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Renombra create_at → created_at y update_at → updated_at en el objeto payout.

    VirtualPOS usa campos sin 'd' en el webhook (discrepancia C17 de la doc).
    """
    payout = payload.get("payout", {})
    if "create_at" in payout:
        if "created_at" not in payout:
            payout["created_at"] = payout["create_at"]
        del payout["create_at"]
    if "update_at" in payout:
        if "updated_at" not in payout:
            payout["updated_at"] = payout["update_at"]
        del payout["update_at"]
    return payload


def _extract_resource_id(payload: dict[str, Any], kind: str) -> str | None:
    if kind == "payment":
        return payload.get("uuid") or payload.get("id")
    if kind == "subscription":
        return payload.get("id") or payload.get("suscription_id") or payload.get("uuid")
    if kind == "payout":
        payout = payload.get("payout") or {}
        return payout.get("id")
    return None


@router.post("/webhooks/virtualpos/{kind}")
async def receive_virtualpos_webhook(
    kind: str,
    request: Request,
    signature: str | None = Header(default=None, alias="Signature"),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Receptor de webhooks de VirtualPOS. Valida, encola y responde 200 (sin trabajo pesado)."""
    if kind not in _VALID_KINDS:
        raise HTTPException(status_code=404, detail=f"Unknown webhook kind: {kind}")

    check_rate_limit(request, f"virtualpos:{kind}")
    raw_body = await read_body_limited(request)

    # Payout requiere firma HMAC-SHA256; payment y subscription no tienen firma documentada
    if kind == "payout":
        secret = settings.virtualpos_payout_webhook_secret
        if not secret:
            logger.error("VIRTUALPOS_PAYOUT_WEBHOOK_SECRET no configurado; rechazando payout webhook.")
            raise HTTPException(status_code=503, detail="Webhook receiver not configured.")
        if not signature:
            logger.warning("VirtualPOS payout webhook sin cabecera Signature; rechazando.")
            raise HTTPException(status_code=401, detail="Missing Signature header.")
        if not _verify_payout_signature(raw_body, signature, secret):
            logger.warning("VirtualPOS payout webhook con firma inválida.")
            raise HTTPException(status_code=401, detail="Invalid signature.")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    if kind == "payout":
        payload = _normalize_payout_payload(payload)
        stored = masked_payload(payload)
    else:
        stored = minimal_payload(payload)  # sin firma: solo ids/estado, el contenido no se confia

    resource_id = _extract_resource_id(payload, kind)
    resource_id = str(resource_id) if isinstance(resource_id, str | int) else None
    inserted = enqueue_event(
        db,
        source="virtualpos",
        event_type=kind,
        key=dedupe_key("virtualpos", kind, resource_id, str(stored.get("status") or ""), bucket=True),
        payload_masked=stored,
        resource_type=kind,
        resource_external_id=resource_id,
        subscription_external_id=resource_id if kind == "subscription" else None,
    )
    logger.info("VirtualPOS webhook %s kind=%s resource_id=%s", "encolado" if inserted else "duplicado", kind, resource_id)
    return {"status": "ok"}
