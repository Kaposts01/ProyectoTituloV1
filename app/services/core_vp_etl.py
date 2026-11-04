"""Materialize VirtualPOS provider tables (vp_*) into Core entities.

Covers both platforms: virtualpos1 and virtualpos2.
Run order: client attributes → subscriptions → charges → payments → rejections
Idempotent: safe to re-run.

Client linkage in subscriptions prefers a supplied vp_subscriptions.client_external_id. The RUT (social_id) fallback
is used only when it identifies a single client within the same platform: a RUT shared by two clients links to none
(REV-01, from origin/sprint-5/estabilizacion-dashboard 1005a26).

Payment → subscription linkage uses client RUT from the payment payload:
  - Exactly 1 subscription for that RUT on that platform → link it
  - 0 or 2+ subscriptions → subscription_id left NULL (ambiguous)
charge_id is NULL when a payment is inserted (the payload carries no charge reference); it is filled
afterwards by an explicit UPDATE from exact sources only (VP-PAR-06): the PAT report (UUID -> Id cargo),
payment_rejection_details (RJ-06/RJ-04) and charge payloads that embed the payment UUID.
"""

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.core import (
    CoreCharge,
    CoreClientAttribute,
    CorePayment,
    CoreSubscription,
    ExternalIdentity,
)
from app.models.rejection import PaymentRejectionDetail
from app.models.vp import VpCharge, VpClient, VpPayment, VpSubscription
from app.services.core_materialization import materialize_core_clients
from app.services.vp_current_amount import load_current_amount
from app.services.vp_typed_fields import parse_amount, parse_date

log = logging.getLogger(__name__)

_BATCH = 500
_VP_SOURCES = ("virtualpos1", "virtualpos2")
_DEFAULT_CURRENCY = "CLP"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date(value: object) -> datetime | None:
    """Dia del valor a medianoche UTC (regla historica del ETL). Desde VP-PAR-13 `vp_*` entrega date/datetime."""
    day = parse_date(value)
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc) if day is not None else None


def _parse_amount(value: object) -> Decimal | None:
    return parse_amount(value)


# ── Índices compartidos ───────────────────────────────────────────────────────

def _build_identity_index(db: Session) -> dict[tuple[str, str], uuid.UUID | None]:
    """(source, external_id) → CoreClient.id"""
    return {
        (row.source, row.external_id): row.client_id
        for row in db.execute(
            select(ExternalIdentity.source, ExternalIdentity.external_id, ExternalIdentity.client_id).where(
                ExternalIdentity.source.in_(_VP_SOURCES),
                ExternalIdentity.resource_type == "client",
            )
        )
    }


def _build_social_id_index(db: Session) -> dict[tuple[str, str], str | None]:
    """(platform, social_id/RUT) → vp_client.external_id; None marks a RUT shared by two or more clients (ambiguous).

    Before REV-01 the first match won, which could attach a subscription or payment to the wrong person (ADR-001: the
    RUT is not a universal identity).
    """
    index: dict[tuple[str, str], str | None] = {}
    for c in db.scalars(select(VpClient).where(VpClient.social_id.isnot(None))):
        key = (c.platform, c.social_id)
        if key in index and index[key] != c.external_id:
            index[key] = None
        else:
            index.setdefault(key, c.external_id)
    return index


# ── Paso 1: atributos de cliente ──────────────────────────────────────────────

