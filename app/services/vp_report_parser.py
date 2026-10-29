"""Parser de los reportes PAT descargados del portal de VirtualPOS (VP-PAR-02, fase PARSER).

Lee CSV en streaming y produce registros tipados SIN datos personales (dataclasses frozen). No toca la base de
datos; la carga vive en `vp_report_import`. Patron: `toku_report_parser` (TK-18).

Tipos (por FIRMA de columnas, nunca por nombre de archivo)
----------------------------------------------------------
* `transacciones` (`TransaccionesPAT-VirtualPOS-*.csv`, 33 columnas): un cobro por fila; clave `Id cargo`.
* `suscriptores` (`SuscriptoresPAT-VirtualPOS-*.csv`, 40 columnas): una suscripcion por fila; clave `Id de suscripcion`.

Reglas
------
* Texto: UTF-8 con o sin BOM; si no decodifica se prueba cp1252 y latin-1. Encabezados y celdas con mojibake
  (UTF-8 leido como latin-1/cp1252) se reparan. Delimitador `,`, `;` o tabulador, detectado en el encabezado.
* Encabezado: se busca en las primeras 10 lineas (tolera titulos previos). Nombres normalizados: sin tildes,
  casefold, espacios colapsados y sin el sufijo entre parentesis (`Total comision (imp. incl.)` -> `total comision`).
  Se exigen todas las columnas de la firma; las extras se informan solo por nombre (`extra_columns`).
  Faltantes -> `ReportFormatError` con NOMBRES de columnas y tipo probable; sin parecido -> `UnsupportedReportError`.
  Jamas se incluyen valores de filas en los errores.
* Lectura por POSICION de la primera aparicion de cada columna (si hay columnas duplicadas gana la primera).
  Solo se leen las columnas necesarias: nombre, apellido, correo, RUT, telefono, nacimiento, genero y direccion del
  cliente nunca se leen ni se guardan.
* Fechas chilenas `dd/mm/aaaa [hh:mm[:ss]]` (tambien ISO) en `America/Santiago`; montos con `$`, miles con punto y
  decimales con coma. `Final numero tarjeta` / `Ultimos 4 digitos pan` solo se acepta si son EXACTAMENTE 4 digitos
  (cualquier otra cosa se descarta y se cuenta en `stats.discarded_card_values`: jamas un PAN).
* `Codigo de vendedor` tiene forma de RUT: solo se guarda `HMAC-SHA256(pepper, normalizado)`; sin pepper queda None
  y la advertencia `seller_hash_skipped_no_pepper`.
* El codigo/glosa de un cobro solo se toma si el cobro esta `rechazado` (en un cobro pagado esa columna trae el
  codigo de autorizacion, que no es un rechazo). `response_code == ''` = rechazado sin codigo.
* Texto libre de procesadores (glosa, motivo): se redactan RUT, correos y secuencias de 12 a 19 digitos.
* `generated_at`: epoch de 10 digitos del nombre de archivo (`...-1792546479.csv`); si no hay o no es razonable,
  «ahora» (UTC) y la advertencia `generated_at_fallback_now`.
* Filas invalidas no tumban el archivo: se cuentan en `stats.skip_reasons` (`invalid_id`, `invalid_date`,
  `invalid_amount`, `duplicate_in_file`) sin valores. Duplicados por clave dentro del archivo: gana el primero.
"""

import csv
import hashlib
import hmac
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO

from app.services.toku_report_parser import (
    CHILE_TZ,
    parse_amount,
    parse_date,
    parse_datetime,
    redact_text,
)

REPORT_TYPES = ("transacciones", "suscriptores")
HEADER_SEARCH_LINES = 10
DELIMITERS = (",", ";", "\t")
_FUZZY_MIN_OVERLAP = 0.7
_MOJIBAKE_MARKERS = ("Ã", "Â", "â€")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_LONG_DIGITS_RE = re.compile(r"\b\d{12,19}\b")
_EPOCH_RE = re.compile(r"(?<!\d)(\d{10})(?!\d)")
_MIN_EPOCH = datetime(2020, 1, 1, tzinfo=UTC)

