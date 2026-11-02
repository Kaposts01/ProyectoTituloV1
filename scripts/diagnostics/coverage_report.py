"""SYNC-D-12 / SYNC-O-14: completitud historica por mes y por canal (certificacion de cobertura), SOLO LECTURA.

Para cada canal recorre TODOS los meses desde el inicio esperado del historico hasta el mes actual (hora de Chile) y
pone lado a lado:

- `base`: lo cargado en el CRM (tablas centralizadas; TCH: `tch_transacciones`). Entidad por canal: VirtualPOS cobros
  (`charges`), Toku y Payku pagos/intentos (`payments`), TCH transacciones. Mismo calculo que `parity_check.py`.
- `referencia`: el conteo del proveedor ya importado en la base, si existe: VirtualPOS = reportes PAT
  (`vp_report_payments`, por fecha programada); Toku = reporte de intentos (`tk_report_attempts`, mes en hora de Chile);
  TCH = control mensual oficial (`tch_recaudacion_mensual`, aceptadas + rechazadas). Payku no tiene reporte cargado.

Estado de cada mes: `hueco` (base en 0), `difiere` (|base - referencia| mayor que la tolerancia), `ok`, o
`sin_referencia` (canal sin reporte o mes fuera de lo que cubre el reporte). Los meses de borde pueden diferir un poco por
huso horario (las fechas de la API vienen en UTC): por eso hay una tolerancia relativa (`--tolerance`, por defecto 2 %).

Inicios esperados (auditoria 2026-10-29, `audit_sync.md`): TCH 2017-01, Payku 2020-08, Toku 2024-10 (intentos),
VirtualPOS 2025-02. `--from` los reemplaza. Cual es la fuente de verdad definitiva de cada conteo es una decision de
negocio abierta (SYNC-D-12); este informe solo muestra los dos lados.

GUARDA: aborta si la base no termina en `_test`, salvo `--read-only` explicito (solo SELECT en transaccion READ ONLY).
No lee archivos ni llama a proveedores; la salida solo trae canal, mes y cantidades.

Uso (desde la raiz del repo):
    $env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/diagnostics/coverage_report.py --channel tch
    $env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/diagnostics/coverage_report.py --only-problems --read-only
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.tch import TchMonthlyCollection
from app.models.toku_report import TkReportAttempt
from app.models.vp_report import VpReportPayment
from app.services.charge_stats import chile_today
from scripts.diagnostics import parity_check, readonly_guard

CHANNELS = parity_check.CHANNELS
EXPECTED_START = {"tch": "2017-01", "payku": "2020-08", "toku": "2024-10", "virtualpos": "2025-02"}
BASE_ENTITY = {"virtualpos": "charge", "toku": "payment", "payku": "payment", "tch": "transaction"}
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_COLUMNS = (("channel", "canal"), ("month", "mes"), ("base", "base"), ("reference", "referencia"), ("diff", "diferencia"),
            ("state", "estado"))


def month_range(start: str, end: str) -> list[str]:
    """Meses AAAA-MM de `start` a `end`, ambos incluidos."""
    year, month = int(start[:4]), int(start[5:7])
    out: list[str] = []
    while f"{year:04d}-{month:02d}" <= end:
        out.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return out


def base_counts(db: Session, channel: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in parity_check.collect(db, channel):
        if row["entity"] == BASE_ENTITY[channel]:
            counts[row["month"]] = counts.get(row["month"], 0) + int(row["count"])
    return counts


def reference_counts(db: Session, channel: str, today_iso: str) -> dict[str, int] | None:
    """Conteo por mes del reporte del proveedor ya importado; None si el canal no tiene reporte."""
    if channel == "virtualpos":
        month = func.to_char(VpReportPayment.scheduled_date, "YYYY-MM")
        query = (
            select(month, func.count())
            .where(VpReportPayment.scheduled_date.is_not(None), func.to_char(VpReportPayment.scheduled_date, "YYYY-MM-DD") <= today_iso)
            .group_by(month)
        )
    elif channel == "toku":
        month = parity_check._chile_month(TkReportAttempt.attempted_at)
        query = select(month, func.count()).where(TkReportAttempt.attempted_at.is_not(None)).group_by(month)
    elif channel == "tch":
        query = select(
            TchMonthlyCollection.period, TchMonthlyCollection.accepted_count + TchMonthlyCollection.rejected_count
        ).where(TchMonthlyCollection.period <= today_iso[:7])
    else:
        return None
    return {str(m): int(c) for m, c in db.execute(query)}


def _state(base: int, reference: int | None, tolerance: float) -> str:
    if base == 0:
        return "hueco"
    if reference is None:
        return "sin_referencia"
    return "difiere" if abs(base - reference) > tolerance * max(reference, 1) else "ok"


def coverage(
    db: Session, channel: str, *, from_month: str | None = None, to_month: str | None = None, tolerance: float = 0.02
) -> list[dict[str, Any]]:
    """Una fila por mes del rango esperado: {channel, month, base, reference, diff, state}."""
    if channel not in CHANNELS:
        raise ValueError(f"Canal desconocido: {channel!r}. Opciones: {', '.join(CHANNELS)}")
    today = chile_today()
    end = min(to_month or today.strftime("%Y-%m"), today.strftime("%Y-%m"))
    base = base_counts(db, channel)
    ref = reference_counts(db, channel, today.isoformat())
    ref_span = (min(ref), max(ref)) if ref else None
    rows = []
    for month in month_range(from_month or EXPECTED_START[channel], end):
        n = base.get(month, 0)
        r = ref.get(month, 0) if ref_span and ref_span[0] <= month <= ref_span[1] else None
        rows.append({"channel": channel, "month": month, "base": n, "reference": r,
                     "diff": None if r is None else n - r, "state": _state(n, r, tolerance)})
    return rows


def summarize(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "(sin meses en el rango)"
    with_data = [r["month"] for r in rows if r["base"]]
    gaps = sum(1 for r in rows if r["state"] == "hueco")
    diffs = sum(1 for r in rows if r["state"] == "difiere")
    first, last = (with_data[0], with_data[-1]) if with_data else ("-", "-")
    return (f"{rows[0]['channel']}: {len(rows)} meses ({rows[0]['month']} a {rows[-1]['month']}); con datos {first} a {last}; "
            f"huecos={gaps}; difieren={diffs}")


def _cells(r: dict[str, Any]) -> list[str]:
    return [str(r["channel"]), r["month"], str(r["base"]), "-" if r["reference"] is None else str(r["reference"]),
            "-" if r["diff"] is None else str(r["diff"]), r["state"]]


def format_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "(sin filas)\n"
    headers = [label for _, label in _COLUMNS]
    cells = [_cells(r) for r in rows]
    widths = [max(len(headers[i]), *(len(c[i]) for c in cells)) for i in range(len(headers))]

    def line(values: list[str]) -> str:
        return "  ".join(v.rjust(widths[i]) if i in (2, 3, 4) else v.ljust(widths[i]) for i, v in enumerate(values)).rstrip()

    return "\n".join([line(headers), "  ".join("-" * w for w in widths), *(line(c) for c in cells)]) + "\n"


def format_csv(rows: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([label for _, label in _COLUMNS])
    for r in rows:
        writer.writerow(_cells(r))
    return buffer.getvalue()


def _month_arg(value: str) -> str:
    if not _MONTH.match(value):
        raise argparse.ArgumentTypeError("use el formato AAAA-MM (p. ej. 2026-03)")
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--channel", choices=(*CHANNELS, "all"), default="all")
    parser.add_argument("--from", dest="from_month", type=_month_arg, help="Primer mes (por defecto, el inicio esperado).")
    parser.add_argument("--to", dest="to_month", type=_month_arg, help="Ultimo mes (por defecto, el actual).")
    parser.add_argument("--tolerance", type=float, default=0.02, help="Diferencia relativa tolerada (0.02 = 2 %%).")
    parser.add_argument("--only-problems", action="store_true", help="Muestra solo meses con hueco o diferencia.")
    parser.add_argument("--strict", action="store_true", help="Codigo de salida 1 si hay huecos o diferencias.")
    parser.add_argument("--format", choices=("table", "csv"), default="table")
    readonly_guard.add_read_only_argument(parser)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db_name = readonly_guard.enforce_database_guard(args.read_only)
    channels = CHANNELS if args.channel == "all" else (args.channel,)
    problems = 0
    db = readonly_guard.open_readonly_session()
    try:
        print(f"Base: {db_name} | ambiente: {settings.env_mode} | solo lectura", file=sys.stderr)
        for channel in channels:
            rows = coverage(db, channel, from_month=args.from_month, to_month=args.to_month, tolerance=args.tolerance)
            problems += sum(1 for r in rows if r["state"] in ("hueco", "difiere"))
            shown = [r for r in rows if r["state"] in ("hueco", "difiere")] if args.only_problems else rows
            if args.format == "table":
                print(f"== {channel} ==")
                print(format_table(shown), end="")
                print(summarize(rows) + "\n")
            else:
                print(format_csv(shown), end="")
    finally:
        db.rollback()
        db.close()
    return 1 if args.strict and problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
