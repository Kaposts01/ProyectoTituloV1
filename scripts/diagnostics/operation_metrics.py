"""MET-02: metricas de uso y operacion de una ventana (por defecto dos semanas) desde tablas existentes, SOLO LECTURA.

Sin migraciones (d159): solo agregados sobre tablas que ya existen. Ver docs/quality/metricas-operacion.md.

Secciones:
- `sync_canales`: `sync_runs` de canales (sin jobs `billing_` ni `cancellation_`) por fuente y estado: corridas,
  duracion media y maxima (s), registros procesados.
- `sync_frescura`: por fuente de canal, horas desde la ultima corrida `completed` hasta el fin de la ventana, y
  corridas fallidas en la ventana.
- `jobs`: `sync_runs` de jobs de facturacion y bajas (`billing_*`, `cancellation_*`) por fuente y estado.
- `etl_runs`: corridas del ETL global por estado: cantidad, duracion media, corridas con algun canal fallido.
- `escrituras`: `write_runs` por fuente, operacion y estado.
- `exportaciones`: `export_jobs` por entidad, estado y si incluye datos personales: cantidad y filas escritas.
- `cambios_cobro`: `billing_change_requests` creadas en la ventana por tipo, plataforma y estado actual.
- `cambios_cobro_eventos`: `billing_change_request_events` de la ventana por tipo de evento.
- `bajas`: `subscription_cancellation_requests` creadas en la ventana por canal, motivo (codigo) y estado actual.
- `bajas_eventos`: `subscription_cancellation_request_events` de la ventana por tipo de evento.
- `alertas`: estado de alertas (`source_records`, `source='alert_state'`) por tipo de condicion: condiciones cuyo
  ULTIMO aviso cae en la ventana y condiciones recuperadas en la ventana (cota inferior: el estado no guarda historial).

Lo que NO se puede medir sin migracion (se declara en la salida): inicios de sesion, sesiones y vistas (no hay tabla de
auditoria de acceso), cantidad exacta de correos de alerta (solo se guarda el ultimo envio por condicion) y tiempos de
respuesta de la API.

Nada personal: solo nombres de fuente/canal/estado/tipo, conteos y duraciones. Nunca ids, RUT, correos, montos por
socio, `error_message`, comentarios ni ids de usuario.

GUARDA: `--database` es obligatorio y explicito. Si el nombre no termina en `_test` (p. ej. `crm`, `crm_sandbox`) el
script aborta, salvo `--read-only` (entonces solo ejecuta SELECT/WITH dentro de una transaccion READ ONLY; ver
`readonly_guard.py`). Correrlo contra `crm` lo decide el usuario. La URL sale de `DATABASE_URL` cambiando SOLO el
nombre de la base; nunca se imprime.

Uso (desde la raiz del repo):
    $env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/diagnostics/operation_metrics.py --database crm_test
    $env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/diagnostics/operation_metrics.py --database crm_test --days 14 --until 2026-11-21 --format markdown
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.billing import BillingChangeRequest, BillingChangeRequestEvent
from app.models.cancellation import (
    SubscriptionCancellationRequest,
    SubscriptionCancellationRequestEvent,
)
from app.models.etl_run import EtlRun
from app.models.export_job import ExportJob
from app.models.source_record import SourceRecord
from app.models.sync_run import SyncRun
from app.models.write_run import WriteRun
from scripts.diagnostics import readonly_guard

CHILE_TZ = ZoneInfo("America/Santiago")
DEFAULT_DAYS = 14
ALERT_STATE_SOURCE = "alert_state"
ALERT_STATE_RESOURCE = "condition"
SYNC_OK = "completed"
SYNC_FAILED = "failed"

LIMITATIONS = (
    "Inicios de sesion, sesiones activas y vistas por pantalla: el CRM no guarda auditoria de acceso (no hay tabla).",
    "Correos de alerta enviados: solo se guarda el ultimo aviso por condicion (source_records alert_state); "
    "los recordatorios intermedios no quedan, asi que el conteo es una cota inferior.",
    "Tiempos de respuesta de la API y errores HTTP: no se persisten.",
    "Estado de una solicitud en el pasado: cambios_cobro y bajas muestran el estado ACTUAL de las creadas en la "
    "ventana; el recorrido queda en las secciones *_eventos.",
)


@dataclass
class Window:
    start: datetime
    end: datetime

    @property
    def days(self) -> float:
        return (self.end - self.start).total_seconds() / 86400


@dataclass
class Report:
    database: str
    window: Window
    sections: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    limitations: tuple[str, ...] = LIMITATIONS


# --------------------------------------------------------------------------------------------------------------- #
# Consultas (solo SELECT)                                                                                          #
# --------------------------------------------------------------------------------------------------------------- #


def _seconds(start_col: Any, end_col: Any) -> Any:
    return func.extract("epoch", end_col - start_col)


def _round(value: Any, digits: int = 1) -> float | None:
    return None if value is None else round(float(value), digits)


def _in_window(column: Any, window: Window) -> list[Any]:
    return [column >= window.start, column < window.end]


def _sync_by_status(db: Session, window: Window, channel: bool) -> list[dict[str, Any]]:
    duration = _seconds(SyncRun.started_at, SyncRun.finished_at)
    kind = SyncRun.is_channel_source() if channel else ~SyncRun.is_channel_source()
    query = (
        select(
            SyncRun.source, SyncRun.status, func.count(), func.avg(duration), func.max(duration),
            func.coalesce(func.sum(SyncRun.records_processed), 0),
        )
        .where(kind, *_in_window(SyncRun.started_at, window))
        .group_by(SyncRun.source, SyncRun.status)
        .order_by(SyncRun.source, SyncRun.status)
    )
    return [
        {"fuente": src, "estado": st, "corridas": int(n), "duracion_media_s": _round(avg), "duracion_max_s": _round(mx),
         "registros": int(recs)}
        for src, st, n, avg, mx, recs in db.execute(query)
    ]


def _sync_freshness(db: Session, window: Window) -> list[dict[str, Any]]:
    channel = SyncRun.is_channel_source()
    sources = db.scalars(select(SyncRun.source).where(channel).distinct().order_by(SyncRun.source)).all()
    last_ok = dict(db.execute(
        select(SyncRun.source, func.max(func.coalesce(SyncRun.finished_at, SyncRun.started_at)))
        .where(channel, SyncRun.status == SYNC_OK, SyncRun.started_at < window.end)
        .group_by(SyncRun.source)
    ).all())
    failed = dict(db.execute(
        select(SyncRun.source, func.count())
        .where(channel, SyncRun.status == SYNC_FAILED, *_in_window(SyncRun.started_at, window))
        .group_by(SyncRun.source)
    ).all())
    rows = []
    for source in sources:
        moment = last_ok.get(source)
        hours = None if moment is None else _round((window.end - moment).total_seconds() / 3600)
        rows.append({"fuente": source, "horas_desde_ultimo_ok": hours, "fallidas_en_ventana": int(failed.get(source, 0))})
    return rows


def _etl_runs(db: Session, window: Window) -> list[dict[str, Any]]:
    with_failures = func.coalesce(func.cardinality(EtlRun.channels_failed), 0) > 0
    query = (
        select(
            EtlRun.status, func.count(), func.avg(_seconds(EtlRun.started_at, EtlRun.finished_at)),
            func.count().filter(with_failures), func.coalesce(func.sum(EtlRun.records_upserted), 0),
        )
        .where(*_in_window(EtlRun.started_at, window))
        .group_by(EtlRun.status)
        .order_by(EtlRun.status)
    )
    return [
        {"estado": st, "corridas": int(n), "duracion_media_s": _round(avg), "con_canal_fallido": int(nf),
         "registros_upsert": int(recs)}
        for st, n, avg, nf, recs in db.execute(query)
    ]


def _write_runs(db: Session, window: Window) -> list[dict[str, Any]]:
    query = (
        select(WriteRun.source, WriteRun.operation, WriteRun.status, func.count(),
               func.avg(_seconds(WriteRun.started_at, WriteRun.finished_at)))
        .where(*_in_window(WriteRun.started_at, window))
        .group_by(WriteRun.source, WriteRun.operation, WriteRun.status)
        .order_by(WriteRun.source, WriteRun.operation, WriteRun.status)
    )
    return [
        {"fuente": src, "operacion": op, "estado": st, "cantidad": int(n), "duracion_media_s": _round(avg)}
        for src, op, st, n, avg in db.execute(query)
    ]


def _exports(db: Session, window: Window) -> list[dict[str, Any]]:
    query = (
        select(ExportJob.entity, ExportJob.status, ExportJob.include_pii, func.count(),
               func.coalesce(func.sum(ExportJob.rows_written), 0))
        .where(*_in_window(ExportJob.created_at, window))
        .group_by(ExportJob.entity, ExportJob.status, ExportJob.include_pii)
        .order_by(ExportJob.entity, ExportJob.status, ExportJob.include_pii)
    )
    return [
        {"entidad": ent, "estado": st, "con_datos_personales": bool(pii), "cantidad": int(n), "filas": int(rows)}
        for ent, st, pii, n, rows in db.execute(query)
    ]


def _billing_requests(db: Session, window: Window) -> list[dict[str, Any]]:
    r = BillingChangeRequest
    query = (
        select(r.request_type, r.platform, r.status, func.count())
        .where(*_in_window(r.created_at, window))
        .group_by(r.request_type, r.platform, r.status)
        .order_by(r.request_type, r.platform, r.status)
    )
    return [{"tipo": t, "plataforma": p, "estado": st, "cantidad": int(n)} for t, p, st, n in db.execute(query)]


def _cancellations(db: Session, window: Window) -> list[dict[str, Any]]:
    r = SubscriptionCancellationRequest
    query = (
        select(r.channel, r.reason_code, r.status, func.count())
        .where(*_in_window(r.created_at, window))
        .group_by(r.channel, r.reason_code, r.status)
        .order_by(r.channel, r.reason_code, r.status)
    )
    return [{"canal": c, "motivo": m, "estado": st, "cantidad": int(n)} for c, m, st, n in db.execute(query)]


def _events(db: Session, model: Any, window: Window) -> list[dict[str, Any]]:
    query = (
        select(model.event_type, func.count())
        .where(*_in_window(model.created_at, window))
        .group_by(model.event_type)
        .order_by(model.event_type)
    )
    return [{"evento": ev, "cantidad": int(n)} for ev, n in db.execute(query)]


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _alerts(db: Session, window: Window) -> list[dict[str, Any]]:
    rows = db.execute(
        select(SourceRecord.external_id, SourceRecord.payload)
        .where(SourceRecord.source == ALERT_STATE_SOURCE, SourceRecord.resource_type == ALERT_STATE_RESOURCE)
    ).all()
    buckets: dict[str, dict[str, int]] = {}
    for key, payload in rows:
        state = payload or {}
        kind = str(key).split(":", 1)[0]  # solo el tipo de condicion (sync_fail, core_lag, ...), sin el detalle
        cell = buckets.setdefault(kind, {"avisadas_en_ventana": 0, "recuperadas_en_ventana": 0, "activas_al_cierre": 0})
        sent = _parse_ts(state.get("last_sent_at"))
        resolved = _parse_ts(state.get("last_resolved_at"))
        if sent is not None and window.start <= sent < window.end:
            cell["avisadas_en_ventana"] += 1
        if resolved is not None and window.start <= resolved < window.end:
            cell["recuperadas_en_ventana"] += 1
        if state.get("active"):
            cell["activas_al_cierre"] += 1
    return [{"condicion": kind, **counts} for kind, counts in sorted(buckets.items())]


SECTIONS = (
    ("sync_canales", lambda db, w: _sync_by_status(db, w, channel=True)),
    ("sync_frescura", _sync_freshness),
    ("jobs", lambda db, w: _sync_by_status(db, w, channel=False)),
    ("etl_runs", _etl_runs),
    ("escrituras", _write_runs),
    ("exportaciones", _exports),
    ("cambios_cobro", _billing_requests),
    ("cambios_cobro_eventos", lambda db, w: _events(db, BillingChangeRequestEvent, w)),
    ("bajas", _cancellations),
    ("bajas_eventos", lambda db, w: _events(db, SubscriptionCancellationRequestEvent, w)),
    ("alertas", _alerts),
)


def collect(db: Session, window: Window, database: str = "") -> Report:
    """Todas las secciones de la ventana [start, end). Solo SELECT."""
    report = Report(database=database, window=window)
    for name, fn in SECTIONS:
        report.sections[name] = fn(db, window)
    return report


# --------------------------------------------------------------------------------------------------------------- #
# Ventana, conexion y salida                                                                                       #
# --------------------------------------------------------------------------------------------------------------- #


def build_window(days: int = DEFAULT_DAYS, until: date | None = None, now: datetime | None = None) -> Window:
    """Ventana de `days` dias que termina al cierre de `until` (hora de Chile) o, sin `until`, ahora."""
    if days < 1:
        raise ValueError("days debe ser >= 1")
    if until is not None:
        end = datetime.combine(until + timedelta(days=1), time.min, tzinfo=CHILE_TZ).astimezone(UTC)
    else:
        end = (now or datetime.now(UTC)).astimezone(UTC)
    return Window(start=end - timedelta(days=days), end=end)


def open_readonly_session(database: str) -> Session:
    """Sesion READ ONLY (y filtro SELECT/WITH) contra `database`, con la URL de DATABASE_URL cambiando solo el nombre."""
    url = make_url(settings.database_url).set(database=database)
    engine = create_engine(url, poolclass=NullPool)
    db = Session(bind=engine)
    db.execute(text(readonly_guard._READ_ONLY_PREAMBLE))
    return readonly_guard.guard_select_only(db)


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "si" if value else "no"
    return str(value)


def _table(rows: list[dict[str, Any]], markdown: bool) -> str:
    if not rows:
        return "(sin filas)\n"
    headers = list(rows[0].keys())
    cells = [[_cell(r[h]) for h in headers] for r in rows]
    if markdown:
        lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
        lines += ["| " + " | ".join(row) + " |" for row in cells]
        return "\n".join(lines) + "\n"
    widths = [max(len(h), *(len(row[i]) for row in cells)) for i, h in enumerate(headers)]
    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip(), "  ".join("-" * w for w in widths)]
    lines += ["  ".join(v.ljust(widths[i]) for i, v in enumerate(row)).rstrip() for row in cells]
    return "\n".join(lines) + "\n"


def _header(report: Report) -> str:
    w = report.window
    return (f"Base: {report.database} | ventana: {w.start.isoformat(timespec='minutes')} a "
            f"{w.end.isoformat(timespec='minutes')} UTC ({w.days:g} dias) | solo lectura")


def format_text(report: Report, markdown: bool = False) -> str:
    out = [("# Metricas de operacion\n\n" if markdown else "") + _header(report) + "\n"]
    for name, rows in report.sections.items():
        out.append(f"{'## ' if markdown else '== '}{name}{'' if markdown else ' =='}\n")
        out.append(_table(rows, markdown))
    out.append(f"{'## ' if markdown else '== '}limitaciones{'' if markdown else ' =='}\n")
    out.append("".join(f"- {item}\n" for item in report.limitations))
    return "\n".join(out)


def format_json(report: Report) -> str:
    payload = {
        "database": report.database,
        "window": {"start": report.window.start.isoformat(), "end": report.window.end.isoformat(), "days": report.window.days},
        "sections": report.sections,
        "limitations": list(report.limitations),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _date_arg(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use el formato AAAA-MM-DD") from exc


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--database", required=True, help="Nombre de la base (obligatorio). Si no termina en _test exige --read-only.")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Largo de la ventana en dias (por defecto 14).")
    parser.add_argument("--until", type=_date_arg, help="Ultimo dia incluido (AAAA-MM-DD, hora de Chile). Por defecto: ahora.")
    parser.add_argument("--format", choices=("table", "markdown", "json"), default="table", help="Formato de salida.")
    readonly_guard.add_read_only_argument(parser)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.days < 1:
        parser.error("--days debe ser >= 1")
    return args


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    database = readonly_guard.enforce_database_guard(args.read_only, db_name=args.database)
    window = build_window(args.days, args.until)
    db = open_readonly_session(database)
    try:
        report = collect(db, window, database)
    finally:
        db.rollback()
        bind = db.get_bind()
        db.close()
        bind.dispose()
    if args.format == "json":
        print(format_json(report), end="")
    else:
        print(format_text(report, markdown=args.format == "markdown"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
