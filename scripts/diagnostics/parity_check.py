"""Conteos por canal, mes y estado en la base, para cuadrar contra los reportes del proveedor (VP-PAR-08 / PK-PAR-08).

SOLO LECTURA: cuenta filas ya cargadas (tablas centralizadas `charges` / `payments` y, para TCH, `tch_transacciones` y
el control mensual `tch_recaudacion_mensual`). No lee ni abre reportes descargados, no llama a ningun proveedor, no
ejecuta migraciones y corre dentro de una transaccion `READ ONLY`: PostgreSQL rechaza cualquier escritura. La salida solo
lleva canal, entidad, mes, estado, cantidad y suma de montos: nada personal.

Uso (desde la raiz del repo):
    $env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/diagnostics/parity_check.py                      # todos los canales
    $env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/diagnostics/parity_check.py --channel payku --from 2025-01
    $env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/diagnostics/parity_check.py --channel virtualpos --format csv

Usa la base del ambiente activo (APP_ENV / DATABASE_URL). GUARDA: si el nombre de la base no termina en `_test` el
script aborta, salvo que se pase explicitamente `--read-only` (entonces solo ejecuta SELECT en una transaccion READ ONLY;
ver `readonly_guard.py`). Ejecutarlo contra `crm` lo decide el usuario. Por defecto no cuenta cobros con fecha
posterior a hoy en hora de Chile (VP-PAR-10: son cobros programados / cancelados a futuro, no hechos); `--include-future`
los incluye.

TK-PAR-10, `--channel toku --vs-report`: compara por mes (hora de Chile) y estado los intentos del reporte de Toku ya
importado (`tk_report_attempts`, fecha de transaccion) contra las transacciones de la API (`tk_transactions`,
`created_at_api` en UTC llevado a America/Santiago), solo hasta el ultimo intento que trae el reporte.
VP-PAR-11, `--channel virtualpos --vs-report`: paridad reportes PAT vs `vp_charges` (`app/services/vp_parity.py`).
Con `--vs-report` el codigo de salida es 1 si hay diferencias.
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

from sqlalchemy import DateTime, Numeric, case, cast, func, literal, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.crm import Charge, Payment
from app.models.tch import TchMonthlyCollection, TchTransaction
from app.models.toku_channel import TokuTransaction
from app.models.toku_report import TkReportAttempt
from app.services import vp_parity
from app.services.charge_stats import chile_today
from scripts.diagnostics import readonly_guard

CHANNELS = ("virtualpos", "toku", "payku", "tch")
_SOURCES = {"virtualpos": ("virtualpos1", "virtualpos2"), "toku": ("toku",), "payku": ("payku",)}
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_NUMERIC = r"^\d+(\.\d+)?$"
_COLUMNS = (("channel", "canal"), ("entity", "entidad"), ("month", "mes"), ("status", "estado"), ("count", "cantidad"), ("amount", "monto"))


def _amount(column: Any) -> Any:
    """Monto como numero; un valor no numerico (p. ej. '$5.000') no suma (mismo criterio que los dashboards)."""
    return case((column.op("~")(_NUMERIC), cast(column, Numeric)), else_=0)


def _in_range(month_expr: Any, from_month: str | None, to_month: str | None) -> list[Any]:
    conditions: list[Any] = []
    if from_month:
        conditions.append(month_expr >= from_month)
    if to_month:
        conditions.append(month_expr <= to_month)
    return conditions


def _crm_rows(
    db: Session, channel: str, model: Any, entity: str, date_column: Any, today_iso: str | None,
    from_month: str | None, to_month: str | None,
) -> list[dict[str, Any]]:
    month = func.substring(date_column, 1, 7)
    day = func.substring(date_column, 1, 10)
    query = (
        select(month, model.status, func.count(), func.coalesce(func.sum(_amount(model.amount)), 0))
        .where(model.source.in_(_SOURCES[channel]), date_column.op("~")(r"^\d{4}-\d{2}"), *_in_range(month, from_month, to_month))
        .group_by(month, model.status)
    )
    if today_iso is not None:
        query = query.where(day <= today_iso)
    return [
        {"channel": channel, "entity": entity, "month": m, "status": status or "(sin estado)", "count": int(count), "amount": float(amount)}
        for m, status, count, amount in db.execute(query)
    ]


def _tch_rows(db: Session, today_month: str | None, from_month: str | None, to_month: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    transactions = (
        select(TchTransaction.period, TchTransaction.status, func.count(), func.coalesce(func.sum(_amount(TchTransaction.amount)), 0))
        .where(TchTransaction.period.op("~")(r"^\d{4}-\d{2}$"), *_in_range(TchTransaction.period, from_month, to_month))
        .group_by(TchTransaction.period, TchTransaction.status)
    )
    controls = select(TchMonthlyCollection).where(*_in_range(TchMonthlyCollection.period, from_month, to_month))
    if today_month is not None:
        transactions = transactions.where(TchTransaction.period <= today_month)
        controls = controls.where(TchMonthlyCollection.period <= today_month)
    for period, status, count, amount in db.execute(transactions):
        rows.append({"channel": "tch", "entity": "transaction", "month": period, "status": status or "(sin estado)",
                     "count": int(count), "amount": float(amount)})
    for control in db.scalars(controls):
        for status, count, amount in (
            ("ACEPTADA", control.accepted_count, control.accepted_amount),
            ("RECHAZADA", control.rejected_count, control.rejected_amount),
        ):
            rows.append({"channel": "tch", "entity": "control_mensual", "month": control.period, "status": status,
                         "count": int(count), "amount": float(amount) if re.match(_NUMERIC, str(amount)) else 0.0})
    return rows


def collect(
    db: Session, channel: str, *, from_month: str | None = None, to_month: str | None = None, include_future: bool = False
) -> list[dict[str, Any]]:
    """Filas {channel, entity, month, status, count, amount} del canal, ordenadas por entidad, mes y estado."""
    if channel not in CHANNELS:
        raise ValueError(f"Canal desconocido: {channel!r}. Opciones: {', '.join(CHANNELS)}")
    today = chile_today()
    if channel == "tch":
        rows = _tch_rows(db, None if include_future else today.strftime("%Y-%m"), from_month, to_month)
    else:
        today_iso = None if include_future else today.isoformat()
        rows = _crm_rows(db, channel, Charge, "charge", Charge.charge_date, today_iso, from_month, to_month)
        rows += _crm_rows(db, channel, Payment, "payment", Payment.payment_date, today_iso, from_month, to_month)
    return sorted(rows, key=lambda r: (r["entity"], r["month"], r["status"]))


def _fmt_amount(value: float) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_table(rows: list[dict[str, Any]]) -> str:
    """Tabla de texto alineada; montos con separador de miles '.' y decimal ','."""
    if not rows:
        return "(sin filas)\n"
    cells = [[str(r["channel"]), str(r["entity"]), str(r["month"]), str(r["status"]), str(r["count"]), _fmt_amount(r["amount"])] for r in rows]
    headers = [label for _, label in _COLUMNS]
    widths = [max(len(headers[i]), *(len(row[i]) for row in cells)) for i in range(len(headers))]
    numeric = {4, 5}

    def line(values: list[str]) -> str:
        return "  ".join(v.rjust(widths[i]) if i in numeric else v.ljust(widths[i]) for i, v in enumerate(values)).rstrip()

    return "\n".join([line(headers), "  ".join("-" * w for w in widths), *(line(row) for row in cells)]) + "\n"


def format_csv(rows: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([label for _, label in _COLUMNS])
    for r in rows:
        writer.writerow([r["channel"], r["entity"], r["month"], r["status"], r["count"], f"{r['amount']:.2f}"])
    return buffer.getvalue()


def open_readonly_session() -> Session:
    """Sesion cuya transaccion es READ ONLY y que solo admite SELECT (PostgreSQL rechaza cualquier escritura)."""
    return readonly_guard.open_readonly_session()


# --------------------------------------------------------------------------------------------------------------- #
# TK-PAR-10: paridad Toku, reporte de intentos vs transacciones de la API (por mes en hora de Chile)               #
# --------------------------------------------------------------------------------------------------------------- #

CHILE_TZ_NAME = "America/Santiago"
# Estado del reporte (Intentos de pago) y de la API llevados a un vocabulario comun. EN PROCESO del reporte aparece
# como FAILED en la API (parity_toku.md, seccion 4), por eso se cuenta como fallido.
_TOKU_STATUS = {
    "autorizado": "autorizado", "authorized": "autorizado", "success": "autorizado", "paid": "autorizado",
    "fallido": "fallido", "failed": "fallido", "en proceso": "fallido",
}
_TOKU_PARITY_COLUMNS = (("month", "mes"), ("status", "estado"), ("report", "reporte"), ("base", "base"), ("diff", "diferencia"))


def _toku_status(value: str | None) -> str:
    key = (value or "").strip().lower()
    return _TOKU_STATUS.get(key, key or "(sin estado)")


def _chile_month(ts: Any) -> Any:
    return func.to_char(func.timezone(literal(CHILE_TZ_NAME), ts), "YYYY-MM")


def toku_report_parity(db: Session, *, from_month: str | None = None, to_month: str | None = None) -> list[dict[str, Any]]:
    """Filas {month, status, report, base, diff} (diff = base - reporte). Vacio si no hay reporte importado."""
    cutoff = db.scalar(select(func.max(TkReportAttempt.attempted_at)))
    if cutoff is None:
        return []
    report_month = _chile_month(TkReportAttempt.attempted_at)
    report_q = (
        select(report_month, TkReportAttempt.status, func.count())
        .where(TkReportAttempt.attempted_at.is_not(None), *_in_range(report_month, from_month, to_month))
        .group_by(report_month, TkReportAttempt.status)
    )
    api_ts = cast(TokuTransaction.created_at_api, DateTime(timezone=True))
    base_month = _chile_month(api_ts)
    base_q = (
        select(base_month, TokuTransaction.status, func.count())
        .where(
            TokuTransaction.created_at_api.op("~")(r"^\d{4}-\d{2}-\d{2}"),
            api_ts <= cutoff,
            *_in_range(base_month, from_month, to_month),
        )
        .group_by(base_month, TokuTransaction.status)
    )
    buckets: dict[tuple[str, str], dict[str, int]] = {}
    for side, query in (("report", report_q), ("base", base_q)):
        for month, status, count in db.execute(query):
            cell = buckets.setdefault((month, _toku_status(status)), {"report": 0, "base": 0})
            cell[side] += int(count)
    return [
        {"month": m, "status": st, "report": c["report"], "base": c["base"], "diff": c["base"] - c["report"]}
        for (m, st), c in sorted(buckets.items())
    ]


def format_toku_parity(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "Sin reporte de intentos de Toku importado (tk_report_attempts vacio): no hay contra que comparar.\n"
    headers = [label for _, label in _TOKU_PARITY_COLUMNS]
    cells = [[str(r[key]) for key, _ in _TOKU_PARITY_COLUMNS] for r in rows]
    widths = [max(len(headers[i]), *(len(row[i]) for row in cells)) for i in range(len(headers))]
    out = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip(), "  ".join("-" * w for w in widths)]
    out += ["  ".join(v.rjust(widths[i]) if i >= 2 else v.ljust(widths[i]) for i, v in enumerate(row)).rstrip() for row in cells]
    differing = sum(1 for r in rows if r["diff"])
    out.append("Paridad OK" if not differing else f"Paridad con diferencias en {differing} fila(s) mes/estado")
    return "\n".join(out) + "\n"


def _month_arg(value: str) -> str:
    if not _MONTH.match(value):
        raise argparse.ArgumentTypeError("use el formato AAAA-MM (p. ej. 2026-03)")
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--channel", choices=(*CHANNELS, "all"), default="all", help="Canal a contar (por defecto todos).")
    parser.add_argument("--from", dest="from_month", type=_month_arg, help="Primer mes (AAAA-MM).")
    parser.add_argument("--to", dest="to_month", type=_month_arg, help="Ultimo mes (AAAA-MM).")
    parser.add_argument("--include-future", action="store_true", help="Incluye cobros con fecha posterior a hoy (Chile).")
    parser.add_argument("--format", choices=("table", "csv"), default="table", help="Formato de salida.")
    parser.add_argument(
        "--vs-report", action="store_true",
        help="Compara contra el reporte importado del proveedor (toku: TK-PAR-10; virtualpos: VP-PAR-11).",
    )
    readonly_guard.add_read_only_argument(parser)
    return parser.parse_args(argv)


def _main_vs_report(db: Session, channels: tuple[str, ...], args: argparse.Namespace) -> int:
    differences = False
    for channel in channels:
        print(f"== {channel} vs reporte ==")
        if channel == "toku":
            rows = toku_report_parity(db, from_month=args.from_month, to_month=args.to_month)
            print(format_toku_parity(rows))
            differences |= any(r["diff"] for r in rows)
        elif channel == "virtualpos":
            result = vp_parity.compute_vp_parity(db, from_month=args.from_month, to_month=args.to_month)
            print(vp_parity.format_result(result))
            differences |= bool(result.differences)
        else:
            print("(sin reporte importado para este canal)\n")
    return 1 if differences else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db_name = readonly_guard.enforce_database_guard(args.read_only)
    channels = CHANNELS if args.channel == "all" else (args.channel,)
    db = open_readonly_session()
    try:
        print(f"Base: {db_name} | ambiente: {settings.env_mode} | solo lectura", file=sys.stderr)
        if args.vs_report:
            return _main_vs_report(db, channels, args)
        for channel in channels:
            rows = collect(db, channel, from_month=args.from_month, to_month=args.to_month, include_future=args.include_future)
            if args.format == "table":
                print(f"== {channel} ==")
                print(format_table(rows))
            else:
                print(format_csv(rows), end="")
    finally:
        db.rollback()
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
