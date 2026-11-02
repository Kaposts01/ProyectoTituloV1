"""VP-PAR-11: paridad permanente entre los reportes PAT de VirtualPOS ya importados y la base (SOLO LECTURA).

Compara, por mes de fecha programada y SOLO dentro de la ventana que cubren los reportes (primera y ultima fecha
programada de `vp_report_payments`), los cobros del reporte `TransaccionesPAT` contra `vp_charges` (la copia de la API):

- `report` / `base`: cobros por mes en cada lado;
- `only_report`: `Id cargo` del reporte que no esta en la base (la sync no lo trajo);
- `only_base`: cobro de la base dentro de la ventana que ningun reporte trae;
- `status_mismatch`: mismo `Id cargo` con distinto estado (`pagado`/`rechazado`/`procesando`...; mismo vocabulario).

Solo hace SELECT; no lee archivos ni llama al proveedor. La salida es agregada (mes y cantidades): nada personal.
Lo usan el script `scripts/diagnostics/vp_parity_check.py` y el job `vp_parity_check` (apagado por defecto).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import and_, func, literal, select
from sqlalchemy.orm import Session

from app.models.vp import VpCharge
from app.models.vp_report import VpReportPayment

_DATE_RE = r"^\d{4}-\d{2}-\d{2}"


@dataclass
class MonthParity:
    month: str
    report: int = 0
    base: int = 0
    only_report: int = 0
    only_base: int = 0
    status_mismatch: int = 0

    @property
    def ok(self) -> bool:
        return self.report == self.base and not (self.only_report or self.only_base or self.status_mismatch)


@dataclass
class VpParityResult:
    window_start: date | None
    window_end: date | None
    months: list[MonthParity] = field(default_factory=list)

    @property
    def has_report(self) -> bool:
        return self.window_start is not None

    @property
    def differences(self) -> list[MonthParity]:
        return [m for m in self.months if not m.ok]

    @property
    def ok(self) -> bool:
        return self.has_report and not self.differences

    def totals(self) -> dict[str, int]:
        keys = ("report", "base", "only_report", "only_base", "status_mismatch")
        return {k: sum(getattr(m, k) for m in self.months) for k in keys}


def _norm(column: Any) -> Any:
    return func.lower(func.trim(func.coalesce(column, literal(""))))


def report_window(db: Session) -> tuple[date | None, date | None]:
    return db.execute(select(func.min(VpReportPayment.scheduled_date), func.max(VpReportPayment.scheduled_date))).one()


def compute_vp_parity(db: Session, *, from_month: str | None = None, to_month: str | None = None) -> VpParityResult:
    """Paridad por mes dentro de la ventana de los reportes; `from_month`/`to_month` (AAAA-MM) la acotan mas."""
    start, end = report_window(db)
    result = VpParityResult(start, end)
    if start is None or end is None:
        return result

    start_iso, end_iso = start.isoformat(), end.isoformat()
    base_day = func.substring(VpCharge.charge_date, 1, 10)
    base_in_window = and_(VpCharge.charge_date.op("~")(_DATE_RE), base_day >= start_iso, base_day <= end_iso)
    report_month = func.to_char(VpReportPayment.scheduled_date, "YYYY-MM")
    base_month = func.substring(VpCharge.charge_date, 1, 7)
    report_in_window = VpReportPayment.scheduled_date.is_not(None)

    def month_filter(expr: Any) -> list[Any]:
        conditions = []
        if from_month:
            conditions.append(expr >= from_month)
        if to_month:
            conditions.append(expr <= to_month)
        return conditions

    months: dict[str, MonthParity] = {}

    def bucket(month: str) -> MonthParity:
        return months.setdefault(month, MonthParity(month))

    report_counts = (
        select(report_month, func.count())
        .where(report_in_window, *month_filter(report_month))
        .group_by(report_month)
    )
    for month, count in db.execute(report_counts):
        bucket(month).report = int(count)

    base_counts = select(base_month, func.count()).where(base_in_window, *month_filter(base_month)).group_by(base_month)
    for month, count in db.execute(base_counts):
        bucket(month).base = int(count)

    # Un mismo `Id cargo` puede estar en las dos cuentas (vp1/vp2): se compara contra cualquiera de ellas.
    in_base = select(VpCharge.id).where(VpCharge.external_id == VpReportPayment.charge_external_id).exists()
    only_report = (
        select(report_month, func.count())
        .where(report_in_window, ~in_base, *month_filter(report_month))
        .group_by(report_month)
    )
    for month, count in db.execute(only_report):
        bucket(month).only_report = int(count)

    in_report = select(VpReportPayment.id).where(VpReportPayment.charge_external_id == VpCharge.external_id).exists()
    only_base = (
        select(base_month, func.count())
        .where(base_in_window, ~in_report, *month_filter(base_month))
        .group_by(base_month)
    )
    for month, count in db.execute(only_base):
        bucket(month).only_base = int(count)

    mismatch = (
        select(report_month, func.count(func.distinct(VpReportPayment.charge_external_id)))
        .join(VpCharge, VpCharge.external_id == VpReportPayment.charge_external_id)
        .where(report_in_window, _norm(VpReportPayment.charge_status) != _norm(VpCharge.status), *month_filter(report_month))
        .group_by(report_month)
    )
    for month, count in db.execute(mismatch):
        bucket(month).status_mismatch = int(count)

    result.months = [months[m] for m in sorted(months)]
    return result


def format_result(result: VpParityResult) -> str:
    """Tabla de texto (mes y cantidades); sin datos personales."""
    if not result.has_report:
        return "Sin reportes PAT importados (vp_report_payments vacio): no hay contra que comparar.\n"
    headers = ["mes", "reporte", "base", "solo_reporte", "solo_base", "estado_distinto", "ok"]
    rows = [
        [m.month, str(m.report), str(m.base), str(m.only_report), str(m.only_base), str(m.status_mismatch), "si" if m.ok else "NO"]
        for m in result.months
    ]
    widths = [max(len(headers[i]), *(len(r[i]) for r in rows)) if rows else len(headers[i]) for i in range(len(headers))]
    lines = [
        f"Ventana de los reportes: {result.window_start.isoformat()} a {result.window_end.isoformat()}",  # type: ignore[union-attr]
        "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip(),
        "  ".join("-" * w for w in widths),
        *("  ".join(c.rjust(widths[i]) if 0 < i < 6 else c.ljust(widths[i]) for i, c in enumerate(r)).rstrip() for r in rows),
    ]
    totals = result.totals()
    lines.append(
        "Total: reporte={report} base={base} solo_reporte={only_report} solo_base={only_base} "
        "estado_distinto={status_mismatch}".format(**totals)
    )
    lines.append("Paridad OK" if result.ok else f"Paridad con diferencias en {len(result.differences)} mes(es)")
    return "\n".join(lines) + "\n"
