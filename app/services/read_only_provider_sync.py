import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_MAX_PAGES = 2000

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.source_record import SourceRecord
from app.models.sync_run import SyncRun
from app.services.payload_sanitization import sanitize_payload
from app.services.sync_progress import ProgressCallback, pagination_totals

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


def store_records(db: Session, source: str, resource_type: str, records: Iterable[dict[str, Any]]) -> int:
    processed = 0
    for record in records:
        statement = insert(SourceRecord).values(
            source=source,
            resource_type=resource_type,
            external_id=_external_id(sanitize_record(record)),
            payload=sanitize_record(record),
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_source_record",
            set_={"payload": statement.excluded.payload, "last_seen_at": datetime.now(UTC)},
            where=SourceRecord.payload.is_distinct_from(statement.excluded.payload),
        )
        processed += int(db.execute(statement.returning(SourceRecord.id)).scalar_one_or_none() is not None)
    return processed


def safe_error_message(exc: Exception, secrets: Iterable[str]) -> str:
    message = str(exc) or f"{type(exc).__name__} (sin mensaje)"
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[redacted]")
    return re.sub(r"\b\d{12,19}\b", "[redacted]", message)[:2000]


ChannelStoreFn = Callable[["Session", str, list], int]


async def sync_read_only_provider(
    db: Session,
    *,
    source: str,
    client_factory: Callable[[], Any],
    resources: Iterable[Resource],
    secrets: Iterable[str],
    channel_store_fn: ChannelStoreFn | None = None,
    progress_callback: ProgressCallback | None = None,
) -> SyncRun:
    run = SyncRun(source=source, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        async with client_factory() as client:
            processed = 0
            for resource_type, page_size, paginated, read_page in resources:
                page = 1
                resource_records = 0
                while page <= _MAX_PAGES:
                    response = await read_page(client, page)
                    records = records_from_response(response)
                    resource_records += len(records)
                    processed += store_records(db, source, resource_type, records)
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
                    logger.warning("%s/%s: se alcanzó el límite de %d páginas, abortando paginación", source, resource_type, _MAX_PAGES)
        run.status = "completed"
        run.records_processed = processed
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
