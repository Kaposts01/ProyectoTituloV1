#!/usr/bin/env python3
"""
ETL CLI para carga de reportes Excel TCH (TECHO Chile) a tablas tch_* del CRM.

Uso:
    # Carga histórica completa (todos los .xlsx de una carpeta)
    python scripts/etl_tch.py --mode full --folder "C:\\Users\\Usuario\\Downloads\\TCH"

    # Carga de un archivo individual (mensual)
    python scripts/etl_tch.py --mode incremental --file "C:\\ruta\\20260831 TCH IG GESTION AGOSTO 2026.XLSX"
"""

import argparse
import logging
import re
import sys
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from sqlalchemy import and_, case, func, literal_column, or_, select, true

from app.db.session import SessionLocal, engine
from app.models.etl_run import EtlRun
from app.models.tch import (
    ORIGIN_CHARGE,
    ORIGIN_HISTORY,
    TchBank,
    TchClient,
    TchCostCenter,
    TchMandateFlow,
    TchMandateType,
    TchMonthlyCollection,
    TchOrigin,
    TchRejectionReason,
    TchReportKpi,
    TchSubscription,
    TchTransaction,
)
from app.scheduler.run_lock import ActiveRunError, start_exclusive_run
from app.services import tch_report_registry as report_registry
from app.services.core_tch_etl import normalize_tch_currency
from app.services.payload_sanitization import sanitize_payload
from app.services.tch_rut import normalize_tch_rut
from app.services.tch_source_records import sync_tch_source_records

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("etl_tch")


def _safe_error_message(exc: Exception) -> str:
    """Keep ETL run metadata useful without retaining account-like identifiers."""
    return re.sub(r"\b\d{8,20}\b", "[redacted]", str(exc))[:2000]


# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------

def _norm_rut(val: Any) -> str | None:
    """Llave del cliente TCH (TCH-PAR-14): formato ``12.345.678-5`` o, si no tiene forma de RUT, ``EXT-...`` aislado.

    Ver ``app/services/tch_rut.py``: el verificador NO cambia la llave; solo decide si el RUT sale del canal como
    senal de identidad.
    """
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    return normalize_tch_rut(val)


def _norm_date(val: Any) -> str | None:
    """Fecha ISO (yyyy-mm-dd) desde una celda del Excel: fecha/datetime, 'dd/mm/yyyy', 'dd-mm-yyyy', 'dd.mm.yyyy' o
    'yyyy-mm-dd' (con o sin hora). Una fecha imposible (31/02) o un texto que no es fecha da None, no un ISO invalido."""
    if val is None or pd.isna(val):
        return None
    try:
        if hasattr(val, "date"):
            return val.date().isoformat()
        s = str(val).strip()
        iso = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
        if iso:
            y, m, d = (int(part) for part in iso.groups())
            return date(y, m, d).isoformat()
        parts = re.match(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?!\d)", s)
        if parts:
            d, m, y = (int(part) for part in parts.groups())
            return date(y, m, d).isoformat()
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def _norm_str(val: Any, max_len: int = 255) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    return s[:max_len] if s else None


def _norm_amount(val: Any) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        if isinstance(val, str):
            val = val.replace("$", "").replace(".", "").replace(",", ".").strip()
        return str(int(float(val)))
    except Exception:
        return None


def _norm_int(val: Any) -> int | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        v = int(float(val))
        return v if v != 0 else None  # 0 no es un ID válido en TCH
    except Exception:
        return None


def _norm_count(val: Any) -> int | None:
    """Entero que admite 0 (a diferencia de _norm_int, donde 0 no es un ID valido)."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return int(float(str(val).replace(",", ".")))
    except (TypeError, ValueError):
        return None


def _norm_bool(val: Any) -> bool | None:
    """Flags del reporte (NVO / RECH MES / ELI MES): 1, SI, X -> True; 0, NO -> False; vacio o ilegible -> None."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    text = str(val).strip().upper()
    if text in {"1", "1.0", "SI", "S", "X", "TRUE", "VERDADERO", "YES"}:
        return True
    if text in {"0", "0.0", "NO", "N", "FALSE", "FALSO"}:
        return False
    return None


def _norm_personality(val: Any) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    text = unicodedata.normalize("NFKD", str(val)).encode("ascii", "ignore").decode().strip().upper()
    if text.startswith("JUR"):
        return "Juridica"
    if text.startswith("NAT"):
        return "Natural"
    return None


def _norm_installment(val: Any) -> str | None:
    """Numero de cuota como texto entero: 12, 12.0, '12', '12.0' y '12,0' dan '12'.

    pandas entrega 12.0 cuando la columna tiene NaN y 12 cuando no; sin normalizar,
    la misma cuota produce claves de deduplicacion distintas segun el archivo.
    """
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    text = str(val).strip()
    if not text:
        return None
    try:
        number = float(text.replace(",", "."))
    except ValueError:
        return text[:20]
    if number.is_integer():
        return str(int(number))
    return text[:20]


def _code_from_reason(reason_text: str | None) -> str | None:
    """Codigo de respuesta derivado del motivo de rechazo (el reporte no trae una columna de codigo).

    Si el motivo empieza con un codigo corto ("R02 - ...", "51: ...") se conserva; si no, se genera
    un identificador estable en mayusculas sin tildes ("Fondos insuficientes" -> FONDOS_INSUFICIENTES).
    """
    if not reason_text or not reason_text.strip():
        return None
    text = unicodedata.normalize("NFKD", reason_text).encode("ascii", "ignore").decode().upper().strip()
    prefix = re.match(r"([A-Z]{0,2}\d{1,3})\s*[-:.)]\s*\S", text)
    if prefix:
        return prefix.group(1)
    prefix = re.fullmatch(r"([A-Z]{0,2}\d{1,3})", text)
    if prefix:
        return prefix.group(1)
    slug = re.sub(r"[^A-Z0-9]+", "_", text).strip("_")
    return slug[:50] or None


