"""Recepcion de webhooks (RT-08): enmascarado de PII, tope de body, rate limit en memoria y encolado idempotente.

El receptor SOLO valida y encola en `webhook_events`; el trabajo pesado (releer por API, consolidar) lo hace el
procesador asincrono (`webhook_processor`). Ningun dato personal del payload se persiste ni se loguea: se pasa por
`sanitize_payload` (credenciales) y `mask_pii` (datos personales) antes de insertar; los canales sin firma
(VirtualPOS payment/subscription y Payku) guardan ADEMAS solo ids/estado (`minimal_payload`).
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.webhook_event import WebhookEvent
from app.services.payload_sanitization import sanitize_payload

MASK = "[masked]"
DEDUPE_BUCKET_SECONDS = 300  # reintentos del mismo aviso sin id de evento dentro de 5 min colapsan en una fila

# Claves que se enmascaran por completo (valor escalar o estructura).
_PII_KEYS = frozenset({
    "email", "mail", "e_mail", "phone", "phone_number", "telefono", "celular", "mobile", "rut", "run", "dni",
    "tax_id", "government_id", "social_id", "document", "document_number", "name", "nombre", "nombres", "apellido",
    "apellidos", "first_name", "last_name", "full_name", "address", "direccion", "street", "city", "comuna",
    "birth_date", "fecha_nacimiento", "gender", "holder", "cardholder", "payment_instrument", "instrument", "card",
    "cards", "ip", "ip_address", "user_agent",
})
# Objetos de persona: se reducen a su id (el id externo no es dato personal y sirve para releer).
_PERSON_OBJECT_KEYS = frozenset({"customer", "payer", "client", "user", "buyer"})

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_RUT_RE = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b")
_PHONE_RE = re.compile(r"\+\d[\d\s-]{7,}\d")


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _mask_string(value: str) -> str:
    value = _EMAIL_RE.sub(MASK, value)
    value = _RUT_RE.sub(MASK, value)
    return _PHONE_RE.sub(MASK, value)


def mask_pii(value: Any) -> Any:
    """Copia del payload sin datos personales (claves de persona, correos, RUT y telefonos dentro de textos)."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, nested in value.items():
            k = _key(str(key))
            if k in _PII_KEYS:
                out[key] = MASK
            elif k in _PERSON_OBJECT_KEYS and isinstance(nested, dict):
                ident = nested.get("id")
                out[key] = {"id": _mask_string(str(ident))} if isinstance(ident, str | int) else MASK
            else:
                out[key] = mask_pii(nested)
        return out
    if isinstance(value, list):
        return [mask_pii(item) for item in value]
    if isinstance(value, str):
        return _mask_string(value)
    return value


def masked_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Credenciales fuera (`sanitize_payload`) y PII enmascarada. Es lo unico que se persiste del cuerpo."""
    return mask_pii(sanitize_payload(payload))


_MINIMAL_KEYS = ("id", "uuid", "status", "suscription_id", "subscription_id", "transaction_id", "payment_key",
                 "id_transaction", "event_type", "kind")


def minimal_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Canales sin firma: solo ids/estado escalares (el contenido nunca se usa; se relee por API)."""
    out: dict[str, Any] = {}
    for key in _MINIMAL_KEYS:
        value = payload.get(key)
        if isinstance(value, str | int) and not isinstance(value, bool):
            out[key] = _mask_string(str(value))[:255]
    subs = payload.get("subscriptions")
    if isinstance(subs, dict) and isinstance(subs.get("id"), str | int):
        out["subscription_id"] = str(subs["id"])[:255]
    return out


# ----------------------------- tope de body -----------------------------


async def read_body_limited(request: Request, max_bytes: int | None = None) -> bytes:
    """Lee el body respetando el tope; 413 si lo supera (antes de parsear o tocar la BD)."""
    limit = max_bytes or settings.webhook_max_body_bytes
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise HTTPException(status_code=413, detail="Payload too large.")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length.") from exc
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail="Payload too large.")
        chunks.append(chunk)
    return b"".join(chunks)


# ----------------------------- rate limit en memoria -----------------------------

_RATE_LOCK = threading.Lock()
_RATE_HITS: dict[tuple[str, str], deque[float]] = {}
_RATE_WINDOW_SECONDS = 60.0
_RATE_MAX_KEYS = 5000


def reset_rate_limits() -> None:
    with _RATE_LOCK:
        _RATE_HITS.clear()


def client_ip(request: Request) -> str:
    """IP del cliente. `X-Forwarded-For` solo se usa con WEBHOOK_TRUST_FORWARDED_FOR (detras de un proxy propio)."""
    if settings.webhook_trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()[:45]
    return request.client.host if request.client else "unknown"


def check_rate_limit(request: Request, route: str, *, now: float | None = None) -> None:
    """Ventana deslizante de 60 s por (ruta, IP). 429 con `Retry-After` al superar el limite."""
    limit = settings.webhook_rate_limit_per_minute
    if limit <= 0:
        return
    current = time.monotonic() if now is None else now
    key = (route, client_ip(request))
    with _RATE_LOCK:
        if len(_RATE_HITS) > _RATE_MAX_KEYS:
            for stale in [k for k, q in _RATE_HITS.items() if not q or current - q[-1] > _RATE_WINDOW_SECONDS]:
                del _RATE_HITS[stale]
        hits = _RATE_HITS.setdefault(key, deque())
        while hits and current - hits[0] > _RATE_WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= limit:
            raise HTTPException(status_code=429, detail="Too many requests.", headers={"Retry-After": "60"})
        hits.append(current)


# ----------------------------- encolado idempotente -----------------------------


def dedupe_key(*parts: str | None, bucket: bool = False, now: float | None = None) -> str:
    """sha256 de las partes (+ ventana de 5 min si el proveedor no manda id de evento)."""
    items = [p or "" for p in parts]
    if bucket:
        items.append(str(int((time.time() if now is None else now) // DEDUPE_BUCKET_SECONDS)))
    return hashlib.sha256("|".join(items).encode("utf-8")).hexdigest()


def _clip(value: object, size: int = 255) -> str | None:
    return str(value)[:size] if value not in (None, "") else None


def enqueue_event(
    db: Session,
    *,
    source: str,
    event_type: str,
    key: str,
    payload_masked: dict[str, Any],
    provider_event_id: str | None = None,
    resource_type: str | None = None,
    resource_external_id: str | None = None,
    subscription_external_id: str | None = None,
) -> bool:
    """Inserta en `webhook_events` (ON CONFLICT DO NOTHING por `dedupe_key`). True = fila nueva, False = duplicado."""
    stmt = (
        insert(WebhookEvent)
        .values(
            source=source,
            event_type=event_type[:100],
            provider_event_id=_clip(provider_event_id),
            resource_type=resource_type,
            resource_external_id=_clip(resource_external_id),
            subscription_external_id=_clip(subscription_external_id),
            status="pending",
            attempts=0,
            next_attempt_at=datetime.now(UTC),
            payload_masked=payload_masked,
            dedupe_key=key,
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(WebhookEvent.id)
    )
    inserted = db.execute(stmt).first() is not None
    db.commit()
    return inserted
