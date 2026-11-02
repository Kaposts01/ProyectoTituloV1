import hashlib
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.virtualpos.client import VirtualPOSAPIError, VirtualPOSClient
from app.models.sync_run import SyncRun
from app.services import sync_cursors
from app.services.channel_consolidation import consolidate_to_centralized
from app.services.channel_store import _VP_PLATFORMS, store_vp_resources
from app.services.charge_recovery import reconcile_charge_recoveries
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

SOURCE = "virtualpos1"

# SYNC-O-05: filtros de fecha por recurso (desde, hasta) y las fechas del registro que la guarda compara. Pagos: una
# pasada por fecha de creacion y otra por fecha de autorizacion (un pago creado antes y autorizado dentro de la
# ventana). Suscripciones y planes se leen siempre completos (la API no filtra suscripciones por fecha).
_WINDOW_PASSES: dict[str, tuple[tuple[tuple[str, str], tuple[str, ...]], ...]] = {
    "client": ((("created_from", "created_to"), ("created", "created_at")),),
    "payment": (
        (("created_from", "created_to"), ("order.created_at", "created_at")),
        (("authorization_from", "authorization_to"), ("order.authorized_at", "authorized_at")),
    ),
}
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
    """Accept common list envelopes without discarding original records.

    Returns [] for an empty or unrecognized dict (VP returns {} on transient
    errors or when the client could not parse the response as JSON).
    Only raises when the response is not a dict or list at all.
    """
    if isinstance(response, list):
        return [record for record in response if isinstance(record, dict)]
    if isinstance(response, dict):
        for key in ("data", "results", "items", "clients", "plans", "suscriptions", "payments", "charges"):
            if isinstance(response.get(key), list):
                return [record for record in response[key] if isinstance(record, dict)]
        return []
    raise ValueError(f"VirtualPOS returned an unexpected response type: {type(response).__name__}")


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
    *,
    contexts: list[dict[str, Any] | None] | None = None,
    result: StoreResult | None = None,
) -> int:
    """Escribe en `source_records` en lotes (SYNC-O-10) y devuelve las filas nuevas o cambiadas.

    `contexts` da un `sync_context` por registro (cobros de varias suscripciones en un solo lote); si falta, todos
    llevan `sync_context`. `result` acumula nuevas/actualizadas/sin cambio para las estadisticas de la corrida.
    """
    sanitized = [_sanitize_record(record) for record in records]
    stored = upsert_source_records(
        db,
        source,
        resource_type,
        sanitized,
        external_id_fn=_external_id,
        contexts=contexts if contexts is not None else [sync_context] * len(sanitized),
    )
    if result is not None:
        result.add(stored)
    return stored.processed