def _norm_period(val: Any) -> str | None:
    """Convierte 'AGOSTO 2026' o datetime a 'YYYY-MM'."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    month_names = {
        "ENERO": "01", "ENE": "01", "FEBRERO": "02", "FEB": "02",
        "MARZO": "03", "MAR": "03", "ABRIL": "04", "ABR": "04",
        "MAYO": "05", "MAY": "05", "JUNIO": "06", "JUN": "06", "JULIO": "07", "JUL": "07",
        "AGOSTO": "08", "AGO": "08", "SEPTIEMBRE": "09", "SETIEMBRE": "09", "SEPT": "09", "SEP": "09",
        "OCTUBRE": "10", "OCT": "10", "NOVIEMBRE": "11", "NOV": "11",
        "DICIEMBRE": "12", "DIC": "12",
    }
    try:
        if hasattr(val, "strftime"):
            return val.strftime("%Y-%m")
        s = str(val).strip().upper()
        for month_name, num in month_names.items():
            if month_name in s:
                years = re.findall(r"(?<!\d)\d{4}(?!\d)", s) or re.findall(r"(?<!\d)\d{2}(?!\d)", s)
                if years:
                    year = int(years[-1])
                    return f"{year + 2000 if year < 100 else year}-{num}"
        if re.match(r"\d{4}-\d{2}", s):
            return s[:7]
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Búsqueda flexible de columnas en DataFrames con headers multinivel
# ---------------------------------------------------------------------------

def _find_col(df: pd.DataFrame, *keywords: str) -> Any:
    """
    Devuelve el nombre de columna (puede ser tupla) cuya repr en string
    contiene TODAS las keywords (case-insensitive, sin distinción de acentos).
    Devuelve la primera coincidencia en orden de aparición.
    """
    kws = [k.lower() for k in keywords]

    def col_matches(col: Any) -> bool:
        col_str = " ".join(str(c).lower() for c in (col if isinstance(col, tuple) else (col,)))
        return all(k in col_str for k in kws)

    for col in df.columns:
        if col_matches(col):
            return col
    return None


def _find_leaf_col(df: pd.DataFrame, *keywords: str, exclude: tuple[str, ...] = ()) -> Any:
    """Primera columna cuyo rotulo final (ultimo nivel del encabezado) contiene todas las keywords."""
    for col in df.columns:
        leaf = str(col[-1] if isinstance(col, tuple) else col).lower()
        if all(k in leaf for k in keywords) and not any(x in leaf for x in exclude):
            return col
    return None


def _find_group_leaf(df: pd.DataFrame, group: str, *leaves: str) -> Any:
    """Columna del grupo ``group`` cuyo rotulo final es exactamente uno de ``leaves`` (sin tildes ni mayusculas)."""
    wanted = {unicodedata.normalize("NFKD", leaf).encode("ascii", "ignore").decode().lower() for leaf in leaves}
    for col in df.columns:
        levels = col if isinstance(col, tuple) else (col,)
        if group not in " ".join(str(level).lower() for level in levels[:-1]):
            continue
        leaf = unicodedata.normalize("NFKD", str(levels[-1])).encode("ascii", "ignore").decode().strip().lower()
        if leaf in wanted:
            return col
    return None


def _find_contact_col(df: pd.DataFrame, keyword: str) -> Any:
    """Busca una columna por su etiqueta final dentro del grupo de contacto."""
    for col in df.columns:
        levels = col if isinstance(col, tuple) else (col,)
        group = " ".join(str(level).lower() for level in levels[:-1])
        leaf = str(levels[-1]).lower()
        if "contacto" in group and keyword in leaf:
            return col
    return None


def _col_val(row: pd.Series, col: Any, default: Any = None) -> Any:
    if col is None or col not in row.index:
        return default
    val = row[col]
    if isinstance(val, float) and pd.isna(val):
        return default
    return val


# ---------------------------------------------------------------------------
# Lectura Excel
# ---------------------------------------------------------------------------

SHEET_ACTIVE = "VIGENTES"
SHEET_DELETED = "ELIMINADOS"
SHEET_REJECTED_MANDATES = "RECHAZADOS"
SHEET_ACCEPTED_CHARGES = "CARGOS ACEPTADOS"
SHEET_REJECTED_CHARGES = "CARGOS RECHAZADOS"
SHEET_TABLES = "TABLAS"
SHEET_COLLECTION_HISTORY_CAN = "HISTORICO RECAUDACION CAN"
SHEET_COLLECTION_HISTORY_FLOW = "HISTORICO RECAUDACION FLUJO"


class ReportBook:
    """Un reporte TCH abierto UNA vez (TCH-PAR-16).

    Antes cada ``pd.read_excel`` reabria el libro (10 MB, 33 hojas) y volvia a parsear la hoja: hasta tres lecturas
    por hoja de detalle (encabezado estandar, sondeo y relectura con el encabezado detectado) y dos por TABLAS.
    Ahora el libro se abre una sola vez con openpyxl en modo ``read_only`` (el mismo modo que usa pandas), cada hoja
    se recorre una sola vez y los DataFrame con distintos encabezados se arman en memoria desde esas celdas, con el
    mismo parser de pandas (``TextParser``): el resultado es identico al de ``pd.read_excel``.

    Las celdas de una hoja se guardan solo hasta ``release`` (memoria acotada a la hoja en curso).
    """

    def __init__(self, filepath: Path) -> None:
        from openpyxl import load_workbook

        self.path = Path(filepath)
        # Mismas opciones que pandas (engine openpyxl): sin estilos en memoria y con valores calculados.
        self._book = load_workbook(self.path, read_only=True, data_only=True, keep_links=False)
        self._cells: dict[str, list[list[Any]]] = {}
        self.sheet_reads: dict[str, int] = {}  # cuantas veces se recorrio cada hoja (pruebas de rendimiento)

    def __enter__(self) -> "ReportBook":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self._cells.clear()
        self._book.close()

    @property
    def sheet_names(self) -> list[str]:
        return list(self._book.sheetnames)

    @staticmethod
    def _convert_cell(cell: Any) -> Any:
        """Igual que el lector openpyxl de pandas: vacio -> "", error -> NaN, numero entero -> int."""
        from openpyxl.cell.cell import TYPE_ERROR, TYPE_NUMERIC

        if cell.value is None:
            return ""
        if cell.data_type == TYPE_ERROR:
            return float("nan")
        if cell.data_type == TYPE_NUMERIC:
            as_int = int(cell.value)
            return as_int if as_int == cell.value else float(cell.value)
        return cell.value

    def _sheet_cells(self, sheet: str) -> list[list[Any]]:
        cached = self._cells.get(sheet)
        if cached is not None:
            return cached
        if sheet not in self._book.sheetnames:
            raise ValueError(f"Worksheet named '{sheet}' not found")
        worksheet = self._book[sheet]
        worksheet.reset_dimensions()
        self.sheet_reads[sheet] = self.sheet_reads.get(sheet, 0) + 1
        data: list[list[Any]] = []
        last_with_data = -1
        for number, row in enumerate(worksheet.rows):
            values = [self._convert_cell(cell) for cell in row]
            while values and values[-1] == "":
                values.pop()
            if values:
                last_with_data = number
            data.append(values)
        data = data[: last_with_data + 1]
        if data:
            width = max(len(row) for row in data)
            data = [row + [""] * (width - len(row)) for row in data]
        self._cells[sheet] = data
        return data

    def cells(self, sheet: str) -> list[list[Any]]:
        """Celdas crudas de la hoja (solo lectura; se recorre la hoja una vez y queda en memoria hasta ``release``)."""
        return self._sheet_cells(sheet)

    def has_sheet(self, sheet: str) -> bool:
        return sheet in self._book.sheetnames

    def frame(self, sheet: str, header: int | list[int] | None = None) -> pd.DataFrame:
        """DataFrame de la hoja con el encabezado pedido, como ``pd.read_excel(path, sheet_name=..., header=...)``."""
        from pandas.io.parsers import TextParser

        cells = self._sheet_cells(sheet)
        if not cells:
            return pd.DataFrame()
        data = [list(row) for row in cells]  # el relleno del encabezado multinivel modifica las filas
        if isinstance(header, list) and len(header) == 1:
            header = header[0]
        if isinstance(header, list):
            if max(header) > len(data) - 1:
                raise ValueError(f"header index {max(header)} exceeds maximum index {len(data) - 1} of data.")
            control = [True] * len(data[0])
            for index in header:
                data[index], control = _fill_multiindex_header(data[index], control)
        return TextParser(data, header=header, skip_blank_lines=False).read()

    def release(self, sheet: str) -> None:
        self._cells.pop(sheet, None)


def _fill_multiindex_header(row: list[Any], control: list[bool]) -> tuple[list[Any], list[bool]]:
    """Rellena hacia la derecha los rotulos de grupo vacios (celdas combinadas), igual que pandas en ``read_excel``."""
    last = row[0]
    for i in range(1, len(row)):
        if not control[i]:
            last = row[i]
        if row[i] == "" or row[i] is None:
            row[i] = last
        else:
            control[i] = False
            last = row[i]
    return row, control


def _as_book(source: "Path | ReportBook") -> tuple["ReportBook", bool]:
    """(libro, lo_abri_yo): acepta un ReportBook ya abierto o una ruta (compatibilidad con llamadas antiguas)."""
    if isinstance(source, ReportBook):
        return source, False
    return ReportBook(Path(source)), True


_STANDARD_HEADER = [5, 6]  # filas 6 y 7 del Excel: rotulos de grupo y de columna; datos desde la fila 8


def _detect_header_rows(cells: list[list[Any]], scan_rows: int = 20, scan_cols: int = 15) -> list[int] | None:
    """Filas del encabezado (grupo, columna) segun donde empiezan los datos: las dos filas sobre el primer numero de
    ficha. Busca el rotulo "Ficha" en las primeras filas/columnas y, bajo el, la primera celda numerica positiva.
    None si la hoja no tiene ese rotulo (p. ej. VIGENTES de dic-2023, tabla numerica sin cartera)."""
    label = None
    for i, row in enumerate(cells[:scan_rows]):
        for j, value in enumerate(row[:scan_cols]):
            if isinstance(value, str) and "FICHA" in value.upper():
                label = (i, j)
                break
        if label:
            break
    if label is None:
        return None
    label_row, column = label
    for i in range(label_row + 1, min(len(cells), label_row + 6)):
        value = cells[i][column] if column < len(cells[i]) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and value > 0:
            return [i - 2, i - 1] if i >= 2 else None
    return None


def _read_sheet(source: "Path | ReportBook", sheet: str) -> pd.DataFrame | None:
    """
    Lee una hoja TCH con headers multinivel.
    Intenta header=[5,6] primero (estándar); si no encuentra 'ficha/dues',
    busca la fila que contiene 'FICHA DUES' y usa las dos anteriores como headers.
    La hoja se recorre una sola vez aunque haga falta el sondeo (TCH-PAR-16).
    """
    book, owned = _as_book(source)
    try:
        if not book.has_sheet(sheet):
            log.warning(f"  No se pudo leer hoja '{sheet}': no existe en el reporte")
            return None
        try:
            header = _STANDARD_HEADER
            detected = _detect_header_rows(book.cells(sheet))
            if detected and detected != _STANDARD_HEADER:
                # Layout B (cierre dic-2022): el bloque de encabezado viene una fila mas abajo. Con [5, 6] la fila de
                # rotulos de columna quedaba como primer dato y no se encontraban el RUT ni los bloques mensuales.
                header = detected
                log.info(f"  Encabezado de '{sheet}' detectado en filas {detected[0]}-{detected[1]} (layout desplazado)")
            df = book.frame(sheet, header=header)
            df = df.dropna(how="all")
            cols_str = " ".join(str(c).lower() for c in df.columns)
            if "ficha" in cols_str or "mandato" in cols_str:
                return df
        except Exception as exc:
            log.warning(f"  No se pudo leer hoja '{sheet}': {type(exc).__name__}")
            return None

        # Fallback: buscar la fila más baja que contenga 'FICHA DUES'
        try:
            raw = book.frame(sheet, header=None)
            header_row = None
            for i in range(len(raw)):
                row_str = " ".join(str(v).upper() for v in raw.iloc[i] if not (isinstance(v, float) and pd.isna(v)))
                if "FICHA" in row_str and ("DUES" in row_str or "MANDATO" in row_str):
                    header_row = i
                    # No hacer break: queremos la fila más baja con esos datos
            if header_row is not None:
                # Usar las 3 filas anteriores como headers (puede variar; intentar -2,-1,0)
                h0 = max(0, header_row - 2)
                df2 = book.frame(sheet, header=list(range(h0, header_row + 1)))
                df2 = df2.dropna(how="all")
                log.info(f"  Headers detectados en filas {h0}-{header_row} (fallback)")
                return df2
        except Exception as exc:
            log.warning(f"  Error en fallback de lectura '{sheet}': {type(exc).__name__}")
        return None
    finally:
        book.release(sheet)
        if owned:
            book.close()


def _report_sort_key(filepath: Path) -> tuple[int, int, int, str]:
    dated = re.search(r"(\d{8})", filepath.stem)
    if dated:
        try:
            date = datetime.strptime(dated.group(1), "%Y%m%d")
            return date.year, date.month, date.day, filepath.name
        except ValueError:
            pass
    period = _norm_period(filepath.stem)
    if period:
        year, month = period.split("-", 1)
        return int(year), int(month), 0, filepath.name
    return 0, 0, 0, filepath.name


def _historical_total_rows(df: pd.DataFrame) -> tuple[int, int] | None:
    accepted_row = rejected_row = None
    for row_index, row in df.iterrows():
        values = " ".join(str(value).upper() for value in row.iloc[:3] if pd.notna(value))
        if "TOTAL RECAUDACION EFECTUADA" in values:
            accepted_row = row_index
        if "TOTAL COBROS RECHAZADOS" in values:
            rejected_row = row_index
    if accepted_row is None or rejected_row is None:
        return None
    return accepted_row, rejected_row


def _historical_period_columns(df: pd.DataFrame) -> dict[int, str]:
    periods: dict[int, str] = {}
    for row_index in range(min(4, len(df))):
        for column_index, value in enumerate(df.iloc[row_index]):
            period = _norm_period(value)
            if period:
                periods[column_index] = period
    return periods


def _historical_revenue_values(source: "Path | ReportBook", sheet: str) -> dict[str, tuple[str, str]]:
    try:
        book, owned = _as_book(source)
    except OSError as exc:
        log.warning("  No se pudo abrir el reporte: %s", type(exc).__name__)
        return {}
    try:
        df = book.frame(sheet, header=None)
    except (OSError, ValueError) as exc:
        log.warning("  No se pudo leer hoja '%s': %s", sheet, type(exc).__name__)
        return {}
    finally:
        book.release(sheet)
        if owned:
            book.close()
    total_rows = _historical_total_rows(df)
    if total_rows is None:
        log.warning("  No se encontraron totales en hoja '%s'", sheet)
        return {}
    accepted_row, rejected_row = total_rows
    values: dict[str, tuple[str, str]] = {}
    for column_index, period in _historical_period_columns(df).items():
        accepted = _norm_amount(df.iat[accepted_row, column_index])
        rejected = _norm_amount(df.iat[rejected_row, column_index])
        if accepted is not None and rejected is not None:
            values[period] = accepted, rejected
    return values


def _transform_monthly_collection(source: "Path | ReportBook") -> list[dict]:
    book, owned = _as_book(source)
    try:
        amounts = _historical_revenue_values(book, SHEET_COLLECTION_HISTORY_FLOW)
        counts = _historical_revenue_values(book, SHEET_COLLECTION_HISTORY_CAN)
    finally:
        if owned:
            book.close()
    filepath = book.path
    periods = sorted(amounts.keys() & counts.keys())
    # Las hojas de control traen meses futuros en cero (hasta 2027-12). El corte es el ultimo mes
    # cerrado: el mes que nombra el reporte, sin pasar del ultimo mes con cobros en el propio control.
    with_charges = [p for p in periods if int(counts[p][0]) + int(counts[p][1]) > 0]
    limits = [p for p in (_report_period(filepath), with_charges[-1] if with_charges else None) if p]
    cutoff = min(limits) if limits else None
    rows = []
    for period in periods:
        if cutoff and period > cutoff:
            continue
        accepted_amount, rejected_amount = amounts[period]
        accepted_count, rejected_count = counts[period]
        rows.append({
            "periodo": period,
            "aceptadas_cantidad": int(accepted_count),
            "aceptadas_monto": accepted_amount,
            "rechazadas_cantidad": int(rejected_count),
            "rechazadas_monto": rejected_amount,
            "archivo_origen": filepath.name,
        })
    return rows


# ---------------------------------------------------------------------------
# Tablas de control adicionales (TCH-PAR-10): FLUJO MANDATOS, RECHAZOS, ENT RECHAZOS, KPI
# ---------------------------------------------------------------------------
# Lectores tolerantes: buscan rotulos (meses en el encabezado, "Motivo", "Cantidad", "Monto") en vez de posiciones
# fijas. Si una hoja no tiene la forma esperada se omite con un aviso y la carga sigue: estas tablas son controles
# agregados y nunca deben hacer fallar la carga de mandatos y cargos. Solo guardan rotulos y numeros: un rotulo con
# forma de RUT o de correo se descarta.

SHEET_FLOW_COUNT = "FLUJO MANDATOS CANT"
SHEET_FLOW_AMOUNT = "FLUJO MANDATOS MONTO"
SHEET_REJECTION_REASONS = "RECHAZOS"
SHEET_ENTITY_REJECTIONS = "ENT RECHAZOS"
SHEET_KPI = "KPI"

_PERIOD_HEADER = re.compile(r"^[A-Z]{3,10}\.?[\s\-/']*\d{2,4}$")
_LOOKS_PERSONAL = re.compile(r"@|\b\d{1,2}\.?\d{3}\.?\d{3}-[\dK]\b", re.IGNORECASE)


def _plain_upper(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().upper().strip()


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value


def _control_label(value: Any, max_len: int = 150) -> str | None:
    """Rotulo de una celda de control: texto no vacio, espacios colapsados, sin forma de RUT ni de correo."""
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    if not text or _LOOKS_PERSONAL.search(text):
        return None
    return text[:max_len]


def _header_period(value: Any) -> str | None:
    """Mes de una celda de encabezado ("ENE 21", "SEPT 2026", fecha). Mas estricto que _norm_period para no leer
    meses dentro de palabras ("INDICADOR 2025")."""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m")
    if isinstance(value, str):
        text = _plain_upper(value)
        if _PERIOD_HEADER.match(text) or re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", text):
            return _norm_period(text)
    return None


def _control_cells(book: ReportBook, sheet: str) -> list[list[Any]] | None:
    if not book.has_sheet(sheet):
        return None
    try:
        return book.cells(sheet)
    except (OSError, ValueError) as exc:
        log.warning("  No se pudo leer hoja '%s': %s", sheet, type(exc).__name__)
        return None


def _flow_kind(label: str) -> str:
    text = _plain_upper(label)
    if "VIGENTE" in text:
        return "vigentes"
    if any(word in text for word in ("ALTA", "NUEV", "INGRES", "NVO")):
        return "altas"
    if any(word in text for word in ("BAJA", "ELIMIN", "ELI ")):
        return "bajas"
    return "otro"


def _flow_values(book: ReportBook, sheet: str, cutoff: str | None) -> dict[tuple[str, str, str], Any]:
    """(periodo, entidad, concepto) -> valor crudo de una hoja FLUJO MANDATOS.

    Encabezado: la primera fila (de las 15 primeras) con al menos dos meses. A la izquierda del primer mes van los
    rotulos: dos o mas rotulos = entidad y concepto; uno solo = concepto (si es vigentes/altas/bajas) de la ultima
    entidad vista, o entidad de una hoja de un solo concepto. Una fila con rotulo y sin numeros es un titulo de
    seccion (entidad). Se omiten los meses posteriores al reporte y los posteriores al ultimo mes con datos.
    """
    cells = _control_cells(book, sheet)
    if not cells:
        return {}
    try:
        header_index = periods = None
        for index, row in enumerate(cells[:15]):
            found = {column: period for column, value in enumerate(row) if (period := _header_period(value))}
            if len(found) >= 2:
                header_index, periods = index, found
                break
        if header_index is None or not periods:
            log.warning("  Hoja '%s' sin encabezado de meses reconocible: se omite", sheet)
            return {}
        first_period_column = min(periods)
        section: str | None = None
        values: dict[tuple[str, str, str], Any] = {}
        for row in cells[header_index + 1:]:
            labels = [label for value in row[:first_period_column] if (label := _control_label(value))]
            numbers = {
                period: row[column]
                for column, period in periods.items()
                if column < len(row) and _is_number(row[column])
            }
            if not labels:
                continue
            if not numbers:
                section = labels[0]
                continue
            if len(labels) >= 2:
                entity, concept = labels[0], " / ".join(labels[1:])[:150]
                section = entity
            elif _flow_kind(labels[0]) != "otro":
                entity, concept = section or "TOTAL", labels[0]
            else:
                entity, concept = labels[0], section or "TOTAL"
            for period, value in numbers.items():
                values[(period, entity, concept)] = value
        with_data = [key[0] for key, value in values.items() if value]
        limits = [p for p in (cutoff, max(with_data) if with_data else None) if p]
        limit = min(limits) if limits else None
        return {key: value for key, value in values.items() if limit is None or key[0] <= limit}
    finally:
        book.release(sheet)


def _transform_mandate_flow(book: ReportBook, cutoff: str | None) -> list[dict]:
    """Filas de tch_flujo_mandatos desde FLUJO MANDATOS CANT (cantidad) y FLUJO MANDATOS MONTO (monto)."""
    counts = _flow_values(book, SHEET_FLOW_COUNT, cutoff)
    amounts = _flow_values(book, SHEET_FLOW_AMOUNT, cutoff)
    rows = []
    for key in sorted(counts.keys() | amounts.keys()):
        period, entity, concept = key
        rows.append({
            "periodo": period,
            "entidad": entity,
            "concepto": concept,
            "tipo": _flow_kind(concept),
            "cantidad": _norm_count(counts.get(key)),
            "monto": _norm_amount(amounts.get(key)),
            "archivo_origen": book.path.name[:255],
        })
    return rows


def _find_header_column(header: list[Any], *words: str, skip: tuple[int, ...] = ()) -> int | None:
    for column, value in enumerate(header):
        label = _control_label(value)
        if column not in skip and label and any(word in _plain_upper(label) for word in words):
            return column
    return None


_ENTITY_HEADERS = {"ENTIDAD", "ENTIDADRECAUDADORA", "BANCO", "BANCOINSTITUCION", "INSTITUCION", "ENTIDADBANCO"}


def _transform_rejection_reasons(book: ReportBook, sheet: str, report_period: str | None) -> list[dict]:
    """Filas de tch_rechazos_motivo desde RECHAZOS o ENT RECHAZOS.

    Encabezado: la primera fila (de las 20 primeras) con una celda "Motivo". Formas reconocidas:
    * columnas "Cantidad"/"N°" y "Monto" (y opcionalmente "Entidad"/"Banco");
    * matriz motivo x entidad: cada columna a la derecha del motivo es una entidad con su cantidad;
    * bloques por entidad: una fila con rotulo en la columna del motivo y sin numeros fija la entidad siguiente.
    Se omiten las filas TOTAL y las que no traen numeros.
    """
    if not report_period:
        if book.has_sheet(sheet):
            log.warning("  Hoja '%s' omitida: no se pudo determinar el mes del reporte", sheet)
        return []
    cells = _control_cells(book, sheet)
    if not cells:
        return []
    try:
        header_index = reason_column = None
        for index, row in enumerate(cells[:20]):
            column = _find_header_column(row, "MOTIVO")
            if column is not None:
                header_index, reason_column = index, column
                break
        if header_index is None or reason_column is None:
            log.warning("  Hoja '%s' sin columna 'Motivo' reconocible: se omite", sheet)
            return []
        header = cells[header_index]
        skip = (reason_column,)
        # Columna de entidad solo con un rotulo generico ("Entidad", "Banco/Institucion"): un rotulo como "Banco
        # Estado" es una entidad de la matriz, no el nombre de la columna.
        entity_column = next(
            (
                column for column, value in enumerate(header)
                if column != reason_column and (label := _control_label(value))
                and re.sub(r"[^A-Z]", "", _plain_upper(label)) in _ENTITY_HEADERS
            ),
            None,
        )
        count_column = _find_header_column(header, "CANT", "NRO", "NUMERO", "CASOS", skip=skip)
        amount_column = _find_header_column(header, "MONTO", skip=skip)
        matrix_columns: dict[int, str] = {}
        if entity_column is None and count_column is None and amount_column is None:
            for column in range(reason_column + 1, len(header)):
                label = _control_label(header[column])
                if label and not _plain_upper(label).startswith("TOTAL"):
                    matrix_columns[column] = label
        out: dict[tuple[str, str], dict] = {}
        current_entity = ""
        for row in cells[header_index + 1:]:
            reason = _control_label(row[reason_column] if reason_column < len(row) else None, 255)
            if not reason or "MOTIVO" in _plain_upper(reason):
                continue
            if _plain_upper(reason).startswith("TOTAL"):
                continue
            numeric = [row[c] for c in range(reason_column + 1, len(row)) if _is_number(row[c])]
            if matrix_columns:
                for column, entity in matrix_columns.items():
                    if column < len(row) and _is_number(row[column]):
                        out[(entity, reason)] = {"cantidad": _norm_count(row[column]), "monto": None}
                continue
            if not numeric:
                if entity_column is None:
                    current_entity = reason[:150]  # titulo de bloque por entidad
                continue
            if entity_column is not None:
                current_entity = _control_label(row[entity_column] if entity_column < len(row) else None) or current_entity
            count = row[count_column] if count_column is not None and count_column < len(row) else None
            amount = row[amount_column] if amount_column is not None and amount_column < len(row) else None
            if count_column is None and amount_column is None:
                count = numeric[0]
                amount = numeric[1] if len(numeric) > 1 else None
            out[(current_entity, reason)] = {
                "cantidad": _norm_count(count) if _is_number(count) else None,
                "monto": _norm_amount(amount) if _is_number(amount) else None,
            }
        return [
            {
                "reporte_periodo": report_period,
                "hoja": sheet,
                "entidad": entity,
                "motivo": reason,
                **measures,
                "archivo_origen": book.path.name[:255],
            }
            for (entity, reason), measures in sorted(out.items())
        ]
    finally:
        book.release(sheet)


def _kpi_value(value: Any) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{float(value):.6f}".rstrip("0").rstrip(".")


def _transform_kpi(book: ReportBook, report_period: str | None) -> list[dict]:
    """Filas de tch_kpi_reporte: por fila, el primer rotulo y el primer numero a su derecha.

    Una fila con rotulo y sin numero es un titulo de seccion y se antepone ("Seccion / Indicador"). Un indicador
    repetido se numera ("Indicador (2)").
    """
    if not report_period:
        if book.has_sheet(SHEET_KPI):
            log.warning("  Hoja '%s' omitida: no se pudo determinar el mes del reporte", SHEET_KPI)
        return []
    cells = _control_cells(book, SHEET_KPI)
    if not cells:
        return []
    try:
        section: str | None = None
        out: dict[str, str] = {}
        for row in cells:
            label_column = next((c for c, v in enumerate(row) if _control_label(v)), None)
            if label_column is None:
                continue
            label = _control_label(row[label_column])
            number = next((v for v in row[label_column + 1:] if _is_number(v)), None)
            if number is None:
                section = label
                continue
            indicator = f"{section} / {label}" if section else label
            indicator = indicator[:240]
            name, suffix = indicator, 2
            while name in out:
                name, suffix = f"{indicator} ({suffix})", suffix + 1
            out[name] = _kpi_value(number)
        return [
            {"reporte_periodo": report_period, "indicador": name, "valor": value, "archivo_origen": book.path.name[:255]}
            for name, value in out.items()
        ]
    finally:
        book.release(SHEET_KPI)


def _upsert_control_rows(db, model, rows: list[dict], constraint: str, measures: tuple[str, ...]) -> int:
    """Upsert "el ultimo reporte gana"; una medida ausente en el reporte nuevo no borra la que ya habia."""
    if not rows:
        return 0
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    table = model.__table__
    statement = pg_insert(model).values([{"id": uuid.uuid4(), **row} for row in rows])
    updates = {name: func.coalesce(statement.excluded[name], table.c[name]) for name in measures}
    updates["archivo_origen"] = statement.excluded.archivo_origen
    updates["updated_at"] = func.now()
    db.execute(statement.on_conflict_do_update(constraint=constraint, set_=updates))
    db.flush()
    return len(rows)


def _load_control_tables(db, book: ReportBook, report_period: str | None) -> dict[str, int]:
    """TCH-PAR-10: carga FLUJO MANDATOS, RECHAZOS, ENT RECHAZOS y KPI. Un fallo aqui solo deja un aviso."""
    counts = {"flujo_mandatos": 0, "rechazos_motivo": 0, "kpi": 0}
    try:
        with db.begin_nested():
            counts["flujo_mandatos"] = _upsert_control_rows(
                db, TchMandateFlow, _transform_mandate_flow(book, report_period),
                "uq_tch_flujo_mandatos_clave", ("cantidad", "monto"),
            )
            reasons = _transform_rejection_reasons(book, SHEET_REJECTION_REASONS, report_period)
            reasons += _transform_rejection_reasons(book, SHEET_ENTITY_REJECTIONS, report_period)
            counts["rechazos_motivo"] = _upsert_control_rows(
                db, TchRejectionReason, reasons, "uq_tch_rechazos_motivo_clave", ("cantidad", "monto"),
            )
            counts["kpi"] = _upsert_control_rows(
                db, TchReportKpi, _transform_kpi(book, report_period), "uq_tch_kpi_reporte_clave", ("valor",),
            )
    except Exception as exc:  # los controles agregados nunca hacen fallar la carga del reporte
        log.warning("  Tablas de control adicionales omitidas: %s", type(exc).__name__)
        return {"flujo_mandatos": 0, "rechazos_motivo": 0, "kpi": 0}
    return counts


def _content_period(transaction_rows: list[dict]) -> str | None:
    """Mes del reporte desde su contenido: el ultimo "Cuota Mes" de las hojas CARGOS."""
    periods = [row["periodo"] for row in transaction_rows if row.get("origen") == ORIGIN_CHARGE and row.get("periodo")]
    return max(periods) if periods else None


# ---------------------------------------------------------------------------
# Transformaciones — VIGENTES / ELIMINADOS
# ---------------------------------------------------------------------------

_MANDATE_STATES = {
    "ACTIVO": "VIGENTE", "ACTIVA": "VIGENTE", "VIGENTE": "VIGENTE",
    "PENDIENTE": "PENDIENTE",
    "RECHAZADO": "RECHAZADA", "RECHAZADA": "RECHAZADA",
    "ELIMINADO": "ELIMINADA", "ELIMINADA": "ELIMINADA",
}


def _find_status_col(df: pd.DataFrame) -> Any:
    """Columna ESTADO del mandato (grupo ANTECEDENTES Y ESTADO MANDATO).

    Los 12 bloques mensuales "N / Estado / Monto" repiten el rotulo "Estado" mas a la derecha;
    la primera coincidencia exacta del rotulo final es la del mandato.
    """
    for col in df.columns:
        leaf = str(col[-1] if isinstance(col, tuple) else col).strip().lower()
        if re.fullmatch(r"estado(\.\d+)?", leaf):
            return col
    return None


def _mandate_status(raw_value: Any, sheet_default: str) -> str:
    """Estado de la ficha desde la columna ESTADO; si falta o no se reconoce, el de la hoja de origen."""
    if raw_value is None or (isinstance(raw_value, float) and pd.isna(raw_value)):
        return sheet_default
    return _MANDATE_STATES.get(str(raw_value).strip().upper(), sheet_default)


def _transform_subscriptions(df: pd.DataFrame, status: str) -> list[dict]:
    """
    ``estado`` es el valor por defecto segun la hoja; manda la columna ESTADO del reporte.

    Mapeo de columnas reales del sheet VIGENTES/ELIMINADOS (estructura 2025-2026):
      ('Ficha DUES', ...)          → numero_ficha
      ('Mandato DUES', ...)        → numero_mandato
      ('SOCIO', 'Rut')             → cliente_rut
      ('SOCIO', 'Nombre/Apellido') → nombre/apellido
      ('ANTECEDENTES...', 'Tipo Mandato') → tipo_mandato
      ('ANTECEDENTES...', 'Banco/Institucion') → banco_nombre
      etc.
    """
    rows = []

    # IDs de suscripción
    col_file_number = _find_col(df, "ficha", "dues") or _find_col(df, "ficha")
    col_mandate = _find_col(df, "mandato", "dues")

    # Datos del socio
    col_rut = _find_col(df, "socio", "rut") or _find_col(df, "rut")
    col_first_name = _find_col(df, "socio", "nombre") or _find_col(df, "nombre")
    col_last_name = _find_col(df, "socio", "apellido") or _find_col(df, "apellido")
    col_birth_date = _find_col(df, "nacimiento")
    col_profession = _find_col(df, "profesi")
    col_member_type = _find_col(df, "tipo", "socio")
    col_law = _find_col(df, "socio", "ley") or _find_col(df, "ley")
    col_adjustment = _find_col(df, "reajuste")
    col_phone = _find_contact_col(df, "telefono")
    col_email = _find_contact_col(df, "email")
    col_address = _find_contact_col(df, "direccion")
    col_street_number = _find_contact_col(df, "numero")
    col_house_apartment = _find_contact_col(df, "casa") or _find_contact_col(df, "depto")
    col_neighborhood = _find_contact_col(df, "villa") or _find_contact_col(df, "pob")
    col_district = _find_contact_col(df, "comuna")
    col_city = _find_contact_col(df, "ciudad")

    # Datos titular
    col_holder_rut = _find_col(df, "titular", "rut")

    # Antecedentes mandato
    col_signature = _find_col(df, "antecedentes", "firma") or _find_col(df, "firma")
    col_mandate_type = _find_col(df, "antecedentes", "tipo", "mandato") or _find_col(df, "tipo", "mandato")
    col_bank = _find_col(df, "banco") or _find_col(df, "institucion")
    col_account_type = _find_col(df, "tipo", "cuenta")
    col_account_number = _find_col(df, "numero", "cuenta")
    # "Ingreso" (grupo ANTECEDENTES) es una fecha; el monto del mandato es "Monto Vigente" (MANDATO ACTUAL).
    col_amount = _find_col(df, "monto", "vigente")
    col_currency = _find_col(df, "moneda", "vigente")
    col_peso_equivalent = _find_col(df, "equivalente", "pesos")
    col_activation_date = _find_col(df, "activac")
    # ('ANTECEDENTES Y ESTADO MANDATOS', 'Ingreso'): fecha de ingreso del mandato, llena en VIGENTES y ELIMINADOS.
    # Rotulo exacto (no "contiene"): "ingreso" podria aparecer en otros rotulos de montos.
    col_entry_date = _find_group_leaf(df, "antecedentes", "ingreso") or _find_group_leaf(df, "", "ingreso")
    col_bank_delivery_date = _find_col(df, "entrega", "banco")
    col_rejection_date = _find_col(df, "fecha", "rechazo")
    col_deletion_date = _find_col(df, "fecha", "eliminado") or _find_col(df, "fecha", "eliminac") or _find_col(df, "fecha", "baja")
    col_reason = _find_col(df, "motivo") or _find_col(df, "raz")
    col_status = _find_status_col(df)

    # TCH-PAR-09
    col_strategy = _find_col(df, "estrategia")
    col_place = _find_col(df, "lugar")
    col_folio = _find_col(df, "folio")
    col_reference = _find_col(df, "socio", "referencia")
    col_personality = _find_col(df, "personalidad")
    col_region = _find_leaf_col(df, "regi")
    col_first_charge_date = _find_col(df, "actual", "primer", "fecha")
    col_first_charge_amount = _find_col(df, "actual", "primer", "monto")
    col_installments_charged = _find_col(df, "actual", "cuotas cobradas")
    col_amount_charged = _find_col(df, "actual", "monto cobrado")
    col_contribution_installments = _find_col(df, "aportes", "cuotas")
    col_contribution_amount = _find_col(df, "aportes", "monto")
    col_average = _find_col(df, "promedio")
    col_months_without_contribution = _find_col(df, "sin aporte")
    col_tenure_months = _find_group_leaf(df, "permanencia", "meses")
    col_tenure_years = _find_group_leaf(df, "permanencia", "años", "anos")
    col_new_flag = _find_leaf_col(df, "nvo")
    col_rejected_flag = _find_leaf_col(df, "rech", "mes")
    col_deleted_flag = _find_leaf_col(df, "eli", "mes")

    # Captación
    col_origin = _find_col(df, "origen")
    col_cost_center = _find_col(df, "centro", "costo")
    col_recruiter = _find_col(df, "captador")

    if col_file_number is None:
        log.warning("  No se encontró columna 'Ficha DUES' en el sheet")
        return rows

    for _, row in df.iterrows():
        file_number = _norm_int(_col_val(row, col_file_number))
        if file_number is None:
            continue
        rut = _norm_rut(_col_val(row, col_rut))

        # El titular de la cuenta puede ser un tercero: sus datos no se guardan ni en el payload.
        raw = sanitize_payload({
            str(k): (None if isinstance(v, float) and pd.isna(v) else str(v))
            for k, v in row.items()
            if "titular" not in str(k).lower()
        })
        currency = normalize_tch_currency(_col_val(row, col_currency))
        raw["moneda_vigente"] = currency  # tambien en el payload: filas cargadas antes de la columna `moneda`

        personality = _norm_personality(_col_val(row, col_personality))
        rut_titular = _norm_rut(_col_val(row, col_holder_rut)) if col_holder_rut else None
        # Solo un indicador: el RUT y el nombre del titular (un tercero) no se guardan.
        different_holder = (rut_titular != rut) if (rut_titular and rut) else None

        subscription_row = {
            "numero_ficha": file_number,
            "numero_mandato": _norm_int(_col_val(row, col_mandate)),
            "cliente_rut": rut,
            "banco_nombre": _norm_str(_col_val(row, col_bank), 100),
            "tipo_mandato": _norm_str(_col_val(row, col_mandate_type), 20),
            "tipo_cuenta": _norm_str(_col_val(row, col_account_type), 50),
            "numero_cuenta": _norm_str(_col_val(row, col_account_number), 50),
            "origen": _norm_str(_col_val(row, col_origin), 150),
            "centro_costo": _norm_str(_col_val(row, col_cost_center), 150),
            "captador": _norm_str(_col_val(row, col_recruiter), 150),
            "ley": _norm_str(_col_val(row, col_law), 50),
            "reajuste": _norm_str(_col_val(row, col_adjustment), 10),
            "firma": _norm_str(_col_val(row, col_signature), 10),
            "monto": _norm_amount(_col_val(row, col_amount)),
            "moneda": currency,
            "equivalente_pesos": _norm_amount(_col_val(row, col_peso_equivalent)),
            "fecha_activacion": _norm_date(_col_val(row, col_activation_date)),
            "fecha_ingreso": _norm_date(_col_val(row, col_entry_date)),
            "fecha_entrega_banco": _norm_date(_col_val(row, col_bank_delivery_date)),
            "fecha_rechazo": _norm_date(_col_val(row, col_rejection_date)),
            "fecha_eliminacion": _norm_date(_col_val(row, col_deletion_date)),
            "razon_baja": _norm_str(_col_val(row, col_reason), 500),
            "estado": _mandate_status(_col_val(row, col_status), status),
            "estrategia": _norm_str(_col_val(row, col_strategy), 150),
            "lugar_captacion": _norm_str(_col_val(row, col_place), 150),
            "folio": _norm_str(_col_val(row, col_folio), 50),
            "referencia": _norm_str(_col_val(row, col_reference), 30),
            "personalidad": personality,
            "titular_distinto": different_holder,
            "fecha_primer_cobro": _norm_date(_col_val(row, col_first_charge_date)),
            "monto_primer_cobro": _norm_amount(_col_val(row, col_first_charge_amount)),
            "cuotas_cobradas": _norm_count(_col_val(row, col_installments_charged)),
            "monto_cobrado": _norm_amount(_col_val(row, col_amount_charged)),
            "aportes_cuotas": _norm_count(_col_val(row, col_contribution_installments)),
            "aportes_monto": _norm_amount(_col_val(row, col_contribution_amount)),
            "promedio_donacion": _norm_amount(_col_val(row, col_average)),
            "meses_sin_aporte": _norm_count(_col_val(row, col_months_without_contribution)),
            "permanencia_meses": _norm_count(_col_val(row, col_tenure_months)),
            "permanencia_anos": _norm_count(_col_val(row, col_tenure_years)),
            "nvo_mes": _norm_bool(_col_val(row, col_new_flag)),
            "rech_mes": _norm_bool(_col_val(row, col_rejected_flag)),
            "eli_mes": _norm_bool(_col_val(row, col_deleted_flag)),
            "raw_payload": raw,
            "_cliente": {
                "rut": rut,
                "nombre": _norm_str(_col_val(row, col_first_name), 150),
                "apellido": _norm_str(_col_val(row, col_last_name), 150),
                "fecha_nacimiento": _norm_date(_col_val(row, col_birth_date)),
                "profesion": _norm_str(_col_val(row, col_profession), 100),
                "tipo_persona": personality or "Natural",
                "tipo_socio": _norm_str(_col_val(row, col_member_type), 50),
                "telefono": _norm_str(_col_val(row, col_phone), 100),
                "email": _norm_str(_col_val(row, col_email), 320),
                "direccion": " ".join(
                    part
                    for part in (
                        _norm_str(_col_val(row, col_address), 200),
                        _norm_str(_col_val(row, col_street_number), 50),
                        _norm_str(_col_val(row, col_house_apartment), 100),
                        _norm_str(_col_val(row, col_neighborhood), 100),
                    )
                    if part
                ) or None,
                "comuna": _norm_str(_col_val(row, col_district), 150),
                "ciudad": _norm_str(_col_val(row, col_city), 150),
                "region": _norm_str(_col_val(row, col_region), 100),
            } if rut else None,
            "_cliente_titular": None,
        }

        rows.append(subscription_row)
    return rows


# ---------------------------------------------------------------------------
# Transformaciones — CARGOS ACEPTADOS / RECHAZADOS
# ---------------------------------------------------------------------------

def _dedupe_key(file_number: int, period: str | None, installment: str | None) -> str:
    """Clave estable de una cuota: ficha | periodo real | cuota (D13, TCH-PAR-03).

    NO lleva estado ni monto: en la fuente cada cuota tiene un estado final, de modo que un rechazo seguido de un pago
    (o un cambio de monto en un reporte posterior) actualiza la MISMA fila. La cuota se normaliza aqui tambien:
    '12', '12.0' y 12.0 dan la misma clave.
    """
    return "|".join([str(file_number), period or "", _norm_installment(installment) or ""])


def _charge_status(status: str) -> str:
    normalized = status.strip().upper()
    if normalized in {"PAGADA", "PAGADO", "ACEPTADA", "ACEPTADO"}:
        return "ACEPTADA"
    if normalized in {"IMPAGA", "IMPAGO", "RECHAZADA", "RECHAZADO"}:
        return "RECHAZADA"
    return normalized


def _transform_transactions(df: pd.DataFrame, status: str, file_name: str) -> list[dict]:
    """
    Estructura real de CARGOS (header=[5,6]):
      ('Número Ficha', ...)              → numero_ficha
      ('Número Mandato', ...)            → numero_mandato
      ('Entidad Recaudadora', ...)       → entidad_recaudadora
      ('Transacción', ...)               → tipo_transaccion
      ('Numero Pagos del Mandato', ...)  → total_cuotas
      ('DETALLE DEL PAGO', 'Periodo')    → NO se usa: es un correlativo 1..n, no un mes
      ('DETALLE DEL PAGO', 'Cuota Mes')  → periodo (mes real del cargo, p. ej. "SEPT 26")
      ('DETALLE DEL PAGO', 'N° Cuota')  → numero_cuota
      ('DETALLE DEL PAGO', 'Monto Cuota') → monto
      ('DETALLE DEL PAGO', 'Fecha Cobro') → fecha_cargo
    """
    rows = []

    col_file_number = _find_col(df, "ficha")
    col_mandate = _find_col(df, "ndato")  # Número Mandato (sin tildes posibles)
    col_collecting_entity = _find_col(df, "entidad") or _find_col(df, "recaudadora")
    col_type = _find_col(df, "transacci")
    col_total_installments = _find_col(df, "pagos", "mandato")
    # El periodo real es "Cuota Mes". Ni la columna numerica "Periodo" ni el nombre del archivo
    # (que puede llevar la fecha del dia siguiente al cierre o no llevar fecha) definen el mes.
    col_installment_month = _find_leaf_col(df, "cuota", "mes")
    # 'N° Cuota' (excluye 'Cuota Mes' y 'Monto Cuota')
    col_installment = (
        _find_leaf_col(df, "cuota", exclude=("mes", "monto"))
        or _find_col(df, "detalle", "cuota")
        or _find_col(df, "n", "cuota")
    )
    col_amount = (
        _find_col(df, "total", "carg")
        or _find_col(df, "total", "rechaz")
        or _find_col(df, "monto", "cuota")
        or _find_col(df, "monto")
    )
    col_date = _find_col(df, "fecha", "cobro") or _find_col(df, "fecha", "intento") or _find_col(df, "fecha", "cargo")
    # Codigo explicito si el reporte lo trae; si no se deriva de "Motivo" (solo en CARGOS RECHAZADOS).
    col_code = _find_leaf_col(df, "codigo") or _find_leaf_col(df, "código") or _find_leaf_col(df, "respuesta")
    # Ojo: buscar "rechazo" en cualquier nivel caia en el grupo "DETALLE DEL RECHAZO" (columna Periodo).
    col_reason = _find_leaf_col(df, "motivo") or _find_leaf_col(df, "raz")

    if col_file_number is None:
        log.warning(f"  No se encontró columna 'Número Ficha' en transacciones ({status})")
        return rows
    if col_installment_month is None:
        log.warning(f"  No se encontró columna 'Cuota Mes' en transacciones ({status}); no se cargan cargos sin periodo real")
        return rows

    without_period = 0
    for _, row in df.iterrows():
        file_number_raw = _col_val(row, col_file_number)
        if file_number_raw is None or (isinstance(file_number_raw, float) and pd.isna(file_number_raw)):
            continue
        try:
            file_number = int(float(file_number_raw))
        except Exception:
            continue
        if file_number <= 0:
            continue

        period = _norm_period(_col_val(row, col_installment_month))
        if period is None:
            without_period += 1
            continue
        raw = sanitize_payload({str(k): (None if isinstance(v, float) and pd.isna(v) else str(v)) for k, v in row.items()})

        installment = _norm_installment(_col_val(row, col_installment)) if col_installment else None
        amount = _norm_amount(_col_val(row, col_amount))
        reason = _norm_str(_col_val(row, col_reason), 500) if col_reason else None
        code = (_norm_str(_col_val(row, col_code), 50) if col_code else None) or _code_from_reason(reason)
        rows.append({
            "numero_ficha": file_number,
            "numero_mandato": _norm_int(_col_val(row, col_mandate)),
            "periodo": period,
            "numero_cuota": installment,
            "total_cuotas": _norm_installment(_col_val(row, col_total_installments)) if col_total_installments else None,
            "monto": amount,
            "fecha_cargo": _norm_date(_col_val(row, col_date)),
            "tipo_transaccion": _norm_str(_col_val(row, col_type), 50) if col_type else None,
            "estado": status,
            "entidad_recaudadora": _norm_str(_col_val(row, col_collecting_entity), 100) if col_collecting_entity else None,
            "codigo_respuesta": code,
            "razon_rechazo": reason,
            "archivo_origen": file_name,
            "dedupe_key": _dedupe_key(file_number, period, installment),
            "origen": ORIGIN_CHARGE,
            "reporte_periodo": None,
            "rechazo_previo": None,
            "rechazo_previo_motivo": None,
            "rechazo_previo_en": None,
            "raw_payload": raw,
        })
    if without_period:
        log.warning(f"  {without_period} cargos ({status}) omitidos: 'Cuota Mes' vacio o ilegible")
    return rows


def _transform_charge_history(df: pd.DataFrame, file_name: str) -> list[dict]:
    """Desnormaliza BK:CT: cada mes contiene N°, Estado y Monto.

    TCH-PAR-04: es el ESTADO MENSUAL de un mandato, sin fecha de cobro. Un mandato RECHAZADO (nunca cobro) repite
    "Rechazada" cada mes: es estado de mandato, no un cobro rechazado, y se omite. Los cobros reales vienen solo de
    las hojas CARGOS; estas filas (origen 'historial') solo completan los meses que ningun CARGOS detalla.
    """
    col_file_number = _find_col(df, "ficha", "dues") or _find_col(df, "ficha")
    col_mandate = _find_col(df, "mandato", "dues")
    col_mandate_status = _find_status_col(df)
    if col_file_number is None:
        return []

    rows = []
    for _, row in df.iterrows():
        file_number = _norm_int(_col_val(row, col_file_number))
        if file_number is None:
            continue
        if col_mandate_status is not None and _mandate_status(_col_val(row, col_mandate_status), "") == "RECHAZADA":
            continue
        mandate = _norm_int(_col_val(row, col_mandate))
        for start in range(62, min(98, len(df.columns)), 3):
            period = _norm_period(df.columns[start][0] if isinstance(df.columns[start], tuple) else df.columns[start])
            if not period:
                continue
            installment = _norm_installment(_col_val(row, df.columns[start]))
            status = _norm_str(_col_val(row, df.columns[start + 1]), 20)
            amount = _norm_amount(_col_val(row, df.columns[start + 2]))
            if not status:
                continue
            original_status = status.upper()
            status = _charge_status(status)
            rows.append(
                {
                    "numero_ficha": file_number,
                    "numero_mandato": mandate,
                    "periodo": period,
                    "numero_cuota": installment,
                    "total_cuotas": None,
                    "monto": amount,
                    "fecha_cargo": None,
                    "tipo_transaccion": "HISTORIAL_MENSUAL",
                    "estado": status,
                    "entidad_recaudadora": None,
                    "codigo_respuesta": None,
                    "razon_rechazo": None,
                    "archivo_origen": file_name,
                    "dedupe_key": _dedupe_key(file_number, period, installment),
                    "origen": ORIGIN_HISTORY,
                    "reporte_periodo": None,
                    "rechazo_previo": None,
                    "rechazo_previo_motivo": None,
                    "rechazo_previo_en": None,
                    "raw_payload": {"periodo": period, "numero_cuota": installment, "estado_original": original_status, "monto": amount},
                }
            )
    return rows


# ---------------------------------------------------------------------------
# Transformaciones — TABLAS (catálogo de bancos)
# ---------------------------------------------------------------------------

def _transform_banks_from_tables(source: "Path | ReportBook") -> list[dict]:
    """Lee la hoja TABLAS y extrae el catálogo de instituciones (la hoja se recorre una sola vez)."""
    try:
        book, owned = _as_book(source)
    except Exception:
        return []
    try:
        try:
            df = book.frame(SHEET_TABLES, header=None)
        except Exception:
            return []

        # Buscar fila que contenga la cabecera de entidades
        header_row = None
        for i, row in df.iterrows():
            vals = [str(v).strip().upper() for v in row if not (isinstance(v, float) and pd.isna(v))]
            if any("NOMBRE" in v for v in vals) and any("COD" in v for v in vals):
                header_row = i
                break

        if header_row is None:
            return []

        df_banks = book.frame(SHEET_TABLES, header=header_row)
    finally:
        book.release(SHEET_TABLES)
        if owned:
            book.close()
    df_banks = df_banks.dropna(how="all")

    col_first_name = _find_col(df_banks, "nombre")
    col_internal_code = _find_col(df_banks, "interno") or _find_col(df_banks, "int")
    col_group_code = _find_col(df_banks, "grupo") or _find_col(df_banks, "grp")

    if col_first_name is None:
        return []

    rows = []
    for _, row in df_banks.iterrows():
        bank_name = _norm_str(_col_val(row, col_first_name), 100)
        if not bank_name or bank_name.upper() in ("NOMBRE", "NAN"):
            continue
        rows.append({
            "nombre": bank_name,
            "codigo_interno": _norm_int(_col_val(row, col_internal_code)) if col_internal_code else None,
            "codigo_grupo": _norm_int(_col_val(row, col_group_code)) if col_group_code else None,
            "activo": True,
        })
    return rows


# ---------------------------------------------------------------------------
# Carga a BD
# ---------------------------------------------------------------------------

_CLIENT_DEFAULTS: dict = {
    "rut": None,
    "nombre": None,
    "apellido": None,
    "fecha_nacimiento": None,
    "profesion": None,
    "tipo_persona": None,
    "tipo_socio": None,
    "telefono": None,
    "email": None,
    "direccion": None,
    "comuna": None,
    "ciudad": None,
    "region": None,
    "raw_payload": None,
}


def _bulk_upsert_clients(db, clients: list[dict]) -> int:
    """Inserta/actualiza clientes en batch usando ON CONFLICT DO UPDATE."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # Deduplicar por RUT (último registro gana si hay diferencias de datos)
    seen: dict[str, dict] = {}
    for c in clients:
        if c and c.get("rut"):
            seen[c["rut"]] = c

    if not seen:
        return 0

    # Normalizar todas las filas al mismo conjunto de columnas para que
    # SQLAlchemy pueda hacer un multi-row INSERT (requiere keys idénticos)
    rows = [{"id": uuid.uuid4(), **{**_CLIENT_DEFAULTS, **c}} for c in seen.values()]

    # Mantenerse bajo los 65535 parámetros de PostgreSQL al incluir contacto.
    CHUNK = 4000
    for i in range(0, len(rows), CHUNK):
        chunk = rows[i : i + CHUNK]
        stmt = pg_insert(TchClient).values(chunk).on_conflict_do_update(
            index_elements=["rut"],
            set_={
                "nombre": pg_insert(TchClient).excluded.nombre,
                "apellido": pg_insert(TchClient).excluded.apellido,
                "fecha_nacimiento": pg_insert(TchClient).excluded.fecha_nacimiento,
                "profesion": pg_insert(TchClient).excluded.profesion,
                "tipo_socio": pg_insert(TchClient).excluded.tipo_socio,
                "telefono": pg_insert(TchClient).excluded.telefono,
                "email": pg_insert(TchClient).excluded.email,
                "direccion": pg_insert(TchClient).excluded.direccion,
                "comuna": pg_insert(TchClient).excluded.comuna,
                "ciudad": pg_insert(TchClient).excluded.ciudad,
                "region": pg_insert(TchClient).excluded.region,
                "tipo_persona": pg_insert(TchClient).excluded.tipo_persona,
            },
        )
        db.execute(stmt)
    db.flush()
    return len(rows)


