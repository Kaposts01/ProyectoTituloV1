"""Salud de la cola `webhook_events` (RT-13 / RT-14). Solo lectura y sin datos personales.

La usan el panel de administracion (`GET /api/v1/admin/webhooks/health`) y las alertas (`app/services/alerts.py`).
Solo devuelve conteos, marcas de tiempo, segundos de demora y codigos fijos de error (`last_error_code`); nunca el
payload, ids de recursos ni textos del proveedor.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.webhook_event import WEBHOOK_EVENT_STATUSES, WebhookEvent

SOURCES = ("toku", "virtualpos", "payku")
WINDOW = timedelta(hours=24)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _iso(value: datetime | None) -> str | None:
    value = _aware(value)
    return value.isoformat() if value else None


def _blank(source: str) -> dict[str, Any]:
    return {"source": source, "counts": dict.fromkeys(WEBHOOK_EVENT_STATUSES, 0), "last_received_at": None,
            "oldest_pending_at": None, "pending_lag_minutes": None, "done_last_24h": 0,
            "avg_processing_seconds_24h": None, "max_processing_seconds_24h": None}


def queue_health(db: Session, now: datetime | None = None) -> dict[str, Any]:
    """Resumen por proveedor: conteos por estado, demora del pendiente mas antiguo, ultimo evento y demora de proceso."""
    now = now or datetime.now(UTC)
    since = now - WINDOW
    per_source: dict[str, dict[str, Any]] = {s: _blank(s) for s in SOURCES}

    def entry(source: str) -> dict[str, Any]:
        return per_source.setdefault(source, _blank(source))  # fuente inesperada: se muestra igual

    for source, status, n in db.execute(
        select(WebhookEvent.source, WebhookEvent.status, func.count()).group_by(WebhookEvent.source, WebhookEvent.status)
    ):
        entry(source)["counts"][status] = int(n)

    for source, last in db.execute(
        select(WebhookEvent.source, func.max(WebhookEvent.received_at)).group_by(WebhookEvent.source)
    ):
        entry(source)["last_received_at"] = _iso(last)

    for source, oldest in db.execute(
        select(WebhookEvent.source, func.min(WebhookEvent.received_at))
        .where(WebhookEvent.status.in_(("pending", "processing")))
        .group_by(WebhookEvent.source)
    ):
        oldest = _aware(oldest)
        item = entry(source)
        item["oldest_pending_at"] = _iso(oldest)
        if oldest is not None:
            item["pending_lag_minutes"] = round(max((now - oldest).total_seconds(), 0) / 60, 1)

    seconds = func.extract("epoch", WebhookEvent.processed_at - WebhookEvent.received_at)
    for source, n, avg, mx in db.execute(
        select(WebhookEvent.source, func.count(), func.avg(seconds), func.max(seconds))
        .where(WebhookEvent.status == "done", WebhookEvent.processed_at >= since)
        .group_by(WebhookEvent.source)
    ):
        item = entry(source)
        item["done_last_24h"] = int(n)
        item["avg_processing_seconds_24h"] = round(float(avg), 1) if avg is not None else None
        item["max_processing_seconds_24h"] = round(float(mx), 1) if mx is not None else None

    codes = [
        {"code": code, "count": int(n)}
        for code, n in db.execute(
            select(WebhookEvent.last_error_code, func.count())
            .where(WebhookEvent.last_error_code.is_not(None),
                   func.coalesce(WebhookEvent.processed_at, WebhookEvent.received_at) >= since)
            .group_by(WebhookEvent.last_error_code)
            .order_by(func.count().desc(), WebhookEvent.last_error_code)
        )
    ]
    return {
        "generated_at": now.isoformat(),
        "processor_enabled": bool(settings.webhook_processor_enabled),
        "sources": [per_source[s] for s in sorted(per_source, key=lambda s: (s not in SOURCES, s))],
        "error_codes_24h": codes,
    }
