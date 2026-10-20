"""Receptor de webhooks de Toku.

Pipeline (docs/integrations/toku/resources/webhooks.md §7):
  POST → verificar firma → INSERT stg_toku_webhook_events → 200 inmediato
  → BackgroundTask: invalidar caché si el evento afecta KPIs.

La firma Toku cubre solo t + event_id, no el body. Los datos del payload
nunca se aplican directamente a BD_CENTRAL; se usan solo como aviso.
"""

import hashlib
import hmac
import logging
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.routes.staging import invalidate_dashboard_cache
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.stg_toku_webhook_event import StgTokuWebhookEvent


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Webhooks"])

# Eventos que impactan KPIs del dashboard → invalidan caché
_CACHE_INVALIDATING_EVENTS = frozenset(
    {
        "invoice.paid",
        "invoice.voided",
        "invoice.updated",
        "invoice.created",
        "transaction.success",
        "transaction.bulk_success",
        "transaction.failed",
        "transaction.bulk_failed",
        "transaction.status_update",
        "subscription.created",
        "subscription.updated",
        "subscription.deleted",
        "subscription.cancelled",
        "payment_method.created",
        "payment_method.attached_products",
        "payment_method.status_update",
        "payment_method.deleted",
    }
)

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


def _invalidate_if_needed(event_type: str) -> None:
    if event_type in _CACHE_INVALIDATING_EVENTS:
        invalidate_dashboard_cache()
        logger.info("Dashboard cache invalidated by webhook event_type=%s", event_type)


@router.post("/webhooks/toku")
async def receive_toku_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    toku_signature: str | None = Header(default=None, alias="Toku-Signature"),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Receptor de webhooks de Toku. Responde 200 siempre en < 5 s."""
    secret = settings.toku_webhook_secret
    if not secret:
        # Sin secret configurado no podemos verificar — rechazar para no acumular datos no autenticados
        logger.error("TOKU_WEBHOOK_SECRET no configurado; rechazando webhook entrante.")
        raise HTTPException(status_code=503, detail="Webhook receiver not configured.")

    raw_body = await request.body()
    try:
        body: dict[str, Any] = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body.") from exc

    event_id: str = body.get("id", "")
    if not event_id:
        raise HTTPException(status_code=400, detail="Missing event id.")

    # Verificar firma
    if not toku_signature:
        logger.warning("Toku webhook recibido sin cabecera Toku-Signature; rechazando.")
        raise HTTPException(status_code=401, detail="Missing Toku-Signature header.")

    valid, signature_t = _verify_toku_signature(toku_signature, event_id, secret)
    if not valid:
        logger.warning("Toku webhook con firma inválida o expirada event_id=%s", event_id)
        raise HTTPException(status_code=401, detail="Invalid or expired signature.")

    event_type: str = body.get("event_type", "unknown")
    payload_hash = hashlib.sha256(raw_body).hexdigest()
    source_ip = (request.headers.get("x-forwarded-for") or request.client.host if request.client else None)

    event = StgTokuWebhookEvent(
        toku_event_id=event_id,
        event_type=event_type,
        resource_id=_extract_resource_id(body, event_type),
        signature_t=signature_t,
        payload=body,
        payload_hash=payload_hash,
        source_ip=str(source_ip)[:45] if source_ip else None,
        process_status="pending",
    )
    try:
        db.add(event)
        db.commit()
        logger.info("Toku webhook staged event_id=%s event_type=%s", event_id, event_type)
    except IntegrityError:
        db.rollback()
        logger.info("Toku webhook duplicate ignored event_id=%s", event_id)

    background_tasks.add_task(_invalidate_if_needed, event_type)
    return {"status": "ok"}
