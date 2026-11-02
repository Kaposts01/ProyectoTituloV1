"""Conversion de los valores de VirtualPOS a columnas tipadas (VP-PAR-07 / VP-PAR-13).

La API entrega montos como numero o texto (`9990`, `"6990"`, `""` cuando el pago esta pendiente) y fechas como texto
sin zona horaria (`yyyy-mm-dd hh:mm:ss` en suscripciones y pagos, `yyyy-mm-dd` en cobros). Estas funciones son la
version Python de las conversiones SQL de las migraciones `20261102_0060` y `20261102_0061`: lo que no se puede
convertir queda en `None` (nunca se inventa un valor) y el `raw_payload` conserva el original.

Fechas: se guardan como `timestamp` SIN zona (la hora tal como la entrega el proveedor). Pasarlas a `timestamptz`
exige decidir en que zona informa VirtualPOS (Chile o UTC); esa decision no esta tomada.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

_AMOUNT_RE = re.compile(r"^\s*-?\d+(\.\d+)?\s*$")
_DATE_RE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})")
_TS_RE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?)?")
_LAST4_RE = re.compile(r"^\d{4}$")


def parse_amount(value: Any) -> Decimal | None:
    """Monto como Decimal; None si falta, viene vacio o no es un numero simple (`-?digitos[.digitos]`)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value)) if value == value and value not in (float("inf"), float("-inf")) else None
    text = str(value)
    if not _AMOUNT_RE.match(text):
        return None
    try:
        return Decimal(text.strip())
    except InvalidOperation:
        return None


def parse_timestamp(value: Any) -> datetime | None:
    """Fecha y hora sin zona; acepta `yyyy-mm-dd[ hh:mm[:ss[.ffffff]]]` (tambien con `T`). Lo demas, None.

    Un sufijo de zona (`Z`, `+00:00`) se ignora: se conserva la hora de pared que trae el texto, igual que el
    `::timestamp` de Postgres en la migracion.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)  # noqa: DTZ001 - hora de pared sin zona, a proposito
    match = _TS_RE.match(str(value))
    if not match:
        return None
    year, month, day, hour, minute, second, fraction = match.groups()
    try:
        return datetime(  # noqa: DTZ001 - hora de pared sin zona, a proposito
            int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0),
            int((fraction or "0").ljust(6, "0")),
        )
    except ValueError:
        return None


def parse_date(value: Any) -> date | None:
    """Solo la fecha (`yyyy-mm-dd` al inicio del texto); None si no es una fecha valida."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    match = _DATE_RE.match(str(value))
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def timestamp_text(value: Any) -> str | None:
    """Texto canonico (`yyyy-mm-dd hh:mm:ss`) de una fecha y hora, o None si no se puede convertir.

    Los extractores del sync entregan las fechas como texto canonico (Postgres lo convierte al insertar) para que
    el desempate de `channel_store.upsert_channel`, que compara `suscription_date` como texto, siga funcionando.
    """
    parsed = parse_timestamp(value)
    return parsed.isoformat(sep=" ") if parsed is not None else None


def date_text(value: Any) -> str | None:
    parsed = parse_date(value)
    return parsed.isoformat() if parsed is not None else None


def first_amount(*values: Any) -> Decimal | None:
    """Primer monto convertible (un `0` cuenta: no se usa `or`)."""
    for value in values:
        parsed = parse_amount(value)
        if parsed is not None:
            return parsed
    return None


def first_timestamp_text(*values: Any) -> str | None:
    for value in values:
        if (parsed := timestamp_text(value)) is not None:
            return parsed
    return None


def first_date_text(*values: Any) -> str | None:
    for value in values:
        if (parsed := date_text(value)) is not None:
            return parsed
    return None


def last4(value: Any) -> str | None:
    text = str(value).strip() if value is not None and not isinstance(value, (bool, dict, list)) else ""
    return text if _LAST4_RE.match(text) else None


def text_or_none(value: Any, max_len: int) -> str | None:
    if value is None or isinstance(value, (bool, dict, list)):
        return None
    text = str(value).strip()
    return text[:max_len] if text else None


def as_legacy_text(value: Any) -> str | None:
    """Texto equivalente al que guardaban las columnas `vp_*` antes de tiparlas (para las tablas `crm` en texto).

    Montos sin ceros de mas (`15000`, `9990.5`); fechas `yyyy-mm-dd`; fecha y hora `yyyy-mm-dd hh:mm:ss`, salvo la
    medianoche exacta, que vuelve como `yyyy-mm-dd` (asi llegaban los datos cargados solo con fecha).
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        normalized = value.normalize()
        return format(normalized if normalized != 0 else Decimal(0), "f")
    if isinstance(value, datetime):
        if value.time() == datetime.min.time():
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _first_deposit(order: dict) -> dict:
    deposits = order.get("deposits")
    if isinstance(deposits, list) and deposits and isinstance(deposits[0], dict):
        return deposits[0]
    return {}


def payment_order(payload: dict) -> dict:
    """`order` del pago: en `GET /payments` viene arriba; en el detalle, dentro de `payment`."""
    order = payload.get("order")
    if isinstance(order, dict):
        return order
    inner = payload.get("payment")
    if isinstance(inner, dict) and isinstance(inner.get("order"), dict):
        return inner["order"]
    return {}


def payment_typed_fields(payload: dict) -> dict[str, Any]:
    """Columnas de VP-PAR-07 en `vp_payments`, desde el payload del pago.

    `authorized_at` (`order.authorized_at`, vacio si no esta pagado), comision, abono y fecha de abono del primer
    tramo de `order.deposits` (asi cuadra con el reporte PAT en la auditoria del 2026-10-29) y el RUT del cliente que
    usa el ETL Core para vincular el pago a su suscripcion.
    """
    order = payment_order(payload)
    deposit = _first_deposit(order)
    client = payload.get("client") if isinstance(payload.get("client"), dict) else {}
    return {
        "client_social_id": text_or_none(client.get("social_id"), 50),
        "authorized_at": timestamp_text(order.get("authorized_at")),
        "processing_fee": parse_amount(deposit.get("processing_fee")),
        "payout_amount": parse_amount(deposit.get("payout_amount")),
        "payout_date": date_text(deposit.get("payout_date")),
    }


def subscription_typed_fields(payload: dict) -> dict[str, Any]:
    """Columnas de VP-PAR-07 en `vp_subscriptions`: tarjeta vigente (`payment_method`), alias POS y origen.

    El `seller_id` (Codigo de vendedor) NO se promueve: tiene forma de RUT y el reporte solo guarda su HMAC; guardarlo
    en claro en una columna es una decision de privacidad pendiente.
    """
    method = payload.get("payment_method") if isinstance(payload.get("payment_method"), dict) else {}
    return {
        "card_type": text_or_none(method.get("card_type"), 20),
        "card_brand": text_or_none(method.get("brand"), 50),
        "card_last4": last4(method.get("last4CardDigit")),
        "terminal_pos": text_or_none(payload.get("terminal_pos"), 255),
        "origin": text_or_none(payload.get("origin"), 100),
    }
