"""Receptor de webhooks de VirtualPOS.

Tipos soportados (kind):
  payment     → POST con uuid; sin firma documentada (usamos el uuid para consultar la API).
  subscription → POST con id/uuid; sin firma documentada.
  payout      → POST con objeto payout; HMAC-SHA256 del body en header `Signature` (hex o base64).

Pipeline (docs/integrations/virtualpos/resources/webhooks.md):
  POST → [payout: verificar HMAC] → INSERT stg_vpos_webhook_events → 200 inmediato
  → BackgroundTask: invalidar caché si el evento afecta KPIs.

Para payout: la firma se calcula sobre el body crudo exacto (no re-serializar).
El campo `create_at` del webhook se normaliza a `created_at` al guardar el payload.
"""

import base64
import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.v1.routes.staging import invalidate_dashboard_cache
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.stg_vpos_webhook_event import StgVposWebhookEvent


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


logger = logging.getLogger(__name__)

router = APIRouter(tags=["Webhooks"])

_VALID_KINDS = frozenset({"payment", "subscription", "payout"})

# Eventos que afectan KPIs del dashboard → invalidan caché
_CACHE_INVALIDATING_KINDS = frozenset({"payment", "subscription"})


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


def _invalidate_if_needed(kind: str) -> None:
    if kind in _CACHE_INVALIDATING_KINDS:
        invalidate_dashboard_cache()
        logger.info("Dashboard cache invalidated by vpos webhook kind=%s", kind)


@router.post("/webhooks/virtualpos/{kind}")
async def receive_virtualpos_webhook(
    kind: str,
    request: Request,
    background_tasks: BackgroundTasks,
    signature: str | None = Header(default=None, alias="Signature"),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Receptor de webhooks de VirtualPOS. Responde 200 en < 2 s."""
    if kind not in _VALID_KINDS:
        raise HTTPException(status_code=404, detail=f"Unknown webhook kind: {kind}")

    raw_body = await request.body()

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
        payload: dict[str, Any] = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body.") from exc

    if kind == "payout":
        payload = _normalize_payout_payload(payload)

    payload_hash = hashlib.sha256(raw_body).hexdigest()
    source_ip = request.headers.get("x-forwarded-for") or (request.client.host if request.client else None)

    event = StgVposWebhookEvent(
        event_kind=kind,
        resource_id=_extract_resource_id(payload, kind),
        payload=payload,
        payload_hash=payload_hash,
        source_ip=str(source_ip)[:45] if source_ip else None,
        signature_verified=(kind == "payout"),
    )
    db.add(event)
    db.commit()
    logger.info("VirtualPOS webhook staged kind=%s resource_id=%s", kind, event.resource_id)

    background_tasks.add_task(_invalidate_if_needed, kind)
    return {"status": "ok"}
