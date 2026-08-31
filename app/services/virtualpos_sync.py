import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.integrations.virtualpos.client import VirtualPOSClient
from app.models.source_record import SourceRecord
from app.models.sync_run import SyncRun

SOURCE = "virtualpos"


def _records_from_response(response: Any) -> list[dict[str, Any]]:
    """Accept common list envelopes without discarding original records."""
    if isinstance(response, list):
        return [record for record in response if isinstance(record, dict)]
    if isinstance(response, dict):
        for key in ("data", "results", "items"):
            if isinstance(response.get(key), list):
                return [record for record in response[key] if isinstance(record, dict)]
    return []


def _external_id(record: dict[str, Any]) -> str:
    for key in ("id", "uuid", "_id", "client_id", "suscription_id", "payment_id", "charge_id"):
        value = record.get(key)
        if value is not None:
            return str(value)
    return hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()


def _subscription_id(record: dict[str, Any]) -> str | None:
    for key in ("id", "suscription_id"):
        value = record.get(key)
        if value is not None:
            return str(value)
    return None


def _store_records(db: Session, resource_type: str, records: Iterable[dict[str, Any]]) -> int:
    processed = 0
    for record in records:
        statement = insert(SourceRecord).values(
            source=SOURCE,
            resource_type=resource_type,
            external_id=_external_id(record),
            payload=record,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_source_record",
            set_={"payload": statement.excluded.payload, "last_seen_at": datetime.now(UTC)},
        )
        db.execute(statement)
        processed += 1
    return processed


async def sync_virtualpos(db: Session) -> SyncRun:
    """Synchronize read-only VirtualPOS resources into raw staging."""
    run = SyncRun(source=SOURCE, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        async with VirtualPOSClient() as client:
            resources = {
                "client": await client.list_clients(),
                "plan": await client.list_plans(),
                "subscription": await client.list_subscriptions(),
                "payment": await client.list_payments(),
            }
            subscriptions = _records_from_response(resources["subscription"])
            processed = sum(
                _store_records(db, resource_type, _records_from_response(response))
                for resource_type, response in resources.items()
            )
            for subscription in subscriptions:
                subscription_id = _subscription_id(subscription)
                if subscription_id is None:
                    continue
                charges = await client.list_charges(subscription_id)
                processed += _store_records(db, "charge", _records_from_response(charges))

        run.status = "completed"
        run.records_processed = processed
        run.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        run.status = "failed"
        run.error_message = str(exc)[:2000]
        run.finished_at = datetime.now(UTC)
        db.add(run)
        db.commit()
        raise

    return run