def _materialize_client_attributes(db: Session, ext_to_core: dict) -> int:
    clients = db.scalars(select(VpClient)).all()
    rows: list[dict] = []
    for c in clients:
        client_id = ext_to_core.get((c.platform, c.external_id))
        observed = c.updated_at or c.created_at
        full_name = " ".join(filter(None, [c.first_name, c.last_name])).strip() or None
        for attr_type, attr_val in [
            ("name", full_name),
            ("email", c.email),
            ("phone", c.phone_number),
            ("rut", c.social_id),
        ]:
            if attr_val and str(attr_val).strip():
                rows.append({
                    "id": uuid.uuid4(),
                    "client_id": client_id,
                    "source": c.platform,
                    "attribute_type": attr_type,
                    "attribute_value": str(attr_val).strip(),
                    "observed_at": observed,
                })

    before = db.scalar(
        select(func.count()).select_from(CoreClientAttribute).where(
            CoreClientAttribute.source.in_(_VP_SOURCES)
        )
    ) or 0
    for i in range(0, len(rows), _BATCH):
        db.execute(
            insert(CoreClientAttribute)
            .values(rows[i : i + _BATCH])
            .on_conflict_do_nothing(constraint="uq_core_client_attribute")
        )
    after = db.scalar(
        select(func.count()).select_from(CoreClientAttribute).where(
            CoreClientAttribute.source.in_(_VP_SOURCES)
        )
    ) or 0
    return after - before


# ── Paso 2: suscripciones ─────────────────────────────────────────────────────

def _materialize_subscriptions(
    db: Session,
    social_to_ext: dict[tuple[str, str], str | None],
    ext_to_core: dict[tuple[str, str], uuid.UUID | None],
) -> int:
    subscriptions = db.scalars(select(VpSubscription)).all()
    # Monto vigente = ultimo monto cobrado (plan fijo no editable en VP); fallback al monto de la suscripcion/plan.
    current_amounts = load_current_amount(db, family="vp")
    rows = []
    for s in subscriptions:
        # An explicit but unresolved client ID must not fall back to a personal attribute (REV-01).
        ext_id = s.client_external_id
        if not ext_id and s.client_social_id:
            ext_id = social_to_ext.get((s.platform, s.client_social_id))
        client_id = ext_to_core.get((s.platform, ext_id)) if ext_id else None
        rows.append({
            "id": uuid.uuid4(),
            "client_id": client_id,
            "source": s.platform,
            "external_id": s.external_id,
            "status": s.status,
            "amount": current_amounts.get((s.platform, s.external_id), _parse_amount(s.amount)),
            "currency": s.currency or _DEFAULT_CURRENCY,
            "started_at": _parse_date(s.suscription_date),
            "ended_at": _parse_date(s.canceled_at),
        })

    before = db.scalar(
        select(func.count()).select_from(CoreSubscription).where(
            CoreSubscription.source.in_(_VP_SOURCES)
        )
    ) or 0
    for i in range(0, len(rows), _BATCH):
        ins = insert(CoreSubscription).values(rows[i : i + _BATCH])
        db.execute(ins.on_conflict_do_update(
            constraint="uq_core_subscription_source_external_id",
            set_={
                "status": ins.excluded.status,
                "amount": ins.excluded.amount,
                "currency": ins.excluded.currency,
                "started_at": ins.excluded.started_at,
                "ended_at": ins.excluded.ended_at,
                "updated_at": datetime.now(tz=timezone.utc),
            },
        ))
    after = db.scalar(
        select(func.count()).select_from(CoreSubscription).where(
            CoreSubscription.source.in_(_VP_SOURCES)
        )
    ) or 0
    return after - before


def _api_last4(raw_payload: object) -> str | None:
    payment_method = raw_payload.get("payment_method") if isinstance(raw_payload, dict) else None
    value = payment_method.get("last4CardDigit") if isinstance(payment_method, dict) else None
    text_value = str(value).strip() if value is not None else ""
    return text_value if len(text_value) == 4 and text_value.isdigit() else None


