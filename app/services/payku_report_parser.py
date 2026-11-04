"""Parser de reportes .xlsx descargados del portal de Payku (PK-PAR-10, d115 opcion b). Sin base de datos.

No hay documentacion oficial del formato en `docs/integrations/payku/`. Las firmas salen de los encabezados medidos en la
auditoria del 2026-10-29 (`docs/planning/auditoria-2026-10-29/parity_payku.md`, seccion 1) y se VALIDAN al abrir: un
archivo con encabezados distintos se rechaza con los NOMBRES de las columnas faltantes (nunca con valores de filas).

Hojas reconocidas (por FIRMA de columnas normalizadas: sin tildes, casefold, espacios colapsados; nunca por nombre):

* `data_transacciones` (archivo `Payku_dataTransacciones`, hoja «Export»): Transaccion, Fecha de Transaccion, Monto,
  Comision, Monto Final; opcionales Proveedor, Tipo de Pago, Orden, Concepto.
* `consolidado` (hoja «Transacciones» de `consolidado_<anio>`): Identificador/vaucher, Fecha, Monto, Comision, Monto
  Final; opcionales Concepto, Orden, Liquidacion, Medio de pago, Debito/Credito.
* `liquidaciones` (hoja «Liquidaciones» del consolidado): Liquidacion, Monto, Estatus, Fecha Deposito.
* `suscripciones` (archivo `Payku_datasubscripciones`): Suscripcion ID, Estatus, Proxima Fecha Cobro.
Hojas sin firma (Monedero, Retiros) se ignoran y se informan por nombre de tipo, no de contenido.

Datos personales: Nombre/Telefono/Email Origen, Email, Nombre, Telefono, 4 ultimos digitos y Orden Externa NUNCA se
leen (lectura por posicion de las columnas necesarias). Del Concepto solo se conserva si es cuota («Cobro: # n») y su
numero; el texto libre (campanas, rifas) no se guarda. Filas invalidas se cuentan por motivo sin valores.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from app.services.toku_report_parser import (
    ReportFormatError,
    UnsupportedReportError,
    norm_header,
    parse_amount,
    parse_date,
    parse_datetime,
)

__all__ = [
    "SIGNATURES",
    "ParsedSheet",
    "PaykuSettlementRecord",
    "PaykuSubscriptionRecord",
    "PaykuTransactionRecord",
    "ReportFormatError",
    "UnsupportedReportError",
    "parse_report",
]

HEADER_SEARCH_ROWS = 10
_FUZZY_MIN_OVERLAP = 0.6

SIGNATURES: dict[str, tuple[str, ...]] = {
    "data_transacciones": ("transaccion", "fecha de transaccion", "monto", "comision", "monto final"),
    "consolidado": ("identificador/vaucher", "fecha", "monto", "comision", "monto final"),
    "liquidaciones": ("liquidacion", "monto", "estatus", "fecha deposito"),
    "suscripciones": ("suscripcion id", "estatus", "proxima fecha cobro"),
}
OPTIONAL_COLUMNS: dict[str, tuple[str, ...]] = {
    "data_transacciones": ("proveedor", "tipo de pago", "orden", "concepto"),
    "consolidado": ("concepto", "orden", "liquidacion", "medio de pago", "debito/credito"),
    "liquidaciones": (),
    "suscripciones": (),
}
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "identificador/vaucher": ("identificador/voucher", "identificador", "vaucher", "voucher"),
    "fecha deposito": ("fecha de deposito",),
    "proxima fecha cobro": ("proxima fecha de cobro",),
    "suscripcion id": ("id suscripcion",),
    "debito/credito": ("debito / credito",),
}
# Columnas personales: nunca se leen (se listan para documentar y para las pruebas).
PERSONAL_COLUMNS = frozenset({
    "nombre origen", "telefono origen", "email origen", "email", "nombre", "telefono", "4 ultimos digitos",
    "orden externa",
})
SHEET_KIND = {"data_transacciones": "transacciones", "consolidado": "transacciones",
              "liquidaciones": "liquidaciones", "suscripciones": "suscripciones"}

_INSTALLMENT_RE = re.compile(r"cobro\s*:?\s*#\s*(\d{1,4})", re.IGNORECASE)
_DMY_DASH_RE = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})(.*)$")
_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


@dataclass(frozen=True)
class PaykuTransactionRecord:
    row_key: str
    transaction_external_id: str
    order_ref: str | None
    occurred_at: datetime | None
    is_installment: bool
    installment_number: int | None
    amount: Decimal | None
    commission: Decimal | None
    net_amount: Decimal | None
    payment_provider: str | None
    payment_type: str | None
    payment_method: str | None
    settlement_external_id: str | None
    source_layout: str


@dataclass(frozen=True)
class PaykuSettlementRecord:
    settlement_external_id: str
    amount: Decimal | None
    status: str | None
    deposit_date: date | None


@dataclass(frozen=True)
class PaykuSubscriptionRecord:
    subscription_external_id: str
    status: str | None
    next_charge_date: date | None


@dataclass
class ParsedSheet:
    layout: str
    records: list[Any]
    rows_total: int = 0
    rows_skipped: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)
    extra_columns: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return SHEET_KIND[self.layout]


# ---- valores ----------------------------------------------------------------------------------------------------------


def _text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _ident(value: Any) -> str | None:
    """Identificador de Payku (voucher, orden, liquidacion, suscripcion): solo si tiene forma de ID (sin espacios)."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = _text(value, 64)
    return text if text and _ID_RE.match(text) else None


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, str):
        m = _DMY_DASH_RE.match(value.strip())
        if m:
            value = f"{m.group(1)}/{m.group(2)}/{m.group(3)}{m.group(4)}"
    return parse_datetime(value)


