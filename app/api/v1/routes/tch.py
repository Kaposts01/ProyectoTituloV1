import hashlib
import logging
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
from app.services import tch_report_registry
from app.services.rejected_month import REJECTED_TX_STATUSES, rejected_current_month

router = APIRouter()
logger = logging.getLogger(__name__)

_TCH_PAID = {"aceptada", "aceptado", "pagada", "pagado", "cobrada", "cobrado", "aprobada", "aprobado"}
_MAX_REPORT_BYTES = 250 * 1024 * 1024
_MAX_REPORT_ARCHIVE_ENTRIES = 1_000
_MAX_REPORT_UNCOMPRESSED_BYTES = 500 * 1024 * 1024


def _get_db() -> Session:
    return SessionLocal()


def _import_report_background(run_id: str, report_path: str) -> None:
    """Processes the isolated upload and removes it whether the ETL succeeds or fails."""
    try:
        from scripts import etl_tch

        etl_tch.import_incremental_file(Path(report_path), uuid.UUID(run_id))
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


def _tch_last_paid_map(db: Session, fichas: list[int]) -> dict[int, str]:
    if not fichas:
        return {}
    rows = db.execute(
        select(TchTransaction.file_number, func.max(TchTransaction.charge_date).label("last_date"))
        .where(TchTransaction.file_number.in_(fichas), func.lower(TchTransaction.status).in_(_TCH_PAID))
        .group_by(TchTransaction.file_number)
    ).all()
    return {r.file_number: r.last_date for r in rows if r.last_date}


def _tch_secondary(estado: str, last_paid: str | None) -> str:
    if estado != "VIGENTE":
        return "inactiva"
    if not last_paid:
        return "Nunca Cobrado"
    try:
        paid_date = date.fromisoformat(last_paid[:10])
        return "incobrable" if paid_date <= datetime.now(tz=timezone.utc).date() - timedelta(days=182) else "cobrable"
    except (ValueError, TypeError):
        return "Nunca Cobrado"


