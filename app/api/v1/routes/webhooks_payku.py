"""Receptor de webhooks de Payku.

Tipos soportados (kind):
  subscription  → {id, status}
  payment       → {transaction_id, verification_key, order, status, subscriptions{…}}
  transaction   → {transaction_id, payment_key, transaction_key, verification_key, order, status}
  nullification → {id, id_transaction, ordencompra, fecha, monto, status}
  payout        → {id, identifier_payout, order, status, update_at, customer{…}}

Autenticación: token secreto en query string `?k=<PAYKU_WEBHOOK_SECRET>`.
Payku no firma el body (no documentado).

Pipeline (docs/integrations/payku/resources/webhooks.md §4):
  POST /{kind}?k=token → validar token → guardar cuerpo crudo + payload → 200 inmediato
  → BackgroundTask: invalidar caché si el evento afecta KPIs.

Acepta JSON y application/x-www-form-urlencoded.
"""

import hmac
import json
import logging
import urllib.parse
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.v1.routes.staging import invalidate_dashboard_cache
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.stg_payku_webhook_event import StgPaykuWebhookEvent


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


logger = logging.getLogger(__name__)

router = APIRouter(tags=["Webhooks"])

_VALID_KINDS = frozenset({"subscription", "payment", "transaction", "nullification", "payout"})

_CACHE_INVALIDATING_KINDS = frozenset({"subscription", "payment", "transaction"})


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


def _invalidate_if_needed(kind: str) -> None:
    if kind in _CACHE_INVALIDATING_KINDS:
        invalidate_dashboard_cache()
        logger.info("Dashboard cache invalidated by payku webhook kind=%s", kind)


@router.post("/webhooks/payku/{kind}")
async def receive_payku_webhook(
    kind: str,
    request: Request,
    background_tasks: BackgroundTasks,
    k: str = Query(default=""),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Receptor de webhooks de Payku. Responde 200 en < 2 s."""
    if kind not in _VALID_KINDS:
        raise HTTPException(status_code=404, detail=f"Unknown webhook kind: {kind}")

    secret = settings.payku_webhook_secret
    if not secret:
        logger.error("PAYKU_WEBHOOK_SECRET no configurado; rechazando webhook entrante.")
        raise HTTPException(status_code=503, detail="Webhook receiver not configured.")

    if not hmac.compare_digest(k, secret):
        logger.warning("Payku webhook con token inválido kind=%s", kind)
        raise HTTPException(status_code=401, detail="Invalid webhook token.")

    raw_body = await request.body()
    content_type = request.headers.get("content-type", "")
    raw_body_str = raw_body.decode("utf-8", errors="replace")

    try:
        payload = _parse_body(raw_body, content_type)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Could not parse body as JSON or form.") from exc

    # Guardar headers relevantes (excluir Authorization/Cookie para no exponer datos sensibles)
    _SKIP_HEADERS = frozenset({"authorization", "cookie", "x-api-key"})
    safe_headers = {k: v for k, v in request.headers.items() if k.lower() not in _SKIP_HEADERS}

    source_ip = request.headers.get("x-forwarded-for") or (request.client.host if request.client else None)

    event = StgPaykuWebhookEvent(
        event_kind=kind,
        payku_resource_id=_extract_resource_id(payload, kind),
        payload=payload,
        raw_body=raw_body_str,
        headers=safe_headers,
        source_ip=str(source_ip)[:45] if source_ip else None,
    )
    db.add(event)
    db.commit()
    logger.info("Payku webhook staged kind=%s resource_id=%s", kind, event.payku_resource_id)

    background_tasks.add_task(_invalidate_if_needed, kind)
    return {"status": "ok"}
