"""d189: alerta de suscripciones de VirtualPOS que terminan pronto. Ver docs/data/alerts.md.

Se registra en `app.services.alerts` con `register_condition_provider` (mismo chequeo, deduplicacion, recordatorio cada
6 h y aviso de «Recuperado»). Detras de `ALERT_VP_ENDING_SOON_ENABLED` (APAGADA por defecto, d138) ademas de
`ALERTS_ENABLED`; la ventana es `ALERT_VP_ENDING_SOON_DAYS` (60).

Poblacion: `vp_subscriptions` sin `removed_at`, en estado `ACTIVA`, con `automatic_renewal = 'F'` y plan
`MONTO_FIJO` (`vp_plans.plan_type`). Fin estimado: la fecha del ULTIMO `vp_charges.charge_date` de la suscripcion; si
no tiene cargos, `suscription_date + num_charges x frecuencia` (de `vp_plans.raw_payload`). Sin fecha estimable no
cuenta. Es la misma regla de la medicion de VALIDATION-PLAN.md («Medicion pendiente»).

Dos condiciones:

- `vp_subscriptions_ending_soon:upcoming`: fin estimado entre hoy y hoy + N dias (hora de Chile).
- `vp_subscriptions_ending_soon:past_end`: fin estimado ya paso pero la suscripcion sigue `ACTIVA` (posible desfase
  de la sincronizacion, o renovacion que el dato no refleja).

Solo lectura y sin datos personales: el correo lleva SOLO conteos por plataforma y mes del fin estimado (nunca
nombres, RUT, correos, ids de suscripcion ni de plan). Advertencia en el texto: `automatic_renewal = 'F'` podria ser el
valor normal en VirtualPOS (pendiente de confirmar con el proveedor, TER-01).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services import alerts

KIND = "vp_subscriptions_ending_soon"
CHANNEL = "VirtualPOS"
GROUP_UPCOMING = "upcoming"
GROUP_PAST_END = "past_end"
LIST_LINK = "/virtualpos/suscripciones"
MAX_DETAIL_LINES = 24  # meses por grupo; los demas se resumen en una linea

RENEWAL_WARNING = (
    "Advertencia: el dato automatic_renewal = F podría ser el valor normal en VirtualPOS y no significar que la "
    "suscripción no se renueve (pendiente de confirmar con VirtualPOS, TER-01). Validar antes de actuar."
)

_SUBJECTS = {
    GROUP_UPCOMING: "suscripciones de VirtualPOS que terminan pronto",
    GROUP_PAST_END: "suscripciones de VirtualPOS activas con el fin ya pasado",
}

# Frecuencia del plan (raw_payload.frequency_type) -> intervalo. Se aceptan los valores en español y en inglés.
_ESTIMATE_SQL = text("""
WITH subs AS (
    SELECT s.platform,
           s.external_id,
           s.suscription_date,
           lower(p.raw_payload ->> 'frequency_type') AS frequency_type,
           CASE WHEN (p.raw_payload ->> 'num_charges') ~ '^[0-9]+$'
                THEN (p.raw_payload ->> 'num_charges')::int END AS num_charges
    FROM vp_subscriptions s
    JOIN vp_plans p ON p.platform = s.platform AND p.external_id = s.plan_external_id
    WHERE s.removed_at IS NULL
      AND upper(coalesce(s.status, '')) = 'ACTIVA'
      AND upper(coalesce(s.automatic_renewal, '')) = 'F'
      AND upper(coalesce(p.plan_type, '')) = 'MONTO_FIJO'
),
estimated AS (
    SELECT subs.platform,
           coalesce(
               (SELECT max(c.charge_date) FROM vp_charges c
                 WHERE c.platform = subs.platform AND c.subscription_external_id = subs.external_id),
               (subs.suscription_date + subs.num_charges * CASE subs.frequency_type
                    WHEN 'diario' THEN interval '1 day'      WHEN 'daily' THEN interval '1 day'
                    WHEN 'semanal' THEN interval '7 days'    WHEN 'weekly' THEN interval '7 days'
                    WHEN 'mensual' THEN interval '1 month'   WHEN 'monthly' THEN interval '1 month'
                    WHEN 'bimestral' THEN interval '2 months' WHEN 'bimonthly' THEN interval '2 months'
                    WHEN 'trimestral' THEN interval '3 months' WHEN 'quarterly' THEN interval '3 months'
                    WHEN 'semestral' THEN interval '6 months' WHEN 'biannual' THEN interval '6 months'
                    WHEN 'anual' THEN interval '1 year'      WHEN 'annual' THEN interval '1 year'
                END)::date
           ) AS estimated_end
    FROM subs
)
SELECT CASE WHEN estimated_end < :today THEN 'past_end' ELSE 'upcoming' END AS grp,
       platform,
       to_char(estimated_end, 'YYYY-MM') AS month,
       count(*) AS n