def project_subscription_report_fields(db: Session) -> dict[tuple[str, str], dict[str, str | None]]:
    """Motivo de rechazo y ultimos 4 de cada suscripcion VP, completando la API con `SuscriptoresPAT` (VP-PAR-09).

    - `rejection_reason`: «Motivo de rechazo» del reporte (la API no lo expone).
    - `card_last4` / `card_last4_source`: la tarjeta vigente de la API (`vp_subscriptions.card_last4`, VP-PAR-07; si
      la fila aun no la tiene, `raw_payload.payment_method.last4CardDigit`) manda; si falta (suscripcion fallida,
      cancelada o sin tarjeta vigente) se usa la del reporte.
    Solo filas del reporte con plataforma `resolved`. `persist_subscription_report_fields` lo guarda en
    `core_subscriptions`. Si las tablas del reporte no existen, el reporte se trata como vacio.
    """
    from app.services.vp_report_import import subscription_report_fields

    try:
        with db.begin_nested():
            report = subscription_report_fields(db)
    except SQLAlchemyError as exc:
        log.warning("VP Core ETL: vp_report_subscriptions no disponible (%s); se omite", type(exc).__name__)
        report = {}
    out: dict[tuple[str, str], dict[str, str | None]] = {}
    for platform, external_id, card_last4, raw_payload in db.execute(
        select(VpSubscription.platform, VpSubscription.external_id, VpSubscription.card_last4,
               VpSubscription.raw_payload).where(VpSubscription.platform.in_(_VP_SOURCES))
    ):
        rep = report.get((platform, external_id), {})
        api_last4 = card_last4 or _api_last4(raw_payload)
        last4 = api_last4 or rep.get("card_last4")
        out[(platform, external_id)] = {
            "rejection_reason": rep.get("rejection_reason"),
            "card_last4": last4,
            "card_last4_source": ("api" if api_last4 else "report") if last4 else None,
        }
    return out


def persist_subscription_report_fields(db: Session, fields: dict[tuple[str, str], dict[str, str | None]]) -> int:
    """Guarda en `core_subscriptions` el motivo de rechazo y los ultimos 4 proyectados (VP-PAR-09, migracion 0060).

    UPDATE explicito por clave primaria solo donde cambia algo (idempotente). Una suscripcion que pierde el motivo o
    la tarjeta (p. ej. el reporte ya no la trae) vuelve a NULL: la columna refleja siempre la proyeccion vigente.
    Devuelve las filas actualizadas.
    """
    updates: list[dict] = []
    for row in db.execute(
        select(CoreSubscription.id, CoreSubscription.source, CoreSubscription.external_id,
               CoreSubscription.rejection_reason, CoreSubscription.card_last4, CoreSubscription.card_last4_source)
        .where(CoreSubscription.source.in_(_VP_SOURCES))
    ):
        new = fields.get((row.source, row.external_id))
        if new is None:
            continue
        current = (row.rejection_reason, row.card_last4, row.card_last4_source)
        target = (new["rejection_reason"], new["card_last4"], new["card_last4_source"])
        if current != target:
            updates.append({"id": row.id, "rejection_reason": target[0], "card_last4": target[1],
                            "card_last4_source": target[2], "updated_at": datetime.now(tz=timezone.utc)})
    for i in range(0, len(updates), _BATCH):
        db.execute(update(CoreSubscription), updates[i : i + _BATCH])
    return len(updates)


# ── Paso 3: cargos ────────────────────────────────────────────────────────────

def _materialize_charges(db: Session) -> int:
    sub_index: dict[tuple[str, str], uuid.UUID] = {
        (row.source, row.external_id): row.id
        for row in db.execute(
            select(CoreSubscription.source, CoreSubscription.external_id, CoreSubscription.id).where(
                CoreSubscription.source.in_(_VP_SOURCES)
            )
        )
    }

    charges = db.scalars(select(VpCharge)).all()
    rows = []
    unlinked = 0
    for c in charges:
        sub_id = sub_index.get((c.platform, c.subscription_external_id)) if c.subscription_external_id else None
        if sub_id is None:
            unlinked += 1
        due = _parse_date(c.charge_date)
        rows.append({
            "id": uuid.uuid4(),
            "subscription_id": sub_id,
            "source": c.platform,
            "external_id": c.external_id,
            "period_reference": due.strftime("%Y-%m") if due else None,
            "due_at": due,
            "amount": _parse_amount(c.amount),
            "currency": c.currency or _DEFAULT_CURRENCY,
            "source_status": c.status,
        })

    if unlinked:
        log.info("VP Core ETL: %d cargos sin suscripción Core identificada (subscription_id=NULL)", unlinked)

    before = db.scalar(
        select(func.count()).select_from(CoreCharge).where(CoreCharge.source.in_(_VP_SOURCES))
    ) or 0
    for i in range(0, len(rows), _BATCH):
        ins = insert(CoreCharge).values(rows[i : i + _BATCH])
        db.execute(ins.on_conflict_do_update(
            constraint="uq_core_charge_source_external_id",
            set_={
                "period_reference": ins.excluded.period_reference,
                "due_at": ins.excluded.due_at,
                "amount": ins.excluded.amount,
                "currency": ins.excluded.currency,
                "source_status": ins.excluded.source_status,
                "updated_at": datetime.now(tz=timezone.utc),
            },
        ))
    after = db.scalar(
        select(func.count()).select_from(CoreCharge).where(CoreCharge.source.in_(_VP_SOURCES))
    ) or 0
    return after - before