def _serialize_sus(s: TchSubscription, last_paid: str | None = None) -> dict:
    return {
        "id": str(s.id),
        "numero_ficha": s.file_number,
        "numero_mandato": s.mandate_number,
        "cliente_rut": s.client_rut,
        "banco_nombre": s.bank_name,
        "tipo_mandato": s.mandate_type,
        "tipo_cuenta": s.account_type,
        "origen": s.origin,
        "centro_costo": s.cost_center,
        "captador": s.recruiter,
        "monto": s.amount,
        "equivalente_pesos": s.peso_equivalent,
        "fecha_activacion": s.activation_date,
        "fecha_rechazo": s.rejection_date,
        "fecha_eliminacion": s.deletion_date,
        "fecha_fin": s.deletion_date or s.rejection_date,
        "razon_baja": s.cancellation_reason,
        "estado": s.status,
        "last_paid_date": last_paid,
        "secondary_status": _tch_secondary(s.status, last_paid),
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _serialize_cliente(c: TchClient) -> dict:
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


def _serialize_trans(t: TchTransaction) -> dict:
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


def _rejected_current_month(transacciones_mensuales: list[dict]) -> dict:
    """Transacciones RECHAZADA del mes actual (hora Chile)."""
    return rejected_current_month(transacciones_mensuales, REJECTED_TX_STATUSES)


def _parse_monto(value: object) -> float:
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


def _recaudo_mensual_kpis(controles: list[TchMonthlyCollection]) -> dict | None:
    """Recaudo aceptado del ultimo periodo con transacciones aceptadas (reportes Excel)."""
    con_aceptadas = [c for c in controles if (c.accepted_count or 0) > 0]
    if not con_aceptadas:
        return None
    ultimo = max(con_aceptadas, key=lambda c: c.period)
    mrr = _parse_monto(ultimo.accepted_amount)
    active_clients = int(ultimo.accepted_count)
    return {
        "period": ultimo.period,
        "mrr": round(mrr, 0),
        "active_clients": active_clients,  # alias heredado de accepted_transactions (no son clientes distintos)
        "accepted_transactions": active_clients,
        "arpu": round(mrr / active_clients, 0),
        "rejected_count": int(ultimo.rejected_count or 0),
        "rejected_amount": round(_parse_monto(ultimo.rejected_amount), 0),
    }


@router.get("/summary", dependencies=[Depends(require_permissions("tch.dashboard.view"))], tags=["TCH"])
def tch_summary() -> dict:
    """KPIs generales del canal TCH."""
    db = _get_db()
    try:
        total_vigentes = db.scalar(
            select(func.count()).select_from(TchSubscription).where(TchSubscription.status == "VIGENTE")
        ) or 0
        total_eliminadas = db.scalar(
            select(func.count()).select_from(TchSubscription).where(TchSubscription.status == "ELIMINADA")
        ) or 0
        controles = db.scalars(
            select(TchMonthlyCollection).order_by(TchMonthlyCollection.period)
        ).all()
        monto_numerico = case(
            (TchTransaction.amount.op("~")(r"^\d+(\.\d+)?$"), cast(TchTransaction.amount, Numeric)),
            else_=0,
        )
        monto_suscripcion = case(
            (TchSubscription.peso_equivalent.op("~")(r"^\d+(\.\d+)?$"), cast(TchSubscription.peso_equivalent, Numeric)),
            else_=0,
        )
        periodo_activacion = func.substring(TchSubscription.activation_date, 1, 7)
        transacciones_fuente = "recaudacion_mensual" if controles else "transacciones"
        if controles:
            total_aceptadas = sum(control.accepted_count for control in controles)
            total_rechazadas = sum(control.rejected_count for control in controles)
            total_trans = total_aceptadas + total_rechazadas
            transacciones_mensuales = [
                {
                    "year": int(control.period[:4]),
                    "month": int(control.period[5:]),
                    "status": status,
                    "count": count,
                    "amount": int(amount),
                }
                for control in controles
                for status, count, amount in (
                    ("ACEPTADA", control.accepted_count, _parse_monto(control.accepted_amount)),
                    ("RECHAZADA", control.rejected_count, _parse_monto(control.rejected_amount)),
                )
            ]
        else:
            total_trans = db.scalar(select(func.count()).select_from(TchTransaction)) or 0
            total_aceptadas = db.scalar(
                select(func.count()).select_from(TchTransaction).where(TchTransaction.status == "ACEPTADA")
            ) or 0
            total_rechazadas = db.scalar(
                select(func.count()).select_from(TchTransaction).where(TchTransaction.status == "RECHAZADA")
            ) or 0
            transacciones_mensuales = _monthly_statuses(
                db.execute(
                    select(
                        TchTransaction.period,
                        TchTransaction.status,
                        func.count(),
                        func.coalesce(func.sum(monto_numerico), 0),
                    )
                    .where(TchTransaction.period.op("~")(r"^\d{4}-\d{2}$"))
                    .group_by(TchTransaction.period, TchTransaction.status)
                    .order_by(TchTransaction.period, TchTransaction.status)
                ).all()
            )
        tasa_rechazo = round(100 * total_rechazadas / total_trans, 1) if total_trans else None
        activaciones_mensuales = _monthly_statuses(
            db.execute(
                select(
                    periodo_activacion,
                    literal("VIGENTE"),
                    func.count(),
                    func.coalesce(func.sum(monto_suscripcion), 0),
                )
                .where(TchSubscription.activation_date.op("~")(r"^\d{4}-\d{2}-\d{2}$"))
                .group_by(periodo_activacion)
                .order_by(periodo_activacion)
            ).all()
        )
        periodo_eliminacion = func.substring(TchSubscription.deletion_date, 1, 7)
        bajas_mensuales = _monthly_statuses(
            db.execute(
                select(
                    periodo_eliminacion,
                    literal("ELIMINADA"),
                    func.count(),
                    func.coalesce(func.sum(monto_suscripcion), 0),
                )
                .where(TchSubscription.deletion_date.op("~")(r"^\d{4}-\d{2}-\d{2}$"))
                .group_by(periodo_eliminacion)
                .order_by(periodo_eliminacion)
            ).all()
        )
        lifecycle_months = sorted({(entry["year"], entry["month"]) for entry in activaciones_mensuales + bajas_mensuales})
        active_subs_monthly: list[dict] = []
        churn_rate_monthly: list[dict] = []
        active_count = 0
        for year, month in lifecycle_months:
            activated = sum(entry["count"] for entry in activaciones_mensuales if (entry["year"], entry["month"]) == (year, month))
            cancelled = sum(entry["count"] for entry in bajas_mensuales if (entry["year"], entry["month"]) == (year, month))
            churn_rate_monthly.append({
                "year": year,
                "month": month,
                "rate": round(100 * cancelled / active_count, 1) if active_count else 0.0,
            })
            active_count = max(0, active_count + activated - cancelled)
            active_subs_monthly.append({"year": year, "month": month, "count": active_count})
        years = sorted(
            {entry["year"] for entry in transacciones_mensuales + activaciones_mensuales + bajas_mensuales},
            reverse=True,
        )

        # ── KPIs ──────────────────────────────────────────────────────────
        mrr = float(
            db.scalar(
                select(func.coalesce(func.sum(monto_suscripcion), 0))
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
        monto_eliminadas = float(
            db.scalar(
                select(func.coalesce(func.sum(monto_suscripcion), 0))
                .select_from(TchSubscription)
                .where(TchSubscription.status == "ELIMINADA")
            ) or 0
        )
        if controles:
            monto_transacciones = int(sum(_parse_monto(c.accepted_amount) + _parse_monto(c.rejected_amount) for c in controles))
        else:
            monto_transacciones = int(
                db.scalar(
                    select(func.coalesce(func.sum(monto_numerico), 0)).select_from(TchTransaction)
                ) or 0
            )
        arpu = round(mrr / active_clients, 0) if active_clients else None
        # Churn mensual promedio historico: promedio de bajas/mes ÷ subs vigentes hoy.
        # None sin base (0 vigentes); 0.0 con base pero sin bajas.
        if not total_vigentes:
            churn_rate = None
        elif bajas_mensuales:
            total_bajas = sum(e["count"] for e in bajas_mensuales)
            num_meses = len({(e["year"], e["month"]) for e in bajas_mensuales})
            avg_bajas_mes = total_bajas / num_meses if num_meses else 0
            churn_rate = round(avg_bajas_mes / total_vigentes * 100, 1)
        else:
            churn_rate = 0.0
        ltv = round(arpu / (churn_rate / 100), 0) if arpu is not None and churn_rate else None
        churn_window_label = "promedio mensual histórico"

        ultimo_run = db.scalar(
            select(EtlRun)
            .where(EtlRun.channels_processed.any("tch"))
            .order_by(EtlRun.started_at.desc())
            .limit(1)
        )

        tch_kpis = {
            "mrr": round(mrr, 0),
            "arpu": arpu,
            "active_clients": active_clients,
            "active_subscribers": total_vigentes,
            "churn_rate": churn_rate,
            "churn_window_label": churn_window_label,
            "ltv": ltv,
            "rejected_charges": _rejected_current_month(transacciones_mensuales),
            "recaudo_mensual": _recaudo_mensual_kpis(controles),
            "source_note": "Fuente: reportes Excel oficiales",
        }
        return {
            "suscripciones": {
                "vigentes": total_vigentes,
                "eliminadas": total_eliminadas,
                "total": total_vigentes + total_eliminadas,
                "monto_vigentes": round(mrr, 0),
                "monto_eliminadas": round(monto_eliminadas, 0),
                "monto_total": round(mrr + monto_eliminadas, 0),
            },
            "transacciones": {
                "total": total_trans,
                "aceptadas": total_aceptadas,
                "rechazadas": total_rechazadas,
                "tasa_rechazo_pct": tasa_rechazo,
                "monto": monto_transacciones,
            },
            "kpis": tch_kpis,
            "churn_window_label": churn_window_label,
            "years": years,
            "transacciones_mensuales": transacciones_mensuales,
            "transacciones_fuente": transacciones_fuente,
            "activaciones_mensuales": activaciones_mensuales,
            "bajas_mensuales": bajas_mensuales,
            "active_subs_monthly": active_subs_monthly,
            "churn_rate_monthly": churn_rate_monthly,
            "alerts": _channel_alerts(
                transacciones_mensuales,
                activaciones_mensuales,
                bajas_mensuales,
                tch_kpis,
                "TCH",
            ),
            "ultimo_etl": {
                "id": str(ultimo_run.id) if ultimo_run else None,
                "status": ultimo_run.status if ultimo_run else None,
                "started_at": ultimo_run.started_at.isoformat() if ultimo_run else None,
                "records_upserted": ultimo_run.records_upserted if ultimo_run else None,
            },
        }
    finally:
        db.close()


@router.get(
    "/clientes",
    dependencies=[Depends(require_permissions("tch.clientes.view"))],
    tags=["TCH"],
)
def list_clientes(
    rut: Annotated[str | None, Query()] = None,
    nombre: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    """Lista paginada de clientes TCH."""
    db = _get_db()
    try:
        query = select(TchClient)
        if rut:
            query = query.where(TchClient.rut.ilike(f"%{rut}%"))
        if nombre:
            query = query.where(
                func.concat_ws(" ", TchClient.name, TchClient.last_name).ilike(f"%{nombre}%")
            )
        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        items = db.scalars(
            query.order_by(TchClient.last_name, TchClient.name).offset((page - 1) * limit).limit(limit)
        ).all()
        return {"total": total, "page": page, "limit": limit, "pages": -(-total // limit), "items": [_serialize_cliente(item) for item in items]}
    finally:
        db.close()


@router.get(
    "/clientes/{rut}",
    dependencies=[Depends(require_permissions("tch.clientes.view"))],
    tags=["TCH"],
)
def get_cliente(rut: str) -> dict:
    """Ficha de cliente TCH con sus mandatos asociados."""
    db = _get_db()
    try:
        cliente = db.scalar(select(TchClient).where(TchClient.rut == rut))
        if cliente is None:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")
        data = _serialize_cliente(cliente)
        suscripciones = db.scalars(
            select(TchSubscription)
            .where(TchSubscription.client_rut == cliente.rut)
            .order_by(TchSubscription.activation_date.desc())
        ).all()
        last_paid_map = _tch_last_paid_map(db, [s.file_number for s in suscripciones])
        data["suscripciones"] = [_serialize_sus(s, last_paid_map.get(s.file_number)) for s in suscripciones]
        return data
    finally:
        db.close()


@router.get(
    "/suscripciones",
    dependencies=[Depends(require_permissions("tch.suscripciones.view"))],
    tags=["TCH"],
)
def list_suscripciones(
    estado: Annotated[str | None, Query()] = None,
    banco: Annotated[str | None, Query()] = None,
    origen: Annotated[str | None, Query()] = None,
    centro_costo: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    """Lista paginada de suscripciones TCH con filtros opcionales."""
    db = _get_db()
    try:
        q = select(TchSubscription)
        if estado:
            q = q.where(TchSubscription.status == estado.upper())
        if banco:
            q = q.where(TchSubscription.bank_name.ilike(f"%{banco}%"))
        if origen:
            q = q.where(TchSubscription.origin.ilike(f"%{origen}%"))
        if centro_costo:
            q = q.where(TchSubscription.cost_center.ilike(f"%{centro_costo}%"))

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
            "items": [_serialize_sus(s, last_paid_map.get(s.file_number)) for s in items],
        }
    finally:
        db.close()


@router.get(
    "/suscripciones/{numero_ficha}",
    dependencies=[Depends(require_permissions("tch.suscripciones.view"))],
    tags=["TCH"],
)
def get_suscripcion(numero_ficha: int) -> dict:
    """Ficha de una suscripción con su historial de transacciones."""
    db = _get_db()
    try:
        sus = db.scalar(select(TchSubscription).where(TchSubscription.file_number == numero_ficha))
        if not sus:
            raise HTTPException(status_code=404, detail="Suscripción no encontrada")
        trans = db.scalars(
            select(TchTransaction)
            .where(TchTransaction.file_number == numero_ficha)
            .order_by(TchTransaction.period.desc(), TchTransaction.charge_date.desc())
        ).all()
        last_paid_map = _tch_last_paid_map(db, [numero_ficha])
        data = _serialize_sus(sus, last_paid_map.get(numero_ficha))
        data["transacciones"] = [_serialize_trans(t) for t in trans]
        return data
    finally:
        db.close()


@router.get(
    "/transacciones",
    dependencies=[Depends(require_permissions("tch.transacciones.view"))],
    tags=["TCH"],
)
def list_transacciones(
    periodo: Annotated[str | None, Query()] = None,
    estado: Annotated[str | None, Query()] = None,
    banco: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> dict:
    """Historial de transacciones TCH con filtros."""
    db = _get_db()
    try:
        q = select(TchTransaction)
        if periodo:
            q = q.where(TchTransaction.period == periodo)
        if estado:
            q = q.where(TchTransaction.status == estado.upper())
        if banco:
            q = q.where(TchTransaction.collecting_entity.ilike(f"%{banco}%"))

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
            "items": [_serialize_trans(t) for t in items],
        }
    finally:
        db.close()


@router.get(
    "/transacciones/{transaction_id}",
    dependencies=[Depends(require_permissions("tch.transacciones.view"))],
    tags=["TCH"],
)
def get_transaccion(transaction_id: uuid.UUID) -> dict:
    """Ficha de un cargo o intento de cobro TCH."""
    db = _get_db()
    try:
        transaction = db.get(TchTransaction, transaction_id)
        if transaction is None:
            raise HTTPException(status_code=404, detail="Transacción no encontrada")
        data = _serialize_trans(transaction)
        suscripcion = db.scalar(
            select(TchSubscription).where(TchSubscription.file_number == transaction.file_number)
        )
        data["suscripcion"] = _serialize_sus(suscripcion) if suscripcion else None
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

    background_tasks.add_task(_import_report_background, str(run.id), temporary_path)
    return {"run_id": str(run.id), "status": "accepted"}


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