def _date(value: Any) -> date | None:
    if isinstance(value, str):
        m = _DMY_DASH_RE.match(value.strip())
        if m:
            value = f"{m.group(1)}/{m.group(2)}/{m.group(3)}{m.group(4)}"
    return parse_date(value)


def installment_from_concept(value: Any) -> int | None:
    """Numero de cuota de un concepto «Cobro: # n» (None si no es cuota)."""
    if value is None:
        return None
    m = _INSTALLMENT_RE.search(str(value))
    return int(m.group(1)) if m else None


def row_key(voucher: str, order_ref: str | None, occurred_at: datetime | None, amount: Decimal | None) -> str:
    raw = "|".join([voucher, order_ref or "", occurred_at.isoformat() if occurred_at else "", str(amount or "")])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---- encabezados ------------------------------------------------------------------------------------------------------


def _column_index(names: list[str], col: str) -> int | None:
    for candidate in (col, *COLUMN_ALIASES.get(col, ())):
        if candidate in names:
            return names.index(candidate)
    return None


def _match(names: list[str]) -> tuple[str | None, str | None, list[str]]:
    """(layout completo, layout probable, faltantes del probable)."""
    best: tuple[float, str | None, list[str]] = (0.0, None, [])
    for layout, signature in SIGNATURES.items():
        missing = [col for col in signature if _column_index(names, col) is None]
        if not missing:
            return layout, None, []
        overlap = 1 - len(missing) / len(signature)
        if overlap > best[0]:
            best = (overlap, layout, missing)
    if best[0] >= _FUZZY_MIN_OVERLAP:
        return None, best[1], best[2]
    return None, None, []


def _find_header(ws) -> tuple[int, list[str]] | tuple[None, list[str]]:
    rows = ws.iter_rows(min_row=1, max_row=HEADER_SEARCH_ROWS, values_only=True)
    first: list[str] = []
    for idx, row in enumerate(rows, start=1):
        names = [norm_header(v) for v in row]
        if not first and any(names):
            first = names
        layout, probable, _missing = _match(names)
        if layout or probable:
            return idx, names
    return None, first


# ---- constructores ----------------------------------------------------------------------------------------------------


