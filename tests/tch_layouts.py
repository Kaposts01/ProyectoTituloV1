"""Las tres variantes de layout de los reportes TCH, en Excel SINTETICO (TCH-PAR-19). Sin datos personales.

Ningun valor sale de los reportes reales: rotulos copiados del inventario de la auditoria (parity_tch.md, seccion 1),
RUT calculados con el modulo 11 y montos inventados.

* Layout A (2017-2021, 2024-2026): filas 1-5 de titulo, fila 6 rotulos de grupo, fila 7 rotulos de columna, datos
  desde la fila 8. Los rotulos que en el Excel son celdas combinadas en vertical (Ficha DUES, Mandato DUES) solo
  tienen valor en la fila de grupo.
* Layout B (cierre dic-2022): el mismo bloque de encabezado una fila mas abajo (grupo en la fila 7, columna en la 8,
  datos desde la 9).
* Sin VIGENTES (cierre dic-2023): la hoja VIGENTES no es la cartera sino una tabla numerica de 11 columnas; si traen
  detalle ELIMINADOS, RECHAZADOS y las hojas CARGOS.

Cada builder devuelve la ruta del .xlsx escrito.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import openpyxl

from tests.tch_synthetic import charges_sheet, control_sheets, mes_label

HISTORY_START = 62  # columna (0-based) del primer bloque mensual "N / Estado / Monto"

# (grupo, columna) de las columnas de identidad. None en la columna = celda combinada en vertical.
_IDENTITY: list[tuple[str, str | None]] = [
    ("Ficha DUES", None),
    ("Mandato DUES", None),
    ("SOCIO", "Rut"),
    ("SOCIO", "Nombre"),
    ("SOCIO", "Apellido"),
    ("ANTECEDENTES Y ESTADO MANDATO", "Fecha Activacion"),
    ("ANTECEDENTES Y ESTADO MANDATO", "ESTADO"),
    ("MANDATO ACTUAL", "Moneda Vigente"),
    ("MANDATO ACTUAL", "Monto Vigente"),
    ("MANDATO ACTUAL", "Fecha Primer Cobro"),
]


def _mandate_sheet(wb: openpyxl.Workbook, title: str, rows: list[dict[str, Any]], *, header_row: int) -> None:
    """Hoja de mandatos con el encabezado en ``header_row`` (0-based) y ``header_row + 1``; datos debajo."""
    ws = wb.create_sheet(title)
    months = sorted({key for row in rows for key in row.get("historial", {})})
    group: list[Any] = [None] * HISTORY_START
    leaf: list[Any] = [None] * HISTORY_START
    for index, (group_label, leaf_label) in enumerate(_IDENTITY):
        group[index] = group_label
        leaf[index] = leaf_label
    for year, month in months:
        group += [mes_label(year, month), None, None]
        leaf += ["N", "Estado", "Monto"]
    for _ in range(header_row):
        ws.append(["REPORTE GESTION SINTETICO"] if _ == 0 else [])
    ws.append(group)
    ws.append(leaf)
    for row in rows:
        values: list[Any] = [None] * HISTORY_START
        values[0] = row["ficha"]
        values[1] = 800000 + row["ficha"] % 1000
        values[2] = row["rut"]
        values[3] = "Nombre"
        values[4] = "Sintetico"
        values[5] = row.get("activacion")
        values[6] = row.get("estado", "Activo")
        values[7] = "Pesos"
        values[8] = row.get("monto", 10000)
        values[9] = row.get("primer_cobro")
        for key in months:
            values += list(row.get("historial", {}).get(key, (None, None, None)))
        ws.append(values)


def _non_portfolio_vigentes(wb: openpyxl.Workbook) -> None:
    """VIGENTES de dic-2023: tabla numerica de 11 columnas, sin fichas."""
    ws = wb.create_sheet("VIGENTES")
    ws.append(["RESUMEN VIGENTES"])
    ws.append([])
    ws.append(["Mes", *[f"C{i}" for i in range(1, 11)]])
    for month in range(1, 13):
        ws.append([month, *[month * 10 + i for i in range(1, 11)]])


# Dos socios sinteticos (RUT validos por modulo 11) y una ficha de mandato rechazado.
SOCIO_A = "11111111-1"
SOCIO_B = "22222222-2"
SOCIO_C = "33333333-3"


def _base_rows(year: int) -> tuple[list[dict], list[dict], list[dict]]:
    active = [
        {"ficha": 961001, "rut": SOCIO_A, "activacion": date(year - 1, 3, 1), "monto": 10000,
         "historial": {(year, 11): (5, "Pagada", 10000), (year, 12): (6.0, "Impaga", 10000)}},  # cuota flotante
        {"ficha": 961002, "rut": SOCIO_B, "activacion": None, "primer_cobro": date(year, 12, 5), "monto": 7000,
         "historial": {(year, 12): (1, "Pagada", 7000)}},  # alta sin fecha de activacion
    ]
    deleted = [{"ficha": 961003, "rut": SOCIO_C, "estado": "Eliminado", "historial": {(year, 11): (2, "Pagada", 5000)}}]
    rejected = [{"ficha": 961004, "rut": SOCIO_C, "estado": "Rechazado", "historial": {(year, 12): (1, "Rechazada", 5000)}}]
    return active, deleted, rejected


def _charges(wb: openpyxl.Workbook, year: int) -> None:
    yy = str(year)[2:]
    charges_sheet(wb, "CARGOS RECHAZADOS", [
        {"ficha": 961001, "cuota": 6, "mes": f"DIC {yy}", "monto": 10000, "fecha": date(year, 12, 3), "motivo": "Fondos insuficientes"},
    ], rechazados=True)
    charges_sheet(wb, "CARGOS ACEPTADOS", [
        {"ficha": 961001, "cuota": 6, "mes": f"DIC {yy}", "monto": 10000, "fecha": date(year, 12, 20), "transaccion": "Reintento"},
        {"ficha": 961002, "cuota": 1.0, "mes": f"DIC {yy}", "monto": 7000, "fecha": date(year, 12, 5)},
    ], rechazados=False)


def _write(path: Path, year: int, *, header_row: int | None) -> Path:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    active, deleted, rejected = _base_rows(year)
    if header_row is None:
        _non_portfolio_vigentes(wb)
        mandate_header = 5
    else:
        _mandate_sheet(wb, "VIGENTES", active, header_row=header_row)
        mandate_header = header_row
    _mandate_sheet(wb, "ELIMINADOS", deleted, header_row=mandate_header)
    _mandate_sheet(wb, "RECHAZADOS", rejected, header_row=mandate_header)
    _charges(wb, year)
    # Control oficial de dic: 2 aceptadas (incluye el reintento) y 0 rechazadas finales; nov: 2 aceptadas.
    control_sheets(wb, [(mes_label(year, 11), 2, 0), (mes_label(year, 12), 2, 0)])
    wb.save(path)
    return path


def layout_a(folder: Path, year: int = 2024, name: str | None = None) -> Path:
    """Layout A. Por defecto con nombre sin fecha numerica, como los mensuales 2025 ("12 - TCH IG DICIEMBRE ...")."""
    return _write(folder / (name or f"12 - TCH IG DICIEMBRE {year}.xlsx"), year, header_row=5)


def layout_b_2022(folder: Path, year: int = 2022, name: str | None = None) -> Path:
    """Layout B (cierre dic-2022): encabezado una fila mas abajo; nombre con la fecha del dia siguiente al cierre."""
    return _write(folder / (name or f"{year + 1}0102 TCH IG DICIEMBRE {year}.xlsx"), year, header_row=6)


def layout_without_portfolio_2023(folder: Path, year: int = 2023, name: str | None = None) -> Path:
    """Cierre dic-2023: VIGENTES sin cartera."""
    return _write(folder / (name or f"{year}1231 TCH IG DICIEMBRE {year}.xlsx"), year, header_row=None)
