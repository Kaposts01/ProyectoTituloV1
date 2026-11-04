"""Filas SINTETICAS de `tk_report_*` y de la API de Toku para probar el ETL core (TK-PAR-05, TK-PAR-06, TK-20).

Se insertan directo en las tablas (sin pasar por el .xlsx): el parser y el importador ya tienen sus propias pruebas.
Todos los IDs son ficticios y no hay datos personales. Se importa como modulo plano (`from toku_signals_support import ...`).
"""

import hashlib
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.toku_channel import TokuSubscription
from app.models.toku_report import (
    TkReportAttempt,
    TkReportDebt,
    TkReportFile,
    TkReportPaymentMethod,
    TkReportProduct,
)

GENERATED = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def add_file(db: Session, report_type: str = "productos", generated: datetime = GENERATED) -> TkReportFile:
    f = TkReportFile(
        report_type=report_type,
        file_sha256=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
        filename="sintetico.xlsx",
        generated_at=generated,
        status="completed",
    )
    db.add(f)
    db.flush()
    return f


class World:
    """Un archivo por tipo de reporte, para colgar filas."""

    def __init__(self, db: Session, generated: datetime = GENERATED):
        self.db = db
        self.generated = generated
        self.files = {
            t: add_file(db, t, generated) for t in ("productos", "medios_pago", "intentos", "deudas")
        }

    def product(
        self,
        sub: str,
        *,
        customer: str | None = None,
        pm: str | None = None,
        pm_status: str | None = "chargeable",
        created: datetime | None = datetime(2024, 8, 13, 13, 0, tzinfo=UTC),
        deleted: datetime | None = None,
        amount: str | None = "10000",
        key: str | None = None,
    ) -> TkReportProduct:
        row = TkReportProduct(
            subscription_external_id=sub,
            product_key_hash=key or hashlib.sha256(sub.encode()).hexdigest(),
            customer_external_id=customer or f"cus_{sub}",
            payment_method_external_id=pm if pm is not None else f"pm_{sub}",
            payment_method_status=pm_status,
            amount=Decimal(amount) if amount else None,
            created_at_source=created,
            deleted_at_source=deleted,
            source_generated_at=self.generated,
            last_file_id=self.files["productos"].id,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def payment_method(
        self, pm: str, status: str = "chargeable", *, key: str = "", deleted: datetime | None = None
    ) -> TkReportPaymentMethod:
        row = TkReportPaymentMethod(
            payment_method_external_id=pm,
            product_key_hash=key,
            status=status,
            deleted_at_source=deleted,
            source_generated_at=self.generated,
            last_file_id=self.files["medios_pago"].id,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def attempt(
        self,
        sub: str,
        debt: str,
        at: datetime,
        *,
        status: str = "FALLIDO",
        code: str | None = "1001",
        severity: str | None = "TE",
        due: date | None = None,
        deleted: datetime | None = None,
    ) -> TkReportAttempt:
        row = TkReportAttempt(
            attempt_external_id=uid("pi"),
            debt_external_id=debt,
            customer_external_id=f"cus_{sub}",
            subscription_external_id=sub,
            product_key_hash=hashlib.sha256(sub.encode()).hexdigest(),
            due_date=due or at.date(),
            attempted_at=at,
            status=status,
            response_code=code if status == "FALLIDO" else None,
            severity=severity if status == "FALLIDO" else None,
            deleted_at_source=deleted,
            source_generated_at=self.generated,
            last_file_id=self.files["intentos"].id,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def debt(
        self, sub: str, debt: str, due: date, *, paid: bool = False, voided: bool = False
    ) -> TkReportDebt:
        row = TkReportDebt(
            debt_external_id=debt,
            subscription_external_id=sub,
            product_key_hash=hashlib.sha256(sub.encode()).hexdigest(),
            customer_external_id=f"cus_{sub}",
            due_date=due,
            amount=Decimal("10000"),
            paid=paid,
            voided=voided,
            source_generated_at=self.generated,
            last_file_id=self.files["deudas"].id,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def failed_installment(self, sub: str, debt: str, day: date, *, attempts: int = 1, code: str = "1001") -> None:
        """Una cuota con `attempts` intentos fallidos en dias consecutivos desde `day`."""
        for i in range(attempts):
            at = datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC) + timedelta(days=i)
            self.attempt(sub, debt, at, code=code, due=day)

    def paid_installment(self, sub: str, debt: str, day: date) -> None:
        self.attempt(sub, debt, datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC), status="AUTORIZADO", due=day)


def api_subscription(
    db: Session,
    sub: str,
    *,
    customer: str | None = None,
    status: str | None = "ACTIVE",
    anchor: str | None = "2026-11-05",
    end_date: str | None = None,
    amount: str | None = "9000",
) -> TokuSubscription:
    row = TokuSubscription(
        external_id=sub,
        customer_id=customer or f"cus_{sub}",
        status=status,
        amount=amount,
        currency_code="CLP",
        anchor=anchor,
        end_date=end_date,
        raw_payload={"id": sub},
    )
    db.add(row)
    db.flush()
    return row