# ── Paso 5: pagos ─────────────────────────────────────────────────────────────

def _build_rut_to_sub_index(db: Session) -> dict[tuple[str, str], list[uuid.UUID]]:
    """(platform, rut) → list of CoreSubscription.id for that platform+rut.

    A RUT shared by two or more VP clients of the platform is left out (REV-01): the payment stays unlinked.
    """
    social_index = _build_social_id_index(db)
    index: dict[tuple[str, str], list[uuid.UUID]] = {}
    for row in db.execute(
        select(VpSubscription.platform, VpSubscription.client_social_id, CoreSubscription.id)
        .join(
            CoreSubscription,
            and_(
                CoreSubscription.source == VpSubscription.platform,
                CoreSubscription.external_id == VpSubscription.external_id,
            ),
        )
        .where(
            VpSubscription.client_social_id.isnot(None),
            VpSubscription.platform.in_(_VP_SOURCES),
        )
        .distinct(VpSubscription.platform, VpSubscription.client_social_id, CoreSubscription.id)
    ):
        key = (row.platform, row.client_social_id)
        if key in social_index and social_index[key] is None:
            continue
        index.setdefault(key, []).append(row.id)
    return index


def _materialize_payments(db: Session, rut_to_sub: dict) -> tuple[int, int]:
    """Returns (inserted, ambiguous_count)."""
    payments = db.scalars(select(VpPayment)).all()

    rows = []
    ambiguous = 0
    for p in payments:
        rut = p.client_social_id  # VP-PAR-07; las filas aun sin la columna caen al payload
        if rut is None and p.raw_payload and isinstance(p.raw_payload, dict):
            rut = (p.raw_payload.get("client") or {}).get("social_id")
        candidates = rut_to_sub.get((p.platform, rut), []) if rut else []
        sub_id = candidates[0] if len(candidates) == 1 else None
        if len(candidates) != 1:
            ambiguous += 1
        rows.append({
            "id": uuid.uuid4(),
            "source": p.platform,
            "external_id": p.external_id,
            "subscription_id": sub_id,
            "charge_id": None,
            "source_status": p.status,
            "occurred_at": _parse_date(p.payment_date),
            "amount": _parse_amount(p.amount),
            "currency": p.currency or _DEFAULT_CURRENCY,
            "rejection_code": None,
            "rejection_reason": None,
            "rejection_reported_at": None,
        })

    before = db.scalar(
        select(func.count()).select_from(CorePayment).where(CorePayment.source.in_(_VP_SOURCES))
    ) or 0
    for i in range(0, len(rows), _BATCH):
        db.execute(
            insert(CorePayment)
            .values(rows[i : i + _BATCH])
            .on_conflict_do_nothing(constraint="uq_core_payment_source_external_id")
        )
    after = db.scalar(
        select(func.count()).select_from(CorePayment).where(CorePayment.source.in_(_VP_SOURCES))
    ) or 0
    return after - before, ambiguous


# ── Paso 6: enriquecer cobros y pagos con el último rechazo verificable ──────

