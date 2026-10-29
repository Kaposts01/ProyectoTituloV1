"""Resumen unificado de la jefatura (UX-07): KPIs del mes y series de 12 meses sobre los 4 canales.

Todo se calcula con consultas AGREGADAS en SQL (no se cargan filas de suscripciones ni de cobros en memoria),
salvo MRR/ARPU del mes en curso, que reutilizan las definiciones vigentes de cada dashboard de canal.
Fechas en hora de Chile. Ver `docs/data/dashboard-general.md` (contrato JSON exacto y definiciones propuestas).

Reglas de honestidad: un KPI sin dato devuelve `None` (nunca 0 inventado) y un mes posterior al actual (Chile)
devuelve `None` en todo. Sin metas (D2 pendiente): `meta=None` y `estado_meta="sin_meta"`.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from sqlalchemy import Numeric, case, cast, func, or_, select
from sqlalchemy.orm import Session

from app.models.crm import Charge as CCharge
from app.models.crm import Subscription as CSub
from app.models.tch import TchMonthlyCollection, TchSubscription, TchTransaction
from app.services import rejected_month
from app.services.charge_stats import (
    charge_outcome,
    charge_rejection_stats,
    parse_charge_date,
)
from app.services.status_history import CANCELLATION_STATES

CHANNELS = ("virtualpos", "toku", "payku", "tch")
SERIES_MONTHS = 12
_SRC_CHANNEL = {"virtualpos1": "virtualpos", "virtualpos2": "virtualpos", "toku": "toku", "payku": "payku"}
_CHANNEL_SOURCES = {
    "virtualpos": ("virtualpos1", "virtualpos2"),
    "toku": ("toku",),
    "payku": ("payku",),
}
# TCH guarda el estado como VIGENTE / ELIMINADA (BAJA_STATES['tch'] es el estado normalizado del historial).
_TCH_CANCELLATION_STATES = frozenset(CANCELLATION_STATES["tch"] | {"eliminada"})
_FAILED_SUBSCRIPTION = "suscripcion_fallida"  # VirtualPOS: nunca fue una alta real (igual que el dashboard actual)

CHURN_DEFINITION = (
    "Propuesta pendiente de confirmación: bajas del mes ÷ socios al inicio del mes (cierre del mes anterior), "
    "en porcentaje y con la misma definición en todos los canales."
)
CHURN_WINDOW_LABEL = "mes calendario (hora de Chile): bajas del mes ÷ socios al cierre del mes anterior"
MEMBERS_NOTE = "suma por canal, no deduplicada"
MEMBERS_UNIT = "suscripciones"

_DATE10 = r"^\d{4}-\d{2}-\d{2}"
_AMOUNT_RE = r"^\d+(\.\d+)?$"


# ── utilidades de mes ──────────────────────────────────────────────────────────────────────────────────
def ym(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def parse_month(value: str) -> tuple[int, int]:
    year, month = value.split("-")
    return int(year), int(month)


def add_months(value: str, delta: int) -> str:
    year, month = parse_month(value)
    index = year * 12 + (month - 1) + delta
    return ym(index // 12, index % 12 + 1)


def months_between(first: str, last: str) -> list[str]:
    out, cur = [], first
    while cur <= last:
        out.append(cur)
        cur = add_months(cur, 1)
    return out


def _num(value: Any) -> int | float | None:
    if value is None:
        return None
    number = float(value)
    return int(number) if number == int(number) else round(number, 2)


def _amount_col(column: Any) -> Any:
    return case((column.op("~")(_AMOUNT_RE), cast(column, Numeric)), else_=0)


def _parse_tch_amount(value: object) -> float:
    """Monto TCH (texto): '$', '.', ',' tolerados; basura -> 0 (misma regla que `tch._parse_tch_amount`)."""
    text = str(value or "").strip().replace("$", "").replace(" ", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        pass
    try:
        return float(text.replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def _add(a: float | None, b: float | None) -> float | None:
    """Suma que conserva None solo si AMBOS faltan."""
    if a is None:
        return b
    if b is None:
        return a
    return a + b


def _invalid(valid: Any) -> Any:
    """NOT valido tratando NULL (fecha ausente) como invalido."""
    return func.coalesce(valid, False).is_(False)


# ── suscripciones: altas, bajas, socios ────────────────────────────────────────────────────────────────
def _cancellation_condition_csub(sources: tuple[str, ...]) -> Any:
    return or_(*[
        (CSub.source == source) & (func.lower(func.trim(CSub.status)).in_(tuple(CANCELLATION_STATES[source])))
        for source in sources
    ])


def _subscription_histograms(
    db: Session, channels: list[str]
) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]], dict[str, int]]:
    """Altas y bajas por canal y mes (toda la historia) + conteo de registros sin fecha utilizable.

    Alta = fecha de alta valida (sin SUSCRIPCION_FALLIDA). Baja = estado de baja del canal (BAJA_STATES) con fecha
    de baja valida, y con alta valida anterior o igual (si no, no se puede ubicar en el tiempo y se cuenta aparte).
    """
    signups: dict[str, dict[str, int]] = {c: defaultdict(int) for c in channels}
    cancellations: dict[str, dict[str, int]] = {c: defaultdict(int) for c in channels}
    quality = {"altas_sin_fecha": 0, "bajas_sin_fecha": 0}

    online = [c for c in channels if c in _CHANNEL_SOURCES]
    if online:
        sources = tuple(s for c in online for s in _CHANNEL_SOURCES[c])
        not_failed = func.lower(func.trim(CSub.status)).is_distinct_from(_FAILED_SUBSCRIPTION)
        valid_signup = CSub.suscription_date.op("~")(_DATE10)
        valid_cancellation = CSub.canceled_at.op("~")(_DATE10)
        is_cancelled = _cancellation_condition_csub(sources)
        signup_month = func.substring(CSub.suscription_date, 1, 7)
        cancellation_month = func.substring(CSub.canceled_at, 1, 7)
        for source, month, n in db.execute(
            select(CSub.source, signup_month, func.count())
            .where(CSub.source.in_(sources), valid_signup, not_failed)
            .group_by(CSub.source, signup_month)
        ):
            signups[_SRC_CHANNEL[source]][month] += n
        for source, month, n in db.execute(
            select(CSub.source, cancellation_month, func.count())
            .where(
                CSub.source.in_(sources), is_cancelled, valid_cancellation, valid_signup, not_failed,
                func.substring(CSub.canceled_at, 1, 10) >= func.substring(CSub.suscription_date, 1, 10),
            )
            .group_by(CSub.source, cancellation_month)
        ):
            cancellations[_SRC_CHANNEL[source]][month] += n
        quality["altas_sin_fecha"] += db.scalar(
            select(func.count()).select_from(CSub).where(CSub.source.in_(sources), not_failed, _invalid(valid_signup))
            ) or 0
        quality["bajas_sin_fecha"] += db.scalar(
            select(func.count()).select_from(CSub).where(
                CSub.source.in_(sources), is_cancelled, not_failed,
                or_(_invalid(valid_cancellation), _invalid(valid_signup),
                    func.substring(CSub.canceled_at, 1, 10) < func.substring(CSub.suscription_date, 1, 10)),
            )
        ) or 0

    if "tch" in channels:
        valid_signup = TchSubscription.activation_date.op("~")(_DATE10)
        valid_cancellation = TchSubscription.deletion_date.op("~")(_DATE10)
        is_cancelled = func.lower(func.trim(TchSubscription.status)).in_(tuple(_TCH_CANCELLATION_STATES))
        signup_month = func.substring(TchSubscription.activation_date, 1, 7)
        cancellation_month = func.substring(TchSubscription.deletion_date, 1, 7)
        for month, n in db.execute(
            select(signup_month, func.count()).where(valid_signup).group_by(signup_month)
        ):
            signups["tch"][month] += n
        for month, n in db.execute(
            select(cancellation_month, func.count())
            .where(
                is_cancelled, valid_cancellation, valid_signup,
                func.substring(TchSubscription.deletion_date, 1, 10)
                >= func.substring(TchSubscription.activation_date, 1, 10),
            )
            .group_by(cancellation_month)
        ):
            cancellations["tch"][month] += n
        quality["altas_sin_fecha"] += db.scalar(
            select(func.count()).select_from(TchSubscription).where(_invalid(valid_signup))
        ) or 0
        quality["bajas_sin_fecha"] += db.scalar(
            select(func.count()).select_from(TchSubscription).where(
                is_cancelled,
                or_(_invalid(valid_cancellation), _invalid(valid_signup),
                    func.substring(TchSubscription.deletion_date, 1, 10)
                    < func.substring(TchSubscription.activation_date, 1, 10)),
            )
        ) or 0
    return signups, cancellations, quality


# ── cobros: ingreso, rechazo, pendiente ────────────────────────────────────────────────────────────────
def _new_cell() -> dict[str, Any]:
    return {"paid_n": 0, "paid_amt": 0.0, "rej_n": 0, "rej_amt": 0.0, "pend_n": 0, "pend_amt": 0.0, "stat_rows": []}


def _charge_cells(
    db: Session, channels: list[str], first: str, last: str, today: date
) -> dict[str, dict[str, dict[str, Any]]]:
    """Celdas {canal: {YYYY-MM: acumulados}} de cobros pagados/rechazados (fecha <= hoy) y pendientes.

    VP/Toku/Payku: tabla `charges` agrupada por dia y estado dentro de la ventana (una consulta). TCH: recaudacion
    mensual oficial (o, sin ella, transacciones por periodo), igual que el dashboard actual.
    """
    cells: dict[str, dict[str, dict[str, Any]]] = {c: defaultdict(_new_cell) for c in channels}
    online = [c for c in channels if c in _CHANNEL_SOURCES]
    if online:
        sources = tuple(s for c in online for s in _CHANNEL_SOURCES[c])
        day = func.substring(CCharge.charge_date, 1, 10)
        month = func.substring(CCharge.charge_date, 1, 7)
        status = func.lower(func.trim(CCharge.status))
        for source, d, st, n, amount in db.execute(
            select(CCharge.source, day, status, func.count(), func.coalesce(func.sum(_amount_col(CCharge.amount)), 0))
            .where(
                CCharge.source.in_(sources),
                CCharge.charge_date.op("~")(r"^\d{4}-\d{2}"),
                month >= first, month <= last,
            )
            .group_by(CCharge.source, day, status)
        ):
            parsed = parse_charge_date(d)
            outcome = charge_outcome(st)
            if parsed is None or outcome in ("excluded", "other"):
                continue
            cell = cells[_SRC_CHANNEL[source]][d[:7]]
            if outcome == "pending":  # programado y aun sin resultado: tambien lo que cae mas adelante en el mes
                cell["pend_n"] += n
                cell["pend_amt"] += float(amount)
            elif parsed <= today:  # cobros futuros (fecha > hoy) no son pagados ni rechazados
                key = "paid" if outcome == "paid" else "rej"
                cell[f"{key}_n"] += n
                cell[f"{key}_amt"] += float(amount)
                cell["stat_rows"].append({"date": d, "status": st, "count": n})

    if "tch" in channels:
        controls = db.scalars(
            select(TchMonthlyCollection).where(TchMonthlyCollection.period.between(first, last))
        ).all()
        has_controls = db.scalar(select(func.count()).select_from(TchMonthlyCollection)) or 0
        if has_controls:
            for control in controls:
                cell = cells["tch"][control.period]
                cell["paid_n"] += control.accepted_count
                cell["paid_amt"] += _parse_tch_amount(control.accepted_amount)
                cell["rej_n"] += control.rejected_count
                cell["rej_amt"] += _parse_tch_amount(control.rejected_amount)
                cell["stat_rows"].append({"date": control.period, "status": "aceptada", "count": control.accepted_count})
                cell["stat_rows"].append({"date": control.period, "status": "rechazada", "count": control.rejected_count})
        else:
            for period, raw_status, n, amount in db.execute(
                select(
                    TchTransaction.period, TchTransaction.status, func.count(),
                    func.coalesce(func.sum(_amount_col(TchTransaction.amount)), 0),
                )
                .where(TchTransaction.period.op("~")(r"^\d{4}-\d{2}$"), TchTransaction.period.between(first, last))
                .group_by(TchTransaction.period, TchTransaction.status)
            ):
                outcome = charge_outcome(raw_status)
                if outcome not in ("paid", "rejected"):
                    continue
                key = "paid" if outcome == "paid" else "rej"
                cell = cells["tch"][period]
                cell[f"{key}_n"] += n
                cell[f"{key}_amt"] += float(amount)
                cell["stat_rows"].append({"date": period, "status": str(raw_status).lower(), "count": n})
    return cells


# ── MRR / ARPU (estado actual; definiciones vigentes de cada dashboard de canal) ──────────────────────
def _mrr_by_channel(db: Session, channels: list[str], today: date) -> dict[str, tuple[float, int]]:
    """{canal: (mrr, clientes_activos)} con las MISMAS definiciones que los dashboards de canal (solo mes en curso)."""
    # Import perezoso: reutiliza helpers de los dashboards de canal sin acoplar el modulo al router en la carga.
    from app.api.v1.routes import staging
    from app.models.crm import PaymentMethod as CPaymentMethod
    from app.models.payku_channel import PaykuTransaction as PkTx
    from app.services.vp_current_amount import load_current_amount

    out: dict[str, tuple[float, int]] = {}
    if "virtualpos" in channels:
        srcs = _CHANNEL_SOURCES["virtualpos"]
        subs = db.execute(
            select(CSub.source, CSub.external_id, CSub.amount, CSub.client_social_id)
            .where(CSub.source.in_(srcs), func.lower(CSub.status) == "activa")
        ).all()
        current_amounts = load_current_amount(db, family="crm", sources=srcs, today=today)
        mrr = 0.0
        ruts: set[str] = set()
        for source, external_id, amount, social_id in subs:
            current_amount = current_amounts.get((source, external_id))
            mrr += staging._amount(current_amount if current_amount is not None else amount)
            if social_id:
                ruts.add(str(social_id))
        if subs:
            out["virtualpos"] = (round(mrr, 0), len(ruts) or len(subs))
    if "toku" in channels:
        chargeable = {
            sub_id
            for method in db.scalars(
                select(CPaymentMethod).where(
                    CPaymentMethod.source == "toku", func.lower(CPaymentMethod.status) == "chargeable"
                )
            )
            for sub_id in staging._toku_subscription_ids(method)
        }
        active = [
            (amount, client)
            for ext, amount, client in db.execute(
                select(CSub.external_id, CSub.amount, CSub.client_external_id)
                .where(CSub.source == "toku", func.lower(CSub.status) == "active")
            )
            if ext in chargeable
        ]
        clients = {client for _, client in active if client}
        if active:
            out["toku"] = (round(sum(staging._amount(a) for a, _ in active), 0), len(clients) or len(active))
    if "payku" in channels:
        active_rows = db.execute(
            select(CSub.external_id, CSub.client_social_id)
            .where(CSub.source == "payku", func.lower(CSub.status).in_(("active", "activa", "activo")))
        ).all()
        active_ids = {str(ext) for ext, _ in active_rows}
        tx_rows = [
            {"subscription_id": sid, "status": st, "amount": amount, "created_at": created, "external_id": eid}
            for sid, st, amount, created, eid in db.execute(
                select(PkTx.subscription_id, PkTx.status, PkTx.amount, PkTx.created_at_api, PkTx.external_id)
                .where(PkTx.subscription_id.in_(active_ids), func.lower(PkTx.status) == "success")
            )
        ] if active_ids else []
        last_success = staging._payku_last_success_by_sub(active_ids, tx_rows)
        rut_of = {str(ext): str(rut) for ext, rut in active_rows if rut}
        ruts = {rut_of[sid] for sid in last_success if sid in rut_of}
        if active_rows:
            out["payku"] = (round(sum(last_success.values()), 0), len(ruts) or len(last_success))
    if "tch" in channels:
        equivalent = _amount_col(TchSubscription.peso_equivalent)
        mrr = float(db.scalar(
            select(func.coalesce(func.sum(equivalent), 0)).where(TchSubscription.status == "VIGENTE")
        ) or 0)
        clients = db.scalar(
            select(func.count(TchSubscription.client_rut.distinct()))
            .where(TchSubscription.status == "VIGENTE", TchSubscription.client_rut.isnot(None))
        ) or 0
        if db.scalar(select(func.count()).select_from(TchSubscription).where(TchSubscription.status == "VIGENTE")):
            out["tch"] = (round(mrr, 0), clients)
    return out


# ── ensamblado ─────────────────────────────────────────────────────────────────────────────────────────
def _kpi(value: float | None, previous: float | None, unit: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    delta = None if value is None or previous is None else value - previous
    pct = None if delta is None or not previous else round(100 * delta / abs(previous), 1)
    return {
        "valor": _num(value),
        "valor_mes_anterior": _num(previous),
        "delta_vs_mes_anterior": _num(round(delta, 1) if delta is not None and unit == "pct" else delta),
        "delta_vs_mes_anterior_pct": pct,
        "meta": None,
        "estado_meta": "sin_meta",
        "unidad": unit,
        **(extra or {}),
    }


def _pct(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or not denominator:
        return None
    return round(100 * numerator / denominator, 1)


def build_general_summary(db: Session, month: str | None, channels: list[str]) -> dict[str, Any]:
    now = rejected_month.now_chile()
    today = now.date()
    current_month = ym(today.year, today.month)
    month = month or current_month
    channels = [c for c in CHANNELS if c in channels]  # orden estable
    first = add_months(month, -(SERIES_MONTHS + 1))  # +1 mes para el delta y +1 para el churn del mes anterior
    window = months_between(first, month)
    series_months = window[-SERIES_MONTHS:]

    signups, cancellations, quality = _subscription_histograms(db, channels) if channels else ({}, {}, {})
    # Los cobros necesitan ademas el inicio del año de `month` y del mes anterior (acumulado del año y su delta).
    charge_first = min(first, ym(parse_month(add_months(month, -1))[0], 1))
    cells = _charge_cells(db, channels, charge_first, month, today) if channels else {}

    def cum(table: dict[str, int], upto: str) -> int:
        return sum(n for m, n in table.items() if m <= upto)

    def per_channel(m: str) -> dict[str, dict[str, Any]]:
        """Metricas de cada canal para el mes `m` (None = sin dato)."""
        out: dict[str, dict[str, Any]] = {}
        future = m > current_month
        for ch in channels:
            res: dict[str, Any] = dict.fromkeys(
                ("socios", "socios_inicio", "activaciones", "bajas", "ingreso", "no_cobrado", "por_cobrar"), None
            )
            res["stat_rows"] = []
            if not future:
                has_history = cum(signups[ch], m) > 0
                if has_history:
                    res["socios"] = cum(signups[ch], m) - cum(cancellations[ch], m)
                    prev = add_months(m, -1)
                    res["socios_inicio"] = cum(signups[ch], prev) - cum(cancellations[ch], prev) if cum(signups[ch], prev) > 0 else None
                    res["activaciones"] = signups[ch].get(m, 0)
                    res["bajas"] = cancellations[ch].get(m, 0)
                cell = cells[ch].get(m)
                if cell is not None:
                    res["ingreso"] = cell["paid_amt"]
                    res["no_cobrado"] = cell["rej_amt"]
                    if ch != "tch":
                        res["por_cobrar"] = cell["pend_amt"]
                    res["stat_rows"] = cell["stat_rows"]
            out[ch] = res
        return out

    def combine(per: dict[str, dict[str, Any]], key: str) -> float | None:
        total = None
        for ch in channels:
            total = _add(total, per[ch][key])
        return total

    monthly: dict[str, dict[str, Any]] = {}
    for m in window:
        per = per_channel(m)
        members, members_start = combine(per, "socios"), combine(per, "socios_inicio")
        acts, cancels = combine(per, "activaciones"), combine(per, "bajas")
        stat_rows = [row for ch in channels for row in per[ch]["stat_rows"]]
        stats = charge_rejection_stats(stat_rows, today)
        monthly[m] = {
            "per": per,
            "socios": members,
            "activaciones": acts,
            "bajas": cancels,
            "crecimiento_neto": None if acts is None or cancels is None else acts - cancels,
            "churn": _pct(cancels, members_start),
            "ingreso": combine(per, "ingreso"),
            "cobrabilidad": _pct(stats["paid"], stats["evaluable"]),
            "no_cobrado": combine(per, "no_cobrado"),
            "por_cobrar": combine(per, "por_cobrar"),
        }

    def ytd(m: str) -> float | None:
        if m > current_month:
            return None
        total = None
        for mm in months_between(ym(parse_month(m)[0], 1), m):
            cell_total = None
            for ch in channels:
                cell = cells[ch].get(mm)
                if cell is not None:
                    cell_total = _add(cell_total, cell["paid_amt"])
            total = _add(total, cell_total)
        return total

    prev = add_months(month, -1)
    cur, old = monthly[month], monthly[prev]

    # MRR / ARPU: foto del estado actual, por eso solo existen para el mes en curso.
    mrr_total = arpu = None
    mrr_by_channel: dict[str, float | None] = dict.fromkeys(channels)
    if month == current_month and channels:
        mrr_stats = _mrr_by_channel(db, channels, today)
        for ch, (mrr, _clients) in mrr_stats.items():
            mrr_by_channel[ch] = mrr
            mrr_total = _add(mrr_total, mrr)
        clients_total = sum(clients for _, clients in mrr_stats.values())
        arpu = round(mrr_total / clients_total, 0) if mrr_total is not None and clients_total else None

    kpis: dict[str, Any] = {
        "socios_totales": _kpi(
            cur["socios"], old["socios"], "count",
            extra={"socios_totales_nota": MEMBERS_NOTE, "socios_totales_unidad": MEMBERS_UNIT},
        ),
        "activaciones": _kpi(cur["activaciones"], old["activaciones"], "count"),
        "bajas": _kpi(cur["bajas"], old["bajas"], "count"),
        "crecimiento_neto": _kpi(cur["crecimiento_neto"], old["crecimiento_neto"], "count"),
        "churn": _kpi(
            cur["churn"], old["churn"], "pct",
            extra={"churn_definicion": CHURN_DEFINITION, "churn_window_label": CHURN_WINDOW_LABEL},
        ),
        "ingreso_total": _kpi(cur["ingreso"], old["ingreso"], "clp"),
        "ingreso_por_canal": {
            ch: _kpi(cur["per"][ch]["ingreso"], old["per"][ch]["ingreso"], "clp") for ch in channels
        },
        "acumulado_anio": _kpi(ytd(month), ytd(prev), "clp"),
        "cobrabilidad": _kpi(cur["cobrabilidad"], old["cobrabilidad"], "pct"),
        "no_cobrado": _kpi(cur["no_cobrado"], old["no_cobrado"], "clp"),
        "por_cobrar": _kpi(cur["por_cobrar"], old["por_cobrar"], "clp"),
        "mrr": _kpi(mrr_total, None, "clp", extra={"por_canal": {ch: _num(v) for ch, v in mrr_by_channel.items()}}),
        "arpu": _kpi(arpu, None, "clp"),
    }

    series = {
        "months": series_months,
        "ingreso_por_canal": [
            {
                "month": m,
                "total": _num(monthly[m]["ingreso"]),
                "canales": {ch: _num(monthly[m]["per"][ch]["ingreso"]) for ch in channels},
            }
            for m in series_months
        ],
        "activaciones": [{"month": m, "valor": _num(monthly[m]["activaciones"])} for m in series_months],
        "bajas": [{"month": m, "valor": _num(monthly[m]["bajas"])} for m in series_months],
        "socios_totales": [{"month": m, "valor": _num(monthly[m]["socios"])} for m in series_months],
    }
    return {
        "month": month,
        "timezone": "America/Santiago",
        "generated_at": datetime.now(now.tzinfo).isoformat(),
        "is_current_month": month == current_month,
        "channels": channels,
        "kpis": kpis,
        "series": series,
        "calidad_datos": quality,
    }