async def sync_virtualpos(
    db: Session,
    platform: str = "virtualpos1",
    progress_callback: ProgressCallback | None = None,
    consolidate: bool = True,
) -> SyncRun:
    """Synchronize read-only VirtualPOS resources into raw staging.

    `consolidate=False` (SYNC-O-04) lo usa el orquestador `sync_all_channels`: no consolida ni reconcilia
    recuperaciones aqui; lo hace UNA vez al final de la corrida (la consolidacion de `virtualpos` cubre ambas
    cuentas, asi que consolidar tras cada cuenta repetia el trabajo). Por defecto conserva el comportamiento
    anterior para los llamadores directos (scripts, /etl/full-sync).
    """
    if platform not in _VP_PLATFORMS:
        raise ValueError(f"Plataforma VirtualPOS desconocida: {platform!r}")
    run = SyncRun(source=platform, status="running", etl_run_id=current_run_id())
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        client_factory = VirtualPOSClient if platform == "virtualpos1" else lambda: VirtualPOSClient(platform)
        async with client_factory() as client:
            processed = 0
            skipped_subscriptions: list[str] = []
            limit = 100
            stats: dict[str, dict[str, Any]] = {}
            cursor_marks: list[tuple[str, str, datetime, int, int]] = []

            async def read_resource(
                resource_type: str,
                read_page: Any,
                timer: ResourceTimer,
                filters: dict[str, str],
                window: ReadWindow | None,
                date_fields: tuple[str, ...],
            ) -> int:
                nonlocal processed
                page = 1
                resource_records = 0
                while True:
                    with timer.api():
                        response = await read_page(page=page, limit=limit, **filters)
                    records = _records_from_response(response)
                    if window is not None:
                        check_page(response, records, window, date_fields, label=f"{platform}/{resource_type}")
                    resource_records += len(records)
                    sanitized = [_sanitize_record(record) for record in records]
                    with timer.upsert(len(records)):
                        processed += _store_records(db, platform, resource_type, sanitized, result=timer.store)
                        store_vp_resources(db, resource_type, sanitized, platform=platform)
                    if progress_callback:
                        total_records, total_pages = pagination_totals(response)
                        progress_callback(resource_type, page, resource_records, total_records, total_pages)
                    if not _has_next_page(response, records, page, limit):
                        break
                    page += 1
                return resource_records

            for resource_type, read_page in (
                ("client", client.list_clients),
                ("payment", client.list_payments),
            ):
                timer = resource_timer(platform, resource_type)
                read_started = datetime.now(UTC)
                window = plan_window(db, platform, resource_type, read_started)
                seen: int | None = None
                if window is not None:
                    # SYNC-O-05: una pasada por filtro de fecha; si alguna delata un filtro ignorado, lectura completa.
                    timer.mode = sync_cursors.MODE_WINDOW
                    try:
                        seen = 0
                        for (from_key, to_key), date_fields in _WINDOW_PASSES[resource_type]:
                            filters = {from_key: window.start_date, to_key: window.end_date}
                            seen += await read_resource(resource_type, read_page, timer, filters, window, date_fields)
                    except WindowFilterIgnored:
                        timer.mode = sync_cursors.MODE_FULL  # respaldo completo (lo ya escrito es idempotente)
                        seen = None
                if seen is None:
                    seen = await read_resource(resource_type, read_page, timer, {}, None, ())
                stats[resource_type] = timer.finish()
                cursor_marks.append((resource_type, timer.mode, read_started, seen, timer.pages))

            plan_timer = resource_timer(platform, "plan")
            plan_started = datetime.now(UTC)
            with plan_timer.api():
                plan_response = await client.list_plans()
            plans = [_sanitize_record(record) for record in _records_from_response(plan_response)]
            with plan_timer.upsert(len(plans)):
                processed += _store_records(db, platform, "plan", plans, result=plan_timer.store)
                store_vp_resources(db, "plan", plans, platform=platform)
            stats["plan"] = plan_timer.finish()
            cursor_marks.append(("plan", sync_cursors.MODE_FULL, plan_started, len(plans), plan_timer.pages))
            if progress_callback:
                progress_callback("plan", 1, len(plans), None, None)

            page = 1
            subscription_records = 0
            sub_timer = resource_timer(platform, "subscription")
            subs_started = datetime.now(UTC)
            charge_timer = resource_timer(platform, "charge")  # los cobros vienen embebidos en cada suscripcion
            while True:
                with sub_timer.api():
                    response = await client.list_subscriptions(page=page, limit=limit)
                subscriptions = _records_from_response(response)
                subscription_records += len(subscriptions)
                sanitized_subs = [_sanitize_record(s) for s in subscriptions]
                with sub_timer.upsert(len(sanitized_subs)):
                    processed += _store_records(db, platform, "subscription", sanitized_subs, result=sub_timer.store)
                    store_vp_resources(
                        db, "subscription", sanitized_subs, platform=platform, skipped_subscriptions=skipped_subscriptions
                    )
                page_charges: list[dict[str, Any]] = []
                page_contexts: list[dict[str, Any] | None] = []
                for subscription in sanitized_subs:
                    subscription_id = _subscription_id(subscription)
                    if subscription_id is None:
                        continue
                    sub_currency = subscription.get("currency")
                    charge_program = subscription.get("charge_program") or []
                    charge_records = [
                        {**c, "currency": c.get("currency") or sub_currency}
                        for c in charge_program
                        if isinstance(c, dict)
                    ]
                    sanitized_charges = [_sanitize_record(c) for c in charge_records]
                    page_charges.extend(sanitized_charges)
                    page_contexts.extend([{"subscription_external_id": subscription_id}] * len(sanitized_charges))
                    with charge_timer.upsert(len(sanitized_charges)):
                        store_vp_resources(
                            db, "charge", sanitized_charges, platform=platform, subscription_external_id=subscription_id
                        )
                    if progress_callback:
                        progress_callback(
                            f"charge ({subscription_id})",
                            1,
                            len(sanitized_charges),
                            len(sanitized_charges),
                            1,
                        )
                with charge_timer.upsert(0):
                    # SYNC-O-10: los cobros de todas las suscripciones de la pagina van a source_records en un lote.
                    processed += _store_records(
                        db, platform, "charge", page_charges, contexts=page_contexts, result=charge_timer.store
                    )
                if progress_callback:
                    total_records, total_pages = pagination_totals(response)
                    progress_callback("subscription", page, subscription_records, total_records, total_pages)
                if not _has_next_page(response, subscriptions, page, limit):
                    break
                page += 1
            stats["subscription"] = sub_timer.finish()
            stats["charge"] = charge_timer.finish()
            cursor_marks.append(
                ("subscription", sync_cursors.MODE_FULL, subs_started, subscription_records, sub_timer.pages)
            )

            # crm_materialization (legacy) desactivado: se consolida desde las tablas canal.
            if consolidate:
                consolidate_to_centralized(db, ["virtualpos"], raise_on_error=True)
                reconcile_charge_recoveries(db, platform)

            # SYNC-O-08: las marcas avanzan solo si la corrida completa termina bien (misma transaccion).
            for resource_type, mode, started_at, seen_count, requests in cursor_marks:
                sync_cursors.record_success(
                    db, platform, resource_type, mode, started_at=started_at, records_seen=seen_count,
                    requests_made=requests,
                )
            run.status = "completed"
            run.resource_stats = stats
            if skipped_subscriptions:
                run.error_message = f"{len(skipped_subscriptions)} suscripciones omitidas por duplicado activo"
        run.records_processed = processed
        run.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        run.status = "failed"
        run.error_message = _safe_error_message(exc)
        if isinstance(exc, VirtualPOSAPIError):
            # NOK con HTTP 200: antes se leía como página vacía; ahora el run falla con el código del proveedor.
            run.error_message = _safe_error_message(Exception(f"Sync interrumpido por VirtualPOS: {exc}"))
        run.finished_at = datetime.now(UTC)
        db.add(run)
        db.commit()
        raise

    return run