def _extract_rejection(payload: object) -> tuple[str, str | None] | None:
    """(código, mensaje) del `rejected_object` de un detalle de pago de VirtualPOS, o None.

    En `GET /v3/payment/{uuid}` el objeto viene en el nivel superior de la respuesta (hermano de
    `payment`). Por compatibilidad también se lee dentro de `payment.order` y de `order`. El código
    puede llegar como `code` o `error_code`. El código `0` es «Operación exitosa», no un rechazo.
    """
    if not isinstance(payload, dict):
        return None
    inner = payload.get("payment") if isinstance(payload.get("payment"), dict) else payload
    candidates = (
        payload.get("rejected_object"),
        ((inner.get("order") if isinstance(inner.get("order"), dict) else None) or {}).get("rejected_object"),
        ((payload.get("order") if isinstance(payload.get("order"), dict) else None) or {}).get("rejected_object"),
    )
    for rejected in candidates:
        if not isinstance(rejected, dict) or not rejected:
            continue
        raw_code = rejected.get("code") if rejected.get("code") not in (None, "") else rejected.get("error_code")
        code = str(raw_code).strip() if raw_code not in (None, "") else ""
        if not code or code == "0":
            continue
        message = str(rejected.get("message") or "").strip()
        return code, (message or None)
    return None


def _rejected_vp_payments(db: Session, extra_keys: set[tuple[str, str]]):
    """VpPayment cuyo `raw_payload` trae `rejected_object` (en cualquiera de las formas conocidas)."""
    has_object = or_(
        VpPayment.raw_payload.has_key("rejected_object"),
        VpPayment.raw_payload["payment"]["order"].has_key("rejected_object"),
        VpPayment.raw_payload["order"].has_key("rejected_object"),
    )
    query = select(VpPayment).where(VpPayment.platform.in_(_VP_SOURCES), has_object)
    for p in db.scalars(query):
        found = _extract_rejection(p.raw_payload)
        if found is not None:
            yield p, found[0], found[1]


def _detail_rows(db: Session) -> list:
    """Glosas capturadas en `payment_rejection_details` (RJ-06/RJ-04) de las cuentas VP, de la mas antigua a la mas nueva.

    Los marcadores («consultado sin glosa», `code = ''`) no son rechazos y se omiten. Si la tabla aun no existe
    (migracion 20261029_0043 sin aplicar) devuelve [] y el ETL sigue con lo que ya hacia.

    El reporte PAT es la fuente de verdad de la glosa (D4/D5, L7-IMPORT): si un cobro tiene una glosa del reporte
    (`capture_source = 'report_pat'`), sus glosas de la API se descartan aqui y la del reporte manda en
    `_enrich_charges_with_rejections` / `_enrich_payments_with_rejections` (ver `is_report_detail`).
    """
    try:
        with db.begin_nested():
            rows = list(db.execute(
                select(
                    PaymentRejectionDetail.source, PaymentRejectionDetail.charge_external_id,
                    PaymentRejectionDetail.payment_external_id, PaymentRejectionDetail.code,
                    PaymentRejectionDetail.reason, PaymentRejectionDetail.rejected_at,
                    PaymentRejectionDetail.capture_source,
                )
                .where(PaymentRejectionDetail.source.in_(_VP_SOURCES), PaymentRejectionDetail.code != "")
                .order_by(PaymentRejectionDetail.rejected_at.asc().nulls_first(), PaymentRejectionDetail.captured_at.asc())
            ))
    except SQLAlchemyError as exc:
        log.warning("VP Core ETL: payment_rejection_details no disponible (%s); se omite", type(exc).__name__)
        return []
    from_report = {(r.source, r.charge_external_id) for r in rows if is_report_detail(r) and r.charge_external_id}
    return [r for r in rows if is_report_detail(r) or (r.source, r.charge_external_id) not in from_report]


def is_report_detail(row) -> bool:
    """True si la glosa viene del reporte PAT (manda sobre la de la API, D4/D5)."""
    return getattr(row, "capture_source", None) == "report_pat"


