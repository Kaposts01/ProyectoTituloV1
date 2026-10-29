"""Captura diaria de la glosa de rechazo de VirtualPOS (RJ-06 / SYNC-D-05).

Medido en produccion (2026-10-29): `GET /v3/suscription/{id}/charges?status=rechazado` trae por cobro
`rejected_object {code, message, doc_url}` Y `payment.order.uuid`. Con UNA peticion por suscripcion se obtienen la
glosa y el vinculo cobro -> pago, sin llamar al detalle de cada pago. Notas de la medicion:

- `order.amount` llega como str en los cobros (int en el detalle del pago): se normaliza a Decimal.
- `message` puede traer acentos: se guarda en UTF-8 y se repara el mojibake (UTF-8 leido como latin-1/cp1252).
- `/attempts` puede venir vacio; no se usa. Una suscripcion cancelada devuelve 0 cobros: se deja un MARCADOR
  (`code = ''`) para no reconsultarla cada noche (se reintenta pasados `recheck_days`).

Que hace una corrida (`capture_vp_rejections`)
1. Candidatas: suscripciones con cobros locales `rechazado` SIN detalle capturado (o con solo un marcador viejo),
   las mas recientes primero, topadas por `max_subscriptions` (por defecto `VP_REJECTION_CAPTURE_MAX_SUBSCRIPTIONS`).
2. Por suscripcion: 1 peticion (mas paginas si hace falta), backoff exponencial ante 429/5xx (respeta
   `Retry-After`), y un SAVEPOINT + commit por suscripcion: un fallo no pierde lo ya capturado.
3. Guarda en `payment_rejection_details` (upsert idempotente por fuente/cobro/pago/codigo), con `checked_at`.
4. Registra las glosas nuevas en `rejection_reason_catalog` y emite `reason_changed` (`status_events`).
5. Rehace el vinculo `vp_payments.charge_external_id` y `core_payments.charge_id` con UPDATE explicito idempotente
   (el sync nocturno reescribe `vp_payments.charge_external_id` a NULL; por eso el vinculo se rehace desde los detalles).

El ETL Core (`core_vp_etl`) lee `payment_rejection_details` para llenar `core_charges.latest_rejection_*` y
`core_payments.rejection_*`. Sin datos personales: solo ids externos, codigos, glosa y montos.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import delete, func, literal_column, not_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.virtualpos.client import VirtualPOSAPIError
from app.models.rejection import PaymentRejectionDetail
from app.models.vp import VpCharge
from app.services import status_events
from app.services.virtualpos_sync import _has_next_page, _records_from_response

log = logging.getLogger(__name__)

VP_PLATFORMS = ("virtualpos1", "virtualpos2")
CAPTURE_SOURCE = "api_charges"
REJECTED_LOCAL_STATES = ("rechazado", "rechazada")
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_PAGES = 20
_PAGE_LIMIT = 100
_MAX_CONSECUTIVE_FAILURES = 10
_MAX_REASON_LEN = 1000
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_LONG_DIGITS_RE = re.compile(r"\b\d{12,19}\b")
_ACQUIRER_CODE_RE = re.compile(r"^-2\d{3}$")
_MOJIBAKE_MARKERS = ("Ã", "Â", "â€")

Sleep = Callable[[float], Awaitable[None]]


# -- helpers puros ------------------------------------------------------------------------------------------------

def fix_text(value: Any) -> str | None:
    """Texto de proveedor apto para guardar: UTF-8 reparado, sin control chars ni secuencias tipo PAN, acotado."""
    if value is None:
        return None
    text_value = str(value)
    if any(marker in text_value for marker in _MOJIBAKE_MARKERS):
        for codec in ("latin-1", "cp1252"):
            try:
                repaired = text_value.encode(codec).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
            text_value = repaired
            break
    text_value = _CONTROL_RE.sub(" ", text_value).strip()
    text_value = _LONG_DIGITS_RE.sub("[redacted]", text_value)
    text_value = re.sub(r" {2,}", " ", text_value)
    return text_value[:_MAX_REASON_LEN] or None


def normalize_amount(value: Any) -> Decimal | None:
    """Monto como Decimal(2) desde str o int (el mismo campo llega con distinto tipo segun el endpoint)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or abs(parsed) >= Decimal(10) ** 16:
        return None
    return parsed.quantize(Decimal("0.01"))


