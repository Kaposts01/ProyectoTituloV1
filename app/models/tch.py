import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class TchBanco(Base):
    __tablename__ = "tch_bancos"
    __table_args__ = (UniqueConstraint("nombre", name="uq_tch_banco_nombre"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    codigo_interno: Mapped[int | None] = mapped_column(Integer, nullable=True)
    codigo_grupo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TchTipoMandato(Base):
    __tablename__ = "tch_tipos_mandato"
    __table_args__ = (UniqueConstraint("codigo", name="uq_tch_tipo_mandato_codigo"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    codigo: Mapped[str] = mapped_column(String(50), nullable=False)
    nombre: Mapped[str | None] = mapped_column(String(100), nullable=True)
    descripcion: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TchOrigen(Base):
    __tablename__ = "tch_origenes"
    __table_args__ = (UniqueConstraint("nombre", name="uq_tch_origen_nombre"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TchCentroCosto(Base):
    __tablename__ = "tch_centros_costo"
    __table_args__ = (UniqueConstraint("nombre", name="uq_tch_centro_costo_nombre"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    estrategia: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TchCliente(Base):
    __tablename__ = "tch_clientes"
    __table_args__ = (UniqueConstraint("rut", name="uq_tch_cliente_rut"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rut: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    nombre: Mapped[str | None] = mapped_column(String(150), nullable=True)
    apellido: Mapped[str | None] = mapped_column(String(150), nullable=True)
    fecha_nacimiento: Mapped[str | None] = mapped_column(String(20), nullable=True)
    profesion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tipo_persona: Mapped[str | None] = mapped_column(String(30), nullable=True)
    tipo_socio: Mapped[str | None] = mapped_column(String(50), nullable=True)
    telefono: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    direccion: Mapped[str | None] = mapped_column(String(500), nullable=True)
    comuna: Mapped[str | None] = mapped_column(String(150), nullable=True)
    ciudad: Mapped[str | None] = mapped_column(String(150), nullable=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TchSuscripcion(Base):
    __tablename__ = "tch_suscripciones"
    __table_args__ = (UniqueConstraint("numero_ficha", name="uq_tch_suscripcion_ficha"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    numero_ficha: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    numero_mandato: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # Referencias de negocio (strings para tolerar datos sucios del Excel)
    cliente_rut: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    banco_nombre: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    tipo_mandato: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    tipo_cuenta: Mapped[str | None] = mapped_column(String(50), nullable=True)
    numero_cuenta: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Datos de captación
    origen: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    centro_costo: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    captador: Mapped[str | None] = mapped_column(String(150), nullable=True)

    # Info mandato
    ley: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reajuste: Mapped[str | None] = mapped_column(String(10), nullable=True)
    firma: Mapped[str | None] = mapped_column(String(10), nullable=True)
    monto: Mapped[str | None] = mapped_column(String(20), nullable=True)
    equivalente_pesos: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Fechas (strings ISO para flexibilidad con datos históricos)
    fecha_activacion: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    fecha_ingreso: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fecha_entrega_banco: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fecha_rechazo: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fecha_eliminacion: Mapped[str | None] = mapped_column(String(20), nullable=True)
    razon_baja: Mapped[str | None] = mapped_column(String(500), nullable=True)

    estado: Mapped[str] = mapped_column(String(20), nullable=False, index=True, default="VIGENTE")

    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TchTransaccion(Base):
    """
    Una fila por cargo/intento mensual.
    La clave de deduplicación evita repetir un mismo cargo histórico presente
    en varios reportes mensuales.
    """

    __tablename__ = "tch_transacciones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    numero_ficha: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    numero_mandato: Mapped[int | None] = mapped_column(Integer, nullable=True)
    periodo: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)  # YYYY-MM
    numero_cuota: Mapped[str | None] = mapped_column(String(20), nullable=True)
    total_cuotas: Mapped[str | None] = mapped_column(String(20), nullable=True)
    monto: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fecha_cargo: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    tipo_transaccion: Mapped[str | None] = mapped_column(String(50), nullable=True)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    entidad_recaudadora: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    codigo_respuesta: Mapped[str | None] = mapped_column(String(50), nullable=True)
    razon_rechazo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    archivo_origen: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TchRecaudacionMensual(Base):
    """Control mensual oficial extraído de los históricos de recaudación TCH."""

    __tablename__ = "tch_recaudacion_mensual"
    __table_args__ = (UniqueConstraint("periodo", name="uq_tch_recaudacion_mensual_periodo"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    periodo: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    aceptadas_cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    aceptadas_monto: Mapped[str] = mapped_column(String(20), nullable=False)
    rechazadas_cantidad: Mapped[int] = mapped_column(Integer, nullable=False)
    rechazadas_monto: Mapped[str] = mapped_column(String(20), nullable=False)
    archivo_origen: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
