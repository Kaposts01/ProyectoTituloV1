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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from sqlalchemy import case, func, select

from app.db.session import SessionLocal
from app.models.etl_run import EtlRun
from app.models.tch import (
    TchBanco,
    TchCentroCosto,
    TchCliente,
    TchOrigen,
    TchRecaudacionMensual,
    TchSuscripcion,
    TchTipoMandato,
    TchTransaccion,
)
from app.services import tch_report_registry as report_registry
from app.services.core_tch_etl import normalize_tch_currency
from app.services.payload_sanitization import sanitize_payload

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
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    rut = re.sub(r"[^\dKk-]", "", str(val).strip().upper())
    if not rut:
        return None
    if "-" not in rut:
        rut = rut[:-1] + "-" + rut[-1]
    try:
        numero, dv = rut.split("-", 1)
        return f"{int(numero):,}".replace(",", ".") + f"-{dv}"
    except Exception:
        return str(val).strip()[:20] or None


def _norm_date(val: Any) -> str | None:
    if val is None or pd.isna(val):
        return None
    try:
        if hasattr(val, "date"):
            return val.date().isoformat()
        s = str(val).strip()
        if "/" in s:
            parts = s.split("/")
            if len(parts) == 3:
                d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                return f"{y:04d}-{m:02d}-{d:02d}"
        if re.match(r"\d{4}-\d{2}-\d{2}", s):
            return s[:10]
    except Exception:
        pass
    return None


def _norm_str(val: Any, max_len: int = 255) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    return s[:max_len] if s else None


def _norm_monto(val: Any) -> str | None:
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


def _norm_cuota(val: Any) -> str | None:
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


def _codigo_from_motivo(motivo: str | None) -> str | None:
    """Codigo de respuesta derivado del motivo de rechazo (el reporte no trae una columna de codigo).

    Si el motivo empieza con un codigo corto ("R02 - ...", "51: ...") se conserva; si no, se genera
    un identificador estable en mayusculas sin tildes ("Fondos insuficientes" -> FONDOS_INSUFICIENTES).
    """
    if not motivo or not motivo.strip():
        return None
    text = unicodedata.normalize("NFKD", motivo).encode("ascii", "ignore").decode().upper().strip()
    prefix = re.match(r"([A-Z]{0,2}\d{1,3})\s*[-:.)]\s*\S", text)
    if prefix:
        return prefix.group(1)
    prefix = re.fullmatch(r"([A-Z]{0,2}\d{1,3})", text)
    if prefix:
        return prefix.group(1)
    slug = re.sub(r"[^A-Z0-9]+", "_", text).strip("_")
    return slug[:50] or None


def _norm_periodo(val: Any) -> str | None:
    """Convierte 'AGOSTO 2026' o datetime a 'YYYY-MM'."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    meses = {
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
        for mes, num in meses.items():
            if mes in s:
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

SHEET_VIGENTES = "VIGENTES"
SHEET_ELIMINADOS = "ELIMINADOS"
SHEET_RECHAZADOS_MANDATOS = "RECHAZADOS"
SHEET_ACEPTADOS = "CARGOS ACEPTADOS"
SHEET_RECHAZADOS = "CARGOS RECHAZADOS"
SHEET_TABLAS = "TABLAS"
SHEET_HISTORICO_RECAUDACION_CAN = "HISTORICO RECAUDACION CAN"
SHEET_HISTORICO_RECAUDACION_FLUJO = "HISTORICO RECAUDACION FLUJO"


def _read_sheet(filepath: Path, sheet: str) -> pd.DataFrame | None:
    """
    Lee una hoja TCH con headers multinivel.
    Intenta header=[5,6] primero (estándar); si no encuentra 'ficha/dues',
    busca la fila que contiene 'FICHA DUES' y usa las dos anteriores como headers.
    """
    try:
        df = pd.read_excel(filepath, sheet_name=sheet, header=[5, 6])
        df = df.dropna(how="all")
        cols_str = " ".join(str(c).lower() for c in df.columns)
        if "ficha" in cols_str or "mandato" in cols_str:
            return df
    except Exception as exc:
        log.warning(f"  No se pudo leer hoja '{sheet}': {exc}")
        return None

    # Fallback: buscar la fila más baja que contenga 'FICHA DUES'
    try:
        raw = pd.read_excel(filepath, sheet_name=sheet, header=None)
        header_row = None
        for i in range(len(raw)):
            row_str = " ".join(str(v).upper() for v in raw.iloc[i] if not (isinstance(v, float) and pd.isna(v)))
            if "FICHA" in row_str and ("DUES" in row_str or "MANDATO" in row_str):
                header_row = i
                # No hacer break: queremos la fila más baja con esos datos
        if header_row is not None:
            # Usar las 3 filas anteriores como headers (puede variar; intentar -2,-1,0)
            h0 = max(0, header_row - 2)
            df2 = pd.read_excel(filepath, sheet_name=sheet, header=list(range(h0, header_row + 1)))
            df2 = df2.dropna(how="all")
            log.info(f"  Headers detectados en filas {h0}-{header_row} (fallback)")
            return df2
    except Exception as exc:
        log.warning(f"  Error en fallback de lectura '{sheet}': {exc}")

    return None


def _report_sort_key(filepath: Path) -> tuple[int, int, int, str]:
    dated = re.search(r"(\d{8})", filepath.stem)
    if dated:
        try:
            date = datetime.strptime(dated.group(1), "%Y%m%d")
            return date.year, date.month, date.day, filepath.name
        except ValueError:
            pass
    period = _norm_periodo(filepath.stem)
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
            period = _norm_periodo(value)
            if period:
                periods[column_index] = period
    return periods


def _historical_revenue_values(filepath: Path, sheet: str) -> dict[str, tuple[str, str]]:
    try:
        df = pd.read_excel(filepath, sheet_name=sheet, header=None)
    except (OSError, ValueError) as exc:
        log.warning("  No se pudo leer hoja '%s': %s", sheet, exc)
        return {}
    total_rows = _historical_total_rows(df)
    if total_rows is None:
        log.warning("  No se encontraron totales en hoja '%s'", sheet)
        return {}
    accepted_row, rejected_row = total_rows
    values: dict[str, tuple[str, str]] = {}
    for column_index, period in _historical_period_columns(df).items():
        accepted = _norm_monto(df.iat[accepted_row, column_index])
        rejected = _norm_monto(df.iat[rejected_row, column_index])
        if accepted is not None and rejected is not None:
            values[period] = accepted, rejected
    return values


def _transform_recaudacion_mensual(filepath: Path) -> list[dict]:
    amounts = _historical_revenue_values(filepath, SHEET_HISTORICO_RECAUDACION_FLUJO)
    counts = _historical_revenue_values(filepath, SHEET_HISTORICO_RECAUDACION_CAN)
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
# Transformaciones — VIGENTES / ELIMINADOS
# ---------------------------------------------------------------------------

_ESTADOS_MANDATO = {
    "ACTIVO": "VIGENTE", "ACTIVA": "VIGENTE", "VIGENTE": "VIGENTE",
    "PENDIENTE": "PENDIENTE",
    "RECHAZADO": "RECHAZADA", "RECHAZADA": "RECHAZADA",
    "ELIMINADO": "ELIMINADA", "ELIMINADA": "ELIMINADA",
}


def _find_estado_col(df: pd.DataFrame) -> Any:
    """Columna ESTADO del mandato (grupo ANTECEDENTES Y ESTADO MANDATO).

    Los 12 bloques mensuales "N / Estado / Monto" repiten el rotulo "Estado" mas a la derecha;
    la primera coincidencia exacta del rotulo final es la del mandato.
    """
    for col in df.columns:
        leaf = str(col[-1] if isinstance(col, tuple) else col).strip().lower()
        if re.fullmatch(r"estado(\.\d+)?", leaf):
            return col
    return None


def _estado_mandato(valor: Any, por_hoja: str) -> str:
    """Estado de la ficha desde la columna ESTADO; si falta o no se reconoce, el de la hoja de origen."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return por_hoja
    return _ESTADOS_MANDATO.get(str(valor).strip().upper(), por_hoja)


