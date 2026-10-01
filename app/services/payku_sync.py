"""Sincronización Payku: clientes, planes, suscripciones + transacciones embebidas.

Las transacciones de suscripción vienen embebidas en el payload de cada suscripción
(campo 'transactions'). No se usa el endpoint /api/transaction porque requiere filtro
de fecha y hace timeout en datos históricos.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.payku.client import PaykuClient
from app.models.sync_run import SyncRun
from app.services.channel_store import store_payku_resources
from app.services.payload_sanitization import sanitize_payload
from app.services.read_only_provider_sync import safe_error_message, store_records
from app.services.sync_progress import ProgressCallback

SOURCE = "payku"
_PER_PAGE = 100
_MAX_PAGES = 2_000


def _records_from(response: Any) -> list[dict[str, Any]]:
    if isinstance(response, list):
        return [r for r in response if isinstance(r, dict)]
    if isinstance(response, dict):
        for key in ("customers", "subscriptions", "plans", "data", "results", "items"):
            val = response.get(key)
            if isinstance(val, list):
                return [r for r in val if isinstance(r, dict)]
    raise ValueError("Payku returned an unexpected collection response envelope")


def _has_more(records: list, per_page: int) -> bool:
    return len(records) == per_page


async def sync_payku(
    db: Session,
    progress_callback: ProgressCallback | None = None,
) -> SyncRun:
    run = SyncRun(source=SOURCE, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        async with PaykuClient() as client:
            processed = 0

            # ── Clientes ────────────────────────────────────────────────
            page, total = 1, 0
            while True:
                if page > _MAX_PAGES:
                    raise RuntimeError("Payku client pagination exceeded the safety limit")
                resp = await client.list_clients(page=page, per_page=_PER_PAGE)
                recs = _records_from(resp)
                sanitized = [sanitize_payload(r) for r in recs]
                total += len(sanitized)
                processed += store_records(db, SOURCE, "client", sanitized)
                store_payku_resources(db, "client", sanitized)
                if progress_callback:
                    progress_callback("client", page, total, None, None)
                if not _has_more(recs, _PER_PAGE):
                    break
                page += 1

            # ── Planes (no paginados) ────────────────────────────────────
            resp = await client.list_plans()
            recs = _records_from(resp)
            sanitized = [sanitize_payload(r) for r in recs]
            processed += store_records(db, SOURCE, "plan", sanitized)
            store_payku_resources(db, "plan", sanitized)
            if progress_callback:
                progress_callback("plan", 1, len(sanitized), len(sanitized), 1)

            # ── Suscripciones + transacciones embebidas ──────────────────
            page, sub_total, tx_total = 1, 0, 0
            while True:
                if page > _MAX_PAGES:
                    raise RuntimeError("Payku subscription pagination exceeded the safety limit")
                resp = await client.list_subscriptions(page=page, per_page=_PER_PAGE)
                subs = _records_from(resp)
                sanitized_subs = [sanitize_payload(s) for s in subs]
                sub_total += len(sanitized_subs)
                processed += store_records(db, SOURCE, "subscription", sanitized_subs)
                store_payku_resources(db, "subscription", sanitized_subs)

                # Extraer transacciones embebidas en cada suscripción
                for sub in sanitized_subs:
                    sub_id = sub.get("id") or sub.get("__external_id")
                    embedded = sub.get("transactions") or []
                    if not isinstance(embedded, list) or not embedded:
                        continue
                    tx_batch = [
                        {**t, "__subscription_id": sub_id}
                        for t in embedded
                        if isinstance(t, dict)
                    ]
                    sanitized_txs = [sanitize_payload(t) for t in tx_batch]
                    processed += store_records(db, SOURCE, "transaction", sanitized_txs)
                    store_payku_resources(db, "transaction", sanitized_txs)
                    tx_total += len(sanitized_txs)

                if progress_callback:
                    progress_callback("subscription", page, sub_total, None, None)
                    if tx_total:
                        progress_callback("transaction", page, tx_total, None, None)
                if not _has_more(subs, _PER_PAGE):
                    break
                page += 1

        run.status = "completed"
        run.records_processed = processed
        run.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        run.status = "failed"
        run.error_message = safe_error_message(
            exc, (settings.payku_api_key, settings.payku_secret_key)
        )
        run.finished_at = datetime.now(UTC)
        db.add(run)
        db.commit()
        raise

    return run
