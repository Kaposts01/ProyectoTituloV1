"""BILL-22: alertas de la Opcion A sobre la cola de conciliacion (BILL-10) y el barrido de solicitudes atascadas.

Se registra en `app.services.alerts` con `register_condition_provider` (RT-13): usa el mismo chequeo, deduplicacion,
recordatorios y avisos de recuperacion, y por eso tampoco envia nada con `ALERTS_ENABLED` apagada o sin
`ALERT_EMAIL_TO` / `ALERT_SMTP_HOST`. Las solicitudes en `requiere_conciliacion` ya las avisa `billing_stuck`; aqui se
agrega lo que esa condicion no ve:

- `billing_reconciliation:queue`: cobros del CRM (`vp_managed_charges`) o `write_runs` en conciliacion cuya solicitud NO
  esta en `requiere_conciliacion` (p. ej. una solicitud reabierta con un cobro aun sin conciliar). Bloquean la suscripcion.
- `billing_reconciliation:stale`: cualquier elemento de la cola abierto hace mas de 24 h (criterio de abort del piloto,
  PI-05).
- `billing_reconciliation:swept`: solicitudes que el barrido (`billing_sweep_applying`) paso a `requiere_conciliacion`
  en las ultimas 24 h: senal de un proceso caido a mitad de una aplicacion.

Solo lectura y sin datos personales: solo tipos y contadores (nunca ids de suscripcion, de cargo ni textos libres).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.billing import EVENT_NEEDS_RECONCILIATION, BillingChangeRequestEvent
from app.services import alerts

KIND = "billing_reconciliation"
CHANNEL = "Cambios de cobro"
SWEPT_WINDOW = timedelta(hours=24)
SWEEP_REASON = "stuck_applying"  # `billing_apply.sweep_stuck_applying` lo deja en el detalle del evento

_KIND_LABELS = {"request": "solicitudes", "managed_charge": "cobros del CRM", "write_run": "escrituras (write_runs)"}
_SUBJECTS = {
    "queue": "cobros en conciliación",
    "stale": "conciliación abierta hace más de 24 h",
    "swept": "solicitudes barridas a conciliación",
}


def _details(counter: Counter[str]) -> tuple[str, ...]:
    return tuple(f"{_KIND_LABELS.get(k, k)}: {n}" for k, n in sorted(counter.items()))


def swept_count(db: Session, now: datetime, window: timedelta = SWEPT_WINDOW) -> int:
    """Solicitudes barridas a `requiere_conciliacion` por el job en la ventana (eventos del actor sistema)."""
    return int(db.scalar(select(func.count(func.distinct(BillingChangeRequestEvent.request_id))).where(
        BillingChangeRequestEvent.event_type == EVENT_NEEDS_RECONCILIATION,
        BillingChangeRequestEvent.actor_user_id.is_(None),
        BillingChangeRequestEvent.detail["reason"].astext == SWEEP_REASON,
        BillingChangeRequestEvent.created_at >= now - window,
    )) or 0)


def evaluate(db: Session, now: datetime) -> list[alerts.Condition]:
    from app.services.billing_consistency import (
        reconciliation_queue,  # import local: modulo pesado
    )

    items = reconciliation_queue(db, now)
    found: list[alerts.Condition] = []
    requests_in_queue = {i.request_id for i in items if i.kind == "request"}
    orphan = Counter(i.kind for i in items if i.kind != "request" and i.request_id not in requests_in_queue)
    if orphan:
        total = sum(orphan.values())
        found.append(alerts.Condition(
            key=f"{KIND}:queue", channel=CHANNEL, title=_SUBJECTS["queue"],
            text=(f"{total} elemento(s) en conciliación fuera de una solicitud en conciliación: bloquean su suscripción "
                  "hasta conciliarlos a mano."),
            details=_details(orphan), link=alerts.BILLING_LINK))
    stale = Counter(i.kind for i in items if i.stale)
    if stale:
        found.append(alerts.Condition(
            key=f"{KIND}:stale", channel=CHANNEL, title=_SUBJECTS["stale"],
            text=(f"{sum(stale.values())} elemento(s) de la cola de conciliación llevan más de 24 h abiertos "
                  "(criterio de abort del piloto, PI-05)."),
            details=_details(stale), link=alerts.BILLING_LINK))
    swept = swept_count(db, now)
    if swept:
        found.append(alerts.Condition(
            key=f"{KIND}:swept", channel=CHANNEL, title=_SUBJECTS["swept"],
            text=(f"El barrido pasó {swept} solicitud(es) de 'aplicando' a 'requiere_conciliacion' en las últimas 24 h "
                  "(proceso caído a mitad de una aplicación)."),
            details=("Revisar en VirtualPOS los cobros de cada solicitud antes de reabrirla.",), link=alerts.BILLING_LINK))
    return found


def describe(detail: str) -> tuple[str, str]:
    return CHANNEL, _SUBJECTS.get(detail, "conciliación de cambios de cobro")


def register() -> None:
    alerts.register_condition_provider(KIND, evaluate, describe)


register()