class _Skip(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _get(row: tuple, pos: dict[str, int | None], col: str) -> Any:
    idx = pos.get(col)
    return row[idx] if idx is not None and idx < len(row) else None


def _amount(row: tuple, pos: dict[str, int | None], col: str, required: bool = False) -> Decimal | None:
    raw = _get(row, pos, col)
    value = parse_amount(raw)
    if value is None and (required or (raw not in (None, "") and str(raw).strip())):
        raise _Skip("invalid_amount")
    return value


def _build_transaction(row: tuple, pos: dict[str, int | None], layout: str) -> PaykuTransactionRecord:
    id_col = "transaccion" if layout == "data_transacciones" else "identificador/vaucher"
    date_col = "fecha de transaccion" if layout == "data_transacciones" else "fecha"
    voucher = _ident(_get(row, pos, id_col))
    if voucher is None:
        raise _Skip("invalid_id")
    occurred = _datetime(_get(row, pos, date_col))
    if occurred is None:
        raise _Skip("invalid_date")
    amount = _amount(row, pos, "monto", required=True)
    order_ref = _ident(_get(row, pos, "orden"))
    installment = installment_from_concept(_get(row, pos, "concepto"))
    if layout == "data_transacciones":
        provider = _text(_get(row, pos, "proveedor"), 50)
        payment_type = _text(_get(row, pos, "tipo de pago"), 50)
        method = None
        settlement = None
    else:
        provider = None
        payment_type = _text(_get(row, pos, "debito/credito"), 50)
        method = _text(_get(row, pos, "medio de pago"), 50)
        settlement = _ident(_get(row, pos, "liquidacion"))
    return PaykuTransactionRecord(
        row_key=row_key(voucher, order_ref, occurred, amount),
        transaction_external_id=voucher, order_ref=order_ref, occurred_at=occurred,
        is_installment=installment is not None, installment_number=installment, amount=amount,
        commission=_amount(row, pos, "comision"), net_amount=_amount(row, pos, "monto final"),
        payment_provider=provider, payment_type=payment_type, payment_method=method,
        settlement_external_id=settlement, source_layout=layout,
    )


def _build_settlement(row: tuple, pos: dict[str, int | None], _layout: str) -> PaykuSettlementRecord:
    ext = _ident(_get(row, pos, "liquidacion"))
    if ext is None:
        raise _Skip("invalid_id")
    return PaykuSettlementRecord(
        settlement_external_id=ext, amount=_amount(row, pos, "monto"), status=_text(_get(row, pos, "estatus"), 30),
        deposit_date=_date(_get(row, pos, "fecha deposito")),
    )


def _build_subscription(row: tuple, pos: dict[str, int | None], _layout: str) -> PaykuSubscriptionRecord:
    ext = _ident(_get(row, pos, "suscripcion id"))
    if ext is None:
        raise _Skip("invalid_id")
    raw_next = _get(row, pos, "proxima fecha cobro")
    next_date = _date(raw_next)
    if next_date is None and raw_next not in (None, "") and str(raw_next).strip():
        raise _Skip("invalid_date")
    return PaykuSubscriptionRecord(
        subscription_external_id=ext, status=_text(_get(row, pos, "estatus"), 50), next_charge_date=next_date,
    )


_BUILDERS = {
    "data_transacciones": _build_transaction,
    "consolidado": _build_transaction,
    "liquidaciones": _build_settlement,
    "suscripciones": _build_subscription,
}
_DEDUPE_KEY = {
    "data_transacciones": "row_key", "consolidado": "row_key",
    "liquidaciones": "settlement_external_id", "suscripciones": "subscription_external_id",
}


def _parse_sheet(ws, header_row: int, names: list[str], layout: str) -> ParsedSheet:
    wanted = (*SIGNATURES[layout], *OPTIONAL_COLUMNS[layout])
    pos = {col: _column_index(names, col) for col in wanted}
    known = {names[i] for i in pos.values() if i is not None}
    extra = tuple(sorted(n for n in names if n and n not in known and n not in PERSONAL_COLUMNS))
    sheet = ParsedSheet(layout=layout, records=[], extra_columns=extra)
    seen: set[str] = set()
    builder = _BUILDERS[layout]
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        if row is None or all(v is None or (isinstance(v, str) and not v.strip()) for v in row):
            continue
        sheet.rows_total += 1
        try:
            record = builder(row, pos, layout)
            key = getattr(record, _DEDUPE_KEY[layout])
            if key in seen:
                raise _Skip("duplicate_in_file")
            seen.add(key)
            sheet.records.append(record)
        except _Skip as skip:
            sheet.rows_skipped += 1
            sheet.skip_reasons[skip.reason] = sheet.skip_reasons.get(skip.reason, 0) + 1
    return sheet


def parse_report(path: str | Path) -> list[ParsedSheet]:
    """Lee todas las hojas reconocibles. Sin ninguna: `UnsupportedReportError`. Encabezado parecido a una firma pero
    incompleto: `ReportFormatError` con los nombres de columnas faltantes (y el tipo probable), nunca con valores."""
    wb = load_workbook(Path(path), read_only=True, data_only=True)
    try:
        sheets: list[ParsedSheet] = []
        for ws in wb.worksheets:
            header_row, names = _find_header(ws)
            if header_row is None:
                continue
            layout, probable, missing = _match(names)
            if layout is None:
                raise ReportFormatError(
                    f"reporte Payku incompleto: tipo probable {probable}; faltan columnas: {', '.join(missing)}"
                )
            sheets.append(_parse_sheet(ws, header_row, names, layout))
        if not sheets:
            raise UnsupportedReportError("tipo de reporte Payku no soportado (sin encabezado reconocible)")
        return sheets
    finally:
        wb.close()


def report_type_for(sheets: list[ParsedSheet]) -> str:
    kinds = {sheet.kind for sheet in sheets}
    return kinds.pop() if len(kinds) == 1 else "consolidado"


def iter_records(sheets: list[ParsedSheet], kind: str) -> Iterator[Any]:
    for sheet in sheets:
        if sheet.kind == kind:
            yield from sheet.records
