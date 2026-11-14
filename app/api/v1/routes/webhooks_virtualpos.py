"""Receptor de webhooks de VirtualPOS.

Tipos soportados (kind = ruta; varios cuerpos no traen el nombre del evento, por eso una ruta por evento):
  payment       -> POST con uuid; sin firma documentada. SOLO se guarda el id: el procesador relee por API.
  subscription  -> POST con uuid (API) o {"status","code","suscription":{"uuid"}} (POS, evento PAT
                   suscription_activated); sin firma documentada. SOLO se guarda el id.
  charge_paid   -> eventos PAT (Portal Comercio): cargo con `id` y `suscription_uuid`. El cuerpo trae datos del
  charge_reject    cliente y del pago que NO se guardan: solo ids y estado. Sin firma documentada.
  card_change   -> evento PAT: {"uuid": <suscripcion>}; sin firma documentada. SOLO se guarda el id.
  payout        -> POST con objeto payout; HMAC-SHA256 del body en header `Signature` (hex o base64).

Algunos envios PAT declaran `Content-Type: application/x-www-form-urlencoded`: se aceptan junto a JSON.

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
from urllib.parse import parse_qsl

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

_CHARGE_KINDS = frozenset({"charge_paid", "charge_reject"})
_SUBSCRIPTION_KINDS = frozenset({"subscription", "card_change"})
_VALID_KINDS = frozenset({"payment", "payout"}) | _CHARGE_KINDS | _SUBSCRIPTION_KINDS
_MAX_FORM_FIELDS = 200


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


def _scalar(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, str | int):
        return None
    text = str(value).strip()
    return text or None


def _nested_uuid(payload: dict[str, Any], head: str) -> str | None:
    obj = payload.get(head)
    return _scalar(obj.get("uuid") or obj.get("id")) if isinstance(obj, dict) else None


def _extract_ids(payload: dict[str, Any], kind: str) -> tuple[str | None, str | None]:
    """(id del recurso, id de suscripcion) segun la ruta. Solo ids: nada mas del cuerpo se usa."""
    if kind == "payment":
        return _scalar(payload.get("uuid")) or _scalar(payload.get("id")), None
    if kind in _SUBSCRIPTION_KINDS:
        sub = (_scalar(payload.get("uuid")) or _nested_uuid(payload, "suscription")
               or _nested_uuid(payload, "subscription") or _scalar(payload.get("id"))
               or _scalar(payload.get("suscription_id")))
        return sub, sub
    if kind in _CHARGE_KINDS:
        charge = _scalar(payload.get("id")) or _scalar(payload.get("charge_id"))
        sub = (_scalar(payload.get("suscription_uuid")) or _scalar(payload.get("subscription_uuid"))
               or _nested_uuid(payload, "suscription"))
        return charge, sub
    if kind == "payout":
        payout = payload.get("payout") or {}
        return (_scalar(payout.get("id")) if isinstance(payout, dict) else None), None
    return None, None


def _form_to_dict(text: str) -> dict[str, Any]:
    """`a=1&suscription[uuid]=x` -> {"a": "1", "suscription": {"uuid": "x"}}. Un unico campo con JSON se desempaqueta."""
    pairs = parse_qsl(text, keep_blank_values=True, max_num_fields=_MAX_FORM_FIELDS)
    if len(pairs) == 1:  # JSON enviado como unico campo del formulario (en el valor o en la clave)
        key, value = pairs[0]
        for candidate in (value, key):
            if candidate.lstrip().startswith("{"):
                try:
                    parsed = json.loads(candidate)
                except ValueError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
    out: dict[str, Any] = {}
    for key, value in pairs:
        if "[" in key and key.endswith("]"):
            head, _, rest = key.partition("[")
            target = out.get(head)
            if not isinstance(target, dict):
                target = out[head] = {}
            target[rest[:-1]] = value
        else:
            out[key] = value
    return out


def _parse_body(raw_body: bytes, content_type: str | None) -> dict[str, Any]:
    """JSON (por defecto) o application/x-www-form-urlencoded (algunos envios PAT). 400 si no es un objeto."""
    is_form = "application/x-www-form-urlencoded" in (content_type or "").lower()
    try:
        text = raw_body.decode("utf-8")
        if is_form:
            try:  # hay emisores que declaran form pero mandan JSON
                payload = json.loads(text)
            except ValueError:
                payload = _form_to_dict(text)
        else:
            payload = json.loads(text)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid body.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid body.")
    return payload


def _resource_type(kind: str) -> str:
    if kind in _CHARGE_KINDS:
        return "charge"
    if kind in _SUBSCRIPTION_KINDS:
        return "subscription"
    return kind


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

    payload = _parse_body(raw_body, request.headers.get("content-type"))

    resource_id, subscription_id = _extract_ids(payload, kind)
    if kind == "payout":
        payload = _normalize_payout_payload(payload)
        stored = masked_payload(payload)
    else:
        # sin firma: solo ids/estado escalares; el cuerpo (cliente, tarjeta, pago) no se confia ni se persiste
        stored = minimal_payload(payload)
        if subscription_id:
            stored["subscription_id"] = subscription_id[:255]

    inserted = enqueue_event(
        db,
        source="virtualpos",
        event_type=kind,
        key=dedupe_key("virtualpos", kind, resource_id, str(stored.get("status") or ""), bucket=True),
        payload_masked=stored,
        resource_type=_resource_type(kind),
        resource_external_id=resource_id,
        subscription_external_id=subscription_id,
    )
    logger.info("VirtualPOS webhook %s kind=%s resource_id=%s", "encolado" if inserted else "duplicado", kind, resource_id)
    return {"status": "ok"}