def _transform_suscripciones(df: pd.DataFrame, estado: str) -> list[dict]:
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
    c_ficha = _find_col(df, "ficha", "dues") or _find_col(df, "ficha")
    c_mandato = _find_col(df, "mandato", "dues")

    # Datos del socio
    c_rut = _find_col(df, "socio", "rut") or _find_col(df, "rut")
    c_nombre = _find_col(df, "socio", "nombre") or _find_col(df, "nombre")
    c_apellido = _find_col(df, "socio", "apellido") or _find_col(df, "apellido")
    c_fnac = _find_col(df, "nacimiento")
    c_prof = _find_col(df, "profesi")
    c_tipo_socio = _find_col(df, "tipo", "socio")
    c_ley = _find_col(df, "socio", "ley") or _find_col(df, "ley")
    c_reajuste = _find_col(df, "reajuste")
    c_telefono = _find_contact_col(df, "telefono")
    c_email = _find_contact_col(df, "email")
    c_direccion = _find_contact_col(df, "direccion")
    c_numero_direccion = _find_contact_col(df, "numero")
    c_casa_depto = _find_contact_col(df, "casa") or _find_contact_col(df, "depto")
    c_villa = _find_contact_col(df, "villa") or _find_contact_col(df, "pob")
    c_comuna = _find_contact_col(df, "comuna")
    c_ciudad = _find_contact_col(df, "ciudad")

    # Datos titular
    c_rut_titular = _find_col(df, "titular", "rut")
    c_nombre_titular = _find_col(df, "titular", "nombre")
    c_apellido_titular = _find_col(df, "titular", "apellido")

    # Antecedentes mandato
    c_firma = _find_col(df, "antecedentes", "firma") or _find_col(df, "firma")
    c_tipo_mandato = _find_col(df, "antecedentes", "tipo", "mandato") or _find_col(df, "tipo", "mandato")
    c_banco = _find_col(df, "banco") or _find_col(df, "institucion")
    c_tipo_cuenta = _find_col(df, "tipo", "cuenta")
    c_num_cuenta = _find_col(df, "numero", "cuenta")
    # "Ingreso" (grupo ANTECEDENTES) es una fecha; el monto del mandato es "Monto Vigente" (MANDATO ACTUAL).
    c_monto = _find_col(df, "monto", "vigente")
    c_moneda = _find_col(df, "moneda", "vigente")
    c_equivalente_pesos = _find_col(df, "equivalente", "pesos")
    c_factivacion = _find_col(df, "activac")
    c_fentrega = _find_col(df, "entrega", "banco")
    c_frechazo = _find_col(df, "fecha", "rechazo")
    c_felim = _find_col(df, "fecha", "eliminado") or _find_col(df, "fecha", "eliminac") or _find_col(df, "fecha", "baja")
    c_razon = _find_col(df, "motivo") or _find_col(df, "raz")
    c_estado = _find_estado_col(df)

    # Captación
    c_origen = _find_col(df, "origen")
    c_centro = _find_col(df, "centro", "costo")
    c_captador = _find_col(df, "captador")

    if c_ficha is None:
        log.warning("  No se encontró columna 'Ficha DUES' en el sheet")
        return rows

    for _, row in df.iterrows():
        ficha = _norm_int(_col_val(row, c_ficha))
        if ficha is None:
            continue
        rut = _norm_rut(_col_val(row, c_rut))

        raw = sanitize_payload({str(k): (None if isinstance(v, float) and pd.isna(v) else str(v)) for k, v in row.items()})
        # tch_suscripciones no tiene columna moneda: la moneda normalizada viaja en el payload.
        raw["moneda_vigente"] = normalize_tch_currency(_col_val(row, c_moneda))

        sus = {
            "numero_ficha": ficha,
            "numero_mandato": _norm_int(_col_val(row, c_mandato)),
            "cliente_rut": rut,
            "banco_nombre": _norm_str(_col_val(row, c_banco), 100),
            "tipo_mandato": _norm_str(_col_val(row, c_tipo_mandato), 20),
            "tipo_cuenta": _norm_str(_col_val(row, c_tipo_cuenta), 50),
            "numero_cuenta": _norm_str(_col_val(row, c_num_cuenta), 50),
            "origen": _norm_str(_col_val(row, c_origen), 150),
            "centro_costo": _norm_str(_col_val(row, c_centro), 150),
            "captador": _norm_str(_col_val(row, c_captador), 150),
            "ley": _norm_str(_col_val(row, c_ley), 50),
            "reajuste": _norm_str(_col_val(row, c_reajuste), 10),
            "firma": _norm_str(_col_val(row, c_firma), 10),
            "monto": _norm_monto(_col_val(row, c_monto)),
            "equivalente_pesos": _norm_monto(_col_val(row, c_equivalente_pesos)),
            "fecha_activacion": _norm_date(_col_val(row, c_factivacion)),
            "fecha_entrega_banco": _norm_date(_col_val(row, c_fentrega)),
            "fecha_rechazo": _norm_date(_col_val(row, c_frechazo)),
            "fecha_eliminacion": _norm_date(_col_val(row, c_felim)),
            "razon_baja": _norm_str(_col_val(row, c_razon), 500),
            "estado": _estado_mandato(_col_val(row, c_estado), estado),
            "raw_payload": raw,
            "_cliente": {
                "rut": rut,
                "nombre": _norm_str(_col_val(row, c_nombre), 150),
                "apellido": _norm_str(_col_val(row, c_apellido), 150),
                "fecha_nacimiento": _norm_date(_col_val(row, c_fnac)),
                "profesion": _norm_str(_col_val(row, c_prof), 100),
                "tipo_persona": "Natural",
                "tipo_socio": _norm_str(_col_val(row, c_tipo_socio), 50),
                "telefono": _norm_str(_col_val(row, c_telefono), 100),
                "email": _norm_str(_col_val(row, c_email), 320),
                "direccion": " ".join(
                    part
                    for part in (
                        _norm_str(_col_val(row, c_direccion), 200),
                        _norm_str(_col_val(row, c_numero_direccion), 50),
                        _norm_str(_col_val(row, c_casa_depto), 100),
                        _norm_str(_col_val(row, c_villa), 100),
                    )
                    if part
                ) or None,
                "comuna": _norm_str(_col_val(row, c_comuna), 150),
                "ciudad": _norm_str(_col_val(row, c_ciudad), 150),
            } if rut else None,
            "_cliente_titular": None,
        }

        if c_rut_titular:
            rut_titular = _norm_rut(_col_val(row, c_rut_titular))
            if rut_titular and rut_titular != rut:
                sus["_cliente_titular"] = {
                    "rut": rut_titular,
                    "nombre": _norm_str(_col_val(row, c_nombre_titular), 150) if c_nombre_titular else None,
                    "apellido": _norm_str(_col_val(row, c_apellido_titular), 150) if c_apellido_titular else None,
                    "tipo_persona": "Natural",
                }

        rows.append(sus)
    return rows


