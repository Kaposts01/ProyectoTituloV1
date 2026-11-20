"""REP-02: arma el resumen semanal y el cierre mensual que se envian por correo. Ver docs/data/scheduled_reports.md.

SOLO cifras agregadas por canal: nunca nombres, RUT, correos, telefonos ni ids de socios o suscripciones. El HTML usa
estilos en linea y tablas, sin JavaScript, sin imagenes ni enlaces externos. El CSV adjunto tiene las columnas
`periodo,canal,activas,altas,bajas,cobros_aprobados,cobros_rechazados,churn,mrr,recuperacion`.

Minimo de agregacion (riesgo de la seccion 7 del plan): una cifra de un canal que salga de 1 a 4 socios se muestra como
`<5` (el 0 se muestra tal cual). Para que no se pueda restar, el total de una columna con alguna cifra enmascarada sale
como `—`; el churn se enmascara si sus dos insumos (bajas o activas) lo estan; el MRR, si el canal tiene menos de 5
clientes activos.

Fuentes de cada cifra (una sola por cifra): altas, bajas, activas, cobros y churn de `report_figures.auto_period_data`
(REP-01); MRR de `dashboard_general._mrr_by_channel` (foto al armar el correo); recuperacion de `charge_recoveries`;
estado de sincronizaciones de `sync_runs._compute_health`, calculado al armar el correo. Este modulo solo lee: no escribe
en `sync_runs`, `etl_runs` ni `source_records`.
"""

from __future__ import annotations

import csv
import html
import io
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.charge_recovery import ChargeRecovery
from app.services.report_figures import auto_period_data

logger = logging.getLogger(__name__)

CHILE = ZoneInfo("America/Santiago")
CHANNELS = ("virtualpos", "toku", "payku", "tch")
LABELS = {"virtualpos": "VirtualPOS", "toku": "Toku", "payku": "Payku", "tch": "TCH", "total": "Total"}
MIN_GROUP = 5
MASKED = "<5"
NOT_AVAILABLE = "—"
CSV_MONTHS = 13
CSV_COLUMNS = (
    "periodo", "canal", "activas", "altas", "bajas", "cobros_aprobados", "cobros_rechazados", "churn", "mrr", "recuperacion",
)
_COUNT_COLUMNS = ("activas", "altas", "bajas", "cobros_aprobados", "cobros_rechazados", "recuperacion")
_ENV_LABELS = {"production": "producción", "sandbox": "sandbox", "qa": "qa"}
_STATE_TEXT = {
    "ok": "Al día", "stale": "Atrasada", "failed": "Con fallos", "running": "En curso", "unknown": "Sin datos",
}
_MONTHS_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre",
    "diciembre",
)


@dataclass(frozen=True)
class BuiltReport:
    kind: str  # weekly | monthly
    period_key: str  # weekly:2026-W47 | monthly:2026-10
    subject: str
    html: str
    text: str
    csv_name: str
    csv_text: str


# ----------------------------- periodos (hora de Chile) -----------------------------


