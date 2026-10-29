"""Consultas de exportacion por entidad y canal (EXP-03). SQL con cursor del lado del servidor, nunca en memoria.

Cada entidad (clientes, suscripciones, cobros, pagos) tiene una lista de `ChannelSpec`: una consulta por proveedor
con su permiso de VISTA. Las consultas devuelven las mismas claves que `ENTITY_COLUMNS[entidad]`. Cuando el usuario
no tiene `export.pii` las columnas personales se seleccionan como NULL (no se cargan ni se transportan).

Los filtros reproducen los del listado (`query`/`filter_field`, estado, fechas, montos). Fechas y montos son texto en
las tablas: se comparan los 10 primeros caracteres ISO y se castea el monto solo si tiene forma numerica.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import (
    Numeric,
    String,
    and_,
    case,
    cast,
    false,
    func,
    literal,
    null,
    or_,
    select,
)
from sqlalchemy.orm import Session, aliased

from app.models.crm import Charge as CCharge
from app.models.crm import Client as CClient
from app.models.crm import Payment as CPayment
from app.models.crm import Subscription as CSub
from app.models.payku_channel import PaykuTransaction as PkTx
from app.models.tch import TchClient, TchSubscription, TchTransaction
from app.services.exporter import ExportColumn

YIELD_PER = 2000
PAID_STATUSES = {"pagado", "pago", "aceptado", "aceptada", "accepted", "paid", "success", "aprobado", "aprobada", "cobrado", "cobrada"}
ACTIVE_STATUSES = {"activa", "activo", "active", "vigente"}

ENTITIES = ("clientes", "suscripciones", "cobros", "pagos")
CHANNELS = ("virtualpos1", "virtualpos2", "toku", "payku", "tch")

ENTITY_COLUMNS: dict[str, tuple[ExportColumn, ...]] = {
    "clientes": (
        ExportColumn("channel", "Canal"), ExportColumn("external_id", "ID externo"), ExportColumn("status", "Estado"),
        ExportColumn("signup_date", "Fecha de alta"),
        ExportColumn("rut", "RUT", pii=True), ExportColumn("name", "Nombre", pii=True),
        ExportColumn("email", "Correo", pii=True), ExportColumn("phone", "Teléfono", pii=True),
        ExportColumn("address", "Dirección", pii=True),
    ),
    "suscripciones": (
        ExportColumn("channel", "Canal"), ExportColumn("subscription_id", "ID de suscripción"),
        ExportColumn("status", "Estado"), ExportColumn("secondary_status", "Estado secundario"),
        ExportColumn("start_date", "Fecha de inicio"), ExportColumn("end_date", "Fecha de término"),
        ExportColumn("amount", "Monto"), ExportColumn("currency", "Moneda"), ExportColumn("last_charge", "Último cobro"),
        ExportColumn("rut", "RUT del cliente", pii=True), ExportColumn("name", "Nombre del cliente", pii=True),
    ),
    "cobros": (
        ExportColumn("channel", "Canal"), ExportColumn("charge_id", "ID de cobro"),
        ExportColumn("subscription_id", "ID de suscripción"), ExportColumn("status", "Estado"),
        ExportColumn("charge_date", "Fecha de cobro"), ExportColumn("period", "Período"),
        ExportColumn("amount", "Monto"), ExportColumn("currency", "Moneda"),
        ExportColumn("rejection_reason", "Motivo de rechazo"),
        ExportColumn("rut", "RUT del cliente", pii=True), ExportColumn("name", "Nombre del cliente", pii=True),
    ),
    "pagos": (
        ExportColumn("channel", "Canal"), ExportColumn("payment_id", "ID de pago"), ExportColumn("charge_id", "ID de cobro"),
        ExportColumn("status", "Estado"), ExportColumn("payment_date", "Fecha de pago"), ExportColumn("amount", "Monto"),
        ExportColumn("currency", "Moneda"),
        ExportColumn("rut", "RUT del cliente", pii=True), ExportColumn("name", "Nombre del cliente", pii=True),
    ),
}

# Campos de busqueda validos por entidad (los mismos del listado) y los que pueden contener datos personales.
FILTER_FIELDS: dict[str, tuple[str, ...]] = {
    "clientes": ("all", "rut", "name", "last_name", "platform", "email", "phone"),
    "suscripciones": ("all", "id", "rut", "client", "platform", "status"),
    "cobros": ("all", "id", "subscription_id", "status"),
    "pagos": ("all", "id", "charge_id", "status"),
}
PERSONAL_FILTER_FIELDS = {"all", "rut", "name", "last_name", "email", "phone", "client"}


@dataclass(frozen=True)
class ExportFilters:
    query: str | None = None
    filter_field: str = "all"
    status: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    amount_min: float | None = None
    amount_max: float | None = None

    def audit(self) -> dict[str, Any]:
        """Filtros para la auditoria. El texto de busqueda solo se guarda si el campo no puede ser un dato personal."""
        out: dict[str, Any] = {}
        if self.query and self.query.strip():
            out["filter_field"] = self.filter_field
            if self.filter_field in PERSONAL_FILTER_FIELDS:
                out["query_len"] = len(self.query.strip())
            else:
                out["query"] = self.query.strip()
        for name in ("status", "amount_min", "amount_max"):
            if getattr(self, name) is not None:
                out[name] = getattr(self, name)
        for name in ("date_from", "date_to"):
            if getattr(self, name) is not None:
                out[name] = getattr(self, name).isoformat()
        return out


@dataclass(frozen=True)
class ChannelSpec:
    provider: str  # virtualpos | toku | payku | tch
    permission: str  # permiso de VISTA del recurso (el mismo del listado)
    sources: tuple[str, ...]  # valores de `canal` que cubre
    build: Callable[[tuple[str, ...], ExportFilters, bool], Any]
    post: Callable[[dict[str, Any]], dict[str, Any]] | None = field(default=None)


# ----------------------------------------------------------------------------- helpers de filtro


def rut_key(value: Any) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isdigit() or ch == "K")


def _rut_key_sql(col: Any) -> Any:
    return func.regexp_replace(func.upper(func.coalesce(col, "")), "[^0-9K]", "", "g")


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _ilike(col: Any, needle: str) -> Any:
    return cast(col, String).ilike(f"%{_escape(needle.strip())}%", escape="\\")


def _rut_match(col: Any, needle: str) -> Any:
    key = rut_key(needle)
    return _rut_key_sql(col).like(f"%{key}%") if key else false()


def _search(filters: ExportFilters, fields: dict[str, Any], rut_field: str | None = None) -> Any | None:
    """Busqueda del listado: `all` = cualquier campo (o RUT normalizado); un campo concreto si se indica."""
    needle = (filters.query or "").strip()
    if not needle:
        return None
    if filters.filter_field == "all":
        parts = [_rut_match(fields[rut_field], needle)] if rut_field else []
        parts += [_ilike(col, needle) for name, col in fields.items() if name != rut_field]
        return or_(*parts)
    col = fields[filters.filter_field]
    return _rut_match(col, needle) if filters.filter_field == rut_field else _ilike(col, needle)


def _iso_date(col: Any) -> Any:
    return case((cast(col, String).op("~")(r"^\d{4}-\d{2}-\d{2}"), func.substr(cast(col, String), 1, 10)), else_=None)


def _numeric(col: Any) -> Any:
    text = cast(col, String)
    return case((text.op("~")(r"^\s*-?\d+(\.\d+)?\s*$"), cast(text, Numeric)), else_=None)


def _common_conditions(filters: ExportFilters, status_col: Any, date_col: Any | None, amount_col: Any | None) -> list[Any]:
    conds: list[Any] = []
    if filters.status and filters.status.strip():
        conds.append(func.lower(cast(status_col, String)) == filters.status.strip().lower())
    if date_col is not None:
        if filters.date_from is not None:
            conds.append(_iso_date(date_col) >= filters.date_from.isoformat())
        if filters.date_to is not None:
            conds.append(_iso_date(date_col) <= filters.date_to.isoformat())
    if amount_col is not None:
        if filters.amount_min is not None:
            conds.append(_numeric(amount_col) >= filters.amount_min)
        if filters.amount_max is not None:
            conds.append(_numeric(amount_col) <= filters.amount_max)
    return conds


def _pii(expr: Any, include_pii: bool) -> Any:
    return expr if include_pii else null()


def _name(first: Any, last: Any) -> Any:
    return func.concat_ws(" ", first, last)


# ----------------------------------------------------------------------------- clientes


def _clients_cclient(sources: tuple[str, ...], f: ExportFilters, pii: bool, label: str) -> Any:
    name = _name(CClient.first_name, CClient.last_name)
    search = _search(f, {
        "rut": CClient.social_id, "name": name, "last_name": func.coalesce(CClient.last_name, ""), "platform": literal(label),
        "email": CClient.email, "phone": CClient.phone_number,
    }, "rut")
    stmt = select(
        CClient.source.label("channel"), CClient.external_id.label("external_id"), CClient.status.label("status"),
        CClient.provider_created_at.label("signup_date"), _pii(CClient.social_id, pii).label("rut"),
        _pii(name, pii).label("name"), _pii(CClient.email, pii).label("email"),
        _pii(CClient.phone_number, pii).label("phone"), null().label("address"),
    ).where(CClient.source.in_(sources), CClient.social_id.isnot(None))
    conds = _common_conditions(f, CClient.status, CClient.provider_created_at, None)
    if search is not None:
        conds.append(search)
    return stmt.where(*conds).order_by(CClient.source, CClient.external_id)


def _clients_tch(_sources: tuple[str, ...], f: ExportFilters, pii: bool) -> Any:
    name = _name(TchClient.name, TchClient.last_name)
    search = _search(f, {
        "rut": TchClient.rut, "name": name, "last_name": func.coalesce(TchClient.last_name, ""), "platform": literal("TCH"),
        "email": TchClient.email, "phone": TchClient.phone,
    }, "rut")
    address = func.concat_ws(", ", TchClient.address, TchClient.district, TchClient.city)
    stmt = select(
        literal("tch").label("channel"), cast(TchClient.id, String).label("external_id"), null().label("status"),
        func.substr(cast(TchClient.created_at, String), 1, 10).label("signup_date"), _pii(TchClient.rut, pii).label("rut"),
        _pii(name, pii).label("name"), _pii(TchClient.email, pii).label("email"),
        _pii(TchClient.phone, pii).label("phone"), _pii(address, pii).label("address"),
    )
    conds = []
    if f.status and f.status.strip():
        conds.append(false())  # los clientes TCH no tienen estado propio
    if f.date_from is not None:
        conds.append(func.substr(cast(TchClient.created_at, String), 1, 10) >= f.date_from.isoformat())
    if f.date_to is not None:
        conds.append(func.substr(cast(TchClient.created_at, String), 1, 10) <= f.date_to.isoformat())
    if search is not None:
        conds.append(search)
    return stmt.where(*conds).order_by(TchClient.id)


# ----------------------------------------------------------------------------- suscripciones


def _secondary_status(status: str, last_paid: str | None) -> str:
    """Misma regla que la vista general de suscripciones (staging._secondary_status)."""
    if str(status).lower() not in ACTIVE_STATUSES:
        return "inactiva"
    if not last_paid:
        return "Nunca Cobrado"
    try:
        paid_date = date.fromisoformat(str(last_paid)[:10])
    except (ValueError, TypeError):
        return "Nunca Cobrado"
    return "incobrable" if paid_date <= datetime.now(tz=timezone.utc).date() - timedelta(days=182) else "cobrable"


def _subs_post(row: dict[str, Any]) -> dict[str, Any]:
    row["secondary_status"] = _secondary_status(row.get("status") or "", row.get("last_charge"))
    return row


def _subs_search(f: ExportFilters, id_col: Any, client_name: Any, rut_col: Any, platform: str, status_col: Any) -> Any | None:
    return _search(f, {"id": id_col, "rut": rut_col, "client": client_name, "platform": literal(platform), "status": status_col}, "rut")


def _subs_cclient(sources: tuple[str, ...], f: ExportFilters, pii: bool, platform: str) -> Any:
    client = CClient
    rut_col = func.coalesce(CSub.client_social_id, client.social_id)
    client_name = _name(client.first_name, client.last_name)
    last_paid = (
        select(func.max(CCharge.charge_date))
        .where(CCharge.source == CSub.source, CCharge.subscription_external_id == CSub.external_id,
               func.lower(CCharge.status).in_(PAID_STATUSES))
        .correlate(CSub).scalar_subquery()
    )
    excluded = or_(
        and_(CSub.source.like("virtualpos%"), func.upper(func.coalesce(CSub.status, "")) == "SUSCRIPCION_FALLIDA"),
    )
    stmt = (
        select(
            CSub.source.label("channel"), CSub.external_id.label("subscription_id"), CSub.status.label("status"),
            CSub.suscription_date.label("start_date"), CSub.canceled_at.label("end_date"), CSub.amount.label("amount"),
            CSub.currency.label("currency"), last_paid.label("last_charge"),
            _pii(rut_col, pii).label("rut"), _pii(client_name, pii).label("name"),
        )
        .select_from(CSub)
        .outerjoin(client, and_(client.source == CSub.source, client.external_id == CSub.client_external_id))
        .where(CSub.source.in_(sources), ~excluded)
    )
    conds = _common_conditions(f, CSub.status, CSub.suscription_date, CSub.amount)
    search = _subs_search(f, CSub.external_id, client_name, rut_col, platform, CSub.status)
    if search is not None:
        conds.append(search)
    return stmt.where(*conds).order_by(CSub.source, CSub.external_id)


def _subs_payku(sources: tuple[str, ...], f: ExportFilters, pii: bool) -> Any:
    client = CClient
    rut_col = func.coalesce(CSub.client_social_id, client.social_id)
    client_name = _name(client.first_name, client.last_name)
    last_paid = (
        select(func.max(PkTx.created_at_api))
        .where(PkTx.subscription_id == CSub.external_id, func.lower(PkTx.status) == "success")
        .correlate(CSub).scalar_subquery()
    )
    stmt = (
        select(
            CSub.source.label("channel"), CSub.external_id.label("subscription_id"), CSub.status.label("status"),
            CSub.suscription_date.label("start_date"), CSub.canceled_at.label("end_date"), CSub.amount.label("amount"),
            CSub.currency.label("currency"), last_paid.label("last_charge"),
            _pii(rut_col, pii).label("rut"), _pii(client_name, pii).label("name"),
        )
        .select_from(CSub)
        .outerjoin(client, and_(client.source == CSub.source, client.external_id == CSub.client_external_id))
        .where(CSub.source.in_(sources), func.upper(func.coalesce(CSub.status, "")) != "REGISTER")
    )
    conds = _common_conditions(f, CSub.status, CSub.suscription_date, CSub.amount)
    search = _subs_search(f, CSub.external_id, client_name, rut_col, "Payku", CSub.status)
    if search is not None:
        conds.append(search)
    return stmt.where(*conds).order_by(CSub.source, CSub.external_id)


def _subs_tch(_sources: tuple[str, ...], f: ExportFilters, pii: bool) -> Any:
    client_name = _name(TchClient.name, TchClient.last_name)
    amount = func.coalesce(func.nullif(TchSubscription.peso_equivalent, ""), TchSubscription.amount)
    last_paid = (
        select(func.max(TchTransaction.charge_date))
        .where(TchTransaction.file_number == TchSubscription.file_number, func.lower(TchTransaction.status).in_(PAID_STATUSES))
        .correlate(TchSubscription).scalar_subquery()
    )
    ended = func.coalesce(TchSubscription.deletion_date, TchSubscription.rejection_date)
    stmt = (
        select(
            literal("tch").label("channel"), cast(TchSubscription.file_number, String).label("subscription_id"),
            TchSubscription.status.label("status"), TchSubscription.activation_date.label("start_date"),
            ended.label("end_date"), amount.label("amount"), literal("CLP").label("currency"), last_paid.label("last_charge"),
            _pii(TchSubscription.client_rut, pii).label("rut"), _pii(client_name, pii).label("name"),
        )
        .select_from(TchSubscription)
        .outerjoin(TchClient, _rut_key_sql(TchSubscription.client_rut) == _rut_key_sql(TchClient.rut))
        .where(func.upper(TchSubscription.status) != "RECHAZADA")
    )
    conds = _common_conditions(f, TchSubscription.status, TchSubscription.activation_date, amount)
    search = _subs_search(f, cast(TchSubscription.file_number, String), client_name, TchSubscription.client_rut, "TCH",
                          TchSubscription.status)
    if search is not None:
        conds.append(search)
    return stmt.where(*conds).order_by(TchSubscription.file_number)


# ----------------------------------------------------------------------------- cobros


def _charges_cclient(sources: tuple[str, ...], f: ExportFilters, pii: bool) -> Any:
    cols = [
        CCharge.source.label("channel"), CCharge.external_id.label("charge_id"),
        CCharge.subscription_external_id.label("subscription_id"), CCharge.status.label("status"),
        CCharge.charge_date.label("charge_date"), null().label("period"), CCharge.amount.label("amount"),
        CCharge.currency.label("currency"), null().label("rejection_reason"),
    ]
    if pii:
        sub, cli = aliased(CSub), aliased(CClient)
        stmt = (
            select(*cols, func.coalesce(cli.social_id, sub.client_social_id).label("rut"),
                   _name(cli.first_name, cli.last_name).label("name"))
            .select_from(CCharge)
            .outerjoin(sub, and_(sub.source == CCharge.source, sub.external_id == CCharge.subscription_external_id))
            .outerjoin(cli, and_(cli.source == CCharge.source,
                                 cli.external_id == func.coalesce(CCharge.client_external_id, sub.client_external_id)))
        )
    else:
        stmt = select(*cols, null().label("rut"), null().label("name"))
    search = _search(f, {"id": CCharge.external_id, "subscription_id": CCharge.subscription_external_id, "status": CCharge.status})
    conds = [CCharge.source.in_(sources), *_common_conditions(f, CCharge.status, CCharge.charge_date, CCharge.amount)]
    if search is not None:
        conds.append(search)
    return stmt.where(*conds).order_by(CCharge.source, CCharge.external_id)


def _charges_tch(_sources: tuple[str, ...], f: ExportFilters, pii: bool) -> Any:
    t = TchTransaction
    cols = [
        literal("tch").label("channel"), cast(t.id, String).label("charge_id"), cast(t.file_number, String).label("subscription_id"),
        t.status.label("status"), t.charge_date.label("charge_date"), t.period.label("period"), t.amount.label("amount"),
        literal("CLP").label("currency"), t.rejection_reason.label("rejection_reason"),
    ]
    if pii:
        stmt = (
            select(*cols, TchSubscription.client_rut.label("rut"), _name(TchClient.name, TchClient.last_name).label("name"))
            .select_from(t)
            .outerjoin(TchSubscription, TchSubscription.file_number == t.file_number)
            .outerjoin(TchClient, TchClient.rut == TchSubscription.client_rut)
        )
    else:
        stmt = select(*cols, null().label("rut"), null().label("name"))
    search = _search(f, {"id": cast(t.id, String), "subscription_id": cast(t.file_number, String), "status": t.status})
    conds = _common_conditions(f, t.status, t.charge_date, t.amount)
    if search is not None:
        conds.append(search)
    return stmt.where(*conds).order_by(t.id)


# ----------------------------------------------------------------------------- pagos


def _payments_cclient(sources: tuple[str, ...], f: ExportFilters, pii: bool) -> Any:
    cols = [
        CPayment.source.label("channel"), CPayment.external_id.label("payment_id"), CPayment.charge_external_id.label("charge_id"),
        CPayment.status.label("status"), CPayment.payment_date.label("payment_date"), CPayment.amount.label("amount"),
        CPayment.currency.label("currency"),
    ]
    if pii:
        cli = aliased(CClient)
        rut = func.coalesce(cli.social_id, CPayment.raw_payload["client"]["social_id"].astext)
        stmt = (
            select(*cols, rut.label("rut"), _name(cli.first_name, cli.last_name).label("name"))
            .select_from(CPayment)
            .outerjoin(cli, and_(cli.source == CPayment.source, cli.external_id == CPayment.client_external_id))
        )
    else:
        stmt = select(*cols, null().label("rut"), null().label("name"))
    search = _search(f, {"id": CPayment.external_id, "charge_id": CPayment.charge_external_id, "status": CPayment.status})
    conds = [CPayment.source.in_(sources), *_common_conditions(f, CPayment.status, CPayment.payment_date, CPayment.amount)]
    if search is not None:
        conds.append(search)
    return stmt.where(*conds).order_by(CPayment.source, CPayment.external_id)


# ----------------------------------------------------------------------------- registro de canales por entidad


def _vp(builder: Callable[..., Any], *extra: Any) -> Callable[[tuple[str, ...], ExportFilters, bool], Any]:
    return lambda sources, f, pii: builder(sources, f, pii, *extra)


ENTITY_SPECS: dict[str, tuple[ChannelSpec, ...]] = {
    "clientes": (
        ChannelSpec("virtualpos", "virtualpos.clients.view", ("virtualpos1", "virtualpos2"), _vp(_clients_cclient, "VirtualPOS")),
        ChannelSpec("toku", "toku.customers.view", ("toku",), _vp(_clients_cclient, "Toku")),
        ChannelSpec("payku", "payku.clients.view", ("payku",), _vp(_clients_cclient, "Payku")),
        ChannelSpec("tch", "tch.clientes.view", ("tch",), _clients_tch),
    ),
    "suscripciones": (
        ChannelSpec("virtualpos", "virtualpos.subscriptions.view", ("virtualpos1", "virtualpos2"),
                    _vp(_subs_cclient, "VirtualPOS"), _subs_post),
        ChannelSpec("toku", "toku.subscriptions.view", ("toku",), _vp(_subs_cclient, "Toku"), _subs_post),
        ChannelSpec("payku", "payku.subscriptions.view", ("payku",), _subs_payku, _subs_post),
        ChannelSpec("tch", "tch.suscripciones.view", ("tch",), _subs_tch, _subs_post),
    ),
    "cobros": (
        ChannelSpec("virtualpos", "virtualpos.charges.view", ("virtualpos1", "virtualpos2"), _charges_cclient),
        ChannelSpec("toku", "toku.invoices.view", ("toku",), _charges_cclient),
        ChannelSpec("tch", "tch.transacciones.view", ("tch",), _charges_tch),
    ),
    "pagos": (
        ChannelSpec("virtualpos", "virtualpos.payments.view", ("virtualpos1", "virtualpos2"), _payments_cclient),
        ChannelSpec("toku", "toku.transactions.view", ("toku",), _payments_cclient),
        ChannelSpec("payku", "payku.transactions.view", ("payku",), _payments_cclient),
    ),
}


def entity_channels(entity: str) -> tuple[str, ...]:
    """Canales (valor de la columna `canal`) que cubre una entidad."""
    return tuple(src for spec in ENTITY_SPECS[entity] for src in spec.sources)


def select_specs(entity: str, channel: str | None, permissions: set[str]) -> tuple[list[tuple[ChannelSpec, tuple[str, ...]]], bool]:
    """Resuelve (spec, fuentes) permitidas. Devuelve (lista, hubo_canal_denegado).

    `canal` puede ser un canal concreto (`virtualpos1`, `toku`...), `virtualpos` (ambas cuentas) o None (todos).
    Un canal pedido explicitamente pero sin permiso de vista se reporta como denegado (403 en la ruta).
    """
    wanted: list[tuple[ChannelSpec, tuple[str, ...]]] = []
    denied = False
    for spec in ENTITY_SPECS[entity]:
        sources = spec.sources
        if channel is not None:
            if channel == spec.provider:
                pass
            elif channel in spec.sources:
                sources = (channel,)
            else:
                continue
        if spec.permission in permissions:
            wanted.append((spec, sources))
        elif channel is not None:
            denied = True
    return wanted, denied


# ----------------------------------------------------------------------------- ejecucion


def count_rows(session: Session, stmt: Any) -> int:
    return session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


def page_plan(counts: list[int], offset: int, limit: int) -> list[tuple[int, int]]:
    """Reparte (offset, limit) globales entre canales concatenados: [(offset_local, limit_local)] por canal."""
    plan: list[tuple[int, int]] = []
    skip, remaining = offset, limit
    for total in counts:
        if skip >= total:
            skip -= total
            plan.append((0, 0))
            continue
        take = min(remaining, total - skip)
        plan.append((skip, take))
        remaining -= take
        skip = 0
    return plan


def iter_rows(
    session_factory: Callable[[], Session],
    items: list[tuple[ChannelSpec, tuple[str, ...]]],
    filters: ExportFilters,
    include_pii: bool,
    *,
    paged: tuple[int, int] | None = None,
) -> Iterator[dict[str, Any]]:
    """Genera las filas canal por canal con cursor del lado del servidor (`stream_results` + `yield_per`)."""
    session = session_factory()
    try:
        statements = [spec.build(sources, filters, include_pii) for spec, sources in items]
        plan: list[tuple[int, int] | None] = [None] * len(statements)
        if paged is not None:
            counts = [count_rows(session, spec.build(sources, filters, False)) for spec, sources in items]
            plan = list(page_plan(counts, *paged))
        for (spec, _sources), stmt, window in zip(items, statements, plan, strict=True):
            if window is not None:
                if window[1] <= 0:
                    continue
                stmt = stmt.offset(window[0]).limit(window[1])
            result = session.execute(stmt.execution_options(stream_results=True, yield_per=YIELD_PER))
            try:
                for row in result.mappings():
                    data = dict(row)
                    yield spec.post(data) if spec.post else data
            finally:
                result.close()
    finally:
        session.close()


def total_rows(session: Session, items: list[tuple[ChannelSpec, tuple[str, ...]]], filters: ExportFilters) -> int:
    return sum(count_rows(session, spec.build(sources, filters, False)) for spec, sources in items)