# ---------------------------------------------------------------------------
# Transformaciones — CARGOS ACEPTADOS / RECHAZADOS
# ---------------------------------------------------------------------------

def _dedupe_key(ficha: int, periodo: str | None, cuota: str | None, estado: str, monto: str | None) -> str:
    # La cuota se normaliza aqui tambien: '12', '12.0' y 12.0 deben dar la misma clave.
    return "|".join([str(ficha), periodo or "", _norm_cuota(cuota) or "", estado, monto or ""])


def _estado_cargo(estado: str) -> str:
    normalized = estado.strip().upper()
    if normalized in {"PAGADA", "PAGADO", "ACEPTADA", "ACEPTADO"}:
        return "ACEPTADA"
    if normalized in {"IMPAGA", "IMPAGO", "RECHAZADA", "RECHAZADO"}:
        return "RECHAZADA"
    return normalized


def _transform_transacciones(df: pd.DataFrame, estado: str, archivo: str) -> list[dict]:
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

    c_ficha = _find_col(df, "ficha")
    c_mandato = _find_col(df, "ndato")  # Número Mandato (sin tildes posibles)
    c_entidad = _find_col(df, "entidad") or _find_col(df, "recaudadora")
    c_tipo = _find_col(df, "transacci")
    c_total_cuotas = _find_col(df, "pagos", "mandato")
    # El periodo real es "Cuota Mes". Ni la columna numerica "Periodo" ni el nombre del archivo
    # (que puede llevar la fecha del dia siguiente al cierre o no llevar fecha) definen el mes.
    c_cuota_mes = _find_leaf_col(df, "cuota", "mes")
    # 'N° Cuota' (excluye 'Cuota Mes' y 'Monto Cuota')
    c_cuota = (
        _find_leaf_col(df, "cuota", exclude=("mes", "monto"))
        or _find_col(df, "detalle", "cuota")
        or _find_col(df, "n", "cuota")
    )
    c_monto = (
        _find_col(df, "total", "carg")
        or _find_col(df, "total", "rechaz")
        or _find_col(df, "monto", "cuota")
        or _find_col(df, "monto")
    )
    c_fecha = _find_col(df, "fecha", "cobro") or _find_col(df, "fecha", "intento") or _find_col(df, "fecha", "cargo")
    # Codigo explicito si el reporte lo trae; si no se deriva de "Motivo" (solo en CARGOS RECHAZADOS).
    c_codigo = _find_leaf_col(df, "codigo") or _find_leaf_col(df, "código") or _find_leaf_col(df, "respuesta")
    # Ojo: buscar "rechazo" en cualquier nivel caia en el grupo "DETALLE DEL RECHAZO" (columna Periodo).
    c_razon = _find_leaf_col(df, "motivo") or _find_leaf_col(df, "raz")

    if c_ficha is None:
        log.warning(f"  No se encontró columna 'Número Ficha' en transacciones ({estado})")
        return rows
    if c_cuota_mes is None:
        log.warning(f"  No se encontró columna 'Cuota Mes' en transacciones ({estado}); no se cargan cargos sin periodo real")
        return rows

    sin_periodo = 0
    for _, row in df.iterrows():
        ficha_raw = _col_val(row, c_ficha)
        if ficha_raw is None or (isinstance(ficha_raw, float) and pd.isna(ficha_raw)):
            continue
        try:
            ficha = int(float(ficha_raw))
        except Exception:
            continue
        if ficha <= 0:
            continue

        periodo = _norm_periodo(_col_val(row, c_cuota_mes))
        if periodo is None:
            sin_periodo += 1
            continue
        raw = sanitize_payload({str(k): (None if isinstance(v, float) and pd.isna(v) else str(v)) for k, v in row.items()})

        cuota = _norm_cuota(_col_val(row, c_cuota)) if c_cuota else None
        monto = _norm_monto(_col_val(row, c_monto))
        razon = _norm_str(_col_val(row, c_razon), 500) if c_razon else None
        codigo = (_norm_str(_col_val(row, c_codigo), 50) if c_codigo else None) or _codigo_from_motivo(razon)
        rows.append({
            "numero_ficha": ficha,
            "numero_mandato": _norm_int(_col_val(row, c_mandato)),
            "periodo": periodo,
            "numero_cuota": cuota,
            "total_cuotas": _norm_cuota(_col_val(row, c_total_cuotas)) if c_total_cuotas else None,
            "monto": monto,
            "fecha_cargo": _norm_date(_col_val(row, c_fecha)),
            "tipo_transaccion": _norm_str(_col_val(row, c_tipo), 50) if c_tipo else None,
            "estado": estado,
            "entidad_recaudadora": _norm_str(_col_val(row, c_entidad), 100) if c_entidad else None,
            "codigo_respuesta": codigo,
            "razon_rechazo": razon,
            "archivo_origen": archivo,
            "dedupe_key": _dedupe_key(ficha, periodo, cuota, estado, monto),
            "raw_payload": raw,
        })
    if sin_periodo:
        log.warning(f"  {sin_periodo} cargos ({estado}) omitidos: 'Cuota Mes' vacio o ilegible")
    return rows