def _parse_ts(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for candidate in (raw.replace("Z", "+00:00"), raw[:19].replace(" ", "T"), raw[:10]):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _clean_id(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    cleaned = str(value).strip()
    return cleaned[:255] or None


def parse_rejected_charge(item: Any) -> dict[str, Any] | None:
    """Detalle de rechazo de un cobro de `/suscription/{id}/charges?status=rechazado`, o None si no aplica.

    Devuelve `{charge_external_id, payment_external_id, code, reason, doc_url, acquirer_code, amount, rejected_at}`.
    `code == ''` significa que el cobro esta rechazado pero el proveedor no informo codigo (el codigo `0` es
    «Operacion exitosa», no un rechazo). Si el cobro no esta rechazado (el filtro no se respeto) devuelve None.
    """
    if not isinstance(item, dict):
        return None
    charge_id = _clean_id(item.get("id"))
    if charge_id is None or str(item.get("status") or "").strip().lower() not in REJECTED_LOCAL_STATES:
        return None
    payment = item.get("payment") if isinstance(item.get("payment"), dict) else {}
    order = payment.get("order") if isinstance(payment.get("order"), dict) else {}
    rejected = item.get("rejected_object") if isinstance(item.get("rejected_object"), dict) else {}

    raw_code = rejected.get("code") if rejected.get("code") not in (None, "") else rejected.get("error_code")
    code = str(raw_code).strip() if raw_code not in (None, "") else ""
    if code == "0":
        code = ""
    code = code[:100]
    reason = fix_text(rejected.get("message")) if code else None
    doc_url = fix_text(rejected.get("doc_url")) if code else None
    amount = normalize_amount(order.get("amount"))
    if amount is None:
        amount = normalize_amount(item.get("amount"))
    return {
        "charge_external_id": charge_id,
        "payment_external_id": _clean_id(order.get("uuid")),
        "code": code,
        "reason": reason,
        "doc_url": doc_url,
        "acquirer_code": code if _ACQUIRER_CODE_RE.match(code) else None,
        "amount": amount,
        "rejected_at": _parse_ts(order.get("created_at")) or _parse_ts(item.get("charge_date")),
    }


# -- persistencia -------------------------------------------------------------------------------------------------

def _upsert_detail(db: Session, platform: str, subscription_id: str, parsed: dict[str, Any], now: datetime) -> bool:
    """Upsert idempotente por (fuente, cobro, pago, codigo). Devuelve True si la fila es NUEVA."""
    values = {
        "source": platform,
        "charge_external_id": parsed["charge_external_id"],
        "payment_external_id": parsed["payment_external_id"],
        "subscription_external_id": subscription_id,
        "code": parsed["code"],
        "reason": parsed["reason"],
        "acquirer_code": parsed["acquirer_code"],
        "doc_url": parsed["doc_url"],
        "amount": parsed["amount"],
        "rejected_at": parsed["rejected_at"],
        "captured_at": now,
        "capture_source": CAPTURE_SOURCE,
        "checked_at": now,
    }
    stmt = insert(PaymentRejectionDetail).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            PaymentRejectionDetail.source,
            func.coalesce(PaymentRejectionDetail.charge_external_id, ""),
            func.coalesce(PaymentRejectionDetail.payment_external_id, ""),
            PaymentRejectionDetail.code,
        ],
        set_={
            "subscription_external_id": stmt.excluded.subscription_external_id,
            "reason": stmt.excluded.reason,
            "acquirer_code": stmt.excluded.acquirer_code,
            "doc_url": stmt.excluded.doc_url,
            "amount": stmt.excluded.amount,
            "rejected_at": stmt.excluded.rejected_at,
            "checked_at": stmt.excluded.checked_at,
        },
    ).returning(literal_column("(xmax = 0)"))
    return bool(db.execute(stmt).scalar_one())


def link_payments_to_charges(db: Session, platform: str | None = None) -> dict[str, int]:
    """UPDATE explicito e idempotente del vinculo pago -> cobro desde `payment_rejection_details`.

    - `vp_payments.charge_external_id` (solo donde esta NULL: el sync nocturno lo reescribe a NULL).
    - `core_payments.charge_id` (solo donde esta NULL y el cobro existe en `core_charges`).
    Un pago enlazado a varios cobros usa el rechazo mas reciente. Devuelve las filas actualizadas.
    """
    params: dict[str, Any] = {"platform": platform}
    link_cte = """
        WITH link AS (
            SELECT DISTINCT ON (source, payment_external_id) source, payment_external_id, charge_external_id
            FROM payment_rejection_details
            WHERE payment_external_id IS NOT NULL AND charge_external_id IS NOT NULL
              AND (CAST(:platform AS text) IS NULL OR source = CAST(:platform AS text))
            ORDER BY source, payment_external_id, rejected_at DESC NULLS LAST, captured_at DESC, charge_external_id
        )
    """
    vp = db.execute(
        text(link_cte + """
            UPDATE vp_payments p SET charge_external_id = link.charge_external_id, updated_at = now()
            FROM link
            WHERE p.platform = link.source AND p.external_id = link.payment_external_id
              AND p.charge_external_id IS NULL
        """),
        params,
    ).rowcount
    core = db.execute(
        text(link_cte + """
            UPDATE core_payments cp SET charge_id = cc.id, updated_at = now()
            FROM link JOIN core_charges cc ON cc.source = link.source AND cc.external_id = link.charge_external_id
            WHERE cp.source = link.source AND cp.external_id = link.payment_external_id
              AND cp.charge_id IS NULL
        """),
        params,
    ).rowcount
    return {"vp_payments": vp or 0, "core_payments": core or 0}