def chile_date(moment: datetime) -> date:
    """Fecha local de Chile de un instante (un datetime sin zona se toma como UTC)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(CHILE).date()


def weekly_period(now: datetime) -> tuple[date, date]:
    """Ultima semana completa (lunes a domingo) anterior a la fecha local de `now`."""
    today = chile_date(now)
    monday = today - timedelta(days=today.weekday() + 7)
    return monday, monday + timedelta(days=6)


def weekly_key(monday: date) -> str:
    year, week, _ = monday.isocalendar()
    return f"weekly:{year}-W{week:02d}"


def monthly_period(now: datetime) -> tuple[date, date]:
    """Mes calendario anterior al de la fecha local de `now`."""
    last = chile_date(now).replace(day=1) - timedelta(days=1)
    return last.replace(day=1), last


def monthly_key(first: date) -> str:
    return f"monthly:{first:%Y-%m}"


def _month_bounds(first: date, back: int) -> tuple[date, date]:
    """Mes que esta `back` meses antes del que empieza en `first`."""
    index = first.year * 12 + (first.month - 1) - back
    start = date(index // 12, index % 12 + 1, 1)
    nxt = date((index + 1) // 12, (index + 1) % 12 + 1, 1)
    return start, nxt - timedelta(days=1)


def _fmt_date(day: date) -> str:
    return day.strftime("%d-%m-%Y")


def _month_label(first: date) -> str:
    return f"{_MONTHS_ES[first.month - 1]} {first.year}"


# ----------------------------- cifras crudas -----------------------------


def _recovery_counts(db: Session, start: date, end: date) -> dict[str, int]:
    """Reintentos de cobro cobrados con exito (`cobrado`) y cerrados en el rango, por canal. Solo conteos."""
    lower = datetime(start.year, start.month, start.day, tzinfo=CHILE)
    upper = datetime(end.year, end.month, end.day, tzinfo=CHILE) + timedelta(days=1)
    rows = db.execute(
        select(ChargeRecovery.source, func.count())
        .where(ChargeRecovery.status == "cobrado", ChargeRecovery.closed_at >= lower, ChargeRecovery.closed_at < upper)
        .group_by(ChargeRecovery.source)
    ).all()
    out: dict[str, int] = {}
    for source, count in rows:
        channel = "virtualpos" if str(source).startswith("virtualpos") else str(source)
        out[channel] = out.get(channel, 0) + int(count)
    return out


def period_figures(db: Session, start: date, end: date) -> dict[str, dict[str, float]]:
    """Cifras crudas (sin enmascarar) de un rango: {canal|total: {...}}. Fuente unica por cifra, ver el docstring."""
    data = auto_period_data(db, start, end)
    recovered = _recovery_counts(db, start, end)
    out: dict[str, dict[str, float]] = {}
    for name in (*CHANNELS, "global"):
        ch = data["channels"][name]
        key = "total" if name == "global" else name
        out[key] = {
            "activas": ch["active_end"],
            "activas_inicio": ch["active_start"],
            "altas": ch["new_subscriptions"],
            "bajas": ch["cancellations"],
            "cobros_aprobados": ch["revenue_count"],
            "cobros_rechazados": ch["rejected"],
            "churn": ch["churn_rate"],
            "recuperacion": sum(recovered.values()) if key == "total" else recovered.get(key, 0),
        }
    return out


def mrr_snapshot(db: Session, today: date) -> dict[str, tuple[float, int]]:
    """MRR y clientes activos por canal, al momento de armar el correo (no hay MRR historico)."""
    from app.services.dashboard_general import _mrr_by_channel

    return _mrr_by_channel(db, list(CHANNELS), today)


# ----------------------------- enmascarado y filas -----------------------------


def _count(value: float) -> tuple[str, bool]:
    n = int(value or 0)
    if 0 < n < MIN_GROUP:
        return MASKED, True
    return str(n), False


def display_rows(
    label: str, figures: dict[str, dict[str, float]], mrr: dict[str, tuple[float, int]] | None = None
) -> list[dict[str, str]]:
    """Filas de texto (las que van al HTML y al CSV) con el minimo de agregacion aplicado."""
    rows: list[dict[str, str]] = []
    masked_columns: set[str] = set()
    for channel in CHANNELS:
        fig = figures[channel]
        row = {"periodo": label, "canal": channel}
        for column in _COUNT_COLUMNS:
            row[column], hidden = _count(fig[column])
            if hidden:
                masked_columns.add(column)
        small = any(0 < int(fig[k] or 0) < MIN_GROUP for k in ("bajas", "activas_inicio"))
        row["churn"] = NOT_AVAILABLE if small else str(round(float(fig["churn"] or 0), 2))
        if mrr is None or channel not in mrr:
            row["mrr"] = ""
        else:
            amount, clients = mrr[channel]
            row["mrr"] = MASKED if 0 < clients < MIN_GROUP else str(round(amount))
        rows.append(row)
    total = {"periodo": label, "canal": "total"}
    for column in _COUNT_COLUMNS:
        total[column] = NOT_AVAILABLE if column in masked_columns else _count(figures["total"][column])[0]
    total["churn"] = (
        NOT_AVAILABLE if NOT_AVAILABLE in (total["bajas"], total["activas"]) or any(r["churn"] == NOT_AVAILABLE for r in rows)
        else str(round(float(figures["total"]["churn"] or 0), 2))
    )
    mrr_values = [r["mrr"] for r in rows if r["mrr"]]
    if not mrr_values:
        total["mrr"] = ""
    elif MASKED in mrr_values:
        total["mrr"] = NOT_AVAILABLE
    else:
        total["mrr"] = str(sum(int(v) for v in mrr_values))
    rows.append(total)
    return rows


def to_csv(rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({**row, "canal": LABELS.get(row["canal"], row["canal"])})
    return buffer.getvalue()


# ----------------------------- estado de sincronizaciones -----------------------------


def sync_status(db: Session, now: datetime) -> list[dict[str, str]]:
    """Estado por canal calculado al armar el correo. Sin mensajes de error ni datos personales."""
    from app.api.v1.routes.sync_runs import _compute_health

    try:
        items = _compute_health(db, now)
    except Exception as exc:  # noqa: BLE001 - el reporte sale igual, con la nota de que el estado no estuvo disponible
        db.rollback()
        logger.warning("Reporte: estado de sincronizaciones no disponible (%s).", type(exc).__name__)
        return []
    out: list[dict[str, str]] = []
    for item in items:
        last = item.get("last_finished_at")
        last_text = "sin sincronizaciones"
        if last:
            last_text = datetime.fromisoformat(str(last)).astimezone(CHILE).strftime("%d-%m-%Y %H:%M")
        out.append({
            "canal": LABELS.get(str(item["channel"]), str(item["channel"])),
            "estado": _STATE_TEXT.get(str(item.get("state")), "Sin datos"),
            "ultima": last_text,
        })
    return out


# ----------------------------- HTML y texto -----------------------------

_TH = "text-align:right;padding:6px 10px;border-bottom:2px solid #1f2a44;font-weight:600;"
_TD = "text-align:right;padding:6px 10px;border-bottom:1px solid #d9dde6;"
_LEFT = "text-align:left;"
_HEADERS = (
    ("canal", "Canal"), ("activas", "Activas"), ("altas", "Altas"), ("bajas", "Bajas"),
    ("cobros_aprobados", "Cobros aprobados"), ("cobros_rechazados", "Cobros rechazados"), ("churn", "Churn"),
    ("mrr", "MRR"), ("recuperacion", "Recuperación"),
)


def _cell(column: str, value: str) -> str:
    if value == "":
        return NOT_AVAILABLE
    if column == "churn" and value not in (NOT_AVAILABLE, MASKED):
        return f"{value}%"
    if column == "mrr" and value.lstrip("-").isdigit():
        return "$" + f"{int(value):,}".replace(",", ".")
    return value


def _table(title: str, rows: list[dict[str, str]], skip_mrr: bool = False) -> str:
    headers = [(k, v) for k, v in _HEADERS if not (skip_mrr and k == "mrr")]
    head = "".join(
        f'<th style="{_TH}{_LEFT if k == "canal" else ""}">{html.escape(v)}</th>' for k, v in headers
    )
    body = []
    for row in rows:
        weight = "font-weight:600;" if row["canal"] == "total" else ""
        cells = "".join(
            f'<td style="{_TD}{_LEFT if k == "canal" else ""}{weight}">'
            f'{html.escape(LABELS.get(row[k], row[k]) if k == "canal" else _cell(k, row[k]))}</td>'
            for k, _ in headers
        )
        body.append(f"<tr>{cells}</tr>")
    return (
        f'<h3 style="margin:22px 0 8px;font-size:15px;color:#1f2a44;">{html.escape(title)}</h3>'
        f'<table style="border-collapse:collapse;width:100%;font-size:13px;"><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table>'
    )


def _sync_table(items: list[dict[str, str]]) -> str:
    if not items:
        return (
            '<h3 style="margin:22px 0 8px;font-size:15px;color:#1f2a44;">Sincronizaciones</h3>'
            '<p style="font-size:13px;">Estado no disponible al armar este correo.</p>'
        )
    rows = "".join(
        f'<tr><td style="{_TD}{_LEFT}">{html.escape(i["canal"])}</td><td style="{_TD}{_LEFT}">{html.escape(i["estado"])}</td>'
        f'<td style="{_TD}">{html.escape(i["ultima"])}</td></tr>'
        for i in items
    )
    return (
        '<h3 style="margin:22px 0 8px;font-size:15px;color:#1f2a44;">Sincronizaciones (al armar este correo)</h3>'
        '<table style="border-collapse:collapse;width:100%;font-size:13px;"><thead><tr>'
        f'<th style="{_TH}{_LEFT}">Canal</th><th style="{_TH}{_LEFT}">Estado</th><th style="{_TH}">Última sincronización</th>'
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def _html(title: str, subtitle: str, env: str, tables: str, sync_html: str) -> str:
    return (
        '<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><title>' + html.escape(title) + "</title></head>"
        '<body style="margin:0;padding:0;background:#f4f6fa;">'
        '<div style="max-width:760px;margin:0 auto;padding:24px;background:#ffffff;font-family:Arial,Helvetica,sans-serif;'
        'color:#1b2236;">'
        f'<h2 style="margin:0 0 4px;font-size:20px;color:#1f2a44;">{html.escape(title)}</h2>'
        f'<p style="margin:0 0 4px;font-size:13px;color:#4b556b;">{html.escape(subtitle)}</p>'
        f'<p style="margin:0 0 8px;font-size:12px;color:#4b556b;">Ambiente: {html.escape(env)}</p>'
        f"{tables}{sync_html}"
        '<p style="margin:24px 0 0;font-size:11px;color:#6b7488;">Mensaje automático de SynkmetriX con cifras agregadas por '
        f"canal; no contiene datos personales. Las cifras de 1 a 4 socios se muestran como {html.escape(MASKED)}; "
        f"{html.escape(NOT_AVAILABLE)} indica que no se puede mostrar sin revelar una cifra pequeña. El MRR es una foto "
        "al armar el correo. Se adjunta un CSV con las mismas cifras.</p>"
        "</div></body></html>"
    )


def _plain(title: str, subtitle: str, rows: list[dict[str, str]]) -> str:
    lines = [title, subtitle, ""]
    for row in rows:
        lines.append(
            f"{LABELS.get(row['canal'], row['canal'])}: activas {row['activas']}, altas {row['altas']}, bajas {row['bajas']}, "
            f"cobros aprobados {row['cobros_aprobados']}, rechazados {row['cobros_rechazados']}, "
            f"recuperación {row['recuperacion']}"
        )
    lines += ["", "Detalle en la versión HTML y en el CSV adjunto.", "Mensaje automático de SynkmetriX. No contiene datos personales."]
    return "\n".join(lines)


def _env_label() -> str:
    return _ENV_LABELS.get(settings.env_mode, settings.env_mode)


# ----------------------------- armado -----------------------------


def build_weekly(db: Session, now: datetime | None = None) -> BuiltReport:
    """Resumen de la ultima semana completa (lunes a domingo). La clave es la semana ISO que se reporta."""
    moment = now or datetime.now(UTC)
    start, end = weekly_period(moment)
    prev_start, prev_end = start - timedelta(days=7), end - timedelta(days=7)
    today = chile_date(moment)
    current = period_figures(db, start, end)
    previous = period_figures(db, prev_start, prev_end)
    mrr = mrr_snapshot(db, today)
    cur_label = f"{start.isocalendar().year}-W{start.isocalendar().week:02d}"
    prev_label = f"{prev_start.isocalendar().year}-W{prev_start.isocalendar().week:02d}"
    rows = display_rows(cur_label, current, mrr)
    prev_rows = display_rows(prev_label, previous)
    csv_text = to_csv(prev_rows + rows)
    title = "Resumen semanal"
    subtitle = f"Semana del {_fmt_date(start)} al {_fmt_date(end)}"
    env = _env_label()
    body = _table(f"Semana {cur_label}", rows) + _table(f"Semana anterior ({prev_label})", prev_rows, skip_mrr=True)
    return BuiltReport(
        kind="weekly",
        period_key=weekly_key(start),
        subject=f"[SynkmetriX · {env}] Resumen semanal {_fmt_date(start)} al {_fmt_date(end)}",
        html=_html(title, subtitle, env, body, _sync_table(sync_status(db, moment))),
        text=_plain(title, subtitle, rows),
        csv_name=f"resumen_semanal_{start.isoformat()}.csv",
        csv_text=csv_text,
    )


def build_monthly(db: Session, now: datetime | None = None) -> BuiltReport:
    """Cierre del mes calendario anterior, con el CSV de los ultimos 13 meses."""
    moment = now or datetime.now(UTC)
    first, last = monthly_period(moment)
    today = chile_date(moment)
    mrr = mrr_snapshot(db, today)
    csv_rows: list[dict[str, str]] = []
    current_rows: list[dict[str, str]] = []
    previous_rows: list[dict[str, str]] = []
    for back in range(CSV_MONTHS - 1, -1, -1):
        start, end = _month_bounds(first, back)
        label = f"{start:%Y-%m}"
        rows = display_rows(label, period_figures(db, start, end), mrr if back == 0 else None)
        csv_rows += rows
        if back == 0:
            current_rows = rows
        elif back == 1:
            previous_rows = rows
    title = "Cierre mensual"
    subtitle = f"{_month_label(first).capitalize()} ({_fmt_date(first)} al {_fmt_date(last)})"
    env = _env_label()
    prev_first, _ = _month_bounds(first, 1)
    body = _table(_month_label(first).capitalize(), current_rows) + _table(
        f"Mes anterior ({_month_label(prev_first)})", previous_rows, skip_mrr=True
    )
    return BuiltReport(
        kind="monthly",
        period_key=monthly_key(first),
        subject=f"[SynkmetriX · {env}] Cierre mensual {_month_label(first)}",
        html=_html(title, subtitle, env, body, _sync_table(sync_status(db, moment))),
        text=_plain(title, subtitle, current_rows),
        csv_name=f"cierre_mensual_{first:%Y-%m}.csv",
        csv_text=to_csv(csv_rows),
    )


def build_report(db: Session, kind: str, now: datetime | None = None) -> BuiltReport:
    if kind == "weekly":
        return build_weekly(db, now)
    if kind == "monthly":
        return build_monthly(db, now)
    raise ValueError("kind debe ser weekly o monthly")


__all__ = ["BuiltReport", "build_monthly", "build_report", "build_weekly", "display_rows", "to_csv"]