def _pg_upsert_catalog(db, model, unique_col: str, values: set[str], extra_cols: dict | None = None) -> int:
    """
    Inserta en un catálogo usando ON CONFLICT DO NOTHING.
    Siempre seguro frente a duplicados en la misma sesión.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    vals = [v for v in values if v]
    if not vals:
        return 0
    rows_to_insert = [{unique_col: v, "id": uuid.uuid4(), **(extra_cols or {})} for v in vals]
    db.execute(
        pg_insert(model).values(rows_to_insert).on_conflict_do_nothing(index_elements=[unique_col])
    )
    db.flush()
    return len(vals)


def _bulk_upsert_catalogs(db, rows: list[dict]) -> None:
    """Pre-carga catálogos únicos de las suscripciones usando ON CONFLICT DO NOTHING."""
    _pg_upsert_catalog(db, TchBank, "nombre", {r.get("banco_nombre") for r in rows})
    _pg_upsert_catalog(db, TchOrigin, "nombre", {r.get("origen") for r in rows})
    _pg_upsert_catalog(db, TchCostCenter, "nombre", {r.get("centro_costo") for r in rows})
    _pg_upsert_catalog(db, TchMandateType, "codigo", {r.get("tipo_mandato") for r in rows})


def _load_bank_catalog(db, rows: list[dict]) -> int:
    """Carga el catálogo de bancos desde la hoja TABLAS usando ON CONFLICT DO NOTHING."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # Deduplicar por nombre
    seen: dict[str, dict] = {}
    for r in rows:
        if r.get("nombre") and r["nombre"] not in seen:
            seen[r["nombre"]] = r

    if not seen:
        return 0

    to_insert = [{"id": uuid.uuid4(), **r} for r in seen.values()]
    db.execute(pg_insert(TchBank).values(to_insert).on_conflict_do_nothing(index_elements=["nombre"]))
    db.flush()
    return len(to_insert)


