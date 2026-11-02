import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

# Origen de una fila de tch_transacciones (TCH-PAR-04).
ORIGIN_CHARGE = "cargo"  # hojas CARGOS ACEPTADOS / CARGOS RECHAZADOS: intento real, con fecha de cobro
ORIGIN_HISTORY = "historial"  # bloques de 12 meses de las hojas de mandatos: estado mensual, sin fecha de cobro


class TchBank(Base):
    __tablename__ = "tch_bancos"
    __table_args__ = (UniqueConstraint("nombre", name="uq_tch_banco_nombre"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column("nombre", String(100), nullable=False)
    internal_code: Mapped[int | None] = mapped_column("codigo_interno", Integer, nullable=True)
    group_code: Mapped[int | None] = mapped_column("codigo_grupo", Integer, nullable=True)
    active: Mapped[bool] = mapped_column("activo", Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TchMandateType(Base):
    __tablename__ = "tch_tipos_mandato"
    __table_args__ = (UniqueConstraint("codigo", name="uq_tch_tipo_mandato_codigo"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column("codigo", String(50), nullable=False)
    name: Mapped[str | None] = mapped_column("nombre", String(100), nullable=True)
    description: Mapped[str | None] = mapped_column("descripcion", String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TchOrigin(Base):
    __tablename__ = "tch_origenes"
    __table_args__ = (UniqueConstraint("nombre", name="uq_tch_origen_nombre"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column("nombre", String(150), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TchCostCenter(Base):
    __tablename__ = "tch_centros_costo"
    __table_args__ = (UniqueConstraint("nombre", name="uq_tch_centro_costo_nombre"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column("nombre", String(150), nullable=False)
    strategy: Mapped[str | None] = mapped_column("estrategia", String(150), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TchClient(Base):
    __tablename__ = "tch_clientes"
    __table_args__ = (UniqueConstraint("rut", name="uq_tch_cliente_rut"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rut: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column("nombre", String(150), nullable=True)
    last_name: Mapped[str | None] = mapped_column("apellido", String(150), nullable=True)
    birth_date: Mapped[str | None] = mapped_column("fecha_nacimiento", String(20), nullable=True)
    profession: Mapped[str | None] = mapped_column("profesion", String(100), nullable=True)
    person_type: Mapped[str | None] = mapped_column("tipo_persona", String(30), nullable=True)
    member_type: Mapped[str | None] = mapped_column("tipo_socio", String(50), nullable=True)
    phone: Mapped[str | None] = mapped_column("telefono", String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    address: Mapped[str | None] = mapped_column("direccion", String(500), nullable=True)
    district: Mapped[str | None] = mapped_column("comuna", String(150), nullable=True)
    city: Mapped[str | None] = mapped_column("ciudad", String(150), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TchSubscription(Base):
    __tablename__ = "tch_suscripciones"
    __table_args__ = (UniqueConstraint("numero_ficha", name="uq_tch_suscripcion_ficha"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_number: Mapped[int] = mapped_column("numero_ficha", Integer, nullable=False, index=True)
    mandate_number: Mapped[int | None] = mapped_column("numero_mandato", Integer, nullable=True, index=True)

    # Referencias de negocio (strings para tolerar datos sucios del Excel)
    client_rut: Mapped[str | None] = mapped_column("cliente_rut", String(20), nullable=True, index=True)
    bank_name: Mapped[str | None] = mapped_column("banco_nombre", String(100), nullable=True, index=True)
    mandate_type: Mapped[str | None] = mapped_column("tipo_mandato", String(20), nullable=True, index=True)
    account_type: Mapped[str | None] = mapped_column("tipo_cuenta", String(50), nullable=True)
    account_number: Mapped[str | None] = mapped_column("numero_cuenta", String(50), nullable=True)

    # Datos de captación
    origin: Mapped[str | None] = mapped_column("origen", String(150), nullable=True, index=True)
    cost_center: Mapped[str | None] = mapped_column("centro_costo", String(150), nullable=True, index=True)
    recruiter: Mapped[str | None] = mapped_column("captador", String(150), nullable=True)

    # Info mandato
    law: Mapped[str | None] = mapped_column("ley", String(50), nullable=True)
    adjustment: Mapped[str | None] = mapped_column("reajuste", String(10), nullable=True)
    signature: Mapped[str | None] = mapped_column("firma", String(10), nullable=True)
    amount: Mapped[str | None] = mapped_column("monto", String(20), nullable=True)
    currency: Mapped[str | None] = mapped_column("moneda", String(3), nullable=True)  # CLP / UF / USD desde "Moneda Vigente"
    peso_equivalent: Mapped[str | None] = mapped_column("equivalente_pesos", String(20), nullable=True)

    # Fechas (strings ISO para flexibilidad con datos históricos)
    activation_date: Mapped[str | None] = mapped_column("fecha_activacion", String(20), nullable=True, index=True)
    entry_date: Mapped[str | None] = mapped_column("fecha_ingreso", String(20), nullable=True)
    bank_delivery_date: Mapped[str | None] = mapped_column("fecha_entrega_banco", String(20), nullable=True)
    rejection_date: Mapped[str | None] = mapped_column("fecha_rechazo", String(20), nullable=True)
    deletion_date: Mapped[str | None] = mapped_column("fecha_eliminacion", String(20), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column("razon_baja", String(500), nullable=True)

    status: Mapped[str] = mapped_column("estado", String(20), nullable=False, index=True, default="VIGENTE")

    # TCH-PAR-09: campos del reporte que antes no se cargaban. Del titular de la cuenta solo se guarda si difiere del
    # socio (indicador), nunca su RUT ni su nombre.
    strategy: Mapped[str | None] = mapped_column("estrategia", String(150), nullable=True)
    recruitment_place: Mapped[str | None] = mapped_column("lugar_captacion", String(150), nullable=True)
    folio: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference: Mapped[str | None] = mapped_column("referencia", String(30), nullable=True)
    personality: Mapped[str | None] = mapped_column("personalidad", String(20), nullable=True)
    different_holder: Mapped[bool | None] = mapped_column("titular_distinto", Boolean, nullable=True)
    first_charge_date: Mapped[str | None] = mapped_column("fecha_primer_cobro", String(20), nullable=True)
    first_charge_amount: Mapped[str | None] = mapped_column("monto_primer_cobro", String(20), nullable=True)
    installments_charged: Mapped[int | None] = mapped_column("cuotas_cobradas", Integer, nullable=True)
    amount_charged: Mapped[str | None] = mapped_column("monto_cobrado", String(20), nullable=True)
    contribution_installments: Mapped[int | None] = mapped_column("aportes_cuotas", Integer, nullable=True)
    contribution_amount: Mapped[str | None] = mapped_column("aportes_monto", String(20), nullable=True)
    average_donation: Mapped[str | None] = mapped_column("promedio_donacion", String(20), nullable=True)
    months_without_contribution: Mapped[int | None] = mapped_column("meses_sin_aporte", Integer, nullable=True)
    tenure_months: Mapped[int | None] = mapped_column("permanencia_meses", Integer, nullable=True)
    tenure_years: Mapped[int | None] = mapped_column("permanencia_anos", Integer, nullable=True)
    new_in_month: Mapped[bool | None] = mapped_column("nvo_mes", Boolean, nullable=True)
    rejected_in_month: Mapped[bool | None] = mapped_column("rech_mes", Boolean, nullable=True)
    deleted_in_month: Mapped[bool | None] = mapped_column("eli_mes", Boolean, nullable=True)

    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TchTransaction(Base):
    """
    Una fila por cuota: (ficha, periodo real, cuota) con el ÚLTIMO estado (D13).
    La clave de deduplicación evita repetir una cuota presente en varios reportes; el rechazo previo de una cuota
    luego aceptada queda como atributo de la misma fila (``rechazo_previo*``), no como segunda fila.
    """

    __tablename__ = "tch_transacciones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_number: Mapped[int] = mapped_column("numero_ficha", Integer, nullable=False, index=True)
    mandate_number: Mapped[int | None] = mapped_column("numero_mandato", Integer, nullable=True)
    period: Mapped[str | None] = mapped_column("periodo", String(10), nullable=True, index=True)  # YYYY-MM
    installment_number: Mapped[str | None] = mapped_column("numero_cuota", String(20), nullable=True)
    total_installments: Mapped[str | None] = mapped_column("total_cuotas", String(20), nullable=True)
    amount: Mapped[str | None] = mapped_column("monto", String(20), nullable=True)
    charge_date: Mapped[str | None] = mapped_column("fecha_cargo", String(20), nullable=True, index=True)
    transaction_type: Mapped[str | None] = mapped_column("tipo_transaccion", String(50), nullable=True)
    status: Mapped[str] = mapped_column("estado", String(20), nullable=False, index=True)
    collecting_entity: Mapped[str | None] = mapped_column("entidad_recaudadora", String(100), nullable=True, index=True)
    response_code: Mapped[str | None] = mapped_column("codigo_respuesta", String(50), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column("razon_rechazo", String(500), nullable=True)
    source_file: Mapped[str | None] = mapped_column("archivo_origen", String(255), nullable=True, index=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    # D13 (TCH-PAR-03/04): clave = ficha|periodo real|cuota; UN estado final por cuota ("el ultimo reporte gana").
    # origen: 'cargo' (hojas CARGOS, con fecha) o 'historial' (estado mensual sin fecha). NULL = fila anterior a la recarga.
    origin: Mapped[str | None] = mapped_column("origen", String(10), nullable=True)
    report_period: Mapped[str | None] = mapped_column("reporte_periodo", String(7), nullable=True)  # YYYY-MM del reporte que trajo la fila
    previous_rejection: Mapped[bool | None] = mapped_column("rechazo_previo", Boolean, nullable=True)
    previous_rejection_reason: Mapped[str | None] = mapped_column("rechazo_previo_motivo", String(500), nullable=True)
    previous_rejection_at: Mapped[str | None] = mapped_column("rechazo_previo_en", String(20), nullable=True)  # fecha ISO del intento rechazado
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TchMonthlyCollection(Base):
    """Control mensual oficial extraído de los históricos de recaudación TCH."""

    __tablename__ = "tch_recaudacion_mensual"
    __table_args__ = (UniqueConstraint("periodo", name="uq_tch_recaudacion_mensual_periodo"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    period: Mapped[str] = mapped_column("periodo", String(7), nullable=False, index=True)
    accepted_count: Mapped[int] = mapped_column("aceptadas_cantidad", Integer, nullable=False)
    accepted_amount: Mapped[str] = mapped_column("aceptadas_monto", String(20), nullable=False)
    rejected_count: Mapped[int] = mapped_column("rechazadas_cantidad", Integer, nullable=False)
    rejected_amount: Mapped[str] = mapped_column("rechazadas_monto", String(20), nullable=False)
    source_file: Mapped[str] = mapped_column("archivo_origen", String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TchFileLoad(Base):
    """SYNC-O-08: registro de reportes Excel TCH cargados, por sha256 del contenido (antes en `source_records`).

    `consolidated_at` lo fija la consolidacion TCH exitosa que ya vio el archivo; NULL = cargado y aun sin consolidar.
    Solo guarda nombre, tamano y conteo: nada del contenido del reporte.
    """

    __tablename__ = "tch_file_loads"

    file_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    rows_loaded: Mapped[int | None] = mapped_column(Integer)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    consolidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
