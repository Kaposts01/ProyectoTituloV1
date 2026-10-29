"""Parser de reportes .xlsx descargados del Backoffice de Toku (TK-18, fase PARSER).

Lee en streaming (openpyxl `read_only=True, data_only=True`) y produce registros tipados SIN datos
personales (dataclasses frozen). No toca la base de datos; la carga vive en `toku_report_import`.

Reglas
------
* Estructura: filas 1-6 = titulo y metadatos (fila 1 `Reporte | <nombre>`, fila 2 fecha de generacion,
  fila 4 inicio y fila 5 termino de la ventana) y encabezado en la fila 7. El encabezado se busca en las
  primeras 10 filas (primera fila cuya primera celda sea `ID`). Si el encabezado esta en la fila 1 no hay
  titulo: `generated_at` = «ahora» (UTC) y se agrega la advertencia `generated_at_fallback_now`. Si hay
  titulo pero no se puede leer la fecha, mismo fallback. Las ventanas quedan en None si no se leen.
* Fechas: ISO (`2026-10-20`, `2026-10-20T10:00:00Z`, con offset) o `dd/mm/aaaa [hh:mm[:ss]]` (Deudas). Las fechas
  sin zona horaria se interpretan como `America/Santiago` (hora local de los reportes de Chile).
* Tipo de reporte: por FIRMA de columnas (nombres normalizados: sin tildes, casefold, espacios colapsados),
  nunca por titulo ni nombre de archivo. Se exigen todas las columnas de la firma; las extras se ignoran y se
  informan solo por nombre (`extra_columns`). Faltantes -> `ReportFormatError` con NOMBRES de columnas y tipo
  probable; sin parecido con ninguna firma -> `UnsupportedReportError` («tipo de reporte no soportado»).
  Jamas se incluyen valores de filas en errores.
* Lectura por POSICION (hay columnas duplicadas, p. ej. `Medio de pago` en inscripciones: se usa la primera).
  Solo se leen las celdas de las columnas necesarias; nombre, mail, celular, RUT, ID Externo, tarjeta, token,
  bin, cuenta y datos PAC nunca se leen ni se guardan.
* D2 (DEC-17): `ID Producto` (texto libre que contiene el RUT) NO se guarda; solo
  `product_key_hash = HMAC-SHA256(pepper, normalizado)` en hex minusculas (64). Normalizado = NFC, strip,
  espacios internos colapsados, casefold. Sin pepper el parser se niega a abrir (`MissingPepperError`).
  Un `ID Producto` vacio da hash `''` (sentinela «sin producto»; nunca sirve de puente).
* `Estado` de Productos es el estado del MEDIO DE PAGO (`payment_method_status`); el ciclo de vida de la
  suscripcion se infiere de `deleted_at_source`.
* Montos: numeros o texto con `$`, miles con punto y decimales con coma o punto; 2 decimales. Booleanos:
  true/false, 1/0, si/no, verdadero/falso (vacio = None; en Deudas vacio = False por ser NOT NULL).
* Filas invalidas no tumban el archivo: se cuentan en `stats.rows_skipped` con un codigo de motivo
  (`invalid_id`, `missing_customer`, `missing_debt`, `invalid_amount`, `invalid_due_date`, `invalid_bool`,
  `duplicate_in_file`) sin valores. Duplicados por clave natural dentro del archivo: se conserva el primero.

Mapeo de gravedad (SU/TE/PE/UE)
-------------------------------
SU = exito, TE = error temporal, PE = error permanente, UE = error desconocido.
* Formato largo (inscripciones): regex `^(SU|TE|PE|UE)([A-Z]{3})(\\d{4})$`; la gravedad son los 2 primeros
  caracteres. Valor presente que no calza -> `UNKNOWN`; vacio -> None. El texto crudo solo se guarda si calza.
* Catalogo (hoja «Codigos de Error Toku», columnas Codigo Toku/Gravedad/Mensaje/Descripcion), lectura
  tolerante de `Gravedad` (sin tildes, casefold): primero un codigo de 2 letras exacto al inicio
  (`SU`, `TE`, `PE`, `UE`, p. ej. `TE - Temporal`); luego por palabra: `exito|success|autoriz|aprobad` -> SU;
  `temporal|temporary|transitor` -> TE; `permanente|permanent|definitiv` -> PE;
  `desconocid|unknown|inesperad|unexpected` -> UE. Si no se puede mapear la fila del catalogo se omite
  (`unmapped_severity`: la tabla de codigos no admite UNKNOWN) y los intentos con ese codigo quedan `UNKNOWN`.
* Intentos: gravedad = catalogo[codigo]; codigo presente fuera del catalogo -> `UNKNOWN`; sin codigo -> None.
"""