# PostgreSQL: en INSERT .. ON CONFLICT DO UPDATE .. RETURNING, `xmax = 0` marca la fila insertada (no la actualizada).
_INSERTED_FLAG = literal_column("(xmax = 0)").label("inserted")


def _load_subscriptions(db, rows: list[dict]) -> tuple[int, int, int]:
    # 1. Pre-cargar catálogos en batch (ON CONFLICT DO NOTHING)
    _bulk_upsert_catalogs(db, rows)

    # 2. Pre-cargar todos los clientes en batch (ON CONFLICT DO UPDATE)
    all_clients = []
    for r in rows:
        if r.get("_cliente"):
            all_clients.append(r["_cliente"])
        if r.get("_cliente_titular"):
            all_clients.append(r["_cliente_titular"])
    _bulk_upsert_clients(db, all_clients)

    # 3. Upsert suscripciones en batch
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    clean_subscriptions = []
    for r in rows:
        r.pop("_cliente", None)
        r.pop("_cliente_titular", None)
        if r.get("numero_ficha"):
            clean_subscriptions.append({"id": uuid.uuid4(), **r})

    if not clean_subscriptions:
        return 0, 0, 0

    # Deduplicar por numero_ficha (último estado gana)
    seen_subscriptions: dict[int, dict] = {}
    for r in clean_subscriptions:
        seen_subscriptions[r["numero_ficha"]] = r
    unique_subscriptions = list(seen_subscriptions.values())

    # Chunk para no superar los 65535 parámetros de PostgreSQL (24 cols x 2700 filas ~= 64800)
    CHUNK_SUBSCRIPTIONS = 2500
    inserted = 0  # TCH-PAR-11: nuevas vs actualizadas por RETURNING (xmax = 0 solo en una fila recien insertada)
    for i in range(0, len(unique_subscriptions), CHUNK_SUBSCRIPTIONS):
        chunk = unique_subscriptions[i : i + CHUNK_SUBSCRIPTIONS]
        stmt = pg_insert(TchSubscription).values(chunk).on_conflict_do_update(
            index_elements=["numero_ficha"],
            set_={
                "estado": pg_insert(TchSubscription).excluded.estado,
                "banco_nombre": pg_insert(TchSubscription).excluded.banco_nombre,
                "tipo_mandato": pg_insert(TchSubscription).excluded.tipo_mandato,
                "origen": pg_insert(TchSubscription).excluded.origen,
                "centro_costo": pg_insert(TchSubscription).excluded.centro_costo,
                "monto": pg_insert(TchSubscription).excluded.monto,
                "moneda": pg_insert(TchSubscription).excluded.moneda,
                "estrategia": pg_insert(TchSubscription).excluded.estrategia,
                "lugar_captacion": pg_insert(TchSubscription).excluded.lugar_captacion,
                "folio": pg_insert(TchSubscription).excluded.folio,
                "referencia": pg_insert(TchSubscription).excluded.referencia,
                "personalidad": pg_insert(TchSubscription).excluded.personalidad,
                "titular_distinto": pg_insert(TchSubscription).excluded.titular_distinto,
                "fecha_primer_cobro": pg_insert(TchSubscription).excluded.fecha_primer_cobro,
                "monto_primer_cobro": pg_insert(TchSubscription).excluded.monto_primer_cobro,
                "cuotas_cobradas": pg_insert(TchSubscription).excluded.cuotas_cobradas,
                "monto_cobrado": pg_insert(TchSubscription).excluded.monto_cobrado,
                "aportes_cuotas": pg_insert(TchSubscription).excluded.aportes_cuotas,
                "aportes_monto": pg_insert(TchSubscription).excluded.aportes_monto,
                "promedio_donacion": pg_insert(TchSubscription).excluded.promedio_donacion,
                "meses_sin_aporte": pg_insert(TchSubscription).excluded.meses_sin_aporte,
                "permanencia_meses": pg_insert(TchSubscription).excluded.permanencia_meses,
                "permanencia_anos": pg_insert(TchSubscription).excluded.permanencia_anos,
                "nvo_mes": pg_insert(TchSubscription).excluded.nvo_mes,
                "rech_mes": pg_insert(TchSubscription).excluded.rech_mes,
                "eli_mes": pg_insert(TchSubscription).excluded.eli_mes,
                "equivalente_pesos": pg_insert(TchSubscription).excluded.equivalente_pesos,
                "fecha_activacion": pg_insert(TchSubscription).excluded.fecha_activacion,
                # El ingreso del mandato no cambia: un reporte sin la columna no borra el ya cargado.
                "fecha_ingreso": func.coalesce(
                    pg_insert(TchSubscription).excluded.fecha_ingreso, TchSubscription.__table__.c.fecha_ingreso
                ),
                "fecha_rechazo": pg_insert(TchSubscription).excluded.fecha_rechazo,
                "fecha_eliminacion": pg_insert(TchSubscription).excluded.fecha_eliminacion,
                "razon_baja": pg_insert(TchSubscription).excluded.razon_baja,
                "raw_payload": pg_insert(TchSubscription).excluded.raw_payload,
            },
        )
        inserted += sum(1 for row in db.execute(stmt.returning(_INSERTED_FLAG)) if row.inserted)
    db.flush()

    return inserted, len(unique_subscriptions) - inserted, 0