_CHARGE_PAYLOAD_LINK_CTE = """
    WITH link AS (
        SELECT platform, raw_payload->'payment'->'order'->>'uuid' AS payment_external_id,
               min(external_id) AS charge_external_id
        FROM vp_charges
        WHERE platform IN ('virtualpos1', 'virtualpos2')
          AND coalesce(raw_payload->'payment'->'order'->>'uuid', '') <> ''
        GROUP BY platform, raw_payload->'payment'->'order'->>'uuid'
        HAVING count(DISTINCT external_id) = 1
    )
"""


def link_payments_from_charge_payloads(db: Session) -> dict[str, int]:
    """Vinculo pago -> cobro cuando el propio cobro trae el UUID del pago (`payment.order.uuid`).

    `GET /suscription/{id}/charges` y `GET /charge/{id}` lo traen; el `charge_program` del listado de suscripciones
    hoy no. Cruce exacto 1 a 1 (un UUID en dos cobros no se vincula), UPDATE solo donde el vinculo esta NULL.
    """
    vp = db.execute(text(_CHARGE_PAYLOAD_LINK_CTE + """
        UPDATE vp_payments p SET charge_external_id = link.charge_external_id, updated_at = now()
        FROM link
        WHERE p.platform = link.platform AND p.external_id = link.payment_external_id AND p.charge_external_id IS NULL
    """)).rowcount or 0
    core = db.execute(text(_CHARGE_PAYLOAD_LINK_CTE + """
        UPDATE core_payments cp SET charge_id = cc.id, updated_at = now()
        FROM link JOIN core_charges cc ON cc.source = link.platform AND cc.external_id = link.charge_external_id
        WHERE cp.source = link.platform AND cp.external_id = link.payment_external_id AND cp.charge_id IS NULL
    """)).rowcount or 0
    return {"vp_payments": vp, "core_payments": core}


def _link_payments_to_charges(db: Session) -> dict[str, int]:
    """Rehace pago -> cobro (`vp_payments.charge_external_id`, `core_payments.charge_id`) desde fuentes exactas.

    VP-PAR-06. Tres fuentes, todas por cruce exacto del UUID del pago y solo donde el vinculo esta NULL:
    1. Reporte PAT (`vp_report_payments`: `UUID transaccion` -> `Id cargo`, 1 a 1). Cubre pagados y rechazados del
       historico cargado y los `core_payments` que el ETL crea despues de la carga del reporte.
    2. Detalles de rechazo (`payment_rejection_details`, RJ-06/RJ-04).
    3. Cobros cuyo payload trae `payment.order.uuid`.
    Nunca por RUT ni por fecha. Cada fuente va en su SAVEPOINT: si su tabla no existe (migracion sin aplicar) se omite.
    Devuelve los `core_payments` vinculados por fuente.
    """
    from app.services.vp_rejection_capture import (
        link_payments_to_charges,  # evita importar el cliente HTTP al cargar el ETL
    )
    from app.services.vp_report_import import link_payments_from_reports

    linked: dict[str, int] = {}
    for name, step in (
        ("reports", link_payments_from_reports),
        ("rejection_details", link_payments_to_charges),
        ("charge_payloads", link_payments_from_charge_payloads),
    ):
        try:
            with db.begin_nested():
                linked[name] = step(db)["core_payments"]
        except SQLAlchemyError as exc:
            log.warning("VP Core ETL: no se pudo rehacer el vinculo pago-cobro desde %s (%s)", name, type(exc).__name__)
            linked[name] = 0
    return linked