# clave -> nombres normalizados aceptados (el primero es el canonico que aparece en los errores)
_TX_SIGNATURE: dict[str, tuple[str, ...]] = {
    "subscription_id": ("id suscripcion", "id de suscripcion"),
    "charges_total": ("total de cargos programados",),
    "charge_number": ("numero de cargo",),
    "amount": ("monto de cargo",),
    "currency": ("moneda de cargo", "moneda"),
    "scheduled": ("fecha programada de cargo",),
    "status": ("estado del cargo",),
    "charge_id": ("id cargo",),
    "fee": ("total comision",),
    "payout": ("total abono",),
    "payout_date": ("fecha de abono",),
    "code": ("codigo de autorizacion/error/rechazo",),
    "gloss": ("glosa de autorizacion/error/rechazo",),
    "uuid": ("uuid transaccion",),
    "last4": ("final numero tarjeta",),
    "medium": ("medio de pago",),
    "authorized": ("fecha de autorizacion",),
    "sub_origin": ("origen de la suscripcion",),
    "pos_alias": ("alias pos",),
    "seller": ("codigo de vendedor",),
    "charge_origin": ("origen del cargo",),
}
_SUB_SIGNATURE: dict[str, tuple[str, ...]] = {
    "subscription_id": ("id de suscripcion", "id suscripcion"),
    "subscribed": ("fecha de suscripcion",),
    "status": ("estado de suscripcion",),
    "plan_id": ("id de plan", "id plan"),
    "charges_total": ("total de cargos programados",),
    "canceled": ("fecha de cancelacion",),
    "authorized": ("total de cargos autorizados",),
    "rejected": ("total de cargos rechazados",),
    "pending": ("total de cargos pendientes",),
    "processing": ("total de cargos en proceso",),
    "canceled_count": ("total de cargos cancelados",),
    "channel": ("canal/origen",),
    "pos_alias": ("alias pos",),
    "seller": ("codigo de vendedor",),
    "card_type": ("tipo tarjeta",),
    "last4": ("ultimos 4 digitos pan",),
    "brand": ("marca",),
    "reason": ("motivo de rechazo",),
}
SIGNATURES = {"transacciones": _TX_SIGNATURE, "suscriptores": _SUB_SIGNATURE}
# Columna que distingue un tipo del otro (sin ella no hay ambiguedad posible).
_DISCRIMINATOR = {"transacciones": "charge_id", "suscriptores": "last4"}


class ReportFormatError(Exception):
    """Formato invalido. El mensaje solo contiene nombres de columnas/tipos, jamas valores de filas."""


class UnsupportedReportError(ReportFormatError):
    """El archivo no corresponde a ningun reporte PAT soportado."""


# ---- registros (sin PII) --------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReportMeta:
    report_type: str
    generated_at: datetime
    warnings: tuple[str, ...] = ()
    extra_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class PaymentRecord:
    charge_external_id: str
    payment_external_id: str | None
    subscription_external_id: str | None
    charge_status: str | None
    scheduled_date: date
    charge_number: int | None
    charges_total: int | None
    amount: Decimal
    currency: str | None
    response_code: str | None
    response_text: str | None
    payment_medium: str | None
    card_last4: str | None
    authorized_at: datetime | None
    processing_fee: Decimal | None
    payout_amount: Decimal | None
    payout_date: datetime | None
    pos_alias: str | None
    seller_code_hash: str | None
    subscription_origin: str | None
    charge_origin: str | None


@dataclass(frozen=True)
class SubscriptionRecord:
    subscription_external_id: str
    status: str | None
    subscribed_at: datetime
    canceled_at: datetime | None
    plan_external_id: str | None
    charges_total: int | None
    charges_authorized: int | None
    charges_rejected: int | None
    charges_pending: int | None
    charges_processing: int | None
    charges_canceled: int | None
    channel_origin: str | None
    pos_alias: str | None
    seller_code_hash: str | None
    card_type: str | None
    card_brand: str | None
    card_last4: str | None
    rejection_reason: str | None


@dataclass
class ParseStats:
    rows_total: int = 0
    rows_skipped: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)
    discarded_card_values: int = 0
    window_start: date | None = None
    window_end: date | None = None

    def skip(self, reason: str) -> None:
        self.rows_skipped += 1
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1

    def see_date(self, value: date | None) -> None:
        if value is None:
            return
        if self.window_start is None or value < self.window_start:
            self.window_start = value
        if self.window_end is None or value > self.window_end:
            self.window_end = value