_TX_OPTIONAL = {
    "numero_mandato": None, "periodo": None, "numero_cuota": None, "total_cuotas": None, "monto": None,
    "fecha_cargo": None, "tipo_transaccion": None, "entidad_recaudadora": None, "codigo_respuesta": None,
    "razon_rechazo": None, "archivo_origen": None, "origen": ORIGIN_CHARGE, "reporte_periodo": None,
    "rechazo_previo": None, "rechazo_previo_motivo": None, "rechazo_previo_en": None, "raw_payload": None,
}


def _transaction_upsert_set(stmt, table) -> dict:
    """SET del ON CONFLICT: UN estado final por cuota, "el ultimo reporte gana" y cargo > historial (D13).

    - ``newer``: el reporte entrante no es anterior al que trajo la fila (empate = el ultimo cargado gana).
    - El estado y el monto salen del reporte mas nuevo.
    - El detalle del cargo (fecha, entidad, tipo, motivo, payload) lo aporta una fila de origen 'cargo'; un historial
      nunca lo borra ni lo reemplaza (precedencia cargo > historial).
    - Una cuota que pasa de RECHAZADA a ACEPTADA (o al reves, si llega un reporte viejo tarde) conserva el motivo y la
      fecha del rechazo como ``rechazo_previo*``; no se crea otra fila.
    """
    e, t = stmt.excluded, table.c
    newer = or_(e.reporte_periodo.is_(None), t.reporte_periodo.is_(None), e.reporte_periodo >= t.reporte_periodo)
    e_cargo = e.origen == ORIGIN_CHARGE
    t_cargo = func.coalesce(t.origen, "") == ORIGIN_CHARGE
    take = or_(and_(e_cargo, or_(~t_cargo, newer)), and_(~e_cargo, ~t_cargo, newer))
    final = case((newer, e.estado), else_=t.estado)
    rej_from_old = and_(newer, t.estado == "RECHAZADA", e.estado == "ACEPTADA")
    rej_from_new = and_(~newer, e.estado == "RECHAZADA", t.estado == "ACEPTADA")

    def detail(column: str):
        return case((take, func.coalesce(e[column], t[column])), else_=t[column])

    return {
        "estado": final,
        "monto": case((newer, func.coalesce(e.monto, t.monto)), else_=t.monto),
        "reporte_periodo": case((newer, func.coalesce(e.reporte_periodo, t.reporte_periodo)), else_=t.reporte_periodo),
        "origen": case((or_(e_cargo, t_cargo), ORIGIN_CHARGE), else_=func.coalesce(e.origen, t.origen)),
        "numero_mandato": func.coalesce(t.numero_mandato, e.numero_mandato),
        "total_cuotas": detail("total_cuotas"),
        "fecha_cargo": detail("fecha_cargo"),
        "tipo_transaccion": detail("tipo_transaccion"),
        "entidad_recaudadora": detail("entidad_recaudadora"),
        "archivo_origen": case((take, e.archivo_origen), else_=t.archivo_origen),
        "raw_payload": case((take, func.coalesce(e.raw_payload, t.raw_payload)), else_=t.raw_payload),
        # Una cuota ACEPTADA no conserva el motivo como rechazo vigente: queda en rechazo_previo_motivo.
        "razon_rechazo": case((final == "ACEPTADA", None), else_=detail("razon_rechazo")),
        "codigo_respuesta": case((final == "ACEPTADA", None), else_=detail("codigo_respuesta")),
        "rechazo_previo": case(
            (or_(rej_from_old, rej_from_new), true()), else_=func.coalesce(t.rechazo_previo, e.rechazo_previo)
        ),
        "rechazo_previo_motivo": case(
            (rej_from_old, func.coalesce(t.razon_rechazo, t.rechazo_previo_motivo)),
            (rej_from_new, e.razon_rechazo),
            else_=func.coalesce(t.rechazo_previo_motivo, e.rechazo_previo_motivo),
        ),
        "rechazo_previo_en": case(
            (rej_from_old, func.coalesce(t.fecha_cargo, t.rechazo_previo_en)),
            (rej_from_new, e.fecha_cargo),
            else_=func.coalesce(t.rechazo_previo_en, e.rechazo_previo_en),
        ),
    }


