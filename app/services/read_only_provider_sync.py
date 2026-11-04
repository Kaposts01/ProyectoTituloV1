import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.models.sync_run import SyncRun
from app.services import sync_cursors
from app.services.channel_removals import detect_removals
from app.services.payload_sanitization import sanitize_payload
from app.services.source_record_store import StoreResult, upsert_source_records
from app.services.sync_metrics import ResourceTimer, current_run_id, resource_timer
from app.services.sync_progress import ProgressCallback, pagination_totals
from app.services.sync_window import (
    ReadWindow,
    WindowFilterIgnored,
    check_page,
    plan_window,
)

logger = logging.getLogger(__name__)

_MAX_PAGES = 2000

SENSITIVE_PAYMENT_FIELDS = {"card_number", "card_pan", "pan", "cvv", "cvc", "security_code"}
PageReader = Callable[[Any, int], Awaitable[Any]]
Resource = tuple[str, int, bool, PageReader]


def sanitize_record(value: Any) -> Any:
    return sanitize_payload(value)


def records_from_response(response: Any) -> list[dict[str, Any]]:
    if isinstance(response, list):
        return [record for record in response if isinstance(record, dict)]
    if isinstance(response, dict):
        for key in (
            "data",
            "results",
            "items",
            "clients",
            "customers",
            "plans",
            "suscriptions",
            "subscriptions",
            "payments",
            "charges",
            "transaction",
            "transactions",
        ):
            if isinstance(response.get(key), list):
                return [record for record in response[key] if isinstance(record, dict)]
    return []


def has_next_page(response: Any, records: list[dict[str, Any]], page: int, limit: int) -> bool:
    if isinstance(response, dict):
        # Cursor-based (Toku): si la clave existe, es la autoridad — null/vacío = última página
        if "next_cursor" in response:
            return bool(response.get("next_cursor"))
        for key in ("pagination", "meta"):
            metadata = response.get(key)
            if isinstance(metadata, dict):
                total_pages = metadata.get("total_pages", metadata.get("last_page", metadata.get("pages")))
                if isinstance(total_pages, int):
                    return page < total_pages
                has_next = metadata.get("has_next", metadata.get("has_next_page"))
                if isinstance(has_next, bool):
                    return has_next
        next_page = response.get("next_page")
        if isinstance(next_page, int):
            return next_page > page
    return len(records) == limit


def _external_id(record: dict[str, Any]) -> str:
    for key in ("id", "uuid", "_id", "client_id", "suscription_id", "subscription_id", "payment_id", "charge_id"):
        value = record.get(key)
        if value is not None:
            return str(value)
    return hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()


def store_records(
    db: Session,
    source: str,
    resource_type: str,
    records: Iterable[dict[str, Any]],
    *,
    result: StoreResult | None = None,
) -> int:
    """Escribe en `source_records` en lotes (SYNC-O-10); devuelve las filas nuevas o con payload cambiado."""
    sanitized = [sanitize_record(record) for record in records]
    stored = upsert_source_records(db, source, resource_type, sanitized, external_id_fn=_external_id)
    if result is not None:
        result.add(stored)
    return stored.processed


def safe_error_message(exc: Exception, secrets: Iterable[str]) -> str:
    message = str(exc) or f"{type(exc).__name__} (sin mensaje)"
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[redacted]")
    return re.sub(r"\b\d{12,19}\b", "[redacted]", message)[:2000]


ChannelStoreFn = Callable[["Session", str, list], int]

# L7-CIERRE: un recurso OPCIONAL cuyo endpoint responde 404 (p. ej. Toku sandbox: `/organization/payments`) se omite y
# la corrida sigue con los demas; queda `partial` con este texto. No lleva marcadores de configuracion o credencial
# (ver app/core/channel_errors.py), asi que no dispara la alerta de primer fallo (d139a). 401/403 y cualquier error de
# un recurso esencial siguen siendo fatales.
OPTIONAL_SKIPPED_PREFIX = "Recursos opcionales omitidos (el endpoint respondio 404)"


def _is_not_found(exc: Exception) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response is not None and exc.response.status_code == 404


@dataclass(frozen=True)
class WindowedRead:
    """SYNC-O-02: lectura por ventana de un recurso. `read_page(client, page, window)`; `date_fields` = fechas del
    registro que la guarda compara con la ventana (rutas con punto para campos anidados)."""

    read_page: Callable[[Any, int, ReadWindow], Awaitable[Any]]
    date_fields: tuple[str, ...]