import hashlib
import hmac
import re
import unicodedata
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import load_workbook

CHILE_TZ = ZoneInfo("America/Santiago")
HEADER_SEARCH_ROWS = 10
LONG_CODE_RE = re.compile(r"^(SU|TE|PE|UE)([A-Z]{3})(\d{4})$")
SHORT_CODE_RE = re.compile(r"^\d{4}$")
_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?\s*(Z|[+-]\d{2}:?\d{2})?$")
_DMY_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$")
_ANY_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?|\d{1,2}/\d{1,2}/\d{4}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?")
MAX_AMOUNT = Decimal("999999999999.99")

SUPPORTED_TYPES = ("productos", "medios_pago", "intentos", "deudas", "inscripciones")


class ReportFormatError(Exception):
    """Formato invalido. El mensaje solo contiene nombres de columnas/tipos, jamas valores de filas."""


class UnsupportedReportError(ReportFormatError):
    """Reporte que no se importa en esta fase (Clientes, Pagos, Mensajes, Liquidaciones, ...)."""


class MissingPepperError(RuntimeError):
    """Falla cerrada: sin pepper no se importa nada."""


def norm_header(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value if value is not None else ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.split()).casefold()


# Firmas minimas por tipo (nombres normalizados). El orden de la tupla define las posiciones del registro.
SIGNATURES: dict[str, tuple[str, ...]] = {
    "productos": (
        "id", "fecha de creacion", "fecha de eliminacion", "id producto", "cliente", "is_recurring", "monto",
        "due_day", "medio de pago", "procesador de pago", "estado",
    ),
    "medios_pago": (
        "id", "fecha de creacion", "fecha de eliminacion", "id producto", "tipo de tarjeta", "marca tarjeta",
        "banco emisor", "estado", "procesador de pago", "last_payment_intent_response_code",
        "last_payment_intent_original_response_message",
    ),
    "intentos": (
        "id", "fecha de creacion", "fecha de eliminacion", "cliente", "deuda", "id producto",
        "fecha de vencimiento", "monto", "estado", "codigo de respuesta toku", "procesador de pago",
        "fecha de transaccion", "id mandato",
    ),
    "deudas": (
        "id", "fecha de creacion", "fecha de eliminacion", "id producto", "fecha de vencimiento", "monto",
        "pagado", "anulado", "cliente", "estado",
    ),
    "inscripciones": (
        "id", "fecha de creacion", "fecha de eliminacion", "medio de pago", "estado transaccion",
        "codigo de respuesta", "estado medio de pago", "fecha ultimo intento de pago",
        "estado ultimo intento de pago", "id_subscription",
    ),
}  # fmt: skip
CATALOG_SIGNATURE = ("codigo toku", "gravedad", "mensaje", "descripcion")
_FUZZY_MIN_OVERLAP = 0.7


# ---- registros (sin PII) ----------------------------------------------------------------------


@dataclass(frozen=True)
class ReportMeta:
    report_type: str
    generated_at: datetime
    window_start: date | None
    window_end: date | None
    warnings: tuple[str, ...] = ()
    extra_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResponseCodeRecord:
    code: str
    severity: str
    message: str
    description: str | None


@dataclass(frozen=True)
class ProductRecord:
    subscription_external_id: str
    product_key_hash: str
    customer_external_id: str
    payment_method_external_id: str | None
    payment_method_status: str | None
    payment_processor: str | None
    amount: Decimal | None
    due_day: int | None
    is_recurring: bool | None
    created_at_source: datetime | None
    deleted_at_source: datetime | None


