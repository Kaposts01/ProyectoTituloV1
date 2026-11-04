"""Reportes descargados del portal de Payku (PK-PAR-10, d115 opcion b; migracion 20261102_0065).

Tablas separadas de las del API (`p_*`): el reporte es una fuente distinta y solo trae cobros exitosos. Sin datos
personales: nunca se guardan nombre, correo, telefono, 4 ultimos digitos ni texto libre del concepto (solo si es una
cuota «Cobro: # n» y su numero).

* `p_report_files`: un registro por archivo subido (sha256, hojas cargadas, contadores, estado, etiqueta de error).
* `p_report_transactions`: transacciones de `dataTransacciones` y de la hoja «Transacciones» del consolidado, con
  comision, monto final (neto), proveedor, tipo y medio de pago y liquidacion. Clave `row_key` = sha256 de
  (voucher, orden, fecha, monto): en los anos antiguos el voucher se repite (parity_payku.md).
* `p_report_settlements`: hoja «Liquidaciones» del consolidado (monto, estado, fecha de deposito).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

PAYKU_REPORT_TYPES = ("transacciones", "liquidaciones", "suscripciones", "consolidado")
PAYKU_REPORT_FILE_STATUSES = ("running", "completed", "failed")
PAYKU_REPORT_LAYOUTS = ("data_transacciones", "consolidado")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class PkReportFile(Base):
    __tablename__ = "p_report_files"
    __table_args__ = (
        UniqueConstraint("report_type", "file_sha256", name="uq_p_report_files_type_sha"),
        CheckConstraint(_in("report_type", PAYKU_REPORT_TYPES), name="ck_pkr_files_report_type"),
        CheckConstraint(_in("status", PAYKU_REPORT_FILE_STATUSES), name="ck_pkr_files_status"),
        CheckConstraint("file_sha256 ~ '^[0-9a-f]{64}$'", name="ck_pkr_files_sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_type: Mapped[str] = mapped_column(String(30), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)  # solo nombre, sin ruta
    sheets: Mapped[str | None] = mapped_column(String(255), nullable=True)  # tipos de hoja cargados, separados por coma
    rows_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rows_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rows_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rows_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", server_default="running")
    error_label: Mapped[str | None] = mapped_column(String(100), nullable=True)  # etiqueta tecnica, sin PII
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PkReportTransaction(Base):
    __tablename__ = "p_report_transactions"
    __table_args__ = (
        UniqueConstraint("row_key", name="uq_p_report_transactions_row_key"),
        CheckConstraint(_in("source_layout", PAYKU_REPORT_LAYOUTS), name="ck_pkr_tx_layout"),
        CheckConstraint("installment_number IS NULL OR installment_number >= 0", name="ck_pkr_tx_installment"),
        Index("ix_p_report_transactions_external_id", "transaction_external_id"),
        Index("ix_p_report_transactions_occurred_at", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    row_key: Mapped[str] = mapped_column(String(64), nullable=False)
    transaction_external_id: Mapped[str] = mapped_column(String(64), nullable=False)  # Transaccion / voucher
    order_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_installment: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    installment_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    commission: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    payment_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payment_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    settlement_external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_layout: Mapped[str] = mapped_column(String(20), nullable=False)
    last_file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("p_report_files.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PkReportSettlement(Base):
    __tablename__ = "p_report_settlements"
    __table_args__ = (UniqueConstraint("settlement_external_id", name="uq_p_report_settlements_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    settlement_external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    deposit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_file_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("p_report_files.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