def _load_transactions(db, rows: list[dict], file_name: str | None = None, stats: dict | None = None) -> int:
    """Upsert por ``dedupe_key`` (ficha|periodo|cuota). Devuelve cuantas cuotas distintas trae el lote.

    Si una misma cuota aparece varias veces en el lote (p. ej. rechazada y luego aceptada en el mismo reporte), las
    repeticiones se aplican en pasadas sucesivas, en el orden recibido: una sentencia INSERT .. ON CONFLICT no puede
    tocar dos veces la misma fila.
    """
    if not rows:
        return 0
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    CHUNK = 2000
    layers: list[list[dict]] = []
    occurrences: dict[str, int] = {}
    for row in rows:
        key = row["dedupe_key"]
        index = occurrences.get(key, 0)
        occurrences[key] = index + 1
        if index == len(layers):
            layers.append([])
        layers[index].append({"id": uuid.uuid4(), **_TX_OPTIONAL, **row})

    table = TchTransaction.__table__
    inserted = 0
    for layer in layers:
        for i in range(0, len(layer), CHUNK):
            stmt = pg_insert(TchTransaction).values(layer[i : i + CHUNK])
            upsert = stmt.on_conflict_do_update(
                constraint="uq_tch_transaccion_dedupe_key", set_=_transaction_upsert_set(stmt, table)
            )
            if stats is None:
                db.execute(upsert)
            else:
                inserted += sum(1 for row in db.execute(upsert.returning(_INSERTED_FLAG)) if row.inserted)
    if stats is not None:
        # TCH-PAR-11: cuotas distintas nuevas y ya existentes (una repeticion dentro del lote no cuenta dos veces).
        stats["insertadas"] = inserted
        stats["actualizadas"] = len(occurrences) - inserted
    return len(occurrences)


def _has_legacy_dedupe_keys(db) -> bool:
    """True si quedan filas con la clave antigua (ficha|periodo|cuota|estado|monto, 4 separadores).

    Una carga incremental sobre ellas duplicaria todas las cuotas: primero hay que reconstruir con ``--mode full``.
    """
    return db.scalar(select(TchTransaction.id).where(TchTransaction.dedupe_key.like("%|%|%|%|%")).limit(1)) is not None


def _load_monthly_collection(db, rows: list[dict]) -> int:
    if not rows:
        return 0
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    statement = pg_insert(TchMonthlyCollection).values(
        [{"id": uuid.uuid4(), **row} for row in rows]
    ).on_conflict_do_update(
        index_elements=["periodo"],
        set_={
            "aceptadas_cantidad": pg_insert(TchMonthlyCollection).excluded.aceptadas_cantidad,
            "aceptadas_monto": pg_insert(TchMonthlyCollection).excluded.aceptadas_monto,
            "rechazadas_cantidad": pg_insert(TchMonthlyCollection).excluded.rechazadas_cantidad,
            "rechazadas_monto": pg_insert(TchMonthlyCollection).excluded.rechazadas_monto,
            "archivo_origen": pg_insert(TchMonthlyCollection).excluded.archivo_origen,
            "updated_at": func.now(),
        },
    )
    db.execute(statement)
    db.flush()
    return len(rows)


_IMPLICIT_CANCELLATION_REASON = "Baja implicita: ficha ausente del ultimo reporte"


def _apply_implicit_cancellations(db, file_numbers_latest_report: set[int]) -> int:
    """Marca ELIMINADA toda ficha VIGENTE/PENDIENTE que no aparece en el ultimo reporte.

    Sin esto, una ficha que figuro como vigente en un cierre viejo y luego desaparecio de
    todas las hojas (387 casos en la carga actual) queda VIGENTE para siempre. Con un
    reporte sin cartera (conjunto vacio) no se hace nada.
    """
    if not file_numbers_latest_report:
        return 0
    stale = (
        TchSubscription.status.in_(("VIGENTE", "PENDIENTE")),
        TchSubscription.file_number.notin_(file_numbers_latest_report),
    )
    result = db.execute(
        TchSubscription.__table__.update()
        .where(*stale)
        .values({
            TchSubscription.status: "ELIMINADA",
            TchSubscription.cancellation_reason: func.coalesce(
                TchSubscription.cancellation_reason, _IMPLICIT_CANCELLATION_REASON
            ),
        })
    )
    db.flush()
    return result.rowcount or 0


def _is_latest_report(latest_loaded_period: str | None, report_period: str | None) -> bool:
    """Un reporte solo puede dar de baja fichas si no es anterior a lo ya cargado."""
    if not report_period:
        return False
    return latest_loaded_period is None or report_period >= latest_loaded_period


def _last_closed_period(db) -> str | None:
    """Ultimo mes con cobros en el control mensual (ignora los meses futuros en cero)."""
    return db.scalar(
        select(func.max(TchMonthlyCollection.period)).where(
            TchMonthlyCollection.accepted_count + TchMonthlyCollection.rejected_count > 0
        )
    )


def _report_period(filepath: Path) -> str | None:
    """Mes del reporte segun su nombre: prefiere el texto del mes ("DICIEMBRE 2025") a la fecha del archivo,
    que en los cierres es la del dia siguiente (20260101)."""
    named = _norm_period(filepath.stem)
    if named and 2015 <= int(named[:4]) <= 2035:
        return named
    year, month, _, _ = _report_sort_key(filepath)
    return f"{year:04d}-{month:02d}" if year else None


def _purge_future_collection(db) -> int:
    """Borra del control mensual los meses posteriores al ultimo mes cerrado (filas en cero)."""
    last_closed = _last_closed_period(db)
    if last_closed is None:
        return 0
    result = db.execute(
        TchMonthlyCollection.__table__.delete().where(
            TchMonthlyCollection.period > last_closed,
            TchMonthlyCollection.accepted_count == 0,
            TchMonthlyCollection.rejected_count == 0,
        )
    )
    db.flush()
    return result.rowcount or 0


class ReportAlreadyLoadedError(ValueError):
    """El contenido del reporte (sha256) ya fue cargado antes."""


class LegacyDedupeKeysError(ValueError):
    """La base aun tiene la clave antigua de cargos: hay que reconstruir con ``--mode full`` antes de cargar mas."""


_LEGACY_KEYS_MESSAGE = (
    "tch_transacciones conserva claves antiguas (ficha|periodo|cuota|estado|monto). Una carga incremental duplicaria "
    "las cuotas: reconstruya primero con scripts/etl_tch.py --mode full (ver docs/data/tch-reload.md)."
)


def _unique_reports_by_sha256(files: list[Path]) -> tuple[list[Path], list[Path]]:
    """Separa los archivos con contenido repetido (el primero, en el orden dado, es el que se conserva)."""
    seen: set[str] = set()
    unique: list[Path] = []
    skipped: list[Path] = []
    for f in files:
        sha = report_registry.file_sha256(f)
        if sha in seen:
            skipped.append(f)
        else:
            seen.add(sha)
            unique.append(f)
    return unique, skipped


def _register_source_records(db) -> dict[str, int]:
    """SYNC-D-16: un ``source_record`` por fila ``tch_*`` (idempotente; ver app/services/tch_source_records.py).

    No se borran en ``_clear_tch_data``: las filas centralizadas los referencian por ``source_record_id`` y, como las
    claves son estables, una recarga completa reutiliza los mismos registros.
    """
    created = sync_tch_source_records(db)
    if any(created.values()):
        log.info("  source_records TCH nuevos: %s", ", ".join(f"{k}={v}" for k, v in created.items()))
    return created


def backfill_source_records(db, *, apply: bool) -> dict[str, int]:
    """Backfill SYNC-D-16 de lo ya cargado: registra las filas ``tch_*`` sin ``source_record``.

    Idempotente: una segunda ejecucion no crea nada. Con ``apply=False`` (dry-run) cuenta y hace ROLLBACK.
    """
    try:
        created = sync_tch_source_records(db)
        if apply:
            db.commit()
        else:
            db.rollback()
        return created
    except Exception:
        db.rollback()
        raise


def _clear_tch_data(db) -> None:
    """Rebuild the local TCH projection from the complete report history."""
    report_registry.clear(db)
    for model in (TchMandateFlow, TchRejectionReason, TchReportKpi, TchMonthlyCollection, TchTransaction, TchSubscription, TchClient, TchCostCenter, TchOrigin, TchMandateType, TchBank):
        db.query(model).delete()
    db.flush()


# ---------------------------------------------------------------------------
# Procesamiento de un archivo
# ---------------------------------------------------------------------------

def _process_file(filepath: Path, db) -> dict:
    report_name = filepath.name
    log.info(f"Procesando: {report_name}")

    file_totals = {"archivo": report_name, "sus_ins": 0, "sus_upd": 0, "trans": 0, "controles": 0, "err": 0}
    file_numbers: set[int] = set()  # fichas presentes en el reporte (VIGENTES + ELIMINADOS + RECHAZADOS)
    file_totals["fichas"] = file_numbers

    # TCH-PAR-16: el libro se abre una sola vez y cada hoja se recorre una sola vez.
    with ReportBook(filepath) as book:
        return _process_book(book, db, file_totals, file_numbers)