def _transform_historial_cargos(df: pd.DataFrame, archivo: str) -> list[dict]:
    """Desnormaliza BK:CT: cada mes contiene N°, Estado y Monto."""
    c_ficha = _find_col(df, "ficha", "dues") or _find_col(df, "ficha")
    c_mandato = _find_col(df, "mandato", "dues")
    if c_ficha is None:
        return []

    rows = []
    for _, row in df.iterrows():
        ficha = _norm_int(_col_val(row, c_ficha))
        if ficha is None:
            continue
        mandato = _norm_int(_col_val(row, c_mandato))
        for start in range(62, min(98, len(df.columns)), 3):
            period = _norm_periodo(df.columns[start][0] if isinstance(df.columns[start], tuple) else df.columns[start])
            if not period:
                continue
            cuota = _norm_cuota(_col_val(row, df.columns[start]))
            estado = _norm_str(_col_val(row, df.columns[start + 1]), 20)
            monto = _norm_monto(_col_val(row, df.columns[start + 2]))
            if not estado:
                continue
            estado_original = estado.upper()
            estado = _estado_cargo(estado)
            rows.append(
                {
                    "numero_ficha": ficha,
                    "numero_mandato": mandato,
                    "periodo": period,
                    "numero_cuota": cuota,
                    "total_cuotas": None,
                    "monto": monto,
                    "fecha_cargo": None,
                    "tipo_transaccion": "HISTORIAL_MENSUAL",
                    "estado": estado,
                    "entidad_recaudadora": None,
                    "codigo_respuesta": None,
                    "razon_rechazo": None,
                    "archivo_origen": archivo,
                    "dedupe_key": _dedupe_key(ficha, period, cuota, estado, monto),
                    "raw_payload": {"periodo": period, "numero_cuota": cuota, "estado_original": estado_original, "monto": monto},
                }
            )
    return rows


# ---------------------------------------------------------------------------
# Transformaciones — TABLAS (catálogo de bancos)
# ---------------------------------------------------------------------------