def _enrich_charges_with_rejections(
    db: Session,
    payment_charge_links: dict[tuple[str, str], str] | None = None,
) -> int:
    """Actualiza CoreCharge.latest_rejection_* con el rechazo más reciente de sus pagos.

    - `rejected_object` se lee en el nivel superior del detalle del pago (ver `_extract_rejection`).
    - El vínculo pago -> cobro sale de `VpPayment.charge_external_id` (hoy NULL en todas las filas) o
      de `payment_charge_links` {(plataforma, id de pago): id de cobro}, que entregarán RJ-06 / RJ-04.
      Sin vínculo no se inventa nada.
    - UPDATE explícito por clave primaria: los ETL insertan con `on_conflict_do_nothing`, así que una
      fila existente nunca se corregiría sola. Solo cambia filas cuyo rechazo difiere y nunca reemplaza
      un rechazo más reciente por uno más antiguo. Idempotente. Retorna los cobros actualizados.
    """
    links = payment_charge_links or {}
    best: dict[tuple[str, str], dict] = {}
    for p, code, reason in _rejected_vp_payments(db, set(links)):
        charge_ext = p.charge_external_id or links.get((p.platform, p.external_id))
        if not charge_ext:
            continue
        occurred = _parse_date(p.payment_date)
        key = (p.platform, charge_ext)
        prev = best.get(key)
        newer = prev is None or (occurred is not None and (prev["occurred_at"] is None or occurred > prev["occurred_at"]))
        if newer:
            best[key] = {"payment_external_id": p.external_id, "code": code, "reason": reason, "occurred_at": occurred}
    for d in _detail_rows(db):
        if not d.charge_external_id:
            continue
        key = (d.source, d.charge_external_id)
        prev = best.get(key)
        occurred = d.rejected_at
        authoritative = is_report_detail(d)
        newer = prev is None or (occurred is not None and (prev["occurred_at"] is None or occurred >= prev["occurred_at"]))
        if authoritative or (newer and not (prev or {}).get("authoritative")):
            best[key] = {"payment_external_id": d.payment_external_id, "code": d.code, "reason": d.reason,
                         "occurred_at": occurred, "authoritative": authoritative}
    if not best:
        return 0

    core_payment_ids = {
        (row.source, row.external_id): row.id
        for row in db.execute(select(CorePayment.source, CorePayment.external_id, CorePayment.id).where(CorePayment.source.in_(_VP_SOURCES)))
    }
    updates: list[dict] = []
    for (platform, charge_ext), rej in best.items():
        current = db.execute(
            select(
                CoreCharge.id, CoreCharge.latest_rejection_payment_id, CoreCharge.latest_rejection_code,
                CoreCharge.latest_rejection_reason, CoreCharge.latest_rejection_at,
            ).where(CoreCharge.source == platform, CoreCharge.external_id == charge_ext)
        ).first()
        if current is None:
            continue
        stale = current.latest_rejection_at is not None and (
            rej["occurred_at"] is None or rej["occurred_at"] < current.latest_rejection_at
        )
        if stale and not rej.get("authoritative"):  # la glosa del PAT manda aunque la de la API sea mas reciente
            continue
        new_values = {
            "latest_rejection_payment_id": core_payment_ids.get((platform, rej["payment_external_id"])),
            "latest_rejection_code": rej["code"],
            "latest_rejection_reason": rej["reason"],
            "latest_rejection_at": rej["occurred_at"],
        }
        old_values = {
            "latest_rejection_payment_id": current.latest_rejection_payment_id,
            "latest_rejection_code": current.latest_rejection_code,
            "latest_rejection_reason": current.latest_rejection_reason,
            "latest_rejection_at": current.latest_rejection_at,
        }
        if new_values != old_values:
            updates.append({"id": current.id, **new_values})
    if updates:
        db.execute(update(CoreCharge), updates)
    return len(updates)