class _Skip(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


# ---- normalizadores -------------------------------------------------------------------------------------


def repair_mojibake(value: str) -> str:
    """Repara UTF-8 leido como latin-1/cp1252 (p. ej. `SuscripciÃ³n` -> `Suscripción`). Si no aplica, igual."""
    if not any(marker in value for marker in _MOJIBAKE_MARKERS):
        return value
    for codec in ("latin-1", "cp1252"):
        try:
            return value.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return value


def norm_name(value: Any) -> str:
    text = repair_mojibake(str(value if value is not None else ""))
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\s*\([^)]*\)", "", text)
    return " ".join(text.split()).casefold()


def _clean(value: Any, limit: int | None = None) -> str | None:
    if value is None:
        return None
    text = _CONTROL_RE.sub(" ", repair_mojibake(str(value))).strip()
    text = re.sub(r" {2,}", " ", text)
    if not text:
        return None
    return text[:limit] if limit else text


def _free_text(value: Any, limit: int = 1000) -> str | None:
    """Texto libre del procesador: sin RUT, correos ni secuencias de 12 a 19 digitos."""
    text = _clean(value)
    if text is None:
        return None
    text = redact_text(text) or text
    return _LONG_DIGITS_RE.sub("[redacted]", text)[:limit]


def _int(value: Any, maximum: int = 2_147_483_647) -> int | None:
    text = _clean(value)
    if text is None or not text.isdigit():
        return None
    number = int(text)
    return number if number <= maximum else None


def _last4(value: Any, stats: ParseStats) -> str | None:
    text = _clean(value)
    if text is None:
        return None
    if re.fullmatch(r"\d{4}", text):
        return text
    stats.discarded_card_values += 1  # jamas se conserva algo distinto de exactamente 4 digitos
    return None