def _pending_subscriptions(db: Session, platform: str, recheck_cutoff: datetime) -> list[tuple[str, list[str]]]:
    """[(suscripcion, [cobros rechazados locales sin detalle])], las de cobro mas reciente primero."""
    captured = (
        select(PaymentRejectionDetail.id)
        .where(
            PaymentRejectionDetail.source == VpCharge.platform,
            PaymentRejectionDetail.charge_external_id == VpCharge.external_id,
            (PaymentRejectionDetail.code != "") | (PaymentRejectionDetail.checked_at >= recheck_cutoff),
        )
        .exists()
    )
    rows = db.execute(
        select(VpCharge.subscription_external_id, VpCharge.external_id, VpCharge.charge_date).where(
            VpCharge.platform == platform,
            func.lower(VpCharge.status).in_(REJECTED_LOCAL_STATES),
            VpCharge.subscription_external_id.is_not(None),
            not_(captured),
        )
    ).all()
    by_sub: dict[str, list[str]] = defaultdict(list)
    latest: dict[str, str] = {}
    for sub, charge, charge_date in rows:
        by_sub[sub].append(charge)
        latest[sub] = max(latest.get(sub, ""), str(charge_date or ""))
    ordered = sorted(by_sub, key=lambda s: (latest[s], s), reverse=True)
    return [(sub, by_sub[sub]) for sub in ordered]


# -- lectura con backoff ------------------------------------------------------------------------------------------

class _RateLimited(Exception):
    """429 persistente tras agotar los reintentos (los 5xx persistentes solo fallan la suscripcion)."""

    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After") if response is not None else None
    try:
        return max(0.0, float(raw)) if raw is not None else None
    except ValueError:
        return None


async def _fetch_page(
    client: Any, subscription_id: str, page: int, *, max_retries: int, backoff_base: float, sleep: Sleep, stats: dict
) -> Any:
    for attempt in range(max_retries + 1):
        try:
            return await client.list_charges(subscription_id, page=page, limit=_PAGE_LIMIT, status="rechazado")
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status not in _RETRYABLE_STATUS:
                raise
            if attempt == max_retries:
                if status == 429:
                    raise _RateLimited(status) from exc  # el proveedor nos limita: se corta la corrida
                raise  # 5xx persistente de esta suscripcion: falla solo ella
            wait = _retry_after(exc.response)
            wait = min(wait if wait is not None else backoff_base * (2**attempt), 60.0)
            stats["retries"] += 1
            await sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover


async def _fetch_rejected_charges(client: Any, subscription_id: str, **kw: Any) -> list[dict]:
    items: list[dict] = []
    page = 1
    while True:
        response = await _fetch_page(client, subscription_id, page, **kw)
        records = _records_from_response(response)
        items.extend(records)
        if page >= _MAX_PAGES or not _has_next_page(response, records, page, _PAGE_LIMIT):
            return items
        page += 1


# -- corrida ------------------------------------------------------------------------------------------------------