def _process_book(book: ReportBook, db, file_totals: dict, file_numbers: set[int]) -> dict:
    filepath = book.path
    report_name = filepath.name
    has_portfolio = False

    # --- Catálogo de bancos desde hoja TABLAS ---
    bank_rows = _transform_banks_from_tables(book)
    n_banks = _load_bank_catalog(db, bank_rows)
    if n_banks:
        log.info(f"  Bancos nuevos: {n_banks}")

    collection_rows = _transform_monthly_collection(book)
    control_rows = _load_monthly_collection(db, collection_rows)
    file_totals["controles"] = control_rows
    if control_rows:
        log.info(f"  Controles mensuales: {control_rows}")

    # TCH-PAR-11: filas de datos leidas por tipo (solo conteos; nada del contenido).
    read = {"suscripciones": 0, "cuotas_cargos": 0}

    # --- VIGENTES ---
    df_active = _read_sheet(book, SHEET_ACTIVE)
    if df_active is not None:
        read["suscripciones"] += len(df_active)
        rows_active = _transform_subscriptions(df_active, "VIGENTE")
        transaction_rows = _transform_charge_history(df_active, report_name)
        has_portfolio = bool(rows_active)
        file_numbers.update(r["numero_ficha"] for r in rows_active)
        i, u, e = _load_subscriptions(db, rows_active)
        file_totals["sus_ins"] += i
        file_totals["sus_upd"] += u
        file_totals["err"] += e
        log.info(f"  VIGENTES: {i} nuevas, {u} actualizadas, {e} errores")

    else:
        transaction_rows = []

    # --- ELIMINADOS ---
    df_deleted = _read_sheet(book, SHEET_DELETED)
    if df_deleted is not None:
        read["suscripciones"] += len(df_deleted)
        rows_deleted = _transform_subscriptions(df_deleted, "ELIMINADA")
        transaction_rows += _transform_charge_history(df_deleted, report_name)
        file_numbers.update(r["numero_ficha"] for r in rows_deleted)
        i, u, e = _load_subscriptions(db, rows_deleted)
        file_totals["sus_ins"] += i
        file_totals["sus_upd"] += u
        file_totals["err"] += e
        log.info(f"  ELIMINADOS: {i} nuevas, {u} actualizadas, {e} errores")

    # --- RECHAZADOS (mandatos) ---
    df_rejected_mandates = _read_sheet(book, SHEET_REJECTED_MANDATES)
    if df_rejected_mandates is not None:
        read["suscripciones"] += len(df_rejected_mandates)
        rows_rejected_mandates = _transform_subscriptions(df_rejected_mandates, "RECHAZADA")
        # Sin historial: los mandatos de esta hoja nunca cobraron (TCH-PAR-04).
        file_numbers.update(r["numero_ficha"] for r in rows_rejected_mandates)
        i, u, e = _load_subscriptions(db, rows_rejected_mandates)
        file_totals["sus_ins"] += i
        file_totals["sus_upd"] += u
        file_totals["err"] += e
        log.info(f"  RECHAZADOS: {i} nuevas, {u} actualizadas, {e} errores")

    if not has_portfolio:
        file_numbers.clear()  # sin hoja VIGENTES legible (p. ej. dic-2023) no se infieren bajas

    # --- CARGOS --- (primero los rechazados: si la misma cuota figura tambien aceptada en el reporte, la aceptada
    # se aplica despues, es el estado final, y el rechazo queda como atributo `rechazo_previo*`).
    history_rows = len(transaction_rows)  # cuotas del historial mensual de las hojas de cartera (VIGENTES/ELIMINADOS)
    df_rejected = _read_sheet(book, SHEET_REJECTED_CHARGES)
    if df_rejected is not None:
        read["cuotas_cargos"] += len(df_rejected)
        transaction_rows += _transform_transactions(df_rejected, "RECHAZADA", report_name)

    df_accepted = _read_sheet(book, SHEET_ACCEPTED_CHARGES)
    if df_accepted is not None:
        read["cuotas_cargos"] += len(df_accepted)
        transaction_rows += _transform_transactions(df_accepted, "ACEPTADA", report_name)

    # "El ultimo reporte gana": cada fila lleva el mes del reporte que la trajo. Se procesan TODAS las ventanas de
    # historial de cada reporte (un reporte posterior puede reexpresar el estado de un mes ya cargado).
    report_period = _report_period(filepath)
    for row in transaction_rows:
        row["reporte_periodo"] = report_period
    transaction_stats: dict = {}
    n_transactions = _load_transactions(db, transaction_rows, report_name, stats=transaction_stats)
    file_totals["trans"] = n_transactions
    log.info(f"  Transacciones: {n_transactions}")

    # TCH-PAR-10: tablas de control adicionales. Mes del reporte: el del nombre o, si el nombre no lo trae, el del
    # contenido (ultimo "Cuota Mes" de CARGOS).
    control_period = report_period or _content_period(transaction_rows)
    file_totals["periodo_reporte"] = control_period
    control_counts = _load_control_tables(db, book, control_period)
    file_totals["controles_extra"] = control_counts
    if any(control_counts.values()):
        log.info("  Controles adicionales: " + ", ".join(f"{k}={v}" for k, v in control_counts.items()))

    file_totals["conciliacion"] = file_reconciliation(
        read=read,
        history_rows=history_rows,
        subscriptions=(file_totals["sus_ins"], file_totals["sus_upd"], file_totals["err"]),
        transactions=transaction_stats,
        transaction_rows=transaction_rows,
        control_rows=collection_rows,
        period=control_period,
    )

    future_months = _purge_future_collection(db)
    if future_months:
        log.info(f"  Meses futuros en cero eliminados del control mensual: {future_months}")

    return file_totals


def file_reconciliation(
    *,
    read: dict[str, int],
    history_rows: int,
    subscriptions: tuple[int, int, int],
    transactions: dict,
    transaction_rows: list[dict],
    control_rows: list[dict],
    period: str | None,
    tolerance: float | None = None,
) -> dict:
    """TCH-PAR-11: conciliacion de UN archivo (solo conteos y periodos; nada personal).

    Filas: leidas, insertadas, actualizadas, omitidas y con error, por suscripciones y cuotas. «Omitidas» = leidas que
    no quedaron como fila distinta (sin ficha o sin «Cuota Mes», o repetidas en el mismo archivo). Las cuotas leidas
    suman las filas de las hojas CARGOS y las del historial mensual de la cartera.

    Control: aceptadas y rechazadas del mes del reporte en el detalle del propio archivo (estado final por cuota) contra
    el control mensual del mismo Excel (hojas RECAUDACION HISTORICA). ``cuadra`` = desvio <= la tolerancia por mes de
    la conciliacion (TCH-PAR-07); ``None`` si el archivo no trae control para ese mes.
    """
    tolerance = DEFAULT_TOLERANCE_MONTH if tolerance is None else tolerance
    sus_ins, sus_upd, sus_err = subscriptions
    sus_read = read.get("suscripciones", 0)
    tx_read = read.get("cuotas_cargos", 0) + history_rows
    tx_ins = int(transactions.get("insertadas", 0))
    tx_upd = int(transactions.get("actualizadas", 0))
    rows = {
        "suscripciones": {
            "leidas": sus_read, "insertadas": sus_ins, "actualizadas": sus_upd,
            "omitidas": max(sus_read - sus_ins - sus_upd - sus_err, 0), "con_error": sus_err,
        },
        "cuotas": {
            "leidas": tx_read, "insertadas": tx_ins, "actualizadas": tx_upd,
            "omitidas": max(tx_read - tx_ins - tx_upd, 0), "con_error": 0,
        },
    }
    rows["total"] = {key: sum(group[key] for group in rows.values()) for key in rows["suscripciones"]}

    control = next((row for row in control_rows if row.get("periodo") == period), None) if period else None
    check: dict[str, Any] = {"periodo": period, "fuente": "RECAUDACION HISTORICA", "cuadra": None}
    if control is not None:
        final: dict[str, str] = {}
        for row in transaction_rows:  # el ultimo estado de cada cuota gana, como en la carga
            if row.get("periodo") == period and row.get("dedupe_key"):
                final[row["dedupe_key"]] = row.get("estado") or ""
        accepted = sum(1 for status in final.values() if status == "ACEPTADA")
        rejected = sum(1 for status in final.values() if status == "RECHAZADA")
        control_accepted = int(control["aceptadas_cantidad"])
        control_rejected = int(control["rechazadas_cantidad"])
        check.update(
            archivo_aceptadas=accepted, archivo_rechazadas=rejected,
            control_aceptadas=control_accepted, control_rechazadas=control_rejected,
            cuadra=_relative_gap(accepted, control_accepted) <= tolerance
            and _relative_gap(rejected, control_rejected) <= tolerance,
        )
    return {"filas": rows, "control": check}


# ---------------------------------------------------------------------------
# Conciliacion contra el control oficial (TCH-PAR-07)
# ---------------------------------------------------------------------------

DEFAULT_TOLERANCE_MONTH = 0.005  # 0,5 % por mes
DEFAULT_TOLERANCE_TOTAL = 0.001  # 0,1 % sobre el total


@dataclass
class MonthReconciliation:
    period: str
    db_accepted: int
    db_rejected: int
    control_accepted: int
    control_rejected: int
    excluded: bool = False
    ok: bool = True


@dataclass
class Reconciliation:
    months: list[MonthReconciliation] = field(default_factory=list)
    total_db: int = 0
    total_control: int = 0
    total_ok: bool = True
    tolerance_month: float = DEFAULT_TOLERANCE_MONTH
    tolerance_total: float = DEFAULT_TOLERANCE_TOTAL

    @property
    def failed_months(self) -> list[str]:
        return [m.period for m in self.months if not m.ok]

    @property
    def ok(self) -> bool:
        return not self.failed_months and self.total_ok


def _relative_gap(db_value: int, control_value: int) -> float:
    return abs(db_value - control_value) / max(control_value, 1)


def reconcile(
    db,
    tolerance_month: float = DEFAULT_TOLERANCE_MONTH,
    tolerance_total: float = DEFAULT_TOLERANCE_TOTAL,
    months: list[str] | None = None,
    exclude_months: set[str] | frozenset[str] | tuple[str, ...] = (),
) -> Reconciliation:
    """Compara intentos aceptados y rechazados por mes de ``tch_transacciones`` con ``tch_recaudacion_mensual``.

    Solo cuenta ACEPTADA y RECHAZADA (como el control). Un mes falla si aceptadas o rechazadas se desvian mas de
    ``tolerance_month`` del control; el total (meses no excluidos) falla si se desvia mas de ``tolerance_total``.
    Los meses en ``exclude_months`` (p. ej. un ano sin detalle en la fuente) se informan pero no cuentan.
    """
    controls = {
        row.period: row
        for row in db.scalars(select(TchMonthlyCollection).order_by(TchMonthlyCollection.period))
        if months is None or row.period in months
    }
    counts: dict[tuple[str, str], int] = {
        (period, status): quantity
        for period, status, quantity in db.execute(
            select(TchTransaction.period, TchTransaction.status, func.count())
            .where(TchTransaction.status.in_(("ACEPTADA", "RECHAZADA")), TchTransaction.period.in_(list(controls)))
            .group_by(TchTransaction.period, TchTransaction.status)
        )
    }
    result = Reconciliation(tolerance_month=tolerance_month, tolerance_total=tolerance_total)
    excluded = set(exclude_months)
    for period, control in controls.items():
        item = MonthReconciliation(
            period=period,
            db_accepted=counts.get((period, "ACEPTADA"), 0),
            db_rejected=counts.get((period, "RECHAZADA"), 0),
            control_accepted=control.accepted_count,
            control_rejected=control.rejected_count,
            excluded=period in excluded,
        )
        if not item.excluded:
            item.ok = (
                _relative_gap(item.db_accepted, item.control_accepted) <= tolerance_month
                and _relative_gap(item.db_rejected, item.control_rejected) <= tolerance_month
            )
            result.total_db += item.db_accepted + item.db_rejected
            result.total_control += item.control_accepted + item.control_rejected
        result.months.append(item)
    result.total_ok = _relative_gap(result.total_db, result.total_control) <= tolerance_total
    return result


def format_reconciliation(result: Reconciliation) -> str:
    """Texto para la consola: solo periodos, conteos y diferencias (nada personal)."""
    lines = [f"{'mes':<8} {'acep BD':>9} {'acep ctl':>9} {'rech BD':>9} {'rech ctl':>9}  estado"]
    for m in result.months:
        status = "excluido" if m.excluded else ("ok" if m.ok else "FALLA")
        lines.append(
            f"{m.period:<8} {m.db_accepted:>9} {m.control_accepted:>9} {m.db_rejected:>9} {m.control_rejected:>9}  {status}"
        )
    gap = _relative_gap(result.total_db, result.total_control) * 100
    lines.append(
        f"TOTAL BD={result.total_db} control={result.total_control} diferencia={gap:.3f} % "
        f"(umbral total {result.tolerance_total * 100:.2f} %, por mes {result.tolerance_month * 100:.2f} %) -> "
        + ("ok" if result.total_ok else "FALLA")
    )
    if result.failed_months:
        lines.append("Meses que no cuadran: " + ", ".join(result.failed_months))
    return "\n".join(lines)


@dataclass
class ReloadOutcome:
    committed: bool
    reconciliation: Reconciliation
    total: int
    active_file_numbers: int = 0
    report_files: int = 0


