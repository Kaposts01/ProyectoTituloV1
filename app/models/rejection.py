"""Detalle de glosa de rechazo por canal (RJ-12, decision D3: tabla unica).

Una fila = un rechazo de un cobro/pago con su codigo y glosa tal como los informa el proveedor (o el
reporte). Sirve de lugar de PASO: los `raw_payload` de `vp_*`/`tk_*`/`p_*` se reemplazan en cada sync, asi que
la glosa capturada vive aqui y el ETL Core la proyecta a `core_payments.rejection_*` y
`core_charges.latest_rejection_*`.

Sin datos personales: solo ids externos, codigo, glosa del procesador, monto y marcas de tiempo.
Un `code` vacio (`''`) es un MARCADOR: el cobro se consulto y el proveedor no informo codigo (evita reconsultar).
Migracion `20261029_0043`.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

CAPTURE_SOURCES = ("api_charges", "api_payment", "report_pat", "toku_projection")


class PaymentRejectionDetail(Base):
    __tablename__ = "payment_rejection_details"
    __table_args__ = (
        CheckConstraint(
            "capture_source IN ('api_charges', 'api_payment', 'report_pat', 'toku_projection')",
            name="ck_prd_capture_source",
        ),
        CheckConstraint(
            "charge_external_id IS NOT NULL OR payment_external_id IS NOT NULL", name="ck_prd_charge_or_payment"
        ),
        # (source, cobro, pago, codigo) con NULL tratado como '' para que un rechazo sin pago no se duplique.
        Index(
            "uq_prd_dedupe",
            "source",
            text("coalesce(charge_external_id, '')"),
            text("coalesce(payment_external_id, '')"),
            "code",
            unique=True,
        ),
        Index("ix_prd_source_charge", "source", "charge_external_id"),
        Index("ix_prd_source_payment", "source", "payment_external_id"),
        Index("ix_prd_source_subscription", "source", "subscription_external_id"),
        Index("ix_prd_checked_at", "checked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    charge_external_id: Mapped[str | None] = mapped_column(String(255))
    payment_external_id: Mapped[str | None] = mapped_column(String(255))
    subscription_external_id: Mapped[str | None] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(100), nullable=False, server_default="")
    reason: Mapped[str | None] = mapped_column(Text)
    acquirer_code: Mapped[str | None] = mapped_column(String(100))
    doc_url: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    capture_source: Mapped[str] = mapped_column(String(30), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