FROM estimated
WHERE estimated_end IS NOT NULL AND estimated_end <= :limit
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3
""")


def _window_days() -> int:
    return max(1, int(settings.alert_vp_ending_soon_days))


def _today(now: datetime) -> date:
    return now.astimezone(ZoneInfo("America/Santiago")).date()


def counts(db: Session, now: datetime) -> dict[str, list[tuple[str, str, int]]]:
    """{grupo: [(plataforma, YYYY-MM, cantidad)]}. Solo agregados; solo lectura."""
    today = _today(now)
    rows = db.execute(_ESTIMATE_SQL, {"today": today, "limit": today + timedelta(days=_window_days())}).all()
    grouped: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for grp, platform, month, n in rows:
        grouped[str(grp)].append((str(platform), str(month), int(n)))
    return dict(grouped)


def _details(rows: list[tuple[str, str, int]]) -> tuple[str, ...]:
    lines = [f"{platform} · {month}: {n}" for platform, month, n in rows]
    if len(lines) > MAX_DETAIL_LINES:
        rest = rows[MAX_DETAIL_LINES:]
        lines = [*lines[:MAX_DETAIL_LINES],
                 f"… y {len(rest)} combinación(es) más de plataforma y mes ({sum(n for _, _, n in rest)} suscripciones)"]
    return tuple(lines)


def evaluate(db: Session, now: datetime) -> list[alerts.Condition]:
    grouped = counts(db, now)
    days = _window_days()
    found: list[alerts.Condition] = []
    upcoming = grouped.get(GROUP_UPCOMING) or []
    if upcoming:
        total = sum(n for _, _, n in upcoming)
        found.append(alerts.Condition(
            key=f"{KIND}:{GROUP_UPCOMING}", channel=CHANNEL, title=_SUBJECTS[GROUP_UPCOMING],
            text=(f"{total} suscripción(es) activa(s) de plan de monto fijo terminan en los próximos {days} días "
                  "(fin estimado por el último cargo programado o por el número de cargos del plan)."),
            details=("Conteo por plataforma y mes del fin estimado:", *_details(upcoming), RENEWAL_WARNING),
            link=LIST_LINK))
    past = grouped.get(GROUP_PAST_END) or []
    if past:
        total = sum(n for _, _, n in past)
        found.append(alerts.Condition(
            key=f"{KIND}:{GROUP_PAST_END}", channel=CHANNEL, title=_SUBJECTS[GROUP_PAST_END],
            text=(f"{total} suscripción(es) de plan de monto fijo siguen activas aunque su último cargo (o fin "
                  "estimado) ya pasó: posible desfase de la sincronización con VirtualPOS."),
            details=("Conteo por plataforma y mes del último cargo:", *_details(past), RENEWAL_WARNING),
            link=LIST_LINK))
    return found


def describe(detail: str) -> tuple[str, str]:
    return CHANNEL, _SUBJECTS.get(detail, "suscripciones de VirtualPOS por terminar")


def register() -> None:
    alerts.register_condition_provider(KIND, evaluate, describe, lambda: bool(settings.alert_vp_ending_soon_enabled))


register()
