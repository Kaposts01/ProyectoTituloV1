import hashlib
import logging
import re
import tempfile
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
)
from sqlalchemy import Numeric, case, cast, func, literal, select
from sqlalchemy.orm import Session

from app.api.v1.routes.staging import _channel_alerts
from app.core.security import require_csrf, require_permissions, require_role
from app.db.session import SessionLocal
from app.models.etl_run import EtlRun
from app.models.tch import (
    TchClient,
    TchMonthlyCollection,
    TchSubscription,
    TchTransaction,
)
from app.scheduler.run_lock import ActiveRunError, start_exclusive_run
from app.services import rejected_month, tch_report_registry
from app.services.account_masking import mask_account_number
from app.services.channel_churn import closed_month_churn
from app.services.charge_stats import rejected_month_kpi

router = APIRouter()
logger = logging.getLogger(__name__)

_TCH_PAID = {"aceptada", "aceptado", "pagada", "pagado", "cobrada", "cobrado", "aprobada", "aprobado"}
_MAX_REPORT_BYTES = 250 * 1024 * 1024
_MAX_REPORT_ARCHIVE_ENTRIES = 1_000
_MAX_REPORT_UNCOMPRESSED_BYTES = 500 * 1024 * 1024


def _get_db() -> Session:
    return SessionLocal()


def _import_report_background(run_id: str, report_path: str, original_name: str | None = None) -> None:
    """Processes the isolated upload and removes it whether the ETL succeeds or fails."""
    try:
        from scripts import etl_tch

        etl_tch.import_incremental_file(Path(report_path), uuid.UUID(run_id), display_name=original_name)
    except Exception:
        logger.exception("La importación del reporte TCH falló (run_id=%s)", run_id)
    finally:
        Path(report_path).unlink(missing_ok=True)


def _validate_xlsx_archive(path: Path) -> None:
    """Reject malformed or disproportionately expanded XLSX archives before ETL."""
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > _MAX_REPORT_ARCHIVE_ENTRIES:
                raise ValueError("El reporte contiene demasiados archivos internos.")
            if sum(entry.file_size for entry in entries) > _MAX_REPORT_UNCOMPRESSED_BYTES:
                raise ValueError("El reporte supera el tamaño descomprimido permitido.")
            names = {entry.filename for entry in entries}
            if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                raise ValueError("El archivo no contiene una estructura XLSX válida.")
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ValueError("El archivo no es un reporte XLSX válido.") from exc


def _tch_last_paid_map(db: Session, file_numbers: list[int]) -> dict[int, str]:
    if not file_numbers:
        return {}
    rows = db.execute(
        select(TchTransaction.file_number, func.max(TchTransaction.charge_date).label("last_date"))
        .where(TchTransaction.file_number.in_(file_numbers), func.lower(TchTransaction.status).in_(_TCH_PAID))
        .group_by(TchTransaction.file_number)
    ).all()
    return {r.file_number: r.last_date for r in rows if r.last_date}


def _tch_secondary(status: str, last_paid: str | None) -> str:
    if status != "VIGENTE":
        return "inactiva"
    if not last_paid:
        return "Nunca Cobrado"
    try:
        paid_date = date.fromisoformat(last_paid[:10])
        return "incobrable" if paid_date <= datetime.now(tz=timezone.utc).date() - timedelta(days=182) else "cobrable"
    except (ValueError, TypeError):
        return "Nunca Cobrado"


