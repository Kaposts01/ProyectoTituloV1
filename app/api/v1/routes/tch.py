import logging
import tempfile
import uuid
import zipfile
from datetime import date, timedelta
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
    TchCliente,
    TchRecaudacionMensual,
    TchSuscripcion,
    TchTransaccion,
)

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
        select(TchTransaccion.numero_ficha, func.max(TchTransaccion.fecha_cargo).label("last_date"))
        .where(TchTransaccion.numero_ficha.in_(fichas), func.lower(TchTransaccion.estado).in_(_TCH_PAID))
        .group_by(TchTransaccion.numero_ficha)
    ).all()
    return {r.numero_ficha: r.last_date for r in rows if r.last_date}


def _tch_secondary(estado: str, last_paid: str | None) -> str:
    if estado != "VIGENTE":
        return "inactiva"
    if not last_paid:
        return "Nunca Cobrado"
    try:
        paid_date = date.fromisoformat(last_paid[:10])
        return "incobrable" if paid_date <= date.today() - timedelta(days=182) else "cobrable"
    except (ValueError, TypeError):
        return "Nunca Cobrado"


def _serialize_sus(s: TchSuscripcion, last_paid: str | None = None) -> dict:
    return {
        "id": str(s.id),
        "numero_ficha": s.numero_ficha,
        "numero_mandato": s.numero_mandato,
        "cliente_rut": s.cliente_rut,
        "banco_nombre": s.banco_nombre,
        "tipo_mandato": s.tipo_mandato,
        "tipo_cuenta": s.tipo_cuenta,
        "origen": s.origen,
        "centro_costo": s.centro_costo,
        "captador": s.captador,
        "monto": s.monto,
        "equivalente_pesos": s.equivalente_pesos,
        "fecha_activacion": s.fecha_activacion,
        "fecha_rechazo": s.fecha_rechazo,
        "fecha_eliminacion": s.fecha_eliminacion,
        "fecha_fin": s.fecha_eliminacion or s.fecha_rechazo,
        "razon_baja": s.razon_baja,
        "estado": s.estado,
        "last_paid_date": last_paid,
        "secondary_status": _tch_secondary(s.estado, last_paid),
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def _serialize_cliente(c: TchCliente) -> dict:
    return {
        "id": str(c.id),
        "rut": c.rut,
        "nombre": c.nombre,
        "apellido": c.apellido,
        "fecha_nacimiento": c.fecha_nacimiento,
        "profesion": c.profesion,
        "tipo_persona": c.tipo_persona,
        "tipo_socio": c.tipo_socio,
        "telefono": c.telefono,
        "email": c.email,
        "direccion": c.direccion,
        "comuna": c.comuna,
        "ciudad": c.ciudad,
    }


def _serialize_trans(t: TchTransaccion) -> dict:
    return {
        "id": str(t.id),
        "numero_ficha": t.numero_ficha,
        "periodo": t.periodo,
        "numero_cuota": t.numero_cuota,
        "total_cuotas": t.total_cuotas,
        "monto": t.monto,
        "fecha_cargo": t.fecha_cargo,
        "tipo_transaccion": t.tipo_transaccion,
        "estado": t.estado,
        "entidad_recaudadora": t.entidad_recaudadora,
        "razon_rechazo": t.razon_rechazo,
        "archivo_origen": t.archivo_origen,
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


@router.get("/summary", dependencies=[Depends(require_permissions("tch.dashboard.view"))], tags=["TCH"])
def tch_summary() -> dict:
    """KPIs generales del canal TCH."""
    db = _get_db()
    try:
        total_vigentes = db.scalar(
            select(func.count()).select_from(TchSuscripcion).where(TchSuscripcion.estado == "VIGENTE")
        ) or 0
        total_eliminadas = db.scalar(
            select(func.count()).select_from(TchSuscripcion).where(TchSuscripcion.estado == "ELIMINADA")
        ) or 0
        controles = db.scalars(
            select(TchRecaudacionMensual).order_by(TchRecaudacionMensual.periodo)
        ).all()
        monto_numerico = case(
            (TchTransaccion.monto.op("~")(r"^\d+(\.\d+)?$"), cast(TchTransaccion.monto, Numeric)),
            else_=0,
        )
        monto_suscripcion = case(
            (TchSuscripcion.equivalente_pesos.op("~")(r"^\d+(\.\d+)?$"), cast(TchSuscripcion.equivalente_pesos, Numeric)),
            else_=0,
        )
        periodo_activacion = func.substring(TchSuscripcion.fecha_activacion, 1, 7)
        if controles:
            total_aceptadas = sum(control.aceptadas_cantidad for control in controles)
            total_rechazadas = sum(control.rechazadas_cantidad for control in controles)
            total_trans = total_aceptadas + total_rechazadas
            transacciones_mensuales = [
                {
                    "year": int(control.periodo[:4]),
                    "month": int(control.periodo[5:]),
                    "status": status,
                    "count": count,
                    "amount": int(amount),
                }
                for control in controles
                for status, count, amount in (
                    ("ACEPTADA", control.aceptadas_cantidad, control.aceptadas_monto),
                    ("RECHAZADA", control.rechazadas_cantidad, control.rechazadas_monto),
                )
            ]
        else:
            total_trans = db.scalar(select(func.count()).select_from(TchTransaccion)) or 0
            total_aceptadas = db.scalar(
                select(func.count()).select_from(TchTransaccion).where(TchTransaccion.estado == "ACEPTADA")
            ) or 0
            total_rechazadas = db.scalar(
                select(func.count()).select_from(TchTransaccion).where(TchTransaccion.estado == "RECHAZADA")
            ) or 0
            transacciones_mensuales = _monthly_statuses(
                db.execute(
                    select(
                        TchTransaccion.periodo,
                        TchTransaccion.estado,
                        func.count(),
                        func.coalesce(func.sum(monto_numerico), 0),
                    )
                    .where(TchTransaccion.periodo.op("~")(r"^\d{4}-\d{2}$"))
                    .group_by(TchTransaccion.periodo, TchTransaccion.estado)
                    .order_by(TchTransaccion.periodo, TchTransaccion.estado)
                ).all()
            )
        tasa_rechazo = round(100 * total_rechazadas / total_trans, 1) if total_trans else 0.0
        activaciones_mensuales = _monthly_statuses(
            db.execute(
                select(
                    periodo_activacion,
                    literal("VIGENTE"),
                    func.count(),
                    func.coalesce(func.sum(monto_suscripcion), 0),
                )
                .where(TchSuscripcion.fecha_activacion.op("~")(r"^\d{4}-\d{2}-\d{2}$"))
                .group_by(periodo_activacion)
                .order_by(periodo_activacion)
            ).all()
        )
        periodo_eliminacion = func.substring(TchSuscripcion.fecha_eliminacion, 1, 7)
        bajas_mensuales = _monthly_statuses(
            db.execute(
                select(
                    periodo_eliminacion,
                    literal("ELIMINADA"),
                    func.count(),
                    func.coalesce(func.sum(monto_suscripcion), 0),
                )
                .where(TchSuscripcion.fecha_eliminacion.op("~")(r"^\d{4}-\d{2}-\d{2}$"))
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
                .select_from(TchSuscripcion)
                .where(TchSuscripcion.estado == "VIGENTE")
            ) or 0
        )
        active_clients = db.scalar(
            select(func.count(TchSuscripcion.cliente_rut.distinct()))
            .select_from(TchSuscripcion)
            .where(TchSuscripcion.estado == "VIGENTE")
            .where(TchSuscripcion.cliente_rut.isnot(None))
        ) or 0
        monto_eliminadas = float(
            db.scalar(
                select(func.coalesce(func.sum(monto_suscripcion), 0))
                .select_from(TchSuscripcion)
                .where(TchSuscripcion.estado == "ELIMINADA")
            ) or 0
        )
        if controles:
            monto_transacciones = int(sum(float(c.aceptadas_monto or 0) + float(c.rechazadas_monto or 0) for c in controles))
        else:
            monto_transacciones = int(
                db.scalar(
                    select(func.coalesce(func.sum(monto_numerico), 0)).select_from(TchTransaccion)
                ) or 0
            )
        arpu = round(mrr / active_clients, 0) if active_clients else 0.0
        # Churn mensual promedio: promedio de bajas/mes ÷ subs vigentes
        if bajas_mensuales and total_vigentes:
            total_bajas = sum(e["count"] for e in bajas_mensuales)
            num_meses = len({(e["year"], e["month"]) for e in bajas_mensuales})
            avg_bajas_mes = total_bajas / num_meses if num_meses else 0
            churn_rate = round(avg_bajas_mes / total_vigentes * 100, 1)
        else:
            churn_rate = 0.0
        ltv = round(arpu / (churn_rate / 100), 0) if churn_rate else 0.0

        ultimo_run = db.scalar(
            select(EtlRun)
            .where(EtlRun.channels_processed.any("tch"))
            .order_by(EtlRun.started_at.desc())
            .limit(1)
        )

        tch_kpis = {
            "mrr": round(mrr, 0),
            "arpu": round(arpu, 0),
            "active_clients": active_clients,
            "active_subscribers": total_vigentes,
            "churn_rate": churn_rate,
            "ltv": round(ltv, 0),
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
            "years": years,
            "transacciones_mensuales": transacciones_mensuales,
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
        query = select(TchCliente)
        if rut:
            query = query.where(TchCliente.rut.ilike(f"%{rut}%"))
        if nombre:
            query = query.where(
                func.concat_ws(" ", TchCliente.nombre, TchCliente.apellido).ilike(f"%{nombre}%")
            )
        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        items = db.scalars(
            query.order_by(TchCliente.apellido, TchCliente.nombre).offset((page - 1) * limit).limit(limit)
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
        cliente = db.scalar(select(TchCliente).where(TchCliente.rut == rut))
        if cliente is None:
            raise HTTPException(status_code=404, detail="Cliente no encontrado")
        data = _serialize_cliente(cliente)
        suscripciones = db.scalars(
            select(TchSuscripcion)
            .where(TchSuscripcion.cliente_rut == cliente.rut)
            .order_by(TchSuscripcion.fecha_activacion.desc())
        ).all()
        last_paid_map = _tch_last_paid_map(db, [s.numero_ficha for s in suscripciones])
        data["suscripciones"] = [_serialize_sus(s, last_paid_map.get(s.numero_ficha)) for s in suscripciones]
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
        q = select(TchSuscripcion)
        if estado:
            q = q.where(TchSuscripcion.estado == estado.upper())
        if banco:
            q = q.where(TchSuscripcion.banco_nombre.ilike(f"%{banco}%"))
        if origen:
            q = q.where(TchSuscripcion.origen.ilike(f"%{origen}%"))
        if centro_costo:
            q = q.where(TchSuscripcion.centro_costo.ilike(f"%{centro_costo}%"))

        total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
        items = db.scalars(
            q.order_by(TchSuscripcion.numero_ficha).offset((page - 1) * limit).limit(limit)
        ).all()
        last_paid_map = _tch_last_paid_map(db, [s.numero_ficha for s in items])
        return {
            "total": total,
            "page": page,
            "limit": limit,
            "pages": -(-total // limit),
            "items": [_serialize_sus(s, last_paid_map.get(s.numero_ficha)) for s in items],
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
        sus = db.scalar(select(TchSuscripcion).where(TchSuscripcion.numero_ficha == numero_ficha))
        if not sus:
            raise HTTPException(status_code=404, detail="Suscripción no encontrada")
        trans = db.scalars(
            select(TchTransaccion)
            .where(TchTransaccion.numero_ficha == numero_ficha)
            .order_by(TchTransaccion.periodo.desc(), TchTransaccion.fecha_cargo.desc())
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
        q = select(TchTransaccion)
        if periodo:
            q = q.where(TchTransaccion.periodo == periodo)
        if estado:
            q = q.where(TchTransaccion.estado == estado.upper())
        if banco:
            q = q.where(TchTransaccion.entidad_recaudadora.ilike(f"%{banco}%"))

        total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
        items = db.scalars(
            q.order_by(TchTransaccion.periodo.desc(), TchTransaccion.numero_ficha)
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
        transaction = db.get(TchTransaccion, transaction_id)
        if transaction is None:
            raise HTTPException(status_code=404, detail="Transacción no encontrada")
        data = _serialize_trans(transaction)
        suscripcion = db.scalar(
            select(TchSuscripcion).where(TchSuscripcion.numero_ficha == transaction.numero_ficha)
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
            while chunk := await report.read(1024 * 1024):
                size += len(chunk)
                if size > _MAX_REPORT_BYTES:
                    raise HTTPException(status_code=413, detail="El reporte supera el tamaño máximo permitido.")
                temporary.write(chunk)
    except Exception:
        if temporary_path:
            Path(temporary_path).unlink(missing_ok=True)
        raise
    finally:
        await report.close()

    db = _get_db()
    try:
        active = db.scalar(select(EtlRun).where(EtlRun.status == "running").limit(1))
        if active:
            raise HTTPException(
                status_code=409,
                detail=f"Ya hay una sincronización activa (run_id={active.id}). Espera a que termine.",
            )
        try:
            _validate_xlsx_archive(Path(temporary_path))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        run = EtlRun(status="running", channels_processed=["tch"], records_upserted=0, phase="tch_import")
        db.add(run)
        db.commit()
        db.refresh(run)
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