@dataclass(frozen=True)
class PaymentMethodRecord:
    payment_method_external_id: str
    product_key_hash: str
    status: str | None
    card_type: str | None
    card_brand: str | None
    issuer_bank: str | None
    processor: str | None
    last_response_code: str | None
    last_response_message: str | None
    created_at_source: datetime | None
    deleted_at_source: datetime | None


@dataclass(frozen=True)
class AttemptRecord:
    attempt_external_id: str
    debt_external_id: str
    customer_external_id: str
    product_key_hash: str
    due_date: date | None
    attempted_at: datetime | None
    status: str | None
    response_code: str | None
    severity: str | None
    amount: Decimal | None
    processor: str | None
    has_mandate: bool
    deleted_at_source: datetime | None


@dataclass(frozen=True)
class DebtRecord:
    debt_external_id: str
    product_key_hash: str
    customer_external_id: str | None
    due_date: date
    amount: Decimal
    paid: bool
    voided: bool
    status: str | None
    deleted_at_source: datetime | None


@dataclass(frozen=True)
class InscriptionRecord:
    inscription_external_id: str
    payment_method_external_id: str | None
    subscription_external_id: str | None
    transaction_status: str | None
    response_code_full: str | None
    severity: str | None
    payment_method_status: str | None
    last_attempt_at: datetime | None
    last_attempt_status: str | None
    deleted_at_source: datetime | None


@dataclass
class ParseStats:
    rows_total: int = 0
    rows_skipped: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.rows_skipped += 1
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1


# ---- normalizadores ---------------------------------------------------------------------------


def normalize_product_key(raw: Any) -> str:
    text = unicodedata.normalize("NFC", str(raw))
    return " ".join(text.split()).casefold()


