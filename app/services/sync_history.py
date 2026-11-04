"""SYNC-O-13 / SYNC-D-11: carga historica reanudable por ventanas de fecha, sobre `sync_cursors`.

Un plan es una fila de `sync_cursors` por ventana: `mode='history'`, `window_start`/`window_end` (fechas inclusive),
`status` (pending -> running -> done | failed), `page` (proxima pagina a leer: la reanudacion sigue en la misma pagina)
y contadores de registros y peticiones. Las marcas de agua de la sync diaria (filas con `window_start` NULL) no se tocan.

Ventanas por canal (research_sync_opt.md, SYNC-O-13):
  * VirtualPOS (cada cuenta): pagos por semana (`created_from`/`created_to`).
  * Toku: transacciones por mes calendario (`start_date`/`end_date`).
  * Payku: transacciones cada 30 dias (`date_init`/`date_end`, el endpoint que sin filtro hace timeout). Solo se agregan
    las transacciones que aun no estan en `payku_transactions`: la sync diaria las trae embebidas en la suscripcion
    (con su `subscription_id`) y esta lectura no debe pisarlas.

Topes: `max_requests` por ejecucion, pausa entre peticiones y franja horaria permitida (hora de Chile). Al llegar a un
tope la ventana queda `pending` con su pagina guardada; la siguiente ejecucion con `--resume` sigue desde ahi. Si el
proveedor ignora el filtro de fecha (registros fuera de la ventana), la ventana queda `failed` y la ejecucion se
detiene: leer "por ventana" seria leer todo el historico una y otra vez.

Nunca se guardan datos personales en `sync_cursors`: solo fechas, paginas, conteos y el tipo de error.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.payku_channel import PaykuTransaction
from app.models.sync_cursor import SyncCursor
from app.services.payload_sanitization import sanitize_payload
from app.services.sync_window import ReadWindow, records_outside

logger = logging.getLogger(__name__)

MODE_HISTORY = "history"
CHILE_TZ = ZoneInfo("America/Santiago")
LOCK_OWNER = "sync_history"
LOCK_MINUTES = 60
_MAX_PAGES_PER_WINDOW = 2_000

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


# ── Plan de ventanas ───────────────────────────────────────────────────────────────────────────────────────


def _weeks(start: date, end: date) -> Iterable[tuple[date, date]]:
    current = start
    while current <= end:
        last = min(current + timedelta(days=6), end)
        yield current, last
        current = last + timedelta(days=1)


def _days30(start: date, end: date) -> Iterable[tuple[date, date]]:
    current = start
    while current <= end:
        last = min(current + timedelta(days=29), end)
        yield current, last
        current = last + timedelta(days=1)


def _months(start: date, end: date) -> Iterable[tuple[date, date]]:
    current = start
    while current <= end:
        month_end = date(current.year, current.month, calendar.monthrange(current.year, current.month)[1])
        last = min(month_end, end)
        yield current, last
        current = last + timedelta(days=1)


@dataclass(frozen=True)
class ChannelSpec:
    """Como leer el historico de un canal. Las funciones reciben el cliente ya abierto."""

    resource: str
    splitter: Callable[[date, date], Iterable[tuple[date, date]]]
    read_page: Callable[[Any, date, date, int], Awaitable[Any]]
    records: Callable[[Any], list[dict[str, Any]]]
    has_next: Callable[[Any, list[dict[str, Any]], int], bool]
    store: Callable[[Session, list[dict[str, Any]]], int]
    date_fields: tuple[str, ...]
    client_factory: Callable[[], Any]


def _vp_spec(platform: str) -> ChannelSpec:
    from app.integrations.virtualpos.client import VirtualPOSClient
    from app.services.channel_store import store_vp_resources
    from app.services.virtualpos_sync import (
        _has_next_page,
        _records_from_response,
        _store_records,
    )

    limit = 100

    def store(db: Session, records: list[dict[str, Any]]) -> int:
        sanitized = [sanitize_payload(r) for r in records]
        written = _store_records(db, platform, "payment", sanitized)
        store_vp_resources(db, "payment", sanitized, platform=platform)
        return written

    return ChannelSpec(
        resource="payment",
        splitter=_weeks,
        read_page=lambda client, start, end, page: client.list_payments(
            page=page, limit=limit, created_from=start.isoformat(), created_to=end.isoformat()
        ),
        records=_records_from_response,
        has_next=lambda response, records, page: _has_next_page(response, records, page, limit),
        store=store,
        date_fields=("order.created_at", "created_at"),
        client_factory=lambda: VirtualPOSClient(platform),
    )


def _toku_spec() -> ChannelSpec:
    from app.integrations.toku.client import TokuClient
    from app.services.channel_store import store_toku_resources
    from app.services.read_only_provider_sync import (
        has_next_page,
        records_from_response,
        store_records,
    )

    page_size = 100

    def store(db: Session, records: list[dict[str, Any]]) -> int:
        written = store_records(db, "toku", "transaction", records)
        store_toku_resources(db, "transaction", records)
        return written

    return ChannelSpec(
        resource="transaction",
        splitter=_months,
        read_page=lambda client, start, end, page: client.list_transactions(
            page=page, page_size=page_size, start_date=start.isoformat(), end_date=end.isoformat()
        ),
        records=records_from_response,
        has_next=lambda response, records, page: has_next_page(response, records, page, page_size),
        store=store,
        date_fields=("transaction_date", "initialization_date"),
        client_factory=TokuClient,
    )


def _payku_spec() -> ChannelSpec:
    from app.integrations.payku.client import PaykuClient
    from app.services.channel_store import (
        extract_payku_transaction,
        store_payku_resources,
    )
    from app.services.payku_sync import _has_more, _records_from
    from app.services.read_only_provider_sync import store_records

    per_page = 50

    def store(db: Session, records: list[dict[str, Any]]) -> int:
        sanitized = [sanitize_payload(r) for r in records]
        ids = {extract_payku_transaction(r).get("external_id"): r for r in sanitized}
        ids.pop(None, None)
        known = set(db.scalars(select(PaykuTransaction.external_id).where(PaykuTransaction.external_id.in_(ids))))
        new = [record for external_id, record in ids.items() if external_id not in known]
        if not new:
            return 0
        written = store_records(db, "payku", "transaction", new)
        store_payku_resources(db, "transaction", new)
        return written

    return ChannelSpec(
        resource="transaction",
        splitter=_days30,
        read_page=lambda client, start, end, page: client.list_transactions(
            date_init=start.isoformat(), date_end=end.isoformat(), page=page, per_page=per_page
        ),
        records=_records_from,
        has_next=lambda _response, records, _page: _has_more(records, per_page),
        store=store,
        date_fields=("created_at", "fecha"),
        client_factory=PaykuClient,
    )


CHANNELS = ("virtualpos1", "virtualpos2", "toku", "payku")


def channel_spec(channel: str) -> ChannelSpec:
    if channel in ("virtualpos1", "virtualpos2"):
        return _vp_spec(channel)
    if channel == "toku":
        return _toku_spec()
    if channel == "payku":
        return _payku_spec()
    raise ValueError(f"Canal sin carga historica: {channel!r}")


_SPLITTERS = {"virtualpos1": _weeks, "virtualpos2": _weeks, "toku": _months, "payku": _days30}
_RESOURCES = {"virtualpos1": "payment", "virtualpos2": "payment", "toku": "transaction", "payku": "transaction"}


def plan_windows(channel: str, start: date, end: date) -> list[tuple[date, date]]:
    """Ventanas del canal entre `start` y `end` (inclusive). Puro: no toca la base ni el proveedor."""
    if channel not in _SPLITTERS:
        raise ValueError(f"Canal sin carga historica: {channel!r}")
    if end < start:
        raise ValueError("La fecha final es anterior a la inicial.")
    return list(_SPLITTERS[channel](start, end))


def save_plan(db: Session, channel: str, start: date, end: date) -> list[SyncCursor]:
    """Registra las ventanas que falten (las existentes conservan su estado y pagina) y devuelve el plan completo."""
    resource = _RESOURCES[channel]
    now = datetime.now(UTC)
    for window_start, window_end in plan_windows(channel, start, end):
        db.execute(
            insert(SyncCursor)
            .values(source=channel, resource=resource, mode=MODE_HISTORY, window_start=window_start,
                    window_end=window_end, status=STATUS_PENDING, page=1, updated_at=now)
            .on_conflict_do_nothing(constraint="uq_sync_cursors_key")
        )
    db.commit()
    return load_plan(db, channel, start, end)


def load_plan(db: Session, channel: str, start: date | None = None, end: date | None = None) -> list[SyncCursor]:
    query = select(SyncCursor).where(
        SyncCursor.source == channel,
        SyncCursor.resource == _RESOURCES[channel],
        SyncCursor.mode == MODE_HISTORY,
        SyncCursor.window_start.isnot(None),
    )
    if start is not None:
        query = query.where(SyncCursor.window_end >= start)
    if end is not None:
        query = query.where(SyncCursor.window_start <= end)
    return list(db.scalars(query.order_by(SyncCursor.window_start)))


# ── Ejecucion ──────────────────────────────────────────────────────────────────────────────────────────────


def parse_hours(value: str | None) -> tuple[int, int] | None:
    """`"22-6"` -> (22, 6): franja permitida [22:00, 06:00) en hora de Chile (puede cruzar la medianoche)."""
    if not value:
        return None
    first, _, last = value.partition("-")
    start, stop = int(first), int(last)
    if not (0 <= start <= 23 and 0 <= stop <= 24) or start == stop:
        raise ValueError("Franja horaria invalida; use HH-HH, p. ej. 22-6.")
    return start, stop


def within_hours(hours: tuple[int, int] | None, now: datetime) -> bool:
    if hours is None:
        return True
    hour = now.astimezone(CHILE_TZ).hour
    start, stop = hours
    return start <= hour < stop if start < stop else hour >= start or hour < stop


@dataclass
class RunSummary:
    windows_done: int = 0
    windows_failed: int = 0
    requests: int = 0
    records: int = 0
    stopped_reason: str | None = None
    windows: list[str] = field(default_factory=list)


def _claimable(cursor: SyncCursor, now: datetime) -> bool:
    if cursor.status == STATUS_DONE:
        return False
    if cursor.locked_by and cursor.locked_until is not None:
        until = cursor.locked_until if cursor.locked_until.tzinfo else cursor.locked_until.replace(tzinfo=UTC)
        if until > now and cursor.status == STATUS_RUNNING:
            return False  # otra ejecucion la tiene tomada
    return True


async def run_plan(
    db: Session,
    channel: str,
    *,
    start: date | None = None,
    end: date | None = None,
    spec: ChannelSpec | None = None,
    max_requests: int = 200,
    pause_seconds: float = 1.0,
    allowed_hours: tuple[int, int] | None = None,
    retry_failed: bool = False,
    now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> RunSummary:
    """Lee las ventanas pendientes del plan, en orden, hasta terminar o llegar a un tope. Reanudable.

    `retry_failed=True` vuelve a intentar las ventanas `failed` (por defecto se saltan: hay que revisarlas).
    """
    spec = spec or channel_spec(channel)
    summary = RunSummary()
    plan = [
        c for c in load_plan(db, channel, start, end)
        if c.status != STATUS_DONE and (retry_failed or c.status != STATUS_FAILED)
    ]
    if not plan:
        summary.stopped_reason = "sin ventanas pendientes"
        return summary
    async with spec.client_factory() as client:
        for cursor in plan:
            now = now_fn()
            if not _claimable(cursor, now):
                continue
            label = f"{cursor.window_start}..{cursor.window_end}"
            cursor.status = STATUS_RUNNING
            cursor.locked_by = LOCK_OWNER
            cursor.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            cursor.last_error = None
            cursor.page = cursor.page or 1
            db.commit()
            window = ReadWindow(
                start=datetime.combine(cursor.window_start, time.min, tzinfo=UTC),
                end=datetime.combine(cursor.window_end, time.max, tzinfo=UTC),
            )
            finished = False
            try:
                while cursor.page <= _MAX_PAGES_PER_WINDOW:
                    if summary.requests >= max_requests:
                        summary.stopped_reason = f"tope de {max_requests} peticiones"
                        break
                    if not within_hours(allowed_hours, now_fn()):
                        summary.stopped_reason = "fuera de la franja horaria permitida"
                        break
                    if summary.requests:
                        await sleep(pause_seconds)
                    response = await spec.read_page(client, cursor.window_start, cursor.window_end, cursor.page)
                    summary.requests += 1
                    cursor.requests_made = (cursor.requests_made or 0) + 1
                    records = spec.records(response)
                    if records_outside(records, window, spec.date_fields):
                        raise FilterIgnoredError(label)
                    if records:
                        spec.store(db, records)
                    cursor.records_seen = (cursor.records_seen or 0) + len(records)
                    summary.records += len(records)
                    if not spec.has_next(response, records, cursor.page):
                        finished = True
                        break
                    cursor.page += 1
                    cursor.updated_at = now_fn()
                    db.commit()  # avance de pagina persistido: la reanudacion sigue aqui
                else:
                    raise RuntimeError("limite de paginas por ventana")
            except Exception as exc:  # noqa: BLE001 - se registra el tipo y se detiene (reanudable)
                db.rollback()
                cursor = db.get(SyncCursor, cursor.id)
                cursor.status = STATUS_FAILED
                cursor.last_error = type(exc).__name__ if not isinstance(exc, FilterIgnoredError) else (
                    "filtro de fecha ignorado por el proveedor"
                )
                cursor.locked_by = None
                cursor.locked_until = None
                cursor.updated_at = now_fn()
                db.commit()
                summary.windows_failed += 1
                summary.windows.append(f"{label}: failed")
                summary.stopped_reason = f"ventana {label} fallida ({cursor.last_error})"
                logger.warning("sync_history %s: ventana %s fallida (%s)", channel, label, cursor.last_error)
                return summary
            cursor.locked_by = None
            cursor.locked_until = None
            cursor.updated_at = now_fn()
            if finished:
                cursor.status = STATUS_DONE
                cursor.last_success_at = now_fn()
                summary.windows_done += 1
                summary.windows.append(f"{label}: done")
            else:
                cursor.status = STATUS_PENDING  # tope alcanzado: queda para la reanudacion, con su pagina
                summary.windows.append(f"{label}: pending (pagina {cursor.page})")
            db.commit()
            if not finished:
                return summary
    return summary


class FilterIgnoredError(Exception):
    """El proveedor devolvio registros fuera de la ventana pedida."""