def _serialize_subscription(s: TchSubscription, last_paid: str | None = None) -> dict:
    return {
        "id": str(s.id),
        "numero_ficha": s.file_number,
        "numero_mandato": s.mandate_number,
        "cliente_rut": s.client_rut,
        "banco_nombre": s.bank_name,
        "tipo_mandato": s.mandate_type,
        "tipo_cuenta": s.account_type,
        # d199 R1: la cuenta bancaria solo sale enmascarada (ultimos 4 digitos); la base la guarda completa.
        "numero_cuenta": mask_account_number(s.account_number),
        "origen": s.origin,
        "centro_costo": s.cost_center,
        "captador": s.recruiter,
        "monto": s.amount,
        "equivalente_pesos": s.peso_equivalent,
        "fecha_activacion": s.activation_date,
        "fecha_ingreso": s.entry_date,
        "fecha_alta_efectiva": effective_activation_value(s),
        "fecha_rechazo": s.rejection_date,
        "fecha_eliminacion": s.deletion_date,
        "fecha_fin": s.deletion_date or s.rejection_date,
        "razon_baja": s.cancellation_reason,
        # Marca para revision (no se corrige): la fecha de baja es anterior a la fecha de alta efectiva.
        "baja_antes_del_alta": cancelled_before_activation(s),
        "estado": s.status,
        "last_paid_date": last_paid,
        "secondary_status": _tch_secondary(s.status, last_paid),
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _serialize_client(c: TchClient) -> dict:
    return {
        "id": str(c.id),
        "rut": c.rut,
        "nombre": c.name,
        "apellido": c.last_name,
        "fecha_nacimiento": c.birth_date,
        "profesion": c.profession,
        "tipo_persona": c.person_type,
        "tipo_socio": c.member_type,
        "telefono": c.phone,
        "email": c.email,
        "direccion": c.address,
        "comuna": c.district,
        "ciudad": c.city,
    }


def _serialize_transaction(t: TchTransaction) -> dict:
    return {
        "id": str(t.id),
        "numero_ficha": t.file_number,
        "periodo": t.period,
        "numero_cuota": t.installment_number,
        "total_cuotas": t.total_installments,
        "monto": t.amount,
        "fecha_cargo": t.charge_date,
        "tipo_transaccion": t.transaction_type,
        "estado": t.status,
        "entidad_recaudadora": t.collecting_entity,
        "razon_rechazo": t.rejection_reason,
        "archivo_origen": t.source_file,
    }


def _monthly_statuses(rows: list[tuple[str, str, int, int | float]]) -> list[dict]:
    entries = []
    for period, status, count, amount in rows:
        year, month = period.split("-", 1)
        entries.append(
            {
                "year": int(year),
                "month": int(month),
                "status": status,
                "count": count,
                "amount": int(amount or 0),
            }
        )
    return entries


def _rejected_current_month(monthly_transactions: list[dict]) -> dict:
    """Cargos RECHAZADA del mes actual (hora Chile) con la definicion unica de charge_stats (UI-29)."""
    return rejected_month_kpi(
        (
            {**entry, "date": f"{int(entry['year']):04d}-{int(entry['month']):02d}"}
            for entry in monthly_transactions
            if entry.get("year") and entry.get("month")
        ),
        rejected_month.now_chile().date(),
        "tch",
    )


def _parse_tch_amount(value: object) -> float:
    """Monto TCH (String(20)) a float; '$', '.', ',' y basura no numerica no deben dar 500."""
    text = str(value or "").strip().replace("$", "").replace(" ", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        pass
    # Formato chileno '1.234.567' o '1.234,5': '.' miles, ',' decimal.
    try:
        return float(text.replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def _monthly_collection_kpis(controls: list[TchMonthlyCollection]) -> dict | None:
    """Recaudo aceptado del ultimo periodo con transacciones aceptadas (reportes Excel)."""
    with_accepted = [c for c in controls if (c.accepted_count or 0) > 0]
    if not with_accepted:
        return None
    latest = max(with_accepted, key=lambda c: c.period)
    mrr = _parse_tch_amount(latest.accepted_amount)
    active_clients = int(latest.accepted_count)
    return {
        "period": latest.period,
        "mrr": round(mrr, 0),
        "active_clients": active_clients,  # alias heredado de accepted_transactions (no son clientes distintos)
        "accepted_transactions": active_clients,
        "arpu": round(mrr / active_clients, 0),
        "rejected_count": int(latest.rejected_count or 0),
        "rejected_amount": round(_parse_tch_amount(latest.rejected_amount), 0),
    }


_ISO_DATE = r"^\d{4}-\d{2}-\d{2}$"
# Orden de respaldo de la fecha de alta. "Ingreso" (ANTECEDENTES Y ESTADO MANDATOS) es el ingreso del mandato a TCH:
# la primera fecha del ciclo (ingreso -> entrega al banco -> activacion -> primer cobro) y la mas lejana de la
# activacion, pero la unica llena en todas las fichas. Va AL FINAL: solo da fecha a las fichas que no tienen ninguna
# de las otras y no mueve de mes ninguna alta que ya tenia fecha.
_ACTIVATION_FALLBACKS = (
    ("fecha_activacion", TchSubscription.activation_date),
    ("fecha_primer_cobro", TchSubscription.first_charge_date),
    ("fecha_entrega_banco", TchSubscription.bank_delivery_date),
    ("fecha_ingreso", TchSubscription.entry_date),
)
ACTIVATION_SOURCE_NOTE = (
    "Desde julio de 2025 el reporte TCH ya no trae la fecha de activación del mandato. Para esas altas se usa la "
    "fecha del primer cobro del mandato actual; si falta, la de entrega al banco, y si falta, la de ingreso del mandato."
)


def effective_activation_value(subscription: TchSubscription) -> str | None:
    """La misma cadena de `_effective_activation_date` sobre una ficha ya cargada (detalle y listado)."""
    for _, column in _ACTIVATION_FALLBACKS:
        value = getattr(subscription, column.key)
        if value and re.fullmatch(_ISO_DATE, value):
            return value
    return None


def cancelled_before_activation(subscription: TchSubscription) -> bool:
    """Baja anterior al alta efectiva: dato inconsistente de la fuente. Solo se marca para revision, no se corrige."""
    signup = effective_activation_value(subscription)
    deletion = subscription.deletion_date
    return bool(signup and deletion and re.fullmatch(_ISO_DATE, deletion) and deletion < signup)


def _effective_activation_date():
    """Fecha del alta (ISO): activacion; si falta, primer cobro; si falta, entrega al banco; si falta, ingreso del
    mandato; NULL sin ninguna."""
    return case(
        *((column.op("~")(_ISO_DATE), column) for _, column in _ACTIVATION_FALLBACKS),
        else_=None,
    )


def _activation_sources(db) -> dict:
    """Cuantas altas salen de cada fecha (TCH-PAR-17): explica el corte de la fuente en el dashboard."""
    source = case(
        *((column.op("~")(_ISO_DATE), literal(name)) for name, column in _ACTIVATION_FALLBACKS),
        else_=literal("sin_fecha"),
    )
    counts = dict(db.execute(select(source, func.count()).select_from(TchSubscription).group_by(source)).all())
    result: dict = {name: int(counts.get(name, 0)) for name, _ in _ACTIVATION_FALLBACKS}
    result["sin_fecha"] = int(counts.get("sin_fecha", 0))
    result["nota"] = ACTIVATION_SOURCE_NOTE
    return result


@router.get("/summary", dependencies=[Depends(require_permissions("tch.dashboard.view"))], tags=["TCH"])
def tch_summary() -> dict:
    """KPIs generales del canal TCH."""
    db = _get_db()
    try:
        total_active = db.scalar(
            select(func.count()).select_from(TchSubscription).where(TchSubscription.status == "VIGENTE")
        ) or 0
        total_deleted = db.scalar(
            select(func.count()).select_from(TchSubscription).where(TchSubscription.status == "ELIMINADA")
        ) or 0
        controls = db.scalars(
            select(TchMonthlyCollection).order_by(TchMonthlyCollection.period)
        ).all()
        numeric_amount = case(
            (TchTransaction.amount.op("~")(r"^\d+(\.\d+)?$"), cast(TchTransaction.amount, Numeric)),
            else_=0,
        )
        subscription_amount = case(
            (TchSubscription.peso_equivalent.op("~")(r"^\d+(\.\d+)?$"), cast(TchSubscription.peso_equivalent, Numeric)),
            else_=0,
        )
        # TCH-PAR-17: desde jul-2025 el reporte ya no trae "Fecha Activacion". Para no perder las altas se usa, en
        # orden, la fecha de activacion, la del primer cobro del mandato actual y la de entrega al banco.
        activation_effective = _effective_activation_date()
        activation_period = func.substring(activation_effective, 1, 7)
        transactions_source = "recaudacion_mensual" if controls else "transacciones"
        if controls:
            total_accepted = sum(control.accepted_count for control in controls)
            total_rejected = sum(control.rejected_count for control in controls)
            total_transactions = total_accepted + total_rejected
            monthly_transactions = [
                {
                    "year": int(control.period[:4]),
                    "month": int(control.period[5:]),
                    "status": status,
                    "count": count,
                    "amount": int(amount),
                }
                for control in controls
                for status, count, amount in (
                    ("ACEPTADA", control.accepted_count, _parse_tch_amount(control.accepted_amount)),
                    ("RECHAZADA", control.rejected_count, _parse_tch_amount(control.rejected_amount)),
                )
            ]
        else:
            total_transactions = db.scalar(select(func.count()).select_from(TchTransaction)) or 0
            total_accepted = db.scalar(
                select(func.count()).select_from(TchTransaction).where(TchTransaction.status == "ACEPTADA")
            ) or 0
            total_rejected = db.scalar(
                select(func.count()).select_from(TchTransaction).where(TchTransaction.status == "RECHAZADA")
            ) or 0
            monthly_transactions = _monthly_statuses(
                db.execute(
                    select(
                        TchTransaction.period,
                        TchTransaction.status,
                        func.count(),
                        func.coalesce(func.sum(numeric_amount), 0),
                    )
                    .where(TchTransaction.period.op("~")(r"^\d{4}-\d{2}$"))
                    .group_by(TchTransaction.period, TchTransaction.status)
                    .order_by(TchTransaction.period, TchTransaction.status)
                ).all()
            )
        rejection_rate = round(100 * total_rejected / total_transactions, 1) if total_transactions else None
        monthly_activations = _monthly_statuses(
            db.execute(
                select(
                    activation_period,
                    literal("VIGENTE"),
                    func.count(),
                    func.coalesce(func.sum(subscription_amount), 0),
                )
                .where(activation_effective.isnot(None))
                .group_by(activation_period)
                .order_by(activation_period)
            ).all()
        )
        activation_sources = _activation_sources(db)
        deletion_period = func.substring(TchSubscription.deletion_date, 1, 7)
        monthly_cancellations = _monthly_statuses(
            db.execute(
                select(
                    deletion_period,
                    literal("ELIMINADA"),
                    func.count(),
                    func.coalesce(func.sum(subscription_amount), 0),
                )
                .where(TchSubscription.deletion_date.op("~")(r"^\d{4}-\d{2}-\d{2}$"))
                .group_by(deletion_period)
                .order_by(deletion_period)
            ).all()
        )
        lifecycle_months = sorted({(entry["year"], entry["month"]) for entry in monthly_activations + monthly_cancellations})
        active_subs_monthly: list[dict] = []
        churn_rate_monthly: list[dict] = []
        active_count = 0
        for year, month in lifecycle_months:
            activated = sum(entry["count"] for entry in monthly_activations if (entry["year"], entry["month"]) == (year, month))
            cancelled = sum(entry["count"] for entry in monthly_cancellations if (entry["year"], entry["month"]) == (year, month))
            churn_rate_monthly.append({
                "year": year,
                "month": month,
                "rate": round(100 * cancelled / active_count, 1) if active_count else 0.0,
            })
            active_count = max(0, active_count + activated - cancelled)
            active_subs_monthly.append({"year": year, "month": month, "count": active_count})
        years = sorted(
            {entry["year"] for entry in monthly_transactions + monthly_activations + monthly_cancellations},
            reverse=True,
        )

        # ── KPIs ──────────────────────────────────────────────────────────
        mrr = float(
            db.scalar(
                select(func.coalesce(func.sum(subscription_amount), 0))
                .select_from(TchSubscription)
                .where(TchSubscription.status == "VIGENTE")
            ) or 0
        )
        active_clients = db.scalar(
            select(func.count(TchSubscription.client_rut.distinct()))
            .select_from(TchSubscription)
            .where(TchSubscription.status == "VIGENTE")
            .where(TchSubscription.client_rut.isnot(None))
        ) or 0
        cancelled_amount = float(
            db.scalar(
                select(func.coalesce(func.sum(subscription_amount), 0))
                .select_from(TchSubscription)
                .where(TchSubscription.status == "ELIMINADA")
            ) or 0
        )
        if controls:
            transactions_amount = int(sum(_parse_tch_amount(c.accepted_amount) + _parse_tch_amount(c.rejected_amount) for c in controls))
        else:
            transactions_amount = int(
                db.scalar(
                    select(func.coalesce(func.sum(numeric_amount), 0)).select_from(TchTransaction)
                ) or 0
            )
        arpu = round(mrr / active_clients, 0) if active_clients else None
        # Churn unificado (DEC-37/D31, L6-DASH): bajas / socios al cierre del mes anterior del ULTIMO MES CERRADO con
        # dato (Chile), desde la serie mensual. None sin base (0 vigentes) o sin ningun mes cerrado en la serie.
        churn_rate, _, churn_window_label = closed_month_churn(
            churn_rate_monthly, has_base=bool(total_active)
        )
        ltv = round(arpu / (churn_rate / 100), 0) if arpu is not None and churn_rate else None

        latest_run = db.scalar(
            select(EtlRun)
            .where(EtlRun.channels_processed.any("tch"))
            .order_by(EtlRun.started_at.desc())
            .limit(1)
        )

        tch_kpis = {
            "mrr": round(mrr, 0),
            "arpu": arpu,
            "active_clients": active_clients,
            "active_subscribers": total_active,
            "churn_rate": churn_rate,
            "churn_window_label": churn_window_label,
            "ltv": ltv,
            "rejected_charges": _rejected_current_month(monthly_transactions),
            "recaudo_mensual": _monthly_collection_kpis(controls),
            "source_note": "Fuente: reportes Excel oficiales",
        }
        return {
            "suscripciones": {
                "vigentes": total_active,
                "eliminadas": total_deleted,
                "total": total_active + total_deleted,
                "monto_vigentes": round(mrr, 0),
                "monto_eliminadas": round(cancelled_amount, 0),
                "monto_total": round(mrr + cancelled_amount, 0),
            },
            "transacciones": {
                "total": total_transactions,
                "aceptadas": total_accepted,
                "rechazadas": total_rejected,
                "tasa_rechazo_pct": rejection_rate,
                "monto": transactions_amount,
            },
            "kpis": tch_kpis,
            "churn_window_label": churn_window_label,
            "years": years,
            "transacciones_mensuales": monthly_transactions,
            "transacciones_fuente": transactions_source,
            "activaciones_mensuales": monthly_activations,
            "activaciones_fuente": activation_sources,
            "bajas_mensuales": monthly_cancellations,
            "active_subs_monthly": active_subs_monthly,
            "churn_rate_monthly": churn_rate_monthly,
            "alerts": _channel_alerts(
                monthly_transactions,
                monthly_activations,
                monthly_cancellations,
                tch_kpis,
                "TCH",
            ),
            "ultimo_etl": {
                "id": str(latest_run.id) if latest_run else None,
                "status": latest_run.status if latest_run else None,
                "started_at": latest_run.started_at.isoformat() if latest_run else None,
                "records_upserted": latest_run.records_upserted if latest_run else None,
            },
        }
    finally:
        db.close()


@router.get(
    "/clientes",
    dependencies=[Depends(require_permissions("tch.clientes.view"))],
    tags=["TCH"],
)
def list_clients(
    rut: Annotated[str | None, Query()] = None,
    name: Annotated[str | None, Query(alias="nombre")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    """Lista paginada de clientes TCH."""
    db = _get_db()
    try:
        query = select(TchClient)
        if rut:
            query = query.where(TchClient.rut.ilike(f"%{rut}%"))
        if name:
            query = query.where(
                func.concat_ws(" ", TchClient.name, TchClient.last_name).ilike(f"%{name}%")
            )
        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        items = db.scalars(
            query.order_by(TchClient.last_name, TchClient.name).offset((page - 1) * limit).limit(limit)
        ).all()
        return {"total": total, "page": page, "limit": limit, "pages": -(-total // limit), "items": [_serialize_client(item) for item in items]}
    finally:
        db.close()


@router.get(
    "/clientes/{rut}",
    dependencies=[Depends(require_permissions("tch.clientes.view"))],
    tags=["TCH"],
)
def get_client(rut: str) -> dict:
    """Ficha de cliente TCH con sus mandatos asociados."""
    db = _get_db()
    try:
        client = db.scalar(select(TchClient).where(TchClient.rut == rut))
        if client is None:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")
        data = _serialize_client(client)
        subscriptions = db.scalars(
            select(TchSubscription)
            .where(TchSubscription.client_rut == client.rut)
            .order_by(TchSubscription.activation_date.desc())
        ).all()
        last_paid_map = _tch_last_paid_map(db, [s.file_number for s in subscriptions])
        data["suscripciones"] = [_serialize_subscription(s, last_paid_map.get(s.file_number)) for s in subscriptions]
        return data
    finally:
        db.close()


@router.get(
    "/suscripciones",
    dependencies=[Depends(require_permissions("tch.suscripciones.view"))],
    tags=["TCH"],
)
def list_subscriptions(
    status: Annotated[str | None, Query(alias="estado")] = None,
    bank: Annotated[str | None, Query(alias="banco")] = None,
    origin: Annotated[str | None, Query(alias="origen")] = None,
    cost_center: Annotated[str | None, Query(alias="centro_costo")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    """Lista paginada de suscripciones TCH con filtros opcionales."""
    db = _get_db()
    try:
        q = select(TchSubscription)
        if status:
            q = q.where(TchSubscription.status == status.upper())
        if bank:
            q = q.where(TchSubscription.bank_name.ilike(f"%{bank}%"))
        if origin:
            q = q.where(TchSubscription.origin.ilike(f"%{origin}%"))
        if cost_center:
            q = q.where(TchSubscription.cost_center.ilike(f"%{cost_center}%"))

        total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
        items = db.scalars(
            q.order_by(TchSubscription.file_number).offset((page - 1) * limit).limit(limit)
        ).all()
        last_paid_map = _tch_last_paid_map(db, [s.file_number for s in items])
        return {
            "total": total,
            "page": page,
            "limit": limit,
            "pages": -(-total // limit),
            "items": [_serialize_subscription(s, last_paid_map.get(s.file_number)) for s in items],
        }
    finally:
        db.close()


@router.get(
    "/suscripciones/{file_number}",
    dependencies=[Depends(require_permissions("tch.suscripciones.view"))],
    tags=["TCH"],
)
def get_subscription(file_number: int) -> dict:
    """Ficha de una suscripción con su historial de transacciones."""
    db = _get_db()
    try:
        subscription = db.scalar(select(TchSubscription).where(TchSubscription.file_number == file_number))
        if not subscription:
            raise HTTPException(status_code=404, detail="Suscripción no encontrada")
        transaction_rows = db.scalars(
            select(TchTransaction)
            .where(TchTransaction.file_number == file_number)
            .order_by(TchTransaction.period.desc(), TchTransaction.charge_date.desc())
        ).all()
        last_paid_map = _tch_last_paid_map(db, [file_number])
        data = _serialize_subscription(subscription, last_paid_map.get(file_number))
        data["transacciones"] = [_serialize_transaction(t) for t in transaction_rows]
        return data
    finally:
        db.close()


@router.get(
    "/transacciones",
    dependencies=[Depends(require_permissions("tch.transacciones.view"))],
    tags=["TCH"],
)
def list_transactions(
    period: Annotated[str | None, Query(alias="periodo")] = None,
    status: Annotated[str | None, Query(alias="estado")] = None,
    bank: Annotated[str | None, Query(alias="banco")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> dict:
    """Historial de transacciones TCH con filtros."""
    db = _get_db()
    try:
        q = select(TchTransaction)
        if period:
            q = q.where(TchTransaction.period == period)
        if status:
            q = q.where(TchTransaction.status == status.upper())
        if bank:
            q = q.where(TchTransaction.collecting_entity.ilike(f"%{bank}%"))

        total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
        items = db.scalars(
            q.order_by(TchTransaction.period.desc(), TchTransaction.file_number)
            .offset((page - 1) * limit)
            .limit(limit)
        ).all()

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "pages": -(-total // limit),
            "items": [_serialize_transaction(t) for t in items],
        }
    finally:
        db.close()


@router.get(
    "/transacciones/{transaction_id}",
    dependencies=[Depends(require_permissions("tch.transacciones.view"))],
    tags=["TCH"],
)
def get_transaction(transaction_id: uuid.UUID) -> dict:
    """Ficha de un cargo o intento de cobro TCH."""
    db = _get_db()
    try:
        transaction = db.get(TchTransaction, transaction_id)
        if transaction is None:
            raise HTTPException(status_code=404, detail="Transacción no encontrada")
        data = _serialize_transaction(transaction)
        subscription = db.scalar(
            select(TchSubscription).where(TchSubscription.file_number == transaction.file_number)
        )
        data["suscripcion"] = _serialize_subscription(subscription) if subscription else None
        return data
    finally:
        db.close()


@router.post(
    "/import-report",
    dependencies=[Depends(require_role("admin")), Depends(require_csrf)],
    tags=["TCH"],
    status_code=202,
)
async def import_report(
    background_tasks: BackgroundTasks,
    report: Annotated[UploadFile, File(description="Reporte Excel TCH (.xlsx)")],
) -> dict:
    """Imports one TCH report incrementally from an administrator-only upload."""
    filename = report.filename or ""
    if Path(filename).suffix.lower() != ".xlsx":
        raise HTTPException(status_code=422, detail="Seleccione un reporte Excel .xlsx.")

    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="synkmetrix-tch-", suffix=".xlsx", delete=False) as temporary:
            temporary_path = temporary.name
            size = 0
            digest = hashlib.sha256()
            while chunk := await report.read(1024 * 1024):
                size += len(chunk)
                if size > _MAX_REPORT_BYTES:
                    raise HTTPException(status_code=413, detail="El reporte supera el tamaño máximo permitido.")
                digest.update(chunk)
                temporary.write(chunk)
    except Exception:
        if temporary_path:
            Path(temporary_path).unlink(missing_ok=True)
        raise
    finally:
        await report.close()

    db = _get_db()
    try:
        try:
            _validate_xlsx_archive(Path(temporary_path))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if tch_report_registry.is_registered(db, digest.hexdigest()):
            raise HTTPException(
                status_code=409,
                detail="Este reporte ya fue cargado (mismo contenido que un archivo anterior).",
            )
        try:  # SYNC-O-11: reserva atomica; con otra sync/ETL activa responde 409
            run = start_exclusive_run(db, channels_processed=["tch"], phase="tch_import")
        except ActiveRunError as busy:
            raise HTTPException(status_code=409, detail=str(busy)) from busy
    except Exception:
        Path(temporary_path).unlink(missing_ok=True)
        raise
    finally:
        db.close()

    background_tasks.add_task(_import_report_background, str(run.id), temporary_path, original_name=Path(filename).name)
    return {"run_id": str(run.id), "status": "accepted"}


@router.get(
    "/archivos",
    dependencies=[Depends(require_permissions("sync_runs.view"))],
    tags=["TCH"],
)
def list_report_files(limit: int = Query(50, ge=1, le=200)) -> dict:
    """TCH-PAR-11: registro de reportes Excel cargados, por archivo: fecha, sha256, mes, filas y resultado.

    Solo metadatos del archivo (nombre, tamano, hash, conteos): nada del contenido del reporte ni datos personales.
    `resultado`: cargado, consolidado (ya lo vio la consolidacion TCH) o fallido. `conciliacion` (TCH-PAR-11):
    `filas` (leidas, insertadas, actualizadas, omitidas, con_error por suscripciones, cuotas y total) y `control`
    (aceptadas/rechazadas del mes del reporte contra el control del mismo Excel; `cuadra` true/false/null).
    """
    db = _get_db()
    try:
        loads = tch_report_registry.list_loads(db, limit)
        # TCH-PAR-11: conciliacion por archivo (conteos de filas y control del propio Excel); None si no se guardo.
        stats = tch_report_registry.stats_by_sha(db, [load.file_sha256 for load in loads])
        return {
            "items": [
                {
                    "sha256": load.file_sha256,
                    "archivo": load.file_name,
                    "periodo": load.report_period,
                    "cargado_en": load.loaded_at.isoformat() if load.loaded_at else None,
                    "consolidado_en": load.consolidated_at.isoformat() if load.consolidated_at else None,
                    "filas": load.rows_loaded,
                    "tamano_bytes": load.size_bytes,
                    "resultado": tch_report_registry.display_result(load),
                    "error": load.error_message,
                    "etl_run_id": str(load.etl_run_id) if load.etl_run_id else None,
                    "conciliacion": stats.get(load.file_sha256),
                }
                for load in loads
            ],
            "limit": limit,
        }
    finally:
        db.close()


@router.get(
    "/etl/runs",
    dependencies=[Depends(require_permissions("sync_runs.view"))],
    tags=["TCH"],
)
def list_tch_etl_runs() -> list[dict]:
    """Historial de las últimas 20 cargas ETL de TCH."""
    db = _get_db()
    try:
        runs = db.scalars(
            select(EtlRun)
            .where(EtlRun.channels_processed.any("tch"))
            .order_by(EtlRun.started_at.desc())
            .limit(20)
        ).all()
        return [
            {
                "id": str(r.id),
                "status": r.status,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "records_upserted": r.records_upserted,
                "error_message": r.error_message,
            }
            for r in runs
        ]
    finally:
        db.close()