def hash_seller_code(raw: Any, pepper: str) -> str | None:
    """HMAC-SHA256 hex (64) del codigo de vendedor normalizado (sin puntos ni espacios, casefold). Sin pepper: None."""
    text = _clean(raw)
    if text is None or not pepper:
        return None
    normalized = re.sub(r"[.\s]", "", unicodedata.normalize("NFC", text)).casefold()
    if not normalized:
        return None
    return hmac.new(pepper.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def _charge_numbers(value: Any) -> tuple[int | None, int | None]:
    """`Cargo 3 de 12` -> (3, 12)."""
    text = _clean(value)
    match = re.search(r"(\d+)\D+(\d+)", text or "")
    if not match:
        return None, None
    a, b = int(match.group(1)), int(match.group(2))
    return (a, b) if a <= 32767 and b <= 32767 else (None, None)


def _generated_at(filename: str | None, now: datetime) -> datetime | None:
    if not filename:
        return None
    match = _EPOCH_RE.search(Path(filename.replace("\\", "/")).name)
    if not match:
        return None
    try:
        moment = datetime.fromtimestamp(int(match.group(1)), tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return moment if _MIN_EPOCH <= moment <= now + timedelta(days=1) else None


# ---- lectura --------------------------------------------------------------------------------------------


def _detect_encoding(path: Path) -> str:
    """utf-8-sig si todo el archivo decodifica; si no, cp1252 y luego latin-1. Rechaza binarios con NUL."""
    for encoding in ("utf-8-sig", "cp1252"):
        decoder = __import__("codecs").getincrementaldecoder(encoding)()
        try:
            with open(path, "rb") as fh:
                first = True
                for block in iter(lambda: fh.read(1024 * 1024), b""):
                    if first and b"\x00" in block[:4096]:
                        raise ReportFormatError("el archivo no es un CSV de texto")
                    first = False
                    decoder.decode(block)
                decoder.decode(b"", final=True)
            return encoding
        except UnicodeDecodeError:
            continue
    return "latin-1"


def _match_type(names: list[str]) -> tuple[str | None, str | None, list[str]]:
    """(tipo exacto | None, tipo probable | None, columnas faltantes del probable)."""
    present = set(names)
    exact = [t for t in REPORT_TYPES if all(any(a in present for a in al) for al in SIGNATURES[t].values())]
    if len(exact) == 1:
        return exact[0], None, []
    if len(exact) > 1:
        raise ReportFormatError("firma de columnas ambigua entre tipos: " + ", ".join(sorted(exact)))
    best, best_ratio = None, 0.0
    for t in REPORT_TYPES:
        sig = SIGNATURES[t]
        ratio = sum(1 for al in sig.values() if any(a in present for a in al)) / len(sig)
        if ratio > best_ratio:
            best, best_ratio = t, ratio
    if best is None or best_ratio < _FUZZY_MIN_OVERLAP:
        return None, None, []
    missing = [al[0] for al in SIGNATURES[best].values() if not any(a in present for a in al)]
    return None, best, missing


def _split(line: str, delimiter: str) -> list[str]:
    try:
        return next(csv.reader([line], delimiter=delimiter), [])
    except csv.Error:
        return []


def _find_header(fh: TextIO) -> tuple[str, str, list[str]]:
    """Lee hasta 10 lineas. Devuelve (tipo, delimitador, celdas del encabezado)."""
    multi_cell_line = False
    probable: tuple[str, list[str]] | None = None
    for _ in range(HEADER_SEARCH_LINES):
        line = fh.readline()
        if line == "":
            break
        for delimiter in DELIMITERS:
            cells = _split(line.rstrip("\r\n"), delimiter)
            if len(cells) < 3:
                continue
            multi_cell_line = True
            exact, near, missing = _match_type([norm_name(c) for c in cells])
            if exact:
                return exact, delimiter, cells
            if near and probable is None:
                probable = (near, missing)
    if probable is not None:
        raise ReportFormatError(
            f"faltan columnas requeridas para el tipo probable «{probable[0]}»: " + ", ".join(probable[1])
        )
    if multi_cell_line:
        raise UnsupportedReportError("tipo de reporte no soportado")
    raise ReportFormatError("no se encontro la fila de encabezado en las primeras 10 lineas")


def _cell(row: list[str], idx: int) -> str | None:
    return row[idx] if idx < len(row) else None


def _row_is_empty(row: list[str]) -> bool:
    return all(not c.strip() for c in row)


@dataclass
class ParsedReport:
    """Reporte abierto: `meta` ya calculada; `records()` itera en streaming (una sola vez)."""

    meta: ReportMeta
    stats: ParseStats
    _fh: TextIO
    _reader: Any
    _positions: dict[str, int]
    _pepper: str

    def __enter__(self) -> "ParsedReport":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:  # noqa: BLE001  # pragma: no cover
            pass

    def records(self) -> Iterator[Any]:
        build = _BUILDERS[self.meta.report_type]
        seen: set[str] = set()
        while True:
            try:
                row = next(self._reader)
            except StopIteration:
                return
            except csv.Error:
                raise ReportFormatError("fila ilegible: el CSV esta mal formado") from None
            if _row_is_empty(row):
                continue
            self.stats.rows_total += 1
            try:
                record = build(row, self._positions, self._pepper, self.stats)
            except _Skip as skip:
                self.stats.skip(skip.reason)
                continue
            key = record.charge_external_id if isinstance(record, PaymentRecord) else record.subscription_external_id
            if key in seen:
                self.stats.skip("duplicate_in_file")
                continue
            seen.add(key)
            yield record


def open_report(
    path: str | Path,
    *,
    pepper: str = "",
    filename: str | None = None,
    now: datetime | None = None,
) -> ParsedReport:
    """Abre el CSV, detecta el tipo por firma y valida columnas. No lee filas de datos todavia."""
    path = Path(path)
    now = now or datetime.now(UTC)
    try:
        encoding = _detect_encoding(path)
        fh = open(path, encoding=encoding, newline="")
    except OSError:
        raise ReportFormatError("el archivo no se pudo leer") from None
    try:
        report_type, delimiter, header_cells = _find_header(fh)
        names = [norm_name(c) for c in header_cells]
        positions: dict[str, int] = {}
        for key, aliases in SIGNATURES[report_type].items():
            positions[key] = min(names.index(a) for a in aliases if a in names)  # primera aparicion
        required = set(positions.values())
        extras = tuple(
            _clean(c, 80) or f"col_{i + 1}" for i, c in enumerate(header_cells) if i not in required and _clean(c)
        )
        warnings: list[str] = []
        generated = _generated_at(filename, now)
        if generated is None:
            warnings.append("generated_at_fallback_now")
            generated = now
        if not pepper:
            warnings.append("seller_hash_skipped_no_pepper")
        meta = ReportMeta(report_type, generated, tuple(warnings), extras)
        reader = csv.reader(fh, delimiter=delimiter)
        return ParsedReport(meta, ParseStats(), fh, reader, positions, pepper)
    except BaseException:
        fh.close()
        raise


# ---- constructores por tipo -----------------------------------------------------------------------------


def _g(row: list[str], pos: dict[str, int], key: str) -> str | None:
    return _cell(row, pos[key])


def _build_payment(row: list[str], pos: dict[str, int], pepper: str, stats: ParseStats) -> PaymentRecord:
    charge = _clean(_g(row, pos, "charge_id"), 255)
    if not charge:
        raise _Skip("invalid_id")
    scheduled = parse_date(_clean(_g(row, pos, "scheduled")))
    if scheduled is None:
        raise _Skip("invalid_date")
    amount = parse_amount(_clean(_g(row, pos, "amount")))
    if amount is None:
        raise _Skip("invalid_amount")
    status = _clean(_g(row, pos, "status"), 50)
    status = status.lower() if status else None
    rejected = status == "rechazado"
    number, total_from_number = _charge_numbers(_g(row, pos, "charge_number"))
    stats.see_date(scheduled)
    return PaymentRecord(
        charge_external_id=charge,
        payment_external_id=_clean(_g(row, pos, "uuid"), 255),
        subscription_external_id=_clean(_g(row, pos, "subscription_id"), 255),
        charge_status=status,
        scheduled_date=scheduled,
        charge_number=number,
        charges_total=_int(_g(row, pos, "charges_total"), 32767) or total_from_number,
        amount=amount,
        currency=_clean(_g(row, pos, "currency"), 10),
        response_code=(_clean(_g(row, pos, "code"), 100) or "") if rejected else None,
        response_text=_free_text(_g(row, pos, "gloss")) if rejected else None,
        payment_medium=_clean(_g(row, pos, "medium"), 30),
        card_last4=_last4(_g(row, pos, "last4"), stats),
        authorized_at=parse_datetime(_clean(_g(row, pos, "authorized"))),
        processing_fee=parse_amount(_clean(_g(row, pos, "fee"))),
        payout_amount=parse_amount(_clean(_g(row, pos, "payout"))),
        payout_date=parse_datetime(_clean(_g(row, pos, "payout_date"))),
        pos_alias=_clean(_g(row, pos, "pos_alias"), 255),
        seller_code_hash=hash_seller_code(_g(row, pos, "seller"), pepper),
        subscription_origin=_clean(_g(row, pos, "sub_origin"), 50),
        charge_origin=_clean(_g(row, pos, "charge_origin"), 100),
    )


def _build_subscription(row: list[str], pos: dict[str, int], pepper: str, stats: ParseStats) -> SubscriptionRecord:
    sub = _clean(_g(row, pos, "subscription_id"), 255)
    if not sub:
        raise _Skip("invalid_id")
    subscribed = parse_datetime(_clean(_g(row, pos, "subscribed")))
    if subscribed is None:
        raise _Skip("invalid_date")
    stats.see_date(subscribed.astimezone(CHILE_TZ).date())
    return SubscriptionRecord(
        subscription_external_id=sub,
        status=_clean(_g(row, pos, "status"), 50),
        subscribed_at=subscribed,
        canceled_at=parse_datetime(_clean(_g(row, pos, "canceled"))),
        plan_external_id=_clean(_g(row, pos, "plan_id"), 255),
        charges_total=_int(_g(row, pos, "charges_total"), 32767),
        charges_authorized=_int(_g(row, pos, "authorized")),
        charges_rejected=_int(_g(row, pos, "rejected")),
        charges_pending=_int(_g(row, pos, "pending")),
        charges_processing=_int(_g(row, pos, "processing")),
        charges_canceled=_int(_g(row, pos, "canceled_count")),
        channel_origin=_clean(_g(row, pos, "channel"), 50),
        pos_alias=_clean(_g(row, pos, "pos_alias"), 255),
        seller_code_hash=hash_seller_code(_g(row, pos, "seller"), pepper),
        card_type=_clean(_g(row, pos, "card_type"), 20),
        card_brand=_clean(_g(row, pos, "brand"), 50),
        card_last4=_last4(_g(row, pos, "last4"), stats),
        rejection_reason=_free_text(_g(row, pos, "reason")),
    )


_BUILDERS = {"transacciones": _build_payment, "suscriptores": _build_subscription}