def _transform_bancos_from_tablas(filepath: Path) -> list[dict]:
    """Lee la hoja TABLAS y extrae el catálogo de instituciones."""
    try:
        df = pd.read_excel(filepath, sheet_name=SHEET_TABLAS, header=None)
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

    df_bancos = pd.read_excel(filepath, sheet_name=SHEET_TABLAS, header=header_row)
    df_bancos = df_bancos.dropna(how="all")

    c_nombre = _find_col(df_bancos, "nombre")
    c_cod_int = _find_col(df_bancos, "interno") or _find_col(df_bancos, "int")
    c_cod_grp = _find_col(df_bancos, "grupo") or _find_col(df_bancos, "grp")

    if c_nombre is None:
        return []

    rows = []
    for _, row in df_bancos.iterrows():
        nombre = _norm_str(_col_val(row, c_nombre), 100)
        if not nombre or nombre.upper() in ("NOMBRE", "NAN"):
            continue
        rows.append({
            "nombre": nombre,
            "codigo_interno": _norm_int(_col_val(row, c_cod_int)) if c_cod_int else None,
            "codigo_grupo": _norm_int(_col_val(row, c_cod_grp)) if c_cod_grp else None,
            "activo": True,
        })
    return rows


# ---------------------------------------------------------------------------
# Carga a BD
# ---------------------------------------------------------------------------

_CLIENTE_DEFAULTS: dict = {
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
    "raw_payload": None,
}


