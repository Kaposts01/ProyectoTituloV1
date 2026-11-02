"""Panel de salud de webhooks (RT-14): conteos por estado, demora, ultimo evento por proveedor y reproceso manual.

Todo exige `webhooks.manage` (permiso de administracion). Nada de datos personales: no se devuelve el payload, ni ids
de recursos o suscripciones, ni texto del proveedor; solo ids internos de evento, tipos, estados, contadores, fechas y
codigos fijos de error. El reproceso solo devuelve a `pending` eventos `failed`/`ignored`; el procesador relee al
proveedor, de modo que reprocesar nunca aplica datos viejos (ver docs/operations/webhooks-runbook.md).
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db
from app.core.security import require_csrf, require_permissions
from app.models.webhook_event import WEBHOOK_EVENT_STATUSES, WebhookEvent
from app.services.rbac import WEBHOOKS_MANAGE
from app.services.webhook_health import SOURCES, queue_health
from app.services.webhook_processor import REQUEUEABLE_STATUSES, requeue_events

router = APIRouter(tags=["Webhooks admin"], dependencies=[Depends(require_permissions(WEBHOOKS_MANAGE))])

_MAX_REQUEUE_IDS = 200


def _event_json(ev: WebhookEvent) -> dict[str, Any]:
    return {
        "id": str(ev.id),
        "source": ev.source,
        "event_type": ev.event_type,
        "status": ev.status,
        "attempts": ev.attempts,
        "last_error_code": ev.last_error_code,
        "received_at": ev.received_at.isoformat() if ev.received_at else None,
        "processed_at": ev.processed_at.isoformat() if ev.processed_at else None,
        "next_attempt_at": ev.next_attempt_at.isoformat() if ev.next_attempt_at else None,
    }


def _check_source(source: str | None) -> None:
    if source is not None and source not in SOURCES:
        raise HTTPException(status_code=422, detail={"code": "invalid_source", "message": "source no válido"})


@router.get("/health")
def get_webhook_health(db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    return queue_health(db)


@router.get("/events")
def list_webhook_events(
    db: Annotated[Session, Depends(get_db)],
    status: Annotated[str | None, Query(description="pending|processing|done|failed|ignored")] = "failed",
    source: Annotated[str | None, Query(description="toku|virtualpos|payku")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    if status is not None and status not in WEBHOOK_EVENT_STATUSES:
        raise HTTPException(status_code=422, detail={"code": "invalid_status", "message": "status no válido"})
    _check_source(source)
    stmt = select(WebhookEvent)
    if status is not None:
        stmt = stmt.where(WebhookEvent.status == status)
    if source is not None:
        stmt = stmt.where(WebhookEvent.source == source)
    rows = db.scalars(stmt.order_by(WebhookEvent.received_at.desc(), WebhookEvent.id).limit(limit)).all()
    return {"items": [_event_json(ev) for ev in rows], "limit": limit}


@router.post("/requeue", dependencies=[Depends(require_csrf)])
def requeue_webhook_events(
    db: Annotated[Session, Depends(get_db)],
    payload: Annotated[dict[str, Any], Body(examples=[{"ids": ["<uuid>"]}, {"all_failed": True, "source": "toku"}])],
) -> dict[str, Any]:
    """Reencola eventos `failed`/`ignored` por id, o todos los `failed` (`all_failed: true`, opcional `source`)."""
    ids_raw = payload.get("ids")
    source = payload.get("source")
    if ids_raw is not None:
        if not isinstance(ids_raw, list) or not ids_raw or len(ids_raw) > _MAX_REQUEUE_IDS:
            raise HTTPException(status_code=422, detail={
                "code": "invalid_ids", "message": f"ids debe ser una lista de 1 a {_MAX_REQUEUE_IDS} identificadores."})
        try:
            ids = [uuid.UUID(str(value)) for value in ids_raw]
        except ValueError:
            raise HTTPException(status_code=422, detail={
                "code": "invalid_ids", "message": "ids contiene un identificador no válido."}) from None
        requeued = requeue_events(db, ids)
    elif payload.get("all_failed") is True:
        if source is not None and not isinstance(source, str):
            raise HTTPException(status_code=422, detail={"code": "invalid_source", "message": "source no válido"})
        _check_source(source)
        requeued = requeue_events(db, None, source=source)
    else:
        raise HTTPException(status_code=422, detail={
            "code": "invalid_requeue_request", "message": "Indica ids o all_failed: true."})
    return {"requeued": requeued, "requeueable_statuses": list(REQUEUEABLE_STATUSES)}
