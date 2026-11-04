"""d139e/f (L5-ALERTAS): alertas operativas de reportes viejos y escrituras fallidas. Ver docs/data/alerts.md.

Se registran en `app.services.alerts` con `register_condition_provider` (mismo chequeo, deduplicacion, recordatorio
cada 6 h y aviso de «Recuperado»). Cada una tiene su bandera, APAGADA por defecto (d138):

- `report_stale:toku` / `report_stale:tch` (`ALERT_REPORT_AGE_ENABLED`): el ultimo reporte cargado tiene mas de
  `REPORT_MAX_AGE_DAYS` (7) dias, o no se cargo ninguno en ese plazo. Toku mira la fecha de generacion de cada tipo
  (DEC-21, la misma regla del panel de importaciones) y la ultima carga; TCH mira la ultima carga de `tch_file_loads`.
- `write_failed` (`ALERT_WRITE_FAILED_ENABLED`): `write_runs` en `failed` en las ultimas 24 h. Los que estan en
  `reconciliation_required` NO cuentan: esos ya los avisa `billing_reconciliation` (cola de conciliacion).

Solo lectura y sin datos personales: tipos de reporte, canales, operaciones y contadores (nunca nombres de archivo,
ids externos ni `error_message`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.write_run import WriteRun
from app.services import alerts

REPORT_KIND = "report_stale"
WRITE_KIND = "write_failed"
WRITE_FAILED_WINDOW = timedelta(hours=24)
REPORTS_LINK = "/admin/sincronizaciones"
WRITES_LINK = "/admin/sincronizaciones"
_REPORT_LABELS = {"toku": "Toku", "tch": "TCH"}


def _max_age_days() -> int:
    from app.services.toku_report_import import REPORT_MAX_AGE_DAYS

    return int(REPORT_MAX_AGE_DAYS)


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _report_condition(channel: str, text: str, details: tuple[str, ...]) -> alerts.Condition:
    label = _REPORT_LABELS[channel]
    return alerts.Condition(
        key=f"{REPORT_KIND}:{channel}", channel=label, title=f"reportes de {label} desactualizados",
        text=text, details=details, link=REPORTS_LINK)


def _toku_report_condition(db: Session, now: datetime, max_days: int) -> alerts.Condition | None:
    from app.models.toku_report import TkReportFile
    from app.services.toku_report_import import report_freshness

    limit = timedelta(days=max_days)
    last_load = _aware(db.scalar(select(func.max(TkReportFile.finished_at)).where(TkReportFile.status == "completed")))
    stale_types = [r for r in report_freshness(db, now) if r["is_stale"]]
    no_recent_load = last_load is None or now - last_load > limit
    if not stale_types and not no_recent_load:
        return None
    details: list[str] = []
    if last_load is None:
        text = f"No hay ningún reporte de Toku cargado (plazo: {max_days} días)."
    elif no_recent_load:
        text = f"No se carga un reporte de Toku hace {(now - last_load).days} días (plazo: {max_days} días)."
    else:
        text = f"{len(stale_types)} tipo(s) de reporte de Toku con datos de más de {max_days} días."
    details += [f"{r['report_type']}: datos de hace {r['age_days']} días" for r in stale_types]
    return _report_condition("toku", text, tuple(details))


def _tch_report_condition(db: Session, now: datetime, max_days: int) -> alerts.Condition | None:
    from app.services.tch_report_registry import last_loaded_at

    last = _aware(last_loaded_at(db))
    if last is not None and now - last <= timedelta(days=max_days):
        return None
    if last is None:
        text = f"No hay ningún reporte TCH cargado (plazo: {max_days} días)."
    else:
        text = f"El último reporte TCH se cargó hace {(now - last).days} días (plazo: {max_days} días)."
    return _report_condition("tch", text, ("TCH depende de que alguien suba el Excel del período.",))


def report_conditions(db: Session, now: datetime) -> list[alerts.Condition]:
    max_days = _max_age_days()
    found = [_toku_report_condition(db, now, max_days), _tch_report_condition(db, now, max_days)]
    return [c for c in found if c is not None]


def describe_report(channel: str) -> tuple[str, str]:
    label = _REPORT_LABELS.get(channel, channel)
    return label, f"reportes de {label} desactualizados"


def write_failed_conditions(db: Session, now: datetime) -> list[alerts.Condition]:
    since = now - WRITE_FAILED_WINDOW
    when = func.coalesce(WriteRun.finished_at, WriteRun.started_at)
    rows = db.execute(
        select(WriteRun.source, WriteRun.operation, func.count())
        .where(WriteRun.status == "failed", when >= since)
        .group_by(WriteRun.source, WriteRun.operation)
        .order_by(WriteRun.source, WriteRun.operation)
    ).all()
    if not rows:
        return []
    total = sum(int(n) for _, _, n in rows)
    return [alerts.Condition(
        key=WRITE_KIND, channel="Escrituras a proveedores", title="escrituras fallidas",
        text=(f"{total} escritura(s) a proveedores fallida(s) en las últimas 24 h, fuera de la cola de conciliación."),
        details=tuple(f"{source} · {operation}: {int(n)}" for source, operation, n in rows), link=WRITES_LINK)]


def register() -> None:
    alerts.register_condition_provider(REPORT_KIND, report_conditions, describe_report,
                                       lambda: bool(settings.alert_report_age_enabled))
    alerts.register_condition_provider(WRITE_KIND, write_failed_conditions,
                                       lambda _d: ("Escrituras a proveedores", "escrituras fallidas"),
                                       lambda: bool(settings.alert_write_failed_enabled))


register()