async def capture_vp_rejections(
    db: Session,
    platform: str,
    client: Any,
    *,
    max_subscriptions: int | None = None,
    pause_seconds: float | None = None,
    recheck_days: int | None = None,
    max_retries: int | None = None,
    backoff_base: float = 1.0,
    sleep: Sleep | None = None,
) -> dict[str, Any]:
    """Captura la glosa de las suscripciones con cobros rechazados sin detalle. Ver el docstring del modulo."""
    if platform not in VP_PLATFORMS:
        raise ValueError(f"Plataforma VirtualPOS desconocida: {platform!r}")
    cap = settings.vp_rejection_capture_max_subscriptions if max_subscriptions is None else max_subscriptions
    pause = settings.vp_rejection_capture_pause_seconds if pause_seconds is None else pause_seconds
    recheck = settings.vp_rejection_capture_recheck_days if recheck_days is None else recheck_days
    retries = settings.vp_rejection_capture_max_retries if max_retries is None else max_retries
    sleeper: Sleep = sleep or asyncio.sleep

    stats: dict[str, Any] = {
        "platform": platform, "subscriptions_pending": 0, "subscriptions_checked": 0, "subscriptions_failed": 0,
        "details_new": 0, "details_updated": 0, "markers": 0, "reasons_new": 0, "payments_linked": 0,
        "retries": 0, "capped": False, "aborted": None,
    }
    cutoff = datetime.now(UTC) - timedelta(days=recheck)
    pending = _pending_subscriptions(db, platform, cutoff)
    stats["subscriptions_pending"] = len(pending)
    batch = pending[: max(cap, 0)]
    stats["capped"] = len(pending) > len(batch)

    consecutive_failures = 0
    for index, (subscription_id, local_charges) in enumerate(batch):
        if index and pause > 0:
            await sleeper(pause)
        try:
            items = await _fetch_rejected_charges(
                client, subscription_id, max_retries=retries, backoff_base=backoff_base, sleep=sleeper, stats=stats
            )
        except _RateLimited as exc:
            stats["subscriptions_failed"] += 1
            stats["aborted"] = "rate_limited"
            log.warning("VP rechazos %s: HTTP %s persistente; se corta la corrida (%d suscripciones listas)",
                        platform, exc.status, stats["subscriptions_checked"])
            break
        except (httpx.HTTPError, VirtualPOSAPIError, ValueError, KeyError) as exc:
            stats["subscriptions_failed"] += 1
            consecutive_failures += 1
            log.warning("VP rechazos %s: fallo la suscripcion (%s)", platform, type(exc).__name__)
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                stats["aborted"] = "too_many_failures"
                break
            continue
        consecutive_failures = 0

        parsed_items = [p for p in (parse_rejected_charge(i) for i in items) if p is not None]
        seen = {p["charge_external_id"] for p in parsed_items}
        for charge_id in local_charges:  # rechazado en local pero ausente en la API: marcador, para no reconsultar
            if charge_id not in seen:
                parsed_items.append({
                    "charge_external_id": charge_id, "payment_external_id": None, "code": "", "reason": None,
                    "doc_url": None, "acquirer_code": None, "amount": None, "rejected_at": None,
                })
                stats["markers"] += 1
        try:
            now = datetime.now(UTC)
            new_entries: list[dict] = []
            with db.begin_nested():
                for parsed in parsed_items:
                    if parsed["code"]:  # la glosa real reemplaza al marcador «consultado sin glosa» del cobro
                        db.execute(
                            delete(PaymentRejectionDetail).where(
                                PaymentRejectionDetail.source == platform,
                                PaymentRejectionDetail.charge_external_id == parsed["charge_external_id"],
                                PaymentRejectionDetail.code == "",
                            )
                        )
                    if _upsert_detail(db, platform, subscription_id, parsed, now):
                        stats["details_new"] += 1
                        if parsed["code"]:
                            new_entries.append({
                                "source": platform, "external_id": parsed["charge_external_id"],
                                "subscription_external_id": subscription_id, "amount": parsed["amount"],
                                "code": parsed["code"], "reason": parsed["reason"],
                            })
                    else:
                        stats["details_updated"] += 1
                stats["reasons_new"] += status_events.emit_reason_events(db, new_entries)
            db.commit()
        except Exception as exc:  # noqa: BLE001 - un fallo de BD en una suscripcion no pierde las ya guardadas
            db.rollback()
            stats["subscriptions_failed"] += 1
            log.warning("VP rechazos %s: no se guardo la suscripcion (%s)", platform, type(exc).__name__)
            continue
        stats["subscriptions_checked"] += 1

    try:
        linked = link_payments_to_charges(db, platform)
        db.commit()
        stats["payments_linked"] = linked["vp_payments"] + linked["core_payments"]
    except Exception as exc:  # noqa: BLE001 - el vinculo se rehace en la proxima corrida y en el ETL Core
        db.rollback()
        log.warning("VP rechazos %s: no se pudo rehacer el vinculo pago-cobro (%s)", platform, type(exc).__name__)
    log.info("VP rechazos %s: %s", platform, {k: v for k, v in stats.items() if k != "platform"})
    return stats


__all__ = [
    "capture_vp_rejections", "fix_text", "link_payments_to_charges", "normalize_amount", "parse_rejected_charge",
]
