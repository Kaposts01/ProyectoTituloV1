"""Reportes TCH SINTETICOS para las pruebas del ETL: mismos rotulos que los reportes reales, sin datos personales.

Layout (igual al real): filas 1 a 5 vacias, fila 6 con los rotulos de grupo, fila 7 con los rotulos de columna y
datos desde la fila 8. Las hojas de mandatos (VIGENTES, ELIMINADOS, RECHAZADOS) llevan las columnas de identidad
al principio y, desde la columna 62, los 12 bloques mensuales "N / Estado / Monto".
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import openpyxl

MONTHS = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]

_BASE_HEADERS = {
    0: ("Ficha DUES", "Ficha DUES"),
    1: ("SOCIO", "Rut"),
    2: ("ANTECEDENTES Y ESTADO MANDATO", "ESTADO"),
    3: ("MANDATO ACTUAL", "Moneda Vigente"),
    4: ("MANDATO ACTUAL", "Monto Vigente"),
}
_FIRST_EXTRA = 5
_HISTORY_START = 62


def mes_label(year: int, month: int) -> str:
    return f"{MONTHS[month - 1]} {year}"


def _empty_rows(ws) -> None:
    for _ in range(5):
        ws.append([])


def mandate_sheet(
    wb: openpyxl.Workbook,
    title: str,
    rows: list[dict[str, Any]],
    extra_headers: list[tuple[str, str]] | None = None,
) -> None:
    """Hoja de mandatos. Cada fila: ficha, rut, estado, monto, moneda, extra={cabecera: valor}, historial={(anio, mes): (cuota, estado, monto)}."""
    extra_headers = extra_headers or []
    ws = wb.create_sheet(title)
    headers: list[tuple[str, str]] = [("RELLENO", f"c{i}") for i in range(_HISTORY_START)]
    for index, header in _BASE_HEADERS.items():
        headers[index] = header
    for offset, header in enumerate(extra_headers):
        headers[_FIRST_EXTRA + offset] = header
    months = sorted({key for row in rows for key in row.get("historial", {})})
    # 12 bloques fijos: los meses sin datos quedan vacios pero con su rotulo, como en el reporte.
    all_months = months or []
    group = [h[0] for h in headers]
    leaf = [h[1] for h in headers]
    for year, month in all_months:
        group += [mes_label(year, month), None, None]
        leaf += ["N", "Estado", "Monto"]
    _empty_rows(ws)
    ws.append(group)
    ws.append(leaf)
    for row in rows:
        values: list[Any] = [None] * _HISTORY_START
        values[0] = row["ficha"]
        values[1] = row.get("rut", "11111111-1")
        values[2] = row.get("estado", "Activo")
        values[3] = row.get("moneda", "Pesos")
        values[4] = row.get("monto", 10000)
        for offset, header in enumerate(extra_headers):
            values[_FIRST_EXTRA + offset] = row.get("extra", {}).get(header)
        for year, month in all_months:
            installment, status, amount = row.get("historial", {}).get((year, month), (None, None, None))
            values += [installment, status, amount]
        ws.append(values)


def charges_sheet(wb: openpyxl.Workbook, title: str, rows: list[dict[str, Any]], rechazados: bool) -> None:
    """Hoja CARGOS. Cada fila: ficha, cuota, mes ("ENE 26"), monto, fecha (date), motivo."""
    ws = wb.create_sheet(title)
    _empty_rows(ws)
    ws.append([None, None, None, None, "DETALLE DEL PAGO", None, None, None, None, None, None] + ([None] if rechazados else []))
    leaf = ["Numero Ficha", "Numero Mandato", "Transaccion", "Periodo", "N Cuota", "Cuota Mes", "Moneda", "Monto Cuota", "TOTAL RECHAZADO" if rechazados else "TOTAL CARGADO", "Fecha Cobro"]
    if rechazados:
        leaf.append("Motivo")
    ws.append(leaf)
    for index, row in enumerate(rows, start=1):
        values = [
            row["ficha"], 800000 + row["ficha"] % 1000, row.get("transaccion", "Normal"), index, row.get("cuota", 1),
            row["mes"], "Pesos", row.get("monto", 10000), row.get("monto", 10000), row.get("fecha", date(2026, 1, 15)),
        ]
        if rechazados:
            values.append(row.get("motivo"))
        ws.append(values)


def control_sheets(wb: openpyxl.Workbook, periodos: list[tuple[str, int, int]]) -> None:
    """HISTORICO RECAUDACION CAN (cantidades) y FLUJO (montos): (rotulo del mes, aceptadas, rechazadas)."""
    for title, factor in (("HISTORICO RECAUDACION CAN", 1), ("HISTORICO RECAUDACION FLUJO", 10000)):
        ws = wb.create_sheet(title)
        ws.append([None, None, None, *[p for p, _, _ in periodos]])
        ws.append(["TOTAL RECAUDACION EFECTUADA", None, None, *[a * factor for _, a, _ in periodos]])
        ws.append(["TOTAL COBROS RECHAZADOS", None, None, *[r * factor for _, _, r in periodos]])


def write_report(
    path: Path,
    *,
    active: list[dict[str, Any]] | None = None,
    eliminados: list[dict[str, Any]] | None = None,
    rechazados_mandatos: list[dict[str, Any]] | None = None,
    aceptados: list[dict[str, Any]] | None = None,
    rechazados: list[dict[str, Any]] | None = None,
    control: list[tuple[str, int, int]] | None = None,
    extra_headers: list[tuple[str, str]] | None = None,
) -> Path:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    if active is not None:
        mandate_sheet(wb, "VIGENTES", active, extra_headers)
    if eliminados is not None:
        mandate_sheet(wb, "ELIMINADOS", eliminados, extra_headers)
    if rechazados_mandatos is not None:
        mandate_sheet(wb, "RECHAZADOS", rechazados_mandatos, extra_headers)
    if aceptados is not None:
        charges_sheet(wb, "CARGOS ACEPTADOS", aceptados, rechazados=False)
    if rechazados is not None:
        charges_sheet(wb, "CARGOS RECHAZADOS", rechazados, rechazados=True)
    if control is not None:
        control_sheets(wb, control)
    wb.save(path)
    return path
