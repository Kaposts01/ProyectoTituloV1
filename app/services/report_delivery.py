"""REP-02: envio idempotente de los reportes por correo. Ver docs/data/scheduled_reports.md.

Un reporte por (`report_kind`, `period_key`) en `report_dispatches`: se reserva la fila (`sending`) con
INSERT ... ON CONFLICT DO NOTHING ANTES de enviar y se pasa a `sent` o `failed`. Hasta `MAX_ATTEMPTS` intentos; un
`sending` de mas de `STALE_SENDING_AFTER` (proceso caido a medio envio) se reintenta. Las banderas
`REPORTS_WEEKLY_ENABLED` / `REPORTS_MONTHLY_ENABLED` mandan: apagadas, no se arma ni se registra nada. El envio de prueba
(`period_key` = `test:<marca de tiempo>`) ignora la bandera pero no la falta de destinatario ni de servidor SMTP.

Nada de lo que se guarda o se loguea lleva direcciones, mensajes de excepcion ni datos personales: solo cantidad de
destinatarios y nombre de la clase del error. No escribe en `sync_runs` ni `etl_runs`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.report_dispatch import ReportDispatch
from app.services import alerts, scheduled_reports

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
STALE_SENDING_AFTER = timedelta(minutes=30)


@dataclass
class DispatchResult:
    status: str  # sent | failed | skipped
    reason: str | None = None  # disabled | no_recipient | no_smtp_host | already_sent | in_progress | exhausted | send_failed
    attempts: int = 0
    error_class: str | None = None
    period_key: str | None = None


def _enabled(kind: str) -> bool:
    return bool(settings.reports_weekly_enabled if kind == "weekly" else settings.reports_monthly_enabled)


def period_key_for(kind: str, now: datetime) -> str:
    if kind == "weekly":
        return scheduled_reports.weekly_key(scheduled_reports.weekly_period(now)[0])
    return scheduled_reports.monthly_key(scheduled_reports.monthly_period(now)[0])


def _claim(db: Session, kind: str, key: str, recipients: int, now: datetime) -> tuple[bool, int, str | None]:
    """Reserva el envio. Devuelve (reservado, intentos, motivo si no se reservo). Hace commit de la reserva."""
    inserted = db.execute(
        insert(ReportDispatch)
        .values(report_kind=kind, period_key=key, status="sending", attempts=1, recipients_count=recipients,
                created_at=now, updated_at=now)
        .on_conflict_do_nothing(constraint="uq_report_dispatches_kind_period")
        .returning(ReportDispatch.id)
    ).first()
    if inserted is not None:
        db.commit()
        return True, 1, None
    row = db.execute(
        select(ReportDispatch.id, ReportDispatch.status, ReportDispatch.attempts)
        .where(ReportDispatch.report_kind == kind, ReportDispatch.period_key == key)
    ).one()
    if row.status == "sent":
        db.rollback()
        return False, row.attempts, "already_sent"
    if row.attempts >= MAX_ATTEMPTS:
        db.rollback()
        return False, row.attempts, "exhausted"
    retryable = (ReportDispatch.status == "failed") | (
        (ReportDispatch.status == "sending") & (ReportDispatch.updated_at < now - STALE_SENDING_AFTER)
    )
    claimed = db.execute(
        update(ReportDispatch)
        .where(ReportDispatch.id == row.id, ReportDispatch.attempts < MAX_ATTEMPTS, retryable)
        .values(status="sending", attempts=ReportDispatch.attempts + 1, recipients_count=recipients, updated_at=now)
        .returning(ReportDispatch.attempts)
    ).first()
    if claimed is None:
        db.rollback()
        return False, row.attempts, "in_progress"
    db.commit()
    return True, int(claimed[0]), None


def _finish(db: Session, kind: str, key: str, ok: bool, error_class: str | None, now: datetime) -> None:
    db.execute(
        update(ReportDispatch)
        .where(ReportDispatch.report_kind == kind, ReportDispatch.period_key == key)
        .values(status="sent" if ok else "failed", error_class=error_class, updated_at=now, sent_at=now if ok else None)
    )
    db.commit()


def dispatch_report(db: Session, kind: str, now: datetime | None = None, *, test: bool = False) -> DispatchResult:
    """Arma y envia el reporte `kind` si corresponde. Una sola vez por periodo. Nunca lanza."""
    moment = now or datetime.now(UTC)
    if not test and not _enabled(kind):
        return DispatchResult("skipped", "disabled")
    recipients = alerts.report_recipients()
    if not recipients:
        logger.warning("Reporte %s: REPORT_EMAIL_TO está vacío: no se envía nada.", kind)
        return DispatchResult("skipped", "no_recipient")
    if not settings.alert_smtp_host.strip():
        logger.warning("Reporte %s: ALERT_SMTP_HOST está vacío: no se envía nada.", kind)
        return DispatchResult("skipped", "no_smtp_host")
    key = f"test:{moment.strftime('%Y%m%dT%H%M%S%f')}" if test else period_key_for(kind, moment)
    try:
        reserved, attempts, reason = _claim(db, kind, key, len(recipients), moment)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("Reporte %s: no se pudo reservar el envío (%s).", kind, type(exc).__name__)
        return DispatchResult("failed", "claim_failed", error_class=type(exc).__name__, period_key=key)
    if not reserved:
        return DispatchResult("skipped", reason, attempts, period_key=key)
    try:
        built = scheduled_reports.build_report(db, kind, moment)
        ok, error_class = alerts.send_report(
            built.subject, built.text, built.html, recipients, ((built.csv_name, built.csv_text),)
        )
    except Exception as exc:  # noqa: BLE001 - un reporte fallido no debe tumbar al programador
        db.rollback()
        ok, error_class = False, type(exc).__name__
        logger.warning("Reporte %s: no se pudo armar (%s).", kind, error_class)
    try:
        _finish(db, kind, key, ok, error_class, datetime.now(UTC))
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("Reporte %s: no se pudo registrar el resultado (%s).", kind, type(exc).__name__)
    logger.info("Reporte %s (%s): %s, intento %d.", kind, key.split(":")[0], "enviado" if ok else "fallido", attempts)
    return DispatchResult("sent" if ok else "failed", None if ok else "send_failed", attempts, error_class, key)