def reload_full(
    db,
    report_files: list[Path],
    *,
    apply: bool,
    tolerance_month: float = DEFAULT_TOLERANCE_MONTH,
    tolerance_total: float = DEFAULT_TOLERANCE_TOTAL,
    exclude_months: set[str] | frozenset[str] | tuple[str, ...] = (),
) -> ReloadOutcome:
    """Reconstruye ``tch_*`` desde todos los reportes en UNA transaccion: todo o nada.

    Se concilia contra el control oficial antes de confirmar. Con ``apply=False`` (dry-run) siempre se hace ROLLBACK.
    Con ``apply=True`` solo se hace COMMIT si la conciliacion cuadra; si no, ROLLBACK y la base queda intacta.
    Cualquier excepcion se propaga despues de revertir.
    """
    total = 0
    latest: dict = {}
    try:
        _clear_tch_data(db)
        for file_name in report_files:
            sha = report_registry.file_sha256(file_name)
            t = _process_file(file_name, db)
            file_rows = t["sus_ins"] + t["sus_upd"] + t["trans"] + t["controles"]
            report_registry.register(
                db, sha, file_name.name, file_name.stat().st_size, rows_loaded=file_rows, report_period=t.get("periodo_reporte"),
                stats=t.get("conciliacion"),
            )
            latest = t
            total += file_rows
            log.info(f"  [{file_name.name}] sus={t['sus_ins']}+{t['sus_upd']} trans={t['trans']} err={t['err']}")
        if latest:
            cancellations = _apply_implicit_cancellations(db, latest["fichas"])
            log.info(f"Bajas implicitas (ausentes de {latest['archivo']}): {cancellations}")
        _register_source_records(db)
        result = reconcile(db, tolerance_month, tolerance_total, exclude_months=exclude_months)
        active_count = db.scalar(select(func.count()).select_from(TchSubscription).where(TchSubscription.status == "VIGENTE")) or 0
        committed = apply and result.ok
        if committed:
            db.commit()
        else:
            db.rollback()
        return ReloadOutcome(committed, result, total, active_file_numbers=active_count, report_files=len(report_files))
    except Exception:
        db.rollback()
        raise


# ---------------------------------------------------------------------------
# Registro en etl_runs
# ---------------------------------------------------------------------------

def _start_run(db) -> EtlRun:
    run = EtlRun(status="running", channels_processed=["tch"], records_upserted=0, phase="tch_load")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _finish_run(db, run: EtlRun, total: int, error: str | None = None, phase: str | None = None) -> None:
    if phase:
        run.phase = phase
    run.status = "failed" if error else "completed"
    run.finished_at = datetime.now(timezone.utc)
    run.records_upserted = total
    run.error_message = error
    db.commit()


def _close_cancellations_from_report(db) -> int:
    """Cierra las bajas TCH `pending_external` cuya ficha ya viene eliminada en lo recien cargado.

    Se llama DESPUES de confirmar la importacion y nunca la hace fallar: si el cierre falla solo queda un aviso en el
    log (el siguiente reporte lo reintenta; es idempotente)."""
    try:
        from app.services import cancellation_apply

        closed = cancellation_apply.close_tch_cancellations_from_report(db)
        if closed:
            log.info(f"  Bajas TCH cerradas por el reporte: {len(closed)}")
        return len(closed)
    except Exception as exc:
        db.rollback()
        log.warning("No se pudieron cerrar las bajas TCH en trámite (%s).", type(exc).__name__)
        return 0


def _registry_file_name(filepath: Path, display_name: str | None) -> str:
    """Nombre que se guarda en el registro: el original de la subida (sin ruta) o el del archivo. Un nombre con forma
    de RUT o de correo no se guarda."""
    name = Path(display_name).name if display_name else filepath.name
    name = re.sub(r"\s+", " ", name).strip()[:255]
    return "[nombre omitido].xlsx" if not name or _LOOKS_PERSONAL.search(name) else name


def _registry_failure_message(exc: Exception) -> str:
    """Texto generico para el registro de archivos: nunca el contenido del reporte (el detalle queda en etl_runs)."""
    if isinstance(exc, LegacyDedupeKeysError):
        return _LEGACY_KEYS_MESSAGE
    return f"La carga fallo ({type(exc).__name__}); ver el detalle en la corrida ETL."


def _register_failed_load(db, sha: str, filepath: Path, file_name: str, exc: Exception, run_id) -> None:
    """TCH-PAR-11: deja el intento fallido en el registro. Nunca hace fallar el manejo del error original."""
    try:
        size = filepath.stat().st_size if filepath.exists() else None
        report_registry.register_failure(
            db, sha, file_name, size, _registry_failure_message(exc),
            report_period=_report_period(Path(file_name)), etl_run_id=run_id,
        )
        db.commit()
    except Exception as registry_exc:
        db.rollback()
        log.warning("No se pudo registrar el intento fallido (%s).", type(registry_exc).__name__)


def import_incremental_file(filepath: Path, run_id=None, display_name: str | None = None) -> int:
    """Carga un reporte TCH individual y deja el resultado trazado en ``etl_runs`` y en el registro de archivos.

    ``display_name``: nombre original del archivo subido (la subida se guarda con un nombre temporal); solo se usa
    para el registro de archivos (TCH-PAR-11), no cambia como se procesa el reporte.
    """
    db = SessionLocal()
    run = None
    total = 0
    sha = None
    file_name = _registry_file_name(filepath, display_name)
    try:
        run = db.get(EtlRun, run_id) if run_id else _start_run(db)
        if run is None:
            raise ValueError("Ejecución ETL no encontrada")
        run.phase = "tch_import"
        db.commit()
        sha = report_registry.file_sha256(filepath)
        if report_registry.is_registered(db, sha):
            raise ReportAlreadyLoadedError("Este reporte ya fue cargado (mismo contenido, sha256 registrado).")
        if _has_legacy_dedupe_keys(db):
            raise LegacyDedupeKeysError(_LEGACY_KEYS_MESSAGE)
        latest_loaded = _last_closed_period(db)
        totals = _process_file(filepath, db)
        total = totals["sus_ins"] + totals["sus_upd"] + totals["trans"] + totals["controles"]
        report_period = _report_period(Path(file_name)) or totals.get("periodo_reporte")
        report_registry.register(
            db, sha, file_name, filepath.stat().st_size, rows_loaded=total,
            report_period=report_period, etl_run_id=run.id, stats=totals.get("conciliacion"),
        )
        if _is_latest_report(latest_loaded, _report_period(filepath)):
            cancellations = _apply_implicit_cancellations(db, totals["fichas"])
            log.info(f"  Bajas implicitas (ausentes del reporte): {cancellations}")
        _register_source_records(db)
        _finish_run(db, run, total)
        _close_cancellations_from_report(db)
        return total
    except Exception as exc:
        db.rollback()
        if sha is not None and not isinstance(exc, ReportAlreadyLoadedError):
            _register_failed_load(db, sha, filepath, file_name, exc, run.id if run is not None else None)
        if run is not None:
            _finish_run(db, run, total, error=_safe_error_message(exc))
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

def _list_reports(folder: Path) -> list[Path]:
    return sorted(
        [f for f in folder.iterdir() if f.suffix.upper() == ".XLSX" and f.is_file() and not f.name.startswith("~$")],
        key=_report_sort_key,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ETL para reportes Excel TCH -> tablas tch_*")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--folder", help="Carpeta con archivos .xlsx (procesa todos)")
    group.add_argument("--file", help="Archivo .xlsx individual")
    group.add_argument(
        "--backfill-source-records",
        action="store_true",
        help="SYNC-D-16: registra en source_records las filas tch_* ya cargadas (dry-run salvo --apply)",
    )
    parser.add_argument("--mode", choices=["full", "incremental"], default="incremental")
    parser.add_argument("--dry-run", action="store_true", help="(modo full, por defecto) reconstruye y hace ROLLBACK")
    parser.add_argument("--apply", action="store_true", help="(modo full) confirma la recarga si la conciliacion cuadra")
    parser.add_argument("--confirm-database", help="Nombre exacto de la base; obligatorio con --apply")
    parser.add_argument("--tolerance-month", type=float, default=DEFAULT_TOLERANCE_MONTH, help="Desvio maximo por mes (0.005 = 0,5 %%)")
    parser.add_argument("--tolerance-total", type=float, default=DEFAULT_TOLERANCE_TOTAL, help="Desvio maximo total (0.001 = 0,1 %%)")
    parser.add_argument("--exclude-months", default="", help="Meses YYYY-MM, separados por coma, que no cuentan en la conciliacion")
    return parser


def _main_backfill(args) -> None:
    """``--backfill-source-records``: dry-run por defecto; ``--apply`` exige ``--confirm-database`` con el nombre exacto."""
    if args.apply and args.dry_run:
        log.error("--apply y --dry-run son excluyentes")
        sys.exit(2)
    database_name = engine.url.database
    if args.apply and args.confirm_database != database_name:
        log.error("--apply exige --confirm-database con el nombre exacto de la base destino (%s)", database_name)
        sys.exit(2)
    db = SessionLocal()
    try:
        created = backfill_source_records(db, apply=args.apply)
    finally:
        db.close()
    summary = ", ".join(f"{k}={v}" for k, v in created.items())
    if args.apply:
        log.info("Backfill source_records TCH CONFIRMADO en '%s': %s", database_name, summary)
    else:
        log.info("Dry-run backfill source_records TCH en '%s' (ROLLBACK): se crearian %s", database_name, summary)


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    if args.backfill_source_records:
        _main_backfill(args)
        return

    full = args.mode == "full"
    if (args.apply or args.dry_run or args.confirm_database) and not full:
        log.error("--apply, --dry-run y --confirm-database solo aplican a --mode full")
        sys.exit(2)
    if args.apply and args.dry_run:
        log.error("--apply y --dry-run son excluyentes")
        sys.exit(2)
    database_name = engine.url.database
    if args.apply and args.confirm_database != database_name:
        log.error("--apply exige --confirm-database con el nombre exacto de la base destino (%s)", database_name)
        sys.exit(2)
    if full and not args.folder:
        log.error("--mode full requiere --folder")
        sys.exit(2)

    if args.folder:
        folder = Path(args.folder)
        if not folder.is_dir():
            log.error(f"Carpeta no encontrada: {folder}")
            sys.exit(1)
        report_files = _list_reports(folder)
        if not report_files:
            log.error(f"No se encontraron archivos .xlsx en {folder}")
            sys.exit(1)
        report_files, duplicates = _unique_reports_by_sha256(report_files)
        for duplicate in duplicates:
            log.warning(f"Archivo omitido por contenido duplicado (sha256): {duplicate.name}")
        log.info(f"Modo full: {len(report_files)} archivos a procesar")
    else:
        f = Path(args.file)
        if not f.exists():
            log.error(f"Archivo no encontrado: {f}")
            sys.exit(1)
        report_files = [f]
        log.info(f"Modo incremental: {f.name}")

    db = SessionLocal()
    try:
        run = start_exclusive_run(db, channels_processed=["tch"], phase="tch_full_reload" if full else "tch_load")
    except ActiveRunError as exc:
        log.error("%s", exc)
        db.close()
        sys.exit(2)
    log.info(f"EtlRun iniciado: {run.id}")
    run_id = run.id

    total = 0
    try:
        if full:
            exclude = {m.strip() for m in args.exclude_months.split(",") if m.strip()}
            log.info("Recarga completa de la base '%s' (%s)", database_name, "APPLY" if args.apply else "dry-run: se hara ROLLBACK")
            outcome = reload_full(
                db,
                report_files,
                apply=args.apply,
                tolerance_month=args.tolerance_month,
                tolerance_total=args.tolerance_total,
                exclude_months=exclude,
            )
            total = outcome.total
            print(format_reconciliation(outcome.reconciliation))
            print(f"Fichas VIGENTES resultantes: {outcome.active_file_numbers}")
            run = db.get(EtlRun, run_id)
            if outcome.committed:
                _finish_run(db, run, total, phase="tch_full_reload")
                log.info("Recarga CONFIRMADA. Total procesados: %s", total)
            elif not args.apply:
                _finish_run(db, run, total, phase="tch_full_dryrun")
                log.info("Dry-run terminado: nada se confirmo (ROLLBACK). Conciliacion %s", "OK" if outcome.reconciliation.ok else "CON DIFERENCIAS")
            else:
                msg = "Conciliacion fuera de umbral; ROLLBACK, la base quedo intacta. Meses: " + ", ".join(outcome.reconciliation.failed_months or ["(total)"])
                _finish_run(db, run, total, error=msg[:2000], phase="tch_full_reload")
                log.error(msg)
                sys.exit(3)
            return

        for file_name in report_files:
            sha = report_registry.file_sha256(file_name)
            latest_loaded = _last_closed_period(db)
            if report_registry.is_registered(db, sha):
                raise ReportAlreadyLoadedError("Este reporte ya fue cargado (mismo contenido, sha256 registrado).")
            if _has_legacy_dedupe_keys(db):
                raise LegacyDedupeKeysError(_LEGACY_KEYS_MESSAGE)
            t = _process_file(file_name, db)
            report_registry.register(
                db, sha, file_name.name, file_name.stat().st_size, report_period=t.get("periodo_reporte"), etl_run_id=run_id,
                stats=t.get("conciliacion"),
            )
            if _is_latest_report(latest_loaded, _report_period(file_name)):
                cancellations = _apply_implicit_cancellations(db, t["fichas"])
                log.info(f"  Bajas implicitas (ausentes del reporte): {cancellations}")
            total += t["sus_ins"] + t["sus_upd"] + t["trans"] + t["controles"]
            log.info(f"  [{file_name.name}] sus={t['sus_ins']}+{t['sus_upd']} trans={t['trans']} err={t['err']}")
        _register_source_records(db)
        _finish_run(db, db.get(EtlRun, run_id), total)
        _close_cancellations_from_report(db)
        log.info(f"ETL completado. Total procesados: {total}")
    except SystemExit:
        raise
    except Exception as exc:
        db.rollback()
        safe_error = _safe_error_message(exc)
        _finish_run(db, db.get(EtlRun, run_id), total, error=safe_error)
        log.error("ETL fallido: %s", safe_error)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
