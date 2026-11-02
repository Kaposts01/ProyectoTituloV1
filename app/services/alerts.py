"""Alertas por correo de fallos de sincronizacion y operacion (SYNC-D-08). Ver docs/data/alerts.md.

Un chequeo (`run_alert_check`, lo llama el job cada 15 min) evalua condiciones y avisa por correo:

- `sync_fail:<canal>`: canal con 2 o mas corridas fallidas seguidas, o 2 o mas dias sin una sincronizacion exitosa.
- `core_lag:<canal>`: el ETL Core va mas de 24 h detras del ultimo sync exitoso (`core_lag_hours`).
- `webhook_failed`: eventos de webhook en `failed` en las ultimas 24 h.
- `webhook_lag`: con el procesador encendido, un evento pendiente lleva mas de `ALERT_WEBHOOK_LAG_MINUTES` (RT-13).
- `webhook_silence:<canal>`: con `ALERT_WEBHOOK_SILENCE_HOURS` > 0, un canal que ya recibio webhooks lleva ese plazo sin
  recibir ninguno (salud del canal; RT-13). Apagada por defecto.
- `cancellation_stuck`: solicitudes de baja en `requires_reconciliation`, o en `applying` mas de 30 min.
- `billing_stuck`: solicitudes de cambio de cobro en `requiere_conciliacion`, o en `aplicando` mas de 30 min.

Deduplicacion: una alerta por condicion y, mientras siga activa, un recordatorio como maximo cada 6 h; al normalizarse
se avisa «recuperado». El estado va en `source_records` (`source='alert_state'`), sin migracion, como la marca del ETL Core.

Reglas duras: nada de datos personales (solo canal, condicion, contadores y horas; nunca `error_message`, ids de
suscripcion ni textos libres); el envio nunca lanza hacia quien llama (un SMTP caido solo deja un aviso en el log con el
nombre de la clase de la excepcion); con `ALERTS_ENABLED` apagada, o sin `ALERT_EMAIL_TO` / `ALERT_SMTP_HOST`, no se envia
nada y no se guarda estado. Una sola ronda de envio por condicion y chequeo: sin reintentos internos (el siguiente
chequeo reintenta lo que no salio).

API reutilizable (para otros modulos, p. ej. BILL-22): `register_condition_provider(kind, evaluate, describe)` agrega una
fuente de condiciones sin tocar el chequeo ni el envio. `evaluate(db, now) -> list[Condition]` debe ser de solo lectura,
sin datos personales, y sus claves deben empezar por `kind` (`kind` o `kind:<detalle>`); `describe(detalle)` devuelve
(canal/area, sujeto) para el aviso de recuperacion, que se arma solo con la clave guardada.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.billing import (
    STATUS_APPLYING,
    STATUS_NEEDS_RECONCILIATION,
    BillingChangeRequest,
)
from app.models.cancellation import SubscriptionCancellationRequest
from app.models.source_record import SourceRecord
from app.models.webhook_event import WebhookEvent
from app.services.webhook_health import queue_health

logger = logging.getLogger(__name__)

STATE_SOURCE = "alert_state"
STATE_RESOURCE = "condition"
REPEAT_EVERY = timedelta(hours=6)
CORE_LAG_ALERT_HOURS = 24.0
MIN_CONSECUTIVE_FAILURES = 2
MIN_DAYS_WITHOUT_SUCCESS = 2
WEBHOOK_FAILED_WINDOW = timedelta(hours=24)
STUCK_APPLYING_AFTER = timedelta(minutes=30)
SMTP_TIMEOUT_SECONDS = 10
SMTPS_PORT = 465

SYNC_LINK = "/admin/sincronizaciones"
BILLING_LINK = "/general/cambios-de-cobro"
CANCELLATION_LINK = "/api/v1/cancellations?status=requires_reconciliation"
WEBHOOK_LINK = "/admin/sincronizaciones#webhooks"

_CHANNEL_LABELS = {"virtualpos": "VirtualPOS", "toku": "Toku", "payku": "Payku", "tch": "TCH"}


@dataclass(frozen=True)
class Condition:
    key: str
    channel: str  # texto para personas (canal o area)
    title: str  # sujeto corto para el asunto
    text: str  # condicion en una frase
    details: tuple[str, ...] = field(default_factory=tuple)
    link: str = SYNC_LINK


@dataclass
class AlertCheckResult:
    sent: int = 0
    failed: int = 0
    active: int = 0
    skipped: str | None = None


# ----------------------------- condiciones -----------------------------


def _channel_label(channel: str) -> str:
    return _CHANNEL_LABELS.get(channel, channel)


def _num(value: float) -> str:
    return f"{value:g}"


def _sync_conditions(db: Session, now: datetime) -> list[Condition]:
    from app.api.v1.routes.sync_runs import _compute_health

    found: list[Condition] = []
    for item in _compute_health(db, now):
        channel = str(item["channel"])
        label = _channel_label(channel)
        consecutive = int(item.get("consecutive_failures") or 0)
        days = item.get("days_without_success")
        parts: list[str] = []
        if consecutive >= MIN_CONSECUTIVE_FAILURES:
            parts.append(f"{consecutive} corridas fallidas seguidas")
        if days is not None and int(days) >= MIN_DAYS_WITHOUT_SUCCESS:
            parts.append(f"{int(days)} días sin una sincronización exitosa")
        if parts:
            state = "en falla" if item.get("status") == "failing" else "degradado"
            found.append(Condition(
                key=f"sync_fail:{channel}", channel=label, title=f"sincronización de {label} con fallas",
                text=" y ".join(parts), details=(f"Estado del canal: {state}.",), link=SYNC_LINK))
        lag = item.get("core_lag_hours")
        if lag is not None and float(lag) > CORE_LAG_ALERT_HOURS:  # type: ignore[arg-type]
            found.append(Condition(
                key=f"core_lag:{channel}", channel=label, title=f"ETL Core de {label} atrasado",
                text=f"El ETL Core va {_num(float(lag))} h detrás de la última sincronización exitosa "  # type: ignore[arg-type]
                     f"(umbral: {_num(CORE_LAG_ALERT_HOURS)} h).",
                link=SYNC_LINK))
    return found


def _webhook_conditions(db: Session, now: datetime) -> list[Condition]:
    since = now - WEBHOOK_FAILED_WINDOW
    rows = db.execute(
        select(WebhookEvent.source, func.count())
        .where(WebhookEvent.status == "failed", func.coalesce(WebhookEvent.processed_at, WebhookEvent.received_at) >= since)
        .group_by(WebhookEvent.source).order_by(WebhookEvent.source)
    ).all()
    if not rows:
        return []
    total = sum(int(n) for _, n in rows)
    return [Condition(
        key="webhook_failed", channel="Webhooks", title="eventos de webhook fallidos",
        text=f"{total} evento(s) de webhook en estado fallido en las últimas 24 h.",
        details=tuple(f"{source}: {int(n)} evento(s)" for source, n in rows), link=SYNC_LINK)]


def _stuck_cancellations(db: Session, now: datetime) -> list[Condition]:
    model = SubscriptionCancellationRequest
    cutoff = now - STUCK_APPLYING_AFTER
    rows = db.execute(
        select(model.status, func.count()).where(
            (model.status == "requires_reconciliation") | ((model.status == "applying") & (model.updated_at < cutoff))
        ).group_by(model.status).order_by(model.status)
    ).all()
    if not rows:
        return []
    total = sum(int(n) for _, n in rows)
    return [Condition(
        key="cancellation_stuck", channel="Bajas de suscripción", title="solicitudes de baja atascadas",
        text=f"{total} solicitud(es) de baja atascada(s) en aplicación o a la espera de conciliación.",
        details=tuple(f"{status}: {int(n)}" for status, n in rows), link=CANCELLATION_LINK)]


def _stuck_billing(db: Session, now: datetime) -> list[Condition]:
    model = BillingChangeRequest
    cutoff = now - STUCK_APPLYING_AFTER
    rows = db.execute(
        select(model.status, func.count()).where(
            (model.status == STATUS_NEEDS_RECONCILIATION) | ((model.status == STATUS_APPLYING) & (model.updated_at < cutoff))
        ).group_by(model.status).order_by(model.status)
    ).all()
    if not rows:
        return []
    total = sum(int(n) for _, n in rows)
    return [Condition(
        key="billing_stuck", channel="Cambios de cobro", title="solicitudes de cobro atascadas",
        text=f"{total} solicitud(es) de cambio de cobro atascada(s) en aplicación o a la espera de conciliación.",
        details=tuple(f"{status}: {int(n)}" for status, n in rows), link=BILLING_LINK)]


def _webhook_queue_conditions(db: Session, now: datetime) -> list[Condition]:
    """RT-13: demora de la cola (solo con el procesador encendido) y silencio de un canal que ya recibia webhooks."""
    health = queue_health(db, now)
    found: list[Condition] = []
    lag_limit = int(settings.alert_webhook_lag_minutes)
    if health["processor_enabled"] and lag_limit > 0:
        late = [(s["source"], float(s["pending_lag_minutes"])) for s in health["sources"]
                if s["pending_lag_minutes"] is not None and float(s["pending_lag_minutes"]) > lag_limit]
        if late:
            worst = max(minutes for _, minutes in late)
            found.append(Condition(
                key="webhook_lag", channel="Webhooks", title="cola de webhooks atrasada",
                text=f"Hay eventos de webhook pendientes hace {_num(round(worst))} min (umbral: {lag_limit} min).",
                details=tuple(f"{_channel_label(src)}: pendiente más antiguo hace {_num(round(m))} min" for src, m in late),
                link=WEBHOOK_LINK))
    silence_hours = int(settings.alert_webhook_silence_hours)
    if silence_hours > 0:
        for item in health["sources"]:
            last = _parse(item["last_received_at"])
            if last is None:  # nunca recibio webhooks: el canal no esta configurado, no hay silencio que avisar
                continue
            if now - last >= timedelta(hours=silence_hours):
                label = _channel_label(item["source"])
                found.append(Condition(
                    key=f"webhook_silence:{item['source']}", channel=label, title=f"sin webhooks de {label}",
                    text=f"No llegan webhooks de {label} hace más de {silence_hours} h.",
                    details=(f"Último recibido: {_local_time(last)}",), link=WEBHOOK_LINK))
    return found


ConditionFn = Callable[[Session, datetime], list[Condition]]
DescribeFn = Callable[[str], tuple[str, str]]


@dataclass(frozen=True)
class ConditionProvider:
    kind: str
    evaluate: ConditionFn
    describe: DescribeFn


_PROVIDERS: dict[str, ConditionProvider] = {}


def register_condition_provider(kind: str, evaluate: ConditionFn, describe: DescribeFn) -> None:
    """Registra (o reemplaza, si `kind` ya existe) una fuente de condiciones. Ver el docstring del modulo."""
    if not kind or ":" in kind:
        raise ValueError("kind debe ser un identificador sin ':'")
    _PROVIDERS[kind] = ConditionProvider(kind, evaluate, describe)


def registered_kinds() -> tuple[str, ...]:
    return tuple(_PROVIDERS)


def _fixed(channel: str, subject: str) -> DescribeFn:
    return lambda _detail: (channel, subject)


def _sync_fail_describe(channel: str) -> tuple[str, str]:
    label = _channel_label(channel)
    return label, f"sincronización de {label}"


def _core_lag_describe(channel: str) -> tuple[str, str]:
    label = _channel_label(channel)
    return label, f"ETL Core de {label}"


def _silence_describe(channel: str) -> tuple[str, str]:
    label = _channel_label(channel)
    return label, f"sin webhooks de {label}"


def _none(_db: Session, _now: datetime) -> list[Condition]:
    return []


# `sync_fail` y `core_lag` salen de una sola lectura de salud (`_sync_conditions`); `core_lag` solo aporta su descripcion.
register_condition_provider("sync_fail", _sync_conditions, _sync_fail_describe)
register_condition_provider("core_lag", _none, _core_lag_describe)
register_condition_provider("webhook_failed", _webhook_conditions, _fixed("Webhooks", "eventos de webhook fallidos"))
register_condition_provider("webhook_lag", _webhook_queue_conditions, _fixed("Webhooks", "cola de webhooks atrasada"))
register_condition_provider("webhook_silence", _none, _silence_describe)
register_condition_provider("cancellation_stuck", _stuck_cancellations,
                            _fixed("Bajas de suscripción", "solicitudes de baja atascadas"))
register_condition_provider("billing_stuck", _stuck_billing, _fixed("Cambios de cobro", "solicitudes de cobro atascadas"))


def _removal_conditions(db: Session, now: datetime) -> list[Condition]:
    # Importacion perezosa: channel_removals importa este modulo.
    from app.services.channel_removals import removal_abort_conditions

    return removal_abort_conditions(db, now)


def _removal_describe(source: str) -> tuple[str, str]:
    from app.services.channel_removals import describe_removal_abort

    return describe_removal_abort(source)


# SYNC-D-13: la deteccion de bajas por desaparicion aborto por superar el umbral (probable error del proveedor).
register_condition_provider("removal_aborted", _removal_conditions, _removal_describe)


def evaluate_conditions(db: Session, now: datetime) -> list[Condition]:
    """Condiciones activas ahora, de todas las fuentes registradas. Solo lectura; sin datos personales."""
    found: list[Condition] = []
    for provider in list(_PROVIDERS.values()):
        found.extend(provider.evaluate(db, now))
    return found


def _describe_key(key: str) -> tuple[str, str]:
    """(canal/area, sujeto) de una clave de condicion; sirve para el aviso de recuperacion sin guardar textos."""
    kind, _, detail = key.partition(":")
    provider = _PROVIDERS.get(kind)
    if provider is None:
        return key, key
    return provider.describe(detail)


# ----------------------------- estado (source_records) -----------------------------


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _load_states(db: Session) -> dict[str, dict[str, Any]]:
    rows = db.execute(select(SourceRecord.external_id, SourceRecord.payload).where(
        SourceRecord.source == STATE_SOURCE, SourceRecord.resource_type == STATE_RESOURCE)).all()
    return {ext: dict(payload or {}) for ext, payload in rows}


def _save_state(db: Session, key: str, payload: dict[str, Any]) -> None:
    statement = insert(SourceRecord).values(
        source=STATE_SOURCE, resource_type=STATE_RESOURCE, external_id=key, payload=payload)
    db.execute(statement.on_conflict_do_update(constraint="uq_source_record", set_={"payload": statement.excluded.payload}))
    db.commit()


# ----------------------------- correo -----------------------------


def _recipients() -> list[str]:
    return [r.strip() for r in settings.alert_email_to.split(",") if r.strip()]


def _local_time(moment: datetime) -> str:
    try:
        return moment.astimezone(ZoneInfo("America/Santiago")).strftime("%d-%m-%Y %H:%M") + " (hora de Chile)"
    except Exception:  # noqa: BLE001 - sin base de zonas horarias: UTC
        return moment.astimezone(UTC).strftime("%d-%m-%Y %H:%M") + " (UTC)"


def _build(kind: str, cond: Condition | None, key: str, since: datetime, now: datetime, recipients: list[str]) -> EmailMessage:
    prefix = {"new": "Alerta", "reminder": "Recordatorio", "recovered": "Recuperado"}[kind]
    channel, subject_title = (cond.channel, cond.title) if cond else _describe_key(key)
    env = {"production": "producción", "sandbox": "sandbox", "qa": "qa"}.get(settings.env_mode, settings.env_mode)
    lines = [f"Canal: {channel}"]
    if kind == "recovered":
        lines += [f"Condición: {subject_title}",
                  "Estado: Recuperado. La condición se normalizó.",
                  f"Estuvo activa desde: {_local_time(since)}",
                  f"Normalizada: {_local_time(now)}"]
        link = cond.link if cond else SYNC_LINK
    else:
        assert cond is not None
        lines += [f"Condición: {cond.text}",
                  "Estado: " + ("Alerta nueva." if kind == "new" else "Sigue activa (recordatorio cada 6 horas)."),
                  f"Activa desde: {_local_time(since)}"]
        lines += [f"Detalle: {d}" for d in cond.details]
        link = cond.link
    lines += [f"Revisar en el panel: {link}", f"Ambiente: {env}", "",
              "Mensaje automático de SynkmetriX. No contiene datos personales."]
    msg = EmailMessage()
    msg["Subject"] = f"[SynkmetriX · {env}] {prefix}: {subject_title}"
    msg["From"] = settings.alert_email_from or settings.alert_smtp_user or "alertas@localhost"
    msg["To"] = ", ".join(recipients)
    msg.set_content("\n".join(lines))
    return msg


def _send(msg: EmailMessage) -> bool:
    """Un solo intento, timeout corto. Nunca lanza: devuelve False y deja el nombre de la clase de la excepcion en el log."""
    host, port = settings.alert_smtp_host, int(settings.alert_smtp_port)
    try:
        if port == SMTPS_PORT:
            server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT_SECONDS,
                                                    context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_SECONDS)
        with server:
            if port != SMTPS_PORT:
                server.ehlo()
                if settings.alert_smtp_starttls:
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
            if settings.alert_smtp_user and settings.alert_smtp_password:
                server.login(settings.alert_smtp_user, settings.alert_smtp_password)
            server.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001 - el correo jamas debe tumbar al llamador
        logger.warning("Alerta no enviada: fallo del SMTP (%s).", type(exc).__name__)
        return False


# ----------------------------- chequeo -----------------------------


def run_alert_check(db: Session, now: datetime | None = None) -> AlertCheckResult:
    """Evalua las condiciones y envia nuevas alertas, recordatorios y avisos de recuperacion. No lanza."""
    result = AlertCheckResult()
    if not settings.alerts_enabled:
        result.skipped = "disabled"
        return result
    recipients = _recipients()
    if not recipients:
        logger.warning("Alertas encendidas pero ALERT_EMAIL_TO está vacío: no se envía nada hasta definirlo.")
        result.skipped = "no_recipient"
        return result
    if not settings.alert_smtp_host.strip():
        logger.warning("Alertas encendidas pero ALERT_SMTP_HOST está vacío: no se envía nada hasta definirlo.")
        result.skipped = "no_smtp_host"
        return result
    moment = now or datetime.now(UTC)
    try:
        active = {c.key: c for c in evaluate_conditions(db, moment)}
        states = _load_states(db)
    except Exception as exc:  # noqa: BLE001 - sin evaluacion confiable no se avisa ni se da nada por recuperado
        db.rollback()
        logger.warning("Alertas: no se pudieron evaluar las condiciones (%s).", type(exc).__name__)
        result.skipped = "evaluation_failed"
        return result
    result.active = len(active)

    try:
        for key, cond in active.items():
            state = states.get(key) or {}
            was_active = bool(state.get("active"))
            since = (_parse(state.get("since")) if was_active else None) or moment
            last_sent = _parse(state.get("last_sent_at")) if was_active else None
            if last_sent is None:
                kind = "new"
            elif moment - last_sent >= REPEAT_EVERY:
                kind = "reminder"
            else:
                continue
            if _send(_build(kind, cond, key, since, moment, recipients)):
                result.sent += 1
                last_sent = moment
            else:
                result.failed += 1
            _save_state(db, key, {"active": True, "since": since.isoformat(),
                                  "last_sent_at": last_sent.isoformat() if last_sent else None})
        for key, state in states.items():
            if key in active or not state.get("active"):
                continue
            since = _parse(state.get("since")) or moment
            if _parse(state.get("last_sent_at")) is None:  # nunca llego a avisarse: no hay nada que dar por recuperado
                _save_state(db, key, {"active": False, "last_resolved_at": moment.isoformat()})
                continue
            if _send(_build("recovered", None, key, since, moment, recipients)):
                result.sent += 1
                _save_state(db, key, {"active": False, "last_resolved_at": moment.isoformat()})
            else:
                result.failed += 1  # sigue marcada como activa: el siguiente chequeo reintenta el aviso
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("Alertas: chequeo interrumpido (%s).", type(exc).__name__)
    return result


# BILL-22: fuentes de otros modulos que se registran al importar (al final: dependen de lo definido arriba).
from app.services import billing_alerts  # noqa: E402,F401