def _bulk_upsert_clientes(db, clientes: list[dict]) -> int:
    """Inserta/actualiza clientes en batch usando ON CONFLICT DO UPDATE."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # Deduplicar por RUT (último registro gana si hay diferencias de datos)
    seen: dict[str, dict] = {}
    for c in clientes:
        if c and c.get("rut"):
            seen[c["rut"]] = c

    if not seen:
        return 0

    # Normalizar todas las filas al mismo conjunto de columnas para que
    # SQLAlchemy pueda hacer un multi-row INSERT (requiere keys idénticos)
    rows = [{"id": uuid.uuid4(), **{**_CLIENTE_DEFAULTS, **c}} for c in seen.values()]

    # Mantenerse bajo los 65535 parámetros de PostgreSQL al incluir contacto.
    CHUNK = 4000
    for i in range(0, len(rows), CHUNK):
        chunk = rows[i : i + CHUNK]
        stmt = pg_insert(TchCliente).values(chunk).on_conflict_do_update(
            index_elements=["rut"],
            set_={
                "nombre": pg_insert(TchCliente).excluded.nombre,
                "apellido": pg_insert(TchCliente).excluded.apellido,
                "fecha_nacimiento": pg_insert(TchCliente).excluded.fecha_nacimiento,
                "profesion": pg_insert(TchCliente).excluded.profesion,
                "tipo_socio": pg_insert(TchCliente).excluded.tipo_socio,
                "telefono": pg_insert(TchCliente).excluded.telefono,
                "email": pg_insert(TchCliente).excluded.email,
                "direccion": pg_insert(TchCliente).excluded.direccion,
                "comuna": pg_insert(TchCliente).excluded.comuna,
                "ciudad": pg_insert(TchCliente).excluded.ciudad,
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
    _pg_upsert_catalog(db, TchBanco, "nombre", {r.get("banco_nombre") for r in rows})
    _pg_upsert_catalog(db, TchOrigen, "nombre", {r.get("origen") for r in rows})
    _pg_upsert_catalog(db, TchCentroCosto, "nombre", {r.get("centro_costo") for r in rows})
    _pg_upsert_catalog(db, TchTipoMandato, "codigo", {r.get("tipo_mandato") for r in rows})


def _load_bancos_catalogo(db, rows: list[dict]) -> int:
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
    db.execute(pg_insert(TchBanco).values(to_insert).on_conflict_do_nothing(index_elements=["nombre"]))
    db.flush()
    return len(to_insert)


def _load_suscripciones(db, rows: list[dict]) -> tuple[int, int, int]:
    # 1. Pre-cargar catálogos en batch (ON CONFLICT DO NOTHING)
    _bulk_upsert_catalogs(db, rows)

    # 2. Pre-cargar todos los clientes en batch (ON CONFLICT DO UPDATE)
    all_clientes = []
    for r in rows:
        if r.get("_cliente"):
            all_clientes.append(r["_cliente"])
        if r.get("_cliente_titular"):
            all_clientes.append(r["_cliente_titular"])
    _bulk_upsert_clientes(db, all_clientes)

    # 3. Upsert suscripciones en batch
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    sus_clean = []
    for r in rows:
        r.pop("_cliente", None)
        r.pop("_cliente_titular", None)
        if r.get("numero_ficha"):
            sus_clean.append({"id": uuid.uuid4(), **r})

    if not sus_clean:
        return 0, 0, 0

    # Deduplicar por numero_ficha (último estado gana)
    seen_sus: dict[int, dict] = {}
    for r in sus_clean:
        seen_sus[r["numero_ficha"]] = r
    unique_sus = list(seen_sus.values())

    # Chunk para no superar los 65535 parámetros de PostgreSQL (24 cols x 2700 filas ~= 64800)
    CHUNK_SUS = 2500
    for i in range(0, len(unique_sus), CHUNK_SUS):
        chunk = unique_sus[i : i + CHUNK_SUS]
        stmt = pg_insert(TchSuscripcion).values(chunk).on_conflict_do_update(
            index_elements=["numero_ficha"],
            set_={
                "estado": pg_insert(TchSuscripcion).excluded.estado,
                "banco_nombre": pg_insert(TchSuscripcion).excluded.banco_nombre,
                "tipo_mandato": pg_insert(TchSuscripcion).excluded.tipo_mandato,
                "origen": pg_insert(TchSuscripcion).excluded.origen,
                "centro_costo": pg_insert(TchSuscripcion).excluded.centro_costo,
                "monto": pg_insert(TchSuscripcion).excluded.monto,
                "equivalente_pesos": pg_insert(TchSuscripcion).excluded.equivalente_pesos,
                "fecha_activacion": pg_insert(TchSuscripcion).excluded.fecha_activacion,
                "fecha_rechazo": pg_insert(TchSuscripcion).excluded.fecha_rechazo,
                "fecha_eliminacion": pg_insert(TchSuscripcion).excluded.fecha_eliminacion,
                "razon_baja": pg_insert(TchSuscripcion).excluded.razon_baja,
                "raw_payload": pg_insert(TchSuscripcion).excluded.raw_payload,
            },
        )
        db.execute(stmt)
    db.flush()

    return len(unique_sus), 0, 0


def _load_transacciones(db, rows: list[dict], archivo: str) -> int:
    if not rows:
        return 0
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # Un mismo cargo puede estar en varios reportes. La clave natural conserva uno solo.
    CHUNK = 2000
    unique_rows = {row["dedupe_key"]: row for row in rows}
    to_insert = [{"id": uuid.uuid4(), **row} for row in unique_rows.values()]
    for i in range(0, len(to_insert), CHUNK):
        stmt = pg_insert(TchTransaccion).values(to_insert[i : i + CHUNK]).on_conflict_do_update(
            constraint="uq_tch_transaccion_dedupe_key",
            set_={
                "fecha_cargo": func.coalesce(pg_insert(TchTransaccion).excluded.fecha_cargo, TchTransaccion.fecha_cargo),
                "tipo_transaccion": case(
                    (pg_insert(TchTransaccion).excluded.fecha_cargo.is_(None), TchTransaccion.tipo_transaccion),
                    else_=pg_insert(TchTransaccion).excluded.tipo_transaccion,
                ),
                "entidad_recaudadora": func.coalesce(pg_insert(TchTransaccion).excluded.entidad_recaudadora, TchTransaccion.entidad_recaudadora),
                "codigo_respuesta": func.coalesce(pg_insert(TchTransaccion).excluded.codigo_respuesta, TchTransaccion.codigo_respuesta),
                "razon_rechazo": func.coalesce(pg_insert(TchTransaccion).excluded.razon_rechazo, TchTransaccion.razon_rechazo),
                "archivo_origen": pg_insert(TchTransaccion).excluded.archivo_origen,
                "raw_payload": case(
                    (pg_insert(TchTransaccion).excluded.fecha_cargo.is_(None), TchTransaccion.raw_payload),
                    else_=pg_insert(TchTransaccion).excluded.raw_payload,
                ),
            },
        )
        db.execute(stmt)
    return len(to_insert)


def _load_recaudacion_mensual(db, rows: list[dict]) -> int:
    if not rows:
        return 0
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    statement = pg_insert(TchRecaudacionMensual).values(
        [{"id": uuid.uuid4(), **row} for row in rows]
    ).on_conflict_do_update(
        index_elements=["periodo"],
        set_={
            "aceptadas_cantidad": pg_insert(TchRecaudacionMensual).excluded.aceptadas_cantidad,
            "aceptadas_monto": pg_insert(TchRecaudacionMensual).excluded.aceptadas_monto,
            "rechazadas_cantidad": pg_insert(TchRecaudacionMensual).excluded.rechazadas_cantidad,
            "rechazadas_monto": pg_insert(TchRecaudacionMensual).excluded.rechazadas_monto,
            "archivo_origen": pg_insert(TchRecaudacionMensual).excluded.archivo_origen,
            "updated_at": func.now(),
        },
    )
    db.execute(statement)
    db.flush()
    return len(rows)


_RAZON_BAJA_IMPLICITA = "Baja implicita: ficha ausente del ultimo reporte"


def _apply_implicit_bajas(db, fichas_ultimo_reporte: set[int]) -> int:
    """Marca ELIMINADA toda ficha VIGENTE/PENDIENTE que no aparece en el ultimo reporte.

    Sin esto, una ficha que figuro como vigente en un cierre viejo y luego desaparecio de
    todas las hojas (387 casos en la carga actual) queda VIGENTE para siempre. Con un
    reporte sin cartera (conjunto vacio) no se hace nada.
    """
    if not fichas_ultimo_reporte:
        return 0
    stale = (
        TchSuscripcion.estado.in_(("VIGENTE", "PENDIENTE")),
        TchSuscripcion.numero_ficha.notin_(fichas_ultimo_reporte),
    )
    result = db.execute(
        TchSuscripcion.__table__.update()
        .where(*stale)
        .values(
            estado="ELIMINADA",
            razon_baja=func.coalesce(TchSuscripcion.razon_baja, _RAZON_BAJA_IMPLICITA),
        )
    )
    db.flush()
    return result.rowcount or 0


def _is_latest_report(ultimo_periodo_cargado: str | None, periodo_reporte: str | None) -> bool:
    """Un reporte solo puede dar de baja fichas si no es anterior a lo ya cargado."""
    if not periodo_reporte:
        return False
    return ultimo_periodo_cargado is None or periodo_reporte >= ultimo_periodo_cargado


def _last_closed_period(db) -> str | None:
    """Ultimo mes con cobros en el control mensual (ignora los meses futuros en cero)."""
    return db.scalar(
        select(func.max(TchRecaudacionMensual.periodo)).where(
            TchRecaudacionMensual.aceptadas_cantidad + TchRecaudacionMensual.rechazadas_cantidad > 0
        )
    )


def _report_period(filepath: Path) -> str | None:
    """Mes del reporte segun su nombre: prefiere el texto del mes ("DICIEMBRE 2025") a la fecha del archivo,
    que en los cierres es la del dia siguiente (20260101)."""
    named = _norm_periodo(filepath.stem)
    if named and 2015 <= int(named[:4]) <= 2035:
        return named
    year, month, _, _ = _report_sort_key(filepath)
    return f"{year:04d}-{month:02d}" if year else None


def _purge_future_recaudacion(db) -> int:
    """Borra del control mensual los meses posteriores al ultimo mes cerrado (filas en cero)."""
    last_closed = _last_closed_period(db)
    if last_closed is None:
        return 0
    result = db.execute(
        TchRecaudacionMensual.__table__.delete().where(
            TchRecaudacionMensual.periodo > last_closed,
            TchRecaudacionMensual.aceptadas_cantidad == 0,
            TchRecaudacionMensual.rechazadas_cantidad == 0,
        )
    )
    db.flush()
    return result.rowcount or 0


class ReportAlreadyLoadedError(ValueError):
    """El contenido del reporte (sha256) ya fue cargado antes."""


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


def _clear_tch_data(db) -> None:
    """Rebuild the local TCH projection from the complete report history."""
    report_registry.clear(db)
    for model in (TchRecaudacionMensual, TchTransaccion, TchSuscripcion, TchCliente, TchCentroCosto, TchOrigen, TchTipoMandato, TchBanco):
        db.query(model).delete()
    db.flush()


# ---------------------------------------------------------------------------
# Procesamiento de un archivo
# ---------------------------------------------------------------------------

def _process_file(filepath: Path, db, loaded_history_periods: set[str]) -> dict:
    nombre = filepath.name
    log.info(f"Procesando: {nombre}")

    totales = {"archivo": nombre, "sus_ins": 0, "sus_upd": 0, "trans": 0, "controles": 0, "err": 0}
    fichas: set[int] = set()  # fichas presentes en el reporte (VIGENTES + ELIMINADOS + RECHAZADOS)
    tiene_cartera = False
    totales["fichas"] = fichas

    # --- Catálogo de bancos desde hoja TABLAS ---
    bancos_rows = _transform_bancos_from_tablas(filepath)
    n_bancos = _load_bancos_catalogo(db, bancos_rows)
    if n_bancos:
        log.info(f"  Bancos nuevos: {n_bancos}")

    controles = _load_recaudacion_mensual(db, _transform_recaudacion_mensual(filepath))
    totales["controles"] = controles
    if controles:
        log.info(f"  Controles mensuales: {controles}")

    # --- VIGENTES ---
    df_vig = _read_sheet(filepath, SHEET_VIGENTES)
    if df_vig is not None:
        rows_vig = _transform_suscripciones(df_vig, "VIGENTE")
        trans_rows = _transform_historial_cargos(df_vig, nombre)
        tiene_cartera = bool(rows_vig)
        fichas.update(r["numero_ficha"] for r in rows_vig)
        i, u, e = _load_suscripciones(db, rows_vig)
        totales["sus_ins"] += i
        totales["sus_upd"] += u
        totales["err"] += e
        log.info(f"  VIGENTES: {i} nuevas, {u} actualizadas, {e} errores")

    else:
        trans_rows = []

    # --- ELIMINADOS ---
    df_elim = _read_sheet(filepath, SHEET_ELIMINADOS)
    if df_elim is not None:
        rows_elim = _transform_suscripciones(df_elim, "ELIMINADA")
        trans_rows += _transform_historial_cargos(df_elim, nombre)
        fichas.update(r["numero_ficha"] for r in rows_elim)
        i, u, e = _load_suscripciones(db, rows_elim)
        totales["sus_ins"] += i
        totales["sus_upd"] += u
        totales["err"] += e
        log.info(f"  ELIMINADOS: {i} nuevas, {u} actualizadas, {e} errores")

    # --- RECHAZADOS (mandatos) ---
    df_mandatos_rech = _read_sheet(filepath, SHEET_RECHAZADOS_MANDATOS)
    if df_mandatos_rech is not None:
        rows_mandatos_rech = _transform_suscripciones(df_mandatos_rech, "RECHAZADA")
        trans_rows += _transform_historial_cargos(df_mandatos_rech, nombre)
        fichas.update(r["numero_ficha"] for r in rows_mandatos_rech)
        i, u, e = _load_suscripciones(db, rows_mandatos_rech)
        totales["sus_ins"] += i
        totales["sus_upd"] += u
        totales["err"] += e
        log.info(f"  RECHAZADOS: {i} nuevas, {u} actualizadas, {e} errores")

    if not tiene_cartera:
        fichas.clear()  # sin hoja VIGENTES legible (p. ej. dic-2023) no se infieren bajas

    # --- CARGOS ---
    df_acep = _read_sheet(filepath, SHEET_ACEPTADOS)
    if df_acep is not None:
        trans_rows += _transform_transacciones(df_acep, "ACEPTADA", nombre)

    df_rech = _read_sheet(filepath, SHEET_RECHAZADOS)
    if df_rech is not None:
        trans_rows += _transform_transacciones(df_rech, "RECHAZADA", nombre)

    history_periods = {
        row["periodo"]
        for row in trans_rows
        if row["tipo_transaccion"] == "HISTORIAL_MENSUAL" and row["periodo"]
    }
    new_history_periods = history_periods - loaded_history_periods
    trans_rows = [
        row
        for row in trans_rows
        if row["tipo_transaccion"] != "HISTORIAL_MENSUAL" or row["periodo"] in new_history_periods
    ]
    loaded_history_periods.update(new_history_periods)
    n_trans = _load_transacciones(db, trans_rows, nombre)
    totales["trans"] = n_trans
    log.info(f"  Transacciones: {n_trans}")

    futuros = _purge_future_recaudacion(db)
    if futuros:
        log.info(f"  Meses futuros en cero eliminados del control mensual: {futuros}")

    return totales


# ---------------------------------------------------------------------------
# Registro en etl_runs
# ---------------------------------------------------------------------------

def _start_run(db) -> EtlRun:
    run = EtlRun(status="running", channels_processed=["tch"], records_upserted=0, phase="tch_load")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _finish_run(db, run: EtlRun, total: int, error: str | None = None) -> None:
    run.status = "failed" if error else "completed"
    run.finished_at = datetime.now(timezone.utc)
    run.records_upserted = total
    run.error_message = error
    db.commit()


def import_incremental_file(filepath: Path, run_id=None) -> int:
    """Carga un reporte TCH individual y deja el resultado trazado en ``etl_runs``."""
    db = SessionLocal()
    run = None
    total = 0
    try:
        run = db.get(EtlRun, run_id) if run_id else _start_run(db)
        if run is None:
            raise ValueError("Ejecución ETL no encontrada")
        run.phase = "tch_import"
        db.commit()
        sha = report_registry.file_sha256(filepath)
        if report_registry.is_registered(db, sha):
            raise ReportAlreadyLoadedError("Este reporte ya fue cargado (mismo contenido, sha256 registrado).")
        ultimo_cargado = _last_closed_period(db)
        totals = _process_file(filepath, db, set())
        report_registry.register(db, sha, filepath.name, filepath.stat().st_size)
        total = totals["sus_ins"] + totals["sus_upd"] + totals["trans"] + totals["controles"]
        if _is_latest_report(ultimo_cargado, _report_period(filepath)):
            bajas = _apply_implicit_bajas(db, totals["fichas"])
            log.info(f"  Bajas implicitas (ausentes del reporte): {bajas}")
        _finish_run(db, run, total)
        return total
    except Exception as exc:
        db.rollback()
        if run is not None:
            _finish_run(db, run, total, error=_safe_error_message(exc))
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="ETL para reportes Excel TCH → tablas tch_*")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--folder", help="Carpeta con archivos .xlsx (procesa todos)")
    group.add_argument("--file", help="Archivo .xlsx individual")
    parser.add_argument("--mode", choices=["full", "incremental"], default="incremental")
    args = parser.parse_args()

    if args.folder:
        folder = Path(args.folder)
        if not folder.is_dir():
            log.error(f"Carpeta no encontrada: {folder}")
            sys.exit(1)
        archivos = sorted(
            [f for f in folder.iterdir() if f.suffix.upper() == ".XLSX" and f.is_file() and not f.name.startswith("~$")],
            key=_report_sort_key,
        )
        if not archivos:
            log.error(f"No se encontraron archivos .xlsx en {folder}")
            sys.exit(1)
        archivos, duplicados = _unique_reports_by_sha256(archivos)
        for duplicado in duplicados:
            log.warning(f"Archivo omitido por contenido duplicado (sha256): {duplicado.name}")
        log.info(f"Modo full: {len(archivos)} archivos a procesar")
    else:
        f = Path(args.file)
        if not f.exists():
            log.error(f"Archivo no encontrado: {f}")
            sys.exit(1)
        archivos = [f]
        log.info(f"Modo incremental: {f.name}")

    db = SessionLocal()
    run = _start_run(db)
    log.info(f"EtlRun iniciado: {run.id}")

    total = 0
    loaded_history_periods: set[str] = set()
    ultimo: dict = {}
    try:
        if args.mode == "full":
            _clear_tch_data(db)
            log.info("Proyección TCH anterior eliminada para reconstrucción histórica")
        for archivo in archivos:
            sha = report_registry.file_sha256(archivo)
            ultimo_cargado = _last_closed_period(db)
            if args.mode == "incremental" and report_registry.is_registered(db, sha):
                raise ReportAlreadyLoadedError("Este reporte ya fue cargado (mismo contenido, sha256 registrado).")
            t = _process_file(archivo, db, loaded_history_periods)
            report_registry.register(db, sha, archivo.name, archivo.stat().st_size)
            if args.mode == "incremental" and _is_latest_report(ultimo_cargado, _report_period(archivo)):
                bajas = _apply_implicit_bajas(db, t["fichas"])
                log.info(f"  Bajas implicitas (ausentes del reporte): {bajas}")
            ultimo = t
            total += t["sus_ins"] + t["sus_upd"] + t["trans"] + t["controles"]
            log.info(
                f"  [{archivo.name}] sus={t['sus_ins']}+{t['sus_upd']} "
                f"trans={t['trans']} err={t['err']}"
            )

        if args.mode == "full" and ultimo:
            bajas = _apply_implicit_bajas(db, ultimo["fichas"])
            log.info(f"Bajas implicitas (ausentes de {ultimo['archivo']}): {bajas}")

        _finish_run(db, run, total)
        log.info(f"ETL completado. Total procesados: {total}")
    except Exception as exc:
        db.rollback()
        safe_error = _safe_error_message(exc)
        _finish_run(db, run, total, error=safe_error)
        log.error("ETL fallido: %s", safe_error)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
