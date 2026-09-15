import hashlib
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.virtualpos.client import VirtualPOSClient
from app.models.source_record import SourceRecord
from app.models.sync_run import SyncRun
from app.services.channel_store import store_vp_resources
from app.services.crm_materialization import materialize_records
from app.services.payload_sanitization import sanitize_payload
from app.services.sync_progress import ProgressCallback, pagination_totals

SOURCE = "virtualpos1"
SENSITIVE_PAYMENT_FIELDS = {"card_number", "card_pan", "pan", "cvv", "cvc", "security_code"}


def _sanitize_record(value: Any) -> Any:
    """Keep provider payloads useful for auditing without retaining card data."""
    return sanitize_payload(value)


def _safe_error_message(exc: Exception) -> str:
    message = str(exc)
    for secret in (settings.virtualpos_api_key, settings.virtualpos_secret_key):
        if secret:
            message = message.replace(secret, "[redacted]")
    return re.sub(r"\b\d{12,19}\b", "[redacted]", message)[:2000]


def _records_from_response(response: Any) -> list[dict[str, Any]]:
    """Accept common list envelopes without discarding original records."""
    if isinstance(response, list):
        return [record for record in response if isinstance(record, dict)]
    if isinstance(response, dict):
        for key in ("data", "results", "items", "clients", "plans", "suscriptions", "payments", "charges"):
            if isinstance(response.get(key), list):
                return [record for record in response[key] if isinstance(record, dict)]
    return []


def _external_id(record: dict[str, Any]) -> str:
    for key in ("id", "uuid", "_id", "client_id", "suscription_id", "payment_id", "charge_id"):
        value = record.get(key)
        if value is not None:
            return str(value)
    order = record.get("order")
    if isinstance(order, dict) and order.get("uuid") is not None:
        return str(order["uuid"])
    return hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()


def _subscription_id(record: dict[str, Any]) -> str | None:
    for key in ("id", "suscription_id"):
        value = record.get(key)
        if value is not None:
            return str(value)
    return None


def _has_next_page(response: Any, records: list[dict[str, Any]], page: int, limit: int) -> bool:
    """Use explicit pagination metadata when present, otherwise a full page implies another request."""
    if isinstance(response, dict):
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


def _store_records(
    db: Session,
    source: str,
    resource_type: str,
    records: Iterable[dict[str, Any]],
    sync_context: dict[str, Any] | None = None,
) -> int:
    processed = 0
    for record in records:
        sanitized_record = _sanitize_record(record)
        statement = insert(SourceRecord).values(
            source=source,
            resource_type=resource_type,
            external_id=_external_id(sanitized_record),
            payload=sanitized_record,
            sync_context=sync_context,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_source_record",
            set_={
                "payload": statement.excluded.payload,
                "sync_context": statement.excluded.sync_context,
                "last_seen_at": datetime.now(UTC),
            },
            where=or_(
                SourceRecord.payload.is_distinct_from(statement.excluded.payload),
                SourceRecord.sync_context.is_distinct_from(statement.excluded.sync_context),
            ),
        )
        result = db.execute(statement.returning(SourceRecord.id))
        processed += int(result.scalar_one_or_none() is not None)
    return processed


async def sync_virtualpos(
    db: Session, platform: str = "virtualpos1", progress_callback: ProgressCallback | None = None
) -> SyncRun:
    """Synchronize read-only VirtualPOS resources into raw staging."""
    run = SyncRun(source=platform, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        client_factory = VirtualPOSClient if platform == "virtualpos1" else lambda: VirtualPOSClient(platform)
        async with client_factory() as client:
            processed = 0
            limit = 100
            for resource_type, read_page in (
                ("client", client.list_clients),
                ("payment", client.list_payments),
            ):
                page = 1
                resource_records = 0
                while True:
                    response = await read_page(page=page, limit=limit)
                    records = _records_from_response(response)
                    resource_records += len(records)
                    sanitized = [_sanitize_record(record) for record in records]
                    processed += _store_records(db, platform, resource_type, sanitized)
                    store_vp_resources(db, resource_type, sanitized, platform=platform)
                    if progress_callback:
                        total_records, total_pages = pagination_totals(response)
                        progress_callback(resource_type, page, resource_records, total_records, total_pages)
                    if not _has_next_page(response, records, page, limit):
                        break
                    page += 1

            plans = [_sanitize_record(record) for record in _records_from_response(await client.list_plans())]
            processed += _store_records(db, platform, "plan", plans)
            store_vp_resources(db, "plan", plans, platform=platform)
            if progress_callback:
                progress_callback("plan", 1, len(plans), None, None)

            page = 1
            subscription_records = 0
            while True:
                response = await client.list_subscriptions(page=page, limit=limit)
                subscriptions = _records_from_response(response)
                subscription_records += len(subscriptions)
                sanitized_subs = [_sanitize_record(s) for s in subscriptions]
                processed += _store_records(db, platform, "subscription", sanitized_subs)
                store_vp_resources(db, "subscription", sanitized_subs, platform=platform)
                for subscription in sanitized_subs:
                    subscription_id = _subscription_id(subscription)
                    if subscription_id is None:
                        continue
                    charge_page = 1
                    charge_records_processed = 0
                    while True:
                        charges = await client.list_charges(subscription_id, page=charge_page, limit=limit)
                        charge_records = _records_from_response(charges)
                        charge_records_processed += len(charge_records)
                        sanitized_charges = [_sanitize_record(charge) for charge in charge_records]
                        processed += _store_records(
                            db,
                            platform,
                            "charge",
                            sanitized_charges,
                            sync_context={"subscription_external_id": subscription_id},
                        )
                        store_vp_resources(db, "charge", sanitized_charges, platform=platform, subscription_external_id=subscription_id)
                        if progress_callback:
                            total_records, total_pages = pagination_totals(charges)
                            progress_callback(
                                f"charge ({subscription_id})",
                                charge_page,
                                charge_records_processed,
                                total_records,
                                total_pages,
                            )
                        if not _has_next_page(charges, charge_records, charge_page, limit):
                            break
                        charge_page += 1
                if progress_callback:
                    total_records, total_pages = pagination_totals(response)
                    progress_callback("subscription", page, subscription_records, total_records, total_pages)
                if not _has_next_page(response, subscriptions, page, limit):
                    break
                page += 1

            staged_records = db.scalars(select(SourceRecord).where(SourceRecord.source == platform)).all()
            materialize_records(db, staged_records)

            run.status = "completed"
        run.records_processed = processed
        run.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        run.status = "failed"
        run.error_message = _safe_error_message(exc)
        run.finished_at = datetime.now(UTC)
        db.add(run)
        db.commit()
        raise

    return run