def _enrich_payments_with_rejections(db: Session) -> int:
    """Actualiza CorePayment.rejection_* desde el `rejected_object` del pago (no necesita vínculo a cobro).

    UPDATE explícito por clave primaria (el ETL inserta pagos con `on_conflict_do_nothing`). Idempotente.
    """
    found: dict[tuple[str, str], tuple[str, str | None, datetime | None]] = {}
    for p, code, reason in _rejected_vp_payments(db, set()):
        found[(p.platform, p.external_id)] = (code, reason, _parse_date(p.payment_date))
    from_report: set[tuple[str, str]] = set()
    for d in _detail_rows(db):
        if d.payment_external_id:
            key = (d.source, d.payment_external_id)
            if key in from_report and not is_report_detail(d):
                continue  # la glosa del PAT manda (D4/D5)
            found[key] = (d.code, d.reason, d.rejected_at)
            if is_report_detail(d):
                from_report.add(key)
    if not found:
        return 0
    updates: list[dict] = []
    for row in db.execute(
        select(CorePayment.id, CorePayment.source, CorePayment.external_id, CorePayment.rejection_code,
               CorePayment.rejection_reason, CorePayment.rejection_reported_at).where(CorePayment.source.in_(_VP_SOURCES))
    ):
        hit = found.get((row.source, row.external_id))
        if hit is None:
            continue
        code, reason, at = hit
        if (row.rejection_code, row.rejection_reason, row.rejection_reported_at) != (code, reason, at):
            updates.append({"id": row.id, "rejection_code": code, "rejection_reason": reason, "rejection_reported_at": at})
    if updates:
        db.execute(update(CorePayment), updates)
    return len(updates)


# ── Punto de entrada ──────────────────────────────────────────────────────────

def run_vp_core_etl(db: Session) -> dict[str, int]:
    """Materialize all VirtualPOS data into Core. Returns counts per entity."""
    log.info("VP Core ETL — materializando clientes (virtualpos1 + virtualpos2)")
    clients_created = materialize_core_clients(db, ["virtualpos"])
    log.info("VP Core ETL — clientes nuevos: %d", clients_created)

    ext_to_core = _build_identity_index(db)
    social_to_ext = _build_social_id_index(db)

    log.info("VP Core ETL — materializando atributos de cliente")
    attrs = _materialize_client_attributes(db, ext_to_core)
    log.info("VP Core ETL — atributos insertados: %d", attrs)

    log.info("VP Core ETL — materializando suscripciones")
    subs = _materialize_subscriptions(db, social_to_ext, ext_to_core)
    log.info("VP Core ETL — suscripciones upserted: %d", subs)

    log.info("VP Core ETL — materializando cargos (~230k registros, puede tardar)")
    charges = _materialize_charges(db)
    log.info("VP Core ETL — cargos upserted: %d", charges)

    log.info("VP Core ETL — construyendo índice RUT→suscripción para pagos")
    rut_to_sub = _build_rut_to_sub_index(db)

    log.info("VP Core ETL — materializando pagos")
    payments, ambiguous = _materialize_payments(db, rut_to_sub)
    log.info("VP Core ETL — pagos insertados: %d (sin suscripción por ambigüedad RUT: %d)", payments, ambiguous)

    log.info("VP Core ETL — enriqueciendo pagos y cobros con el último rechazo")
    links = _link_payments_to_charges(db)
    payments_linked = sum(links.values())
    payment_rejections = _enrich_payments_with_rejections(db)
    rejections = _enrich_charges_with_rejections(db)
    log.info("VP Core ETL — pagos con rechazo: %d; cobros con rechazo enriquecido: %d", payment_rejections, rejections)

    report_fields = project_subscription_report_fields(db)
    subs_with_reason = sum(1 for v in report_fields.values() if v["rejection_reason"])
    last4_from_report = sum(1 for v in report_fields.values() if v["card_last4_source"] == "report")
    subs_report_updated = persist_subscription_report_fields(db, report_fields)
    log.info("VP Core ETL — suscripciones con motivo del reporte: %d; últimos 4 completados desde el reporte: %d; "
             "core_subscriptions actualizadas: %d", subs_with_reason, last4_from_report, subs_report_updated)

    db.commit()
    return {
        "clients_created": clients_created,
        "subscriptions_report_reason": subs_with_reason,
        "subscriptions_last4_from_report": last4_from_report,
        "subscriptions_report_fields_updated": subs_report_updated,
        "attributes_inserted": attrs,
        "subscriptions_upserted": subs,
        "charges_upserted": charges,
        "charges_rejection_enriched": rejections,
        "payments_rejection_enriched": payment_rejections,
        "payments_charge_linked": payments_linked,
        "payments_charge_linked_from_reports": links["reports"],
        "payments_inserted": payments,
        "payments_unlinked_ambiguous_rut": ambiguous,
    }