def hash_product_key(raw: Any, pepper: str) -> str:
    """HMAC-SHA256 hex (64, minusculas) del `ID Producto` normalizado. Vacio -> '' (sin producto)."""
    if not pepper:
        raise MissingPepperError("falta TOKU_REPORT_HASH_PEPPER")
    if raw is None:
        return ""
    normalized = normalize_product_key(raw)
    if not normalized:
        return ""
    return hmac.new(pepper.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def _text(value: Any, limit: int | None = None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit] if limit else text


def _ext_id(value: Any, prefix: str) -> str | None:
    text = _text(value, 255)
    return text if text and text.startswith(prefix) else None


def _opt_ext_id(value: Any, prefix: str) -> str | None:
    return _ext_id(value, prefix)


_RUT_RE = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def redact_text(text: str | None, limit: int | None = None) -> str | None:
    """Texto libre de procesadores: se redactan RUT y correos por precaucion."""
    if text is None:
        return None
    clean = _EMAIL_RE.sub("[redacted]", _RUT_RE.sub("[redacted]", text))
    return clean[:limit] if limit else clean


def parse_datetime(value: Any) -> datetime | None:
    """datetime con zona (UTC si el texto trae Z/offset; America/Santiago si es ingenuo) o None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=CHILE_TZ)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=CHILE_TZ)
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        m = _ISO_RE.match(text)
        if m:
            y, mo, d, hh, mi, ss, tz = m.groups()
            dt = datetime(int(y), int(mo), int(d), int(hh or 0), int(mi or 0), int(ss or 0))  # noqa: DTZ001 - zona asignada abajo
            if tz:
                if tz == "Z":
                    return dt.replace(tzinfo=UTC)
                sign = 1 if tz[0] == "+" else -1
                digits = tz[1:].replace(":", "")
                return dt.replace(tzinfo=timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))))
            return dt.replace(tzinfo=CHILE_TZ)
        m = _DMY_RE.match(text)
        if m:
            d, mo, y, hh, mi, ss = m.groups()
            return datetime(int(y), int(mo), int(d), int(hh or 0), int(mi or 0), int(ss or 0), tzinfo=CHILE_TZ)
    except ValueError:
        return None
    return None


def parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    dt = parse_datetime(value)
    if dt is None:
        return None
    return dt.astimezone(CHILE_TZ).date() if dt.tzinfo is not CHILE_TZ else dt.date()


def parse_amount(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float, Decimal)):
            amount = Decimal(str(value))
        else:
            text = re.sub(r"[\s$]", "", str(value))
            if not text:
                return None
            if "." in text and "," in text:
                text = text.replace(".", "").replace(",", ".")
            elif "," in text:
                text = text.replace(",", ".")
            elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", text):
                text = text.replace(".", "")
            amount = Decimal(text)
        if not amount.is_finite():
            return None
        amount = amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    return amount if abs(amount) <= MAX_AMOUNT else None


_TRUE = {"true", "1", "si", "yes", "verdadero", "y", "s"}
_FALSE = {"false", "0", "no", "falso", "n"}


def parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = norm_header(value)
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return None


def parse_due_day(value: Any) -> int | None:
    try:
        day = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return day if 1 <= day <= 31 else None


def severity_from_long_code(value: Any) -> tuple[str | None, str | None]:
    """(codigo_largo_valido_o_None, gravedad). Presente pero invalido -> (None, 'UNKNOWN'); vacio -> (None, None)."""
    text = _text(value)
    if text is None:
        return None, None
    text = text.upper()
    m = LONG_CODE_RE.match(text)
    return (text, m.group(1)) if m else (None, "UNKNOWN")


_SHORT_SEVERITY_RE = re.compile(r"^(su|te|pe|ue)(?![a-z])")
_SEVERITY_WORDS = (
    ("SU", ("exito", "success", "autoriz", "aprobad")),
    ("PE", ("permanente", "permanent", "definitiv")),
    ("TE", ("temporal", "temporary", "transitor")),
    ("UE", ("desconocid", "unknown", "inesperad", "unexpected")),
)  # fmt: skip


def map_catalog_severity(value: Any) -> str | None:
    """Gravedad del catalogo -> SU/TE/PE/UE o None si no se puede mapear (ver docstring del modulo)."""
    text = norm_header(value)
    if not text:
        return None
    m = _SHORT_SEVERITY_RE.match(text)
    if m:
        return m.group(1).upper()
    for code, words in _SEVERITY_WORDS:
        if any(w in text for w in words):
            return code
    return None


# ---- lectura ----------------------------------------------------------------------------------


def _cell(row: tuple, idx: int | None) -> Any:
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def _row_is_empty(row: tuple) -> bool:
    return all(c is None or (isinstance(c, str) and not c.strip()) for c in row)


def _open_workbook(path: str | Path):
    try:
        return load_workbook(filename=str(path), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - zip corrupto, no es xlsx, etc. Sin eco del mensaje (puede traer rutas)
        raise ReportFormatError(f"el archivo no es un .xlsx legible ({type(exc).__name__})") from None


def _find_header(rows: Iterator[tuple], *, first_is_id: bool = True, require: tuple[str, ...] = ()) -> tuple[int, tuple, list[tuple]] | None:
    """Consume hasta 10 filas. Devuelve (indice0_del_encabezado, fila, filas_previas) o None."""
    head: list[tuple] = []
    for i, row in enumerate(rows):
        if i >= HEADER_SEARCH_ROWS:
            break
        names = [norm_header(c) for c in row]
        if (first_is_id and names and names[0] == "id") or (require and set(require) <= set(names)):
            return i, row, head
        head.append(row)
    return None


def _meta_from_title(prev_rows: list[tuple]) -> tuple[datetime | None, date | None, date | None]:
    def row_date(idx: int) -> datetime | None:
        if idx >= len(prev_rows):
            return None
        for c in prev_rows[idx]:
            if isinstance(c, (datetime, date)):
                return parse_datetime(c)
            if isinstance(c, str):
                m = _ANY_DATE_RE.search(c)
                if m:
                    dt = parse_datetime(m.group(0))
                    if dt:
                        return dt
        return None

    generated = row_date(1)
    start, end = row_date(3), row_date(4)
    return generated, (start.date() if start else None), (end.date() if end else None)


def detect_report_type(header_names: list[str]) -> str:
    present = set(header_names)
    exact = [t for t in SUPPORTED_TYPES if set(SIGNATURES[t]) <= present]
    if exact:
        best = max(exact, key=lambda t: len(SIGNATURES[t]))
        ties = [t for t in exact if len(SIGNATURES[t]) == len(SIGNATURES[best])]
        if len(ties) > 1:
            raise ReportFormatError("firma de columnas ambigua entre tipos: " + ", ".join(sorted(ties)))
        return best
    scored = sorted(
        ((len(present & set(SIGNATURES[t])) / len(SIGNATURES[t]), t) for t in SUPPORTED_TYPES), reverse=True
    )
    ratio, probable = scored[0]
    if ratio >= _FUZZY_MIN_OVERLAP:
        missing = [c for c in SIGNATURES[probable] if c not in present]
        raise ReportFormatError(
            f"faltan columnas requeridas para el tipo probable «{probable}»: " + ", ".join(missing)
        )
    raise UnsupportedReportError("tipo de reporte no soportado")


@dataclass
class ParsedReport:
    """Reporte abierto: `meta` ya calculada; `records()` itera en streaming (una sola vez)."""

    meta: ReportMeta
    stats: ParseStats
    _wb: Any
    _rows: Iterator[tuple]
    _positions: dict[str, int]
    _pepper: str
    _severity: Mapping[str, str]

    def __enter__(self) -> "ParsedReport":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._wb.close()
        except Exception:  # noqa: BLE001  # pragma: no cover
            pass

    def records(self) -> Iterator[Any]:
        build = _BUILDERS[self.meta.report_type]
        seen: set[Any] = set()
        for row in self._rows:
            if _row_is_empty(row):
                continue
            self.stats.rows_total += 1
            try:
                result = build(row, self._positions, self._pepper, self._severity)
            except _Skip as skip:
                self.stats.skip(skip.reason)
                continue
            record, key = result
            if key in seen:
                self.stats.skip("duplicate_in_file")
                continue
            seen.add(key)
            yield record


class _Skip(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


def open_report(
    path: str | Path,
    *,
    pepper: str,
    severity_lookup: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> ParsedReport:
    """Abre el archivo, detecta el tipo por firma y valida columnas. No lee filas de datos todavia."""
    if not pepper:
        raise MissingPepperError("falta TOKU_REPORT_HASH_PEPPER")
    wb = _open_workbook(path)
    try:
        ws = wb.worksheets[0] if wb.worksheets else None
        if ws is None:
            raise ReportFormatError("el archivo no tiene hojas")
        rows = ws.iter_rows(values_only=True)
        found = _find_header(rows)
        if found is None:
            raise ReportFormatError("no se encontro la fila de encabezado (primera celda `ID`) en las primeras 10 filas")
        header_idx, header_row, prev = found
        names = [norm_header(c) for c in header_row]
        report_type = detect_report_type(names)
        positions: dict[str, int] = {}
        for col in SIGNATURES[report_type]:
            positions[col] = names.index(col)  # primera aparicion (columnas duplicadas)
        required = set(positions.values())
        extras = tuple(
            _text(c, 80) or f"col_{i + 1}"
            for i, c in enumerate(header_row)
            if i not in required and _text(c)
        )

        warnings: list[str] = []
        generated = window_start = window_end = None
        if header_idx >= 5:  # hay bloque de titulo
            generated, window_start, window_end = _meta_from_title(prev)
        if generated is None:
            warnings.append("generated_at_fallback_now")
            generated = now or datetime.now(UTC)
        meta = ReportMeta(report_type, generated, window_start, window_end, tuple(warnings), extras)
        return ParsedReport(meta, ParseStats(), wb, rows, positions, pepper, severity_lookup if severity_lookup is not None else {})
    except BaseException:
        wb.close()
        raise


def read_response_catalog(path: str | Path) -> tuple[list[ResponseCodeRecord], ParseStats]:
    """Hoja «Codigos de Error Toku» (cualquier hoja cuyo encabezado traiga Codigo Toku y Gravedad)."""
    stats = ParseStats()
    out: list[ResponseCodeRecord] = []
    wb = _open_workbook(path)
    try:
        for ws in wb.worksheets:
            rows = ws.iter_rows(values_only=True)
            found = _find_header(rows, first_is_id=False, require=("codigo toku", "gravedad"))
            if found is None:
                continue
            _, header_row, _ = found
            names = [norm_header(c) for c in header_row]
            pos = {c: (names.index(c) if c in names else None) for c in CATALOG_SIGNATURE}
            seen: set[str] = set()
            for row in rows:
                if _row_is_empty(row):
                    continue
                stats.rows_total += 1
                code = _text(_cell(row, pos["codigo toku"]))
                if code and code.isdigit() and len(code) < 4:
                    code = code.zfill(4)
                if not code or not SHORT_CODE_RE.match(code):
                    stats.skip("invalid_code")
                    continue
                severity = map_catalog_severity(_cell(row, pos["gravedad"]))
                if severity is None:
                    stats.skip("unmapped_severity")
                    continue
                message = _text(_cell(row, pos["mensaje"])) or ""
                if not message:
                    stats.skip("missing_message")
                    continue
                if code in seen:
                    stats.skip("duplicate_in_file")
                    continue
                seen.add(code)
                out.append(
                    ResponseCodeRecord(code, severity, message, _text(_cell(row, pos["descripcion"])))
                )
            break
    finally:
        wb.close()
    return out, stats


# ---- constructores por tipo -------------------------------------------------------------------


def _g(row: tuple, pos: dict[str, int], col: str) -> Any:
    return _cell(row, pos[col])


def _build_product(row, pos, pepper, _sev):
    sub = _ext_id(_g(row, pos, "id"), "sub_")
    if not sub:
        raise _Skip("invalid_id")
    customer = _text(_g(row, pos, "cliente"), 255)
    if not customer:
        raise _Skip("missing_customer")
    rec = ProductRecord(
        subscription_external_id=sub,
        product_key_hash=hash_product_key(_g(row, pos, "id producto"), pepper),
        customer_external_id=customer,
        payment_method_external_id=_ext_id(_g(row, pos, "medio de pago"), "pm_"),
        payment_method_status=_text(_g(row, pos, "estado"), 100),
        payment_processor=_text(_g(row, pos, "procesador de pago"), 100),
        amount=parse_amount(_g(row, pos, "monto")),
        due_day=parse_due_day(_g(row, pos, "due_day")),
        is_recurring=parse_bool(_g(row, pos, "is_recurring")),
        created_at_source=parse_datetime(_g(row, pos, "fecha de creacion")),
        deleted_at_source=parse_datetime(_g(row, pos, "fecha de eliminacion")),
    )
    return rec, sub


def _build_payment_method(row, pos, pepper, _sev):
    pm = _ext_id(_g(row, pos, "id"), "pm_")
    if not pm:
        raise _Skip("invalid_id")
    code = _text(_g(row, pos, "last_payment_intent_response_code"), 10)
    rec = PaymentMethodRecord(
        payment_method_external_id=pm,
        product_key_hash=hash_product_key(_g(row, pos, "id producto"), pepper),
        status=_text(_g(row, pos, "estado"), 100),
        card_type=_text(_g(row, pos, "tipo de tarjeta"), 50),
        card_brand=_text(_g(row, pos, "marca tarjeta"), 50),
        issuer_bank=_text(_g(row, pos, "banco emisor"), 100),
        processor=_text(_g(row, pos, "procesador de pago"), 100),
        last_response_code=code,
        last_response_message=redact_text(_text(_g(row, pos, "last_payment_intent_original_response_message"))),
        created_at_source=parse_datetime(_g(row, pos, "fecha de creacion")),
        deleted_at_source=parse_datetime(_g(row, pos, "fecha de eliminacion")),
    )
    return rec, (pm, rec.product_key_hash)


def _build_attempt(row, pos, pepper, severity):
    pi = _ext_id(_g(row, pos, "id"), "pi_")
    if not pi:
        raise _Skip("invalid_id")
    debt = _text(_g(row, pos, "deuda"), 255)
    if not debt:
        raise _Skip("missing_debt")
    customer = _text(_g(row, pos, "cliente"), 255)
    if not customer:
        raise _Skip("missing_customer")
    raw_code = _text(_g(row, pos, "codigo de respuesta toku"))
    if raw_code and raw_code.isdigit() and len(raw_code) < 4:
        raw_code = raw_code.zfill(4)
    code = raw_code if raw_code and SHORT_CODE_RE.match(raw_code) else None
    if code:
        sev = severity.get(code, "UNKNOWN")
    else:
        sev = "UNKNOWN" if raw_code else None
    status = _text(_g(row, pos, "estado"), 50)
    rec = AttemptRecord(
        attempt_external_id=pi,
        debt_external_id=debt,
        customer_external_id=customer,
        product_key_hash=hash_product_key(_g(row, pos, "id producto"), pepper),
        due_date=parse_date(_g(row, pos, "fecha de vencimiento")),
        attempted_at=parse_datetime(_g(row, pos, "fecha de transaccion"))
        or parse_datetime(_g(row, pos, "fecha de creacion")),
        status=status.upper() if status else None,
        response_code=code,
        severity=sev,
        amount=parse_amount(_g(row, pos, "monto")),
        processor=_text(_g(row, pos, "procesador de pago"), 100),
        has_mandate=_text(_g(row, pos, "id mandato")) is not None,  # solo presencia, nunca el valor
        deleted_at_source=parse_datetime(_g(row, pos, "fecha de eliminacion")),
    )
    return rec, pi


def _build_debt(row, pos, pepper, _sev):
    debt = _text(_g(row, pos, "id"), 255)
    if not debt or not debt.startswith("in_"):
        raise _Skip("invalid_id")
    due = parse_date(_g(row, pos, "fecha de vencimiento"))
    if due is None:
        raise _Skip("invalid_due_date")
    amount = parse_amount(_g(row, pos, "monto"))
    if amount is None:
        raise _Skip("invalid_amount")
    flags = []
    for col in ("pagado", "anulado"):
        raw = _g(row, pos, col)
        value = parse_bool(raw)
        if value is None and _text(raw) is not None:
            raise _Skip("invalid_bool")
        flags.append(bool(value))  # vacio = False (columna NOT NULL)
    rec = DebtRecord(
        debt_external_id=debt,
        product_key_hash=hash_product_key(_g(row, pos, "id producto"), pepper),
        customer_external_id=_text(_g(row, pos, "cliente"), 255),
        due_date=due,
        amount=amount,
        paid=flags[0],
        voided=flags[1],
        status=_text(_g(row, pos, "estado"), 50),
        deleted_at_source=parse_datetime(_g(row, pos, "fecha de eliminacion")),
    )
    return rec, debt


def _build_inscription(row, pos, pepper, _sev):
    ins = _ext_id(_g(row, pos, "id"), "pmii_")
    if not ins:
        raise _Skip("invalid_id")
    full, sev = severity_from_long_code(_g(row, pos, "codigo de respuesta"))
    rec = InscriptionRecord(
        inscription_external_id=ins,
        payment_method_external_id=_ext_id(_g(row, pos, "medio de pago"), "pm_"),
        subscription_external_id=_ext_id(_g(row, pos, "id_subscription"), "sub_"),
        transaction_status=_text(_g(row, pos, "estado transaccion"), 100),
        response_code_full=full,
        severity=sev,
        payment_method_status=_text(_g(row, pos, "estado medio de pago"), 100),
        last_attempt_at=parse_datetime(_g(row, pos, "fecha ultimo intento de pago")),
        last_attempt_status=_text(_g(row, pos, "estado ultimo intento de pago"), 100),
        deleted_at_source=parse_datetime(_g(row, pos, "fecha de eliminacion")),
    )
    return rec, ins


_BUILDERS = {
    "productos": _build_product,
    "medios_pago": _build_payment_method,
    "intentos": _build_attempt,
    "deudas": _build_debt,
    "inscripciones": _build_inscription,
}