async def sync_read_only_provider(
    db: Session,
    *,
    source: str,
    client_factory: Callable[[], Any],
    resources: Iterable[Resource],
    secrets: Iterable[str],
    channel_store_fn: ChannelStoreFn | None = None,
    progress_callback: ProgressCallback | None = None,
    windowed: dict[str, WindowedRead] | None = None,
    optional_resources: Iterable[str] = (),
) -> SyncRun:
    """Lee cada recurso del proveedor a `source_records` (y a las tablas canal) y deja la corrida en `sync_runs`.

    `optional_resources`: recursos secundarios cuyo 404 no hace fallar la corrida (se omiten y queda `partial`).
    """
    optional = frozenset(optional_resources)
    skipped: list[str] = []
    run = SyncRun(source=source, status="running", etl_run_id=current_run_id())
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        async with client_factory() as client:
            processed = 0
            stats: dict[str, dict[str, Any]] = {}
            truncated: set[str] = set()  # recursos cortados por el tope de paginas (lectura parcial)
            subscriptions_read: tuple[datetime, bool] | None = None  # SYNC-D-13: (inicio, lectura completa)

            async def read_resource(
                resource_type: str, page_size: int, paginated: bool, read_page: PageReader, timer: ResourceTimer,
                window: ReadWindow | None, date_fields: tuple[str, ...],
            ) -> int:
                nonlocal processed
                page = 1
                resource_records = 0
                while page <= _MAX_PAGES:
                    with timer.api():
                        response = await read_page(client, page)
                    records = records_from_response(response)
                    if window is not None:
                        check_page(response, records, window, date_fields, label=f"{source}/{resource_type}")
                    resource_records += len(records)
                    with timer.upsert(len(records)):
                        processed += store_records(db, source, resource_type, records, result=timer.store)
                        if channel_store_fn and records:
                            channel_store_fn(db, resource_type, records)
                    if progress_callback:
                        total_records, total_pages = pagination_totals(response)
                        progress_callback(resource_type, page, resource_records, total_records, total_pages)
                    if not paginated or not has_next_page(response, records, page, page_size):
                        break
                    page += 1
                    if source == "toku" and resource_type == "transaction":
                        await asyncio.sleep(1)
                else:
                    truncated.add(resource_type)
                    logger.warning("%s/%s: se alcanzó el límite de %d páginas, abortando paginación", source, resource_type, _MAX_PAGES)
                return resource_records

            for resource_type, page_size, paginated, read_page in resources:
                timer = resource_timer(source, resource_type)
                read_started = datetime.now(UTC)
                spec = (windowed or {}).get(resource_type)
                window = plan_window(db, source, resource_type, read_started) if spec is not None else None
                seen: int | None = None
                if window is not None and spec is not None:
                    timer.mode = sync_cursors.MODE_WINDOW
                    windowed_reader = spec.read_page

                    async def read_window_page(c: Any, p: int, _w=window, _r=windowed_reader) -> Any:
                        return await _r(c, p, _w)

                    try:
                        seen = await read_resource(
                            resource_type, page_size, paginated, read_window_page, timer, window, spec.date_fields
                        )
                    except WindowFilterIgnored:
                        timer.mode = sync_cursors.MODE_FULL  # respaldo: lectura completa (lo ya escrito es idempotente)
                        seen = None
                if seen is None:
                    try:
                        seen = await read_resource(resource_type, page_size, paginated, read_page, timer, None, ())
                    except Exception as exc:
                        if resource_type not in optional or not _is_not_found(exc):
                            raise
                        # Lo ya leido de paginas anteriores se conserva; el recurso no marca exito en su cursor.
                        skipped.append(resource_type)
                        stats[resource_type] = {**timer.finish(), "skipped": True, "reason": "http_404"}
                        logger.warning("%s/%s omitido: el endpoint respondio 404 (recurso opcional)", source, resource_type)
                        continue
                summary = timer.finish()
                stats[resource_type] = summary
                if resource_type == "subscription":
                    full = timer.mode == sync_cursors.MODE_FULL and resource_type not in truncated
                    subscriptions_read = (read_started, full)
                sync_cursors.record_success(
                    db, source, resource_type, timer.mode, started_at=read_started, records_seen=seen,
                    requests_made=timer.pages,
                )
            if subscriptions_read is not None:
                # SYNC-D-13: bajas por desaparicion solo si todas las paginas de suscripciones se leyeron sin ventana.
                detect_removals(db, source, seen_since=subscriptions_read[0], complete=subscriptions_read[1], run_id=run.id)
        run.status = "partial" if skipped else "completed"
        run.error_message = f"{OPTIONAL_SKIPPED_PREFIX}: {', '.join(skipped)}" if skipped else None
        run.records_processed = processed
        run.resource_stats = stats
        run.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        run.status = "failed"
        run.error_message = safe_error_message(exc, secrets)
        run.finished_at = datetime.now(UTC)
        db.add(run)
        db.commit()
        raise

    return run
